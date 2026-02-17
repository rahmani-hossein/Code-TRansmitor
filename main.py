"""
Stratified segmentation using SensitivityAnalyser.
For each cohort_date:
  1. Compute 1D sensitivity (sens_mean) per mortgage
  2. Rank: most negative sensitivity → rank 1 → segment 0
  3. Assign segments via quantile cut
"""

def preProcessingForOptimizer(self):
    # ── existing preprocessing ──────────────────────────────────────────────
    df_oot_spark = df_oot_spark.withColumn(
        "expected_volume", col("close_balance") * col("smoothed_prediction")
    )
    df_oot_spark = df_oot_spark.withColumn(
        "expected_profit", col("npv") * col("smoothed_prediction")
    )

    # ── Step 1: compute 1D sensitivity per mortgage ─────────────────────────
    sensitivity_analyser = SensitivityAnalyser(
        df=self.df,
        config_path=self.eval_config_path
    )

    df_clean = sensitivity_analyser.preprocess()          # your existing prep
    sensitivity_df = sensitivity_analyser.calculate_1d_sensitivity(
        df_clean=df_clean,
        treatment_col=sensitivity_analyser.treatment_col,
        method="mean",       # only need sens_mean
        verbose=False
    )
    # sensitivity_df now has [mtg_col, cohort_date_col, "sens_mean"]

    # ── Step 2 & 3: rank + segment, stratified by cohort_date ───────────────
    segment_count = self.segment_count   # e.g. 10
    segment_dfs   = []

    for cohort_dt, group in sensitivity_df.groupby(
        sensitivity_analyser.cohort_date_col
    ):
        group = group.copy()

        # rank: ascending=True  →  most negative sens_mean gets rank 1
        group["rank"] = group["sens_mean"].rank(
            method="first", ascending=True
        ).astype(int)

        # segment: rank 1 → segment 0  (most sensitive / most negative)
        group["segment"] = pd.qcut(
            group["rank"],
            q=segment_count,
            labels=range(0, segment_count),   # 0 = most negative
            duplicates="drop"
        ).astype(int)

        segment_dfs.append(group)

    # ── Step 4: join segments back to main OOT dataframe ────────────────────
    segmented_df = pd.concat(segment_dfs, ignore_index=True)

    # keep only the keys + the two new columns
    seg_cols = [
        sensitivity_analyser.mtg_col,
        sensitivity_analyser.cohort_date_col,
        "sens_mean",
        "segment"
    ]
    segmented_df = segmented_df[seg_cols]

    # convert to Spark and join
    segmented_spark = spark.createDataFrame(segmented_df)

    df_oot_spark = df_oot_spark.join(
        segmented_spark,
        on=[self.mtg_col, self.cohort_date_col],
        how="left"
    )

    # ── Step 5: select final columns (mirror your existing selected_cols) ────
    selected_cols = [
        "mtgnum", "segment", "close_balance",
        "snapshot_date", "termcd_lead_bucket",
        "smoothed_prediction", "expected_volume",
        "expected_profit", "npv", "cost_of_funds",
        "sens_mean"           # renamed from "sensitivity" for clarity
    ]
    df_temp = df_oot_spark.select(*selected_cols)

    return df_temp