"""
base.py — Abstract Base Class for Review Agents
================================================
Defines the standard interface, execution harness, and prompt builders
for all specialized review agents.
"""
from __future__ import annotations

import time
import logging
from abc import ABC, abstractmethod
from typing import Optional

from ai_code_reviewer.llm.client import LLMClient
from ai_code_reviewer.llm.prompts import build_agent_prompt, parse_llm_findings
from ai_code_reviewer.schemas import (
    AgentReviewResult,
    EnrichedPRContext,
    FindingCategory,
    ReviewFinding,
    SeverityLevel,
)

logger = logging.getLogger(__name__)


class BaseReviewAgent(ABC):
    """
    Abstract base class for all specialized code review agents.
    """

    def __init__(
        self,
        name: str,
        category: FindingCategory,
        description: str,
        llm_client: Optional[LLMClient] = None,
    ):
        self.name = name
        self.category = category
        self.description = description
        self.llm_client = llm_client or LLMClient()

    async def _call_llm_reasoning(
        self,
        pr_context: EnrichedPRContext,
    ) -> tuple[str, list[ReviewFinding]]:
        """
        Executes deep semantic reasoning using the configured LLM client.
        """
        if not self.llm_client.is_configured:
            return "", []

        system_prompt, user_prompt = build_agent_prompt(self.category, pr_context)
        raw_result = await self.llm_client.complete_structured(system_prompt, user_prompt)
        return parse_llm_findings(raw_result, self.category)

    def _merge_findings(
        self,
        deterministic_findings: list[ReviewFinding],
        llm_findings: list[ReviewFinding],
    ) -> list[ReviewFinding]:
        """
        Merges deterministic AST/regex findings with LLM findings,
        deduplicating overlapping observations on the same line.
        """
        merged: list[ReviewFinding] = list(deterministic_findings)
        seen_locations = {(f.file, f.line_start) for f in deterministic_findings}

        for lf in llm_findings:
            if (lf.file, lf.line_start) not in seen_locations:
                seen_locations.add((lf.file, lf.line_start))
                merged.append(lf)

        return merged

    @abstractmethod
    async def analyze(self, pr_context: EnrichedPRContext) -> AgentReviewResult:
        """
        Main analysis method to be implemented by each specialized agent.
        """
        raise NotImplementedError

    async def execute(self, pr_context: EnrichedPRContext) -> AgentReviewResult:
        """
        Harness wrapping agent execution with timing, error recovery, and validation.
        """
        start_time = time.perf_counter()
        logger.info("Agent [%s] starting analysis on PR #%d", self.name, pr_context.review_context.pr_number)

        try:
            result = await self.analyze(pr_context)
        except Exception as exc:
            logger.error("Agent [%s] failed during analysis: %s", self.name, exc, exc_info=True)
            result = AgentReviewResult(
                agent_name=self.name,
                category=self.category,
                findings=[],
                summary=f"Analysis failed due to internal error: {exc}",
                passed=False,
                execution_time_ms=0.0,
            )

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        result.execution_time_ms = round(elapsed_ms, 2)

        # Check pass status: fails if any critical or high findings exist
        has_critical_or_high = any(
            f.severity in (SeverityLevel.CRITICAL, SeverityLevel.HIGH)
            for f in result.findings
        )
        result.passed = not has_critical_or_high

        logger.info(
            "Agent [%s] finished in %.1f ms with %d findings (passed=%s)",
            self.name,
            result.execution_time_ms,
            len(result.findings),
            result.passed,
        )
        return result

    def format_code_prompt_context(self, pr_context: EnrichedPRContext) -> str:
        """
        Builds a concise prompt representation of modified files, enclosing AST symbols,
        and git diff hunks for downstream LLM prompts (Step 4).
        """
        sections = [
            f"PR Title: {pr_context.review_context.pr_title}",
            f"Repository: {pr_context.review_context.repo_full_name}",
            f"Author: {pr_context.review_context.author_login}",
            f"Modified Files: {len(pr_context.files)}",
            "---",
        ]

        for file_diff in pr_context.files:
            sections.append(f"### File: `{file_diff.filename}` (status: {file_diff.status}, language: {file_diff.language})")

            if file_diff.symbols:
                sections.append("#### Changed Code Symbols (Functions/Classes):")
                for sym in file_diff.symbols:
                    sections.append(
                        f"```symbol:{sym.name} (lines {sym.start_line}-{sym.end_line}, changed lines: {sym.modified_lines})\n"
                        f"{sym.code_snippet}\n"
                        "```"
                    )

            if file_diff.patch:
                sections.append(f"#### Git Unified Diff:\n```diff\n{file_diff.patch}\n```")

            sections.append("")

        return "\n".join(sections)
