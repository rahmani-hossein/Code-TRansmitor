#!/usr/bin/env python3
"""
init_repo.py — Repo initializer using LM Studio (fully local, no API key needed).

Scans your repo and writes:
  - CLAUDE.md   (stack, commands, architecture, conventions)
  - SUMMARY.md  (what it does, key files, onboarding checklist)

Setup:
    1. Open LM Studio → download any model (e.g. Mistral 7B, Llama 3, Qwen 2.5)
    2. Go to Local Server tab → Start Server (default port: 1234)
    3. pip install openai
    4. python init_repo.py

Usage:
    python init_repo.py                        # current directory
    python init_repo.py --path /my/repo        # specific repo
    python init_repo.py --port 1234            # custom port (default: 1234)
    python init_repo.py --model "mistral-7b"   # override model name
    python init_repo.py --dry-run              # preview context, skip API call
"""

import os
import sys
import json
import argparse
from pathlib import Path

# ── CONFIG ───────────────────────────────────────────────────────────────────

DEFAULT_PORT  = 1234
DEFAULT_MODEL = "local-model"  # LM Studio ignores this — uses whatever is loaded

HIGH_VALUE_FILES = [
    "README.md", "README.rst", "README.txt",
    "pyproject.toml", "setup.py", "setup.cfg",
    "package.json", "requirements.txt", "requirements-dev.txt",
    "Makefile", "Dockerfile", ".env.example",
    "go.mod", "Cargo.toml",
    "CONTRIBUTING.md", ".pre-commit-config.yaml",
    "pytest.ini", "conftest.py", "tox.ini",
]

SKIP_DIRS = {
    ".git", "__pycache__", ".mypy_cache", ".pytest_cache",
    "node_modules", ".venv", "venv", "env", ".env",
    "dist", "build", ".tox", ".idea", ".vscode",
    "htmlcov", ".coverage",
}

MAX_FILE_CHARS    = 3000
MAX_TREE_LINES    = 80
MAX_CONTEXT_CHARS = 12000

# ── REPO SCANNER ─────────────────────────────────────────────────────────────

def build_tree(root):
    lines = []

    def walk(path, prefix="", depth=0):
        if depth > 4 or len(lines) >= MAX_TREE_LINES:
            return
        try:
            entries = sorted(path.iterdir(), key=lambda e: (e.is_file(), e.name))
        except PermissionError:
            return
        for entry in entries:
            if entry.name in SKIP_DIRS or entry.name.startswith("."):
                continue
            connector = "├── " if entry != entries[-1] else "└── "
            lines.append(f"{prefix}{connector}{entry.name}{'/' if entry.is_dir() else ''}")
            if entry.is_dir():
                ext = "│   " if entry != entries[-1] else "    "
                walk(entry, prefix + ext, depth + 1)

    lines.append(f"{root.name}/")
    walk(root)
    if len(lines) >= MAX_TREE_LINES:
        lines.append("... (truncated)")
    return "\n".join(lines)


def read_high_value_files(root):
    results = {}
    for fname in HIGH_VALUE_FILES:
        fpath = root / fname
        if fpath.exists() and fpath.is_file():
            try:
                results[fname] = fpath.read_text(errors="replace")[:MAX_FILE_CHARS]
            except Exception:
                pass
    return results


def find_entry_points(root):
    candidates = ["main.py", "app.py", "cli.py", "run.py", "server.py",
                  "index.ts", "index.js", "main.ts", "main.go"]
    found = []
    for name in candidates:
        if (root / name).exists():
            found.append(name)
        if (root / "src" / name).exists():
            found.append(f"src/{name}")
    return found


def collect_context(root):
    sections = []
    sections.append(f"## Directory Structure\n```\n{build_tree(root)}\n```")

    for fname, content in read_high_value_files(root).items():
        sections.append(f"## {fname}\n```\n{content}\n```")

    entries = find_entry_points(root)
    if entries:
        sections.append("## Entry Points\n" + "\n".join(f"- {e}" for e in entries))

    src_dirs = [d for d in root.iterdir()
                if d.is_dir() and (d / "__init__.py").exists()
                and d.name not in SKIP_DIRS]
    if src_dirs:
        sections.append("## Python Packages\n" + "\n".join(f"- {d.name}/" for d in src_dirs))

    return "\n\n".join(sections)[:MAX_CONTEXT_CHARS]


# ── LM STUDIO API CALL ───────────────────────────────────────────────────────

def call_model(system, user, base_url, model, max_tokens=1500):
    try:
        from openai import OpenAI
    except ImportError:
        print("ERROR: Run: pip install openai")
        sys.exit(1)

    client = OpenAI(
        base_url=base_url,
        api_key="lm-studio",  # LM Studio requires a value but ignores it
    )

    try:
        response = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ]
        )
    except Exception as e:
        print(f"\nERROR: Could not reach LM Studio at {base_url}")
        print(f"  Make sure LM Studio is open and the local server is running.")
        print(f"  Local Server tab → click 'Start Server'")
        print(f"  Details: {e}")
        sys.exit(1)

    return response.choices[0].message.content.strip()


# ── CLAUDE.md GENERATION ──────────────────────────────────────────────────────

