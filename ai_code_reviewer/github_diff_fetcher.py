"""
github_diff_fetcher.py — GitHub PR Diff & AST Enrichment Orchestrator
======================================================================
Fetches PR file diffs and source code from GitHub, parses unified patches,
and uses Tree-sitter AST parsing to build an EnrichedPRContext.
"""
from __future__ import annotations

import logging
from typing import Optional

from github import Github, GithubException

from ai_code_reviewer.github_auth import get_github_client
from ai_code_reviewer.diff_parser import detect_language, parse_diff_patch, should_ignore_file
from ai_code_reviewer.ast_parser import extract_symbols_from_source
from ai_code_reviewer.schemas import (
    CodeSymbolNode,
    EnrichedFileDiff,
    EnrichedPRContext,
    ReviewContext,
)

logger = logging.getLogger(__name__)


def _estimate_token_count(text: str) -> int:
    """Rough heuristic: 1 token ~= 4 characters / 0.75 words."""
    return max(1, len(text) // 4)


def fetch_enriched_pr_context(
    context: ReviewContext,
    github_client: Optional[Github] = None,
) -> EnrichedPRContext:
    """
    Fetches the pull request files from GitHub, extracts modified AST symbols,
    and returns a structured EnrichedPRContext.

    Args:
        context: ReviewContext containing repo, PR number, commit SHA, and installation ID.
        github_client: Optional pre-configured PyGithub client (useful for unit testing/mocking).

    Returns:
        EnrichedPRContext ready for multi-agent LLM analysis.
    """
    if github_client is None:
        if context.installation_id is None:
            raise ValueError(
                f"Cannot authenticate GitHub client: installation_id missing for {context.repo_full_name}"
            )
        github_client = get_github_client(context.installation_id)

    logger.info(
        "Fetching PR files for %s #%d (head SHA: %s)",
        context.repo_full_name,
        context.pr_number,
        context.head_sha[:8],
    )

    repo = github_client.get_repo(context.repo_full_name)
    pr = repo.get_pull(context.pr_number)

    enriched_files: list[EnrichedFileDiff] = []
    total_text_length = 0

    for pr_file in pr.get_files():
        filename = pr_file.filename
        status = pr_file.status or "modified"

        if should_ignore_file(filename):
            logger.debug("Skipping ignored/binary file: %s", filename)
            continue

        language = detect_language(filename)
        patch = pr_file.patch or ""
        hunks, changed_lines, deleted_lines = parse_diff_patch(patch)

        symbols: list[CodeSymbolNode] = []
        unscoped_lines: list[int] = list(changed_lines)

        # Only fetch full source & run AST parsing if file is not deleted and has modified lines
        if status != "removed" and changed_lines:
            try:
                content_file = repo.get_contents(filename, ref=context.head_sha)
                if hasattr(content_file, "decoded_content"):
                    source_bytes = content_file.decoded_content
                    extracted_symbols, uncovered_lines = extract_symbols_from_source(
                        source_bytes,
                        language=language,
                        changed_lines=changed_lines,
                    )
                    symbols = extracted_symbols
                    unscoped_lines = uncovered_lines
            except GithubException as exc:
                logger.warning(
                    "Could not fetch raw contents for %s at %s: %s",
                    filename,
                    context.head_sha[:8],
                    exc,
                )
            except Exception as exc:
                logger.warning("AST extraction failed on %s: %s", filename, exc)

        old_filename_val = getattr(pr_file, "previous_filename", None)
        old_filename = old_filename_val if isinstance(old_filename_val, str) else None

        enriched_file = EnrichedFileDiff(
            filename=str(filename),
            old_filename=old_filename,
            status=str(status),
            additions=int(pr_file.additions or 0) if isinstance(pr_file.additions, int) else 0,
            deletions=int(pr_file.deletions or 0) if isinstance(pr_file.deletions, int) else 0,
            language=language,
            patch=patch if patch else None,
            hunks=hunks,
            changed_lines=changed_lines,
            deleted_lines=deleted_lines,
            symbols=symbols,
            unscoped_diff_lines=unscoped_lines,
        )
        enriched_files.append(enriched_file)

        # Accumulate text length for token estimation
        total_text_length += len(patch)
        for s in symbols:
            total_text_length += len(s.code_snippet)

    total_symbols = sum(len(f.symbols) for f in enriched_files)
    estimated_tokens = _estimate_token_count(" " * total_text_length)

    logger.info(
        "Enriched PR %s #%d: %d files, %d AST symbols, ~%d tokens",
        context.repo_full_name,
        context.pr_number,
        len(enriched_files),
        total_symbols,
        estimated_tokens,
    )

    return EnrichedPRContext(
        review_context=context,
        files=enriched_files,
        total_symbols_modified=total_symbols,
        estimated_tokens=estimated_tokens,
    )
