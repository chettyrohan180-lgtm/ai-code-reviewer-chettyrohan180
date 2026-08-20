"""
simulate_review.py — Offline Local PR Review Simulator
======================================================
CLI utility for testing the entire AST parsing and multi-agent review
pipeline locally on any file or git diff without needing live webhooks.

Usage:
  python scripts/simulate_review.py --file src/auth.py
  python scripts/simulate_review.py --file src/auth.py --lines 10,11,12
  python scripts/simulate_review.py --git
"""
from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_code_reviewer.ast_parser import extract_symbols_from_source
from ai_code_reviewer.diff_parser import detect_language, parse_diff_patch
from ai_code_reviewer.pipeline import ReviewPipelineOrchestrator
from ai_code_reviewer.schemas import (
    CodeSymbolNode,
    EnrichedFileDiff,
    EnrichedPRContext,
    ReviewContext,
)


def run_git_diff() -> str:
    """Gets unified git diff of unstaged changes."""
    try:
        res = subprocess.run(
            ["git", "diff", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout
    except Exception as exc:
        print(f"Error running git diff: {exc}")
        return ""


async def simulate_file_review(file_path: str, changed_lines: list[int] | None = None) -> None:
    path = Path(file_path)
    if not path.exists():
        print(f"Error: File not found at '{file_path}'")
        return

    content = path.read_text(encoding="utf-8")
    lines_count = len(content.splitlines())
    language = detect_language(file_path)

    # If no line numbers passed, simulate modifying all lines in the file
    target_lines = changed_lines or list(range(1, lines_count + 1))

    print(f"\n[AST Parser] Analyzing '{file_path}' ({language}, {len(target_lines)} target line(s))...")
    symbols, unscoped = extract_symbols_from_source(content, language, target_lines)
    print(f"   Extracted {len(symbols)} enclosing AST symbol(s), {len(unscoped)} unscoped line(s)")
    for sym in symbols:
        print(f"     • {sym.name} ({sym.node_type}) lines {sym.start_line}-{sym.end_line}")

    file_diff = EnrichedFileDiff(
        filename=file_path,
        status="modified",
        language=language,
        changed_lines=target_lines,
        symbols=symbols,
        unscoped_diff_lines=unscoped,
    )

    review_context = ReviewContext(
        installation_id=1,
        repo_full_name="local/simulated-repo",
        repo_clone_url="https://github.com/local/simulated-repo.git",
        pr_number=1,
        pr_title=f"Local Simulation Review of {path.name}",
        head_sha="00000000local",
        head_branch="feature/local",
        base_branch="main",
        author_login="local-developer",
        additions=len(target_lines),
        deletions=0,
        changed_files=1,
    )

    pr_context = EnrichedPRContext(
        review_context=review_context,
        files=[file_diff],
        total_symbols_modified=len(symbols),
    )

    print("\n[Multi-Agent Pipeline] Running Security, Performance, Logic, and Quality Agents...")
    orchestrator = ReviewPipelineOrchestrator()
    review = await orchestrator.run_review(pr_context)

    print("\n" + "=" * 70)
    print(review.summary_markdown)
    print("=" * 70 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Autonomous AI Code Reviewer — Local Simulator")
    parser.add_argument("--file", "-f", type=str, help="Path to source file to review")
    parser.add_argument("--lines", "-l", type=str, help="Comma-separated 1-indexed line numbers (e.g. 10,11,12)")
    parser.add_argument("--git", "-g", action="store_true", help="Analyze current git diff against HEAD")

    args = parser.parse_args()

    if args.git:
        patch = run_git_diff()
        if not patch:
            print("No local git changes detected against HEAD.")
            return
        hunks, changed, deleted = parse_diff_patch(patch)
        print(f"Parsed git patch: {len(hunks)} hunk(s), {len(changed)} added line(s)")
    elif args.file:
        changed_lines = [int(x.strip()) for x in args.lines.split(",")] if args.lines else None
        asyncio.run(simulate_file_review(args.file, changed_lines))
    else:
        # Default demo: test simulation on security_agent.py
        demo_file = "ai_code_reviewer/agents/security_agent.py"
        print(f"No arguments specified. Running demo simulation on '{demo_file}'...")
        asyncio.run(simulate_file_review(demo_file, [1, 2, 3]))


if __name__ == "__main__":
    main()