CLAUDE_MD_SYSTEM = """You are a senior software engineer performing codebase initialization.
Analyze the repository context and generate structured project config.

Rules:
- Be specific to THIS codebase, not generic
- Only include commands you can infer from the context
- Omit fields you cannot confidently fill (set to null)
- No fluff, no filler

Respond ONLY with a valid JSON object — no markdown fences, no explanation:
{
  "overview": "1-2 sentence project summary",
  "stack": ["tech1", "tech2"],
  "commands": {
    "install": "command or null",
    "build": "command or null",
    "test": "command or null",
    "lint": "command or null",
    "run": "command or null"
  },
  "architecture": [
    {"folder": "src/models/", "purpose": "what it does"}
  ],
  "conventions": ["convention 1", "convention 2"],
  "avoid": ["thing to avoid"],
  "notes": "any extra context worth knowing"
}"""


def generate_claude_md(context, base_url, model, repo_name):
    print("  Writing CLAUDE.md...")
    raw = call_model(
        system=CLAUDE_MD_SYSTEM,
        user=f"Repository context:\n\n{context}\n\nGenerate the JSON now.",
        base_url=base_url,
        model=model,
        max_tokens=1000,
    )
    raw = raw.replace("```json", "").replace("```", "").strip()

    # Some local models add extra text before/after JSON — try to extract it
    if "{" in raw and "}" in raw:
        raw = raw[raw.index("{"):raw.rindex("}")+1]

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print("  WARNING: Could not parse JSON (model may need a larger context window)")
        print("  Tip: try a model with >= 8k context, e.g. Mistral 7B or Qwen 2.5")
        return raw

    lines = [
        f"# CLAUDE.md - {repo_name}",
        "",
        "> Auto-generated by init_repo.py - update as the project evolves.",
        "",
        "## Overview",
        data.get("overview", ""),
        "",
    ]

    if data.get("stack"):
        lines += ["## Tech Stack"] + [f"- {t}" for t in data["stack"]] + [""]

    cmds = {k: v for k, v in data.get("commands", {}).items() if v}
    if cmds:
        lines += ["## Key Commands", "```bash"]
        for name, cmd in cmds.items():
            lines += [f"# {name.capitalize()}", cmd, ""]
        lines += ["```", ""]

    if data.get("architecture"):
        lines += ["## Architecture"] + \
                 [f"- `{a['folder']}` - {a['purpose']}" for a in data["architecture"]] + [""]

    if data.get("conventions"):
        lines += ["## Conventions"] + [f"- {c}" for c in data["conventions"]] + [""]

    if data.get("avoid"):
        lines += ["## Things to Avoid"] + [f"- {a}" for a in data["avoid"]] + [""]

    if data.get("notes"):
        lines += ["## Notes", data["notes"], ""]

    return "\n".join(lines)


# ── SUMMARY.md GENERATION ─────────────────────────────────────────────────────

SUMMARY_MD_SYSTEM = """You are a senior engineer writing onboarding documentation for a new teammate.
You have the full repository context and the already-generated CLAUDE.md.

Write a thorough but readable SUMMARY.md using this exact structure:

# Project Summary - {repo_name}

## What This Project Does
2-3 paragraphs: purpose, business context, how it fits the larger system.

## The 3 Most Important Files to Read First
For each: filename, why it matters, what you will learn from it.

## How It All Fits Together
A short narrative (not bullets) of the data/execution flow from input to output.

## Onboarding Checklist
Numbered steps a new engineer should follow on day 1.

## Open Questions / TODOs
Things that are unclear, missing, or worth investigating.

Rules:
- Reference actual filenames and folders from the context
- Do not invent things - if unclear, say so
- Write for ML engineers / data scientists"""


def generate_summary_md(context, claude_md, base_url, model, repo_name):
    print("  Writing SUMMARY.md...")
    system = SUMMARY_MD_SYSTEM.replace("{repo_name}", repo_name)
    user = f"Repository context:\n{context}\n\n---\nAlready generated CLAUDE.md:\n{claude_md}"
    return call_model(system=system, user=user, base_url=base_url, model=model, max_tokens=2000)


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Repo initializer using LM Studio — writes CLAUDE.md + SUMMARY.md."
    )
    parser.add_argument("--path",    default=".",          help="Repo root (default: current dir)")
    parser.add_argument("--port",    default=DEFAULT_PORT, type=int, help="LM Studio port (default: 1234)")
    parser.add_argument("--model",   default=DEFAULT_MODEL, help="Model name (default: whatever is loaded)")
    parser.add_argument("--dry-run", action="store_true",  help="Print context, skip API calls")
    args = parser.parse_args()

    root = Path(args.path).resolve()
    if not root.exists():
        print(f"ERROR: Path not found: {root}")
        sys.exit(1)

    base_url = f"http://localhost:{args.port}/v1"

    print(f"\n/init - {root.name}")
    print(f"LM Studio → {base_url}  |  model: {args.model}")
    print("-" * 50)

    print("Scanning directory structure...")
    print("Reading config files...")
    print("Detecting entry points...")
    context = collect_context(root)
    print(f"Context assembled: {len(context):,} chars")

    if args.dry_run:
        print("\n-- DRY RUN --")
        print(context)
        return

    # Call 1: CLAUDE.md
    claude_md = generate_claude_md(context, base_url, args.model, root.name)
    (root / "CLAUDE.md").write_text(claude_md)
    print(f"  Done: {root / 'CLAUDE.md'}")

    # Call 2: SUMMARY.md
    summary_md = generate_summary_md(context, claude_md, base_url, args.model, root.name)
    (root / "SUMMARY.md").write_text(summary_md)
    print(f"  Done: {root / 'SUMMARY.md'}")

    print("\n" + "-" * 50)
    print("Done!")
    print("  CLAUDE.md   - project config (Copilot reads this automatically)")
    print("  SUMMARY.md  - human-readable onboarding doc")
    print("\nNext: commit both files to your repo.")


if __name__ == "__main__":
    main()