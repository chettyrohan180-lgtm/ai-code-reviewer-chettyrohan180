"""
quality_agent.py — Code Quality & Style Review Agent
=====================================================
Audits PR code changes for maintainability, type annotations,
docstrings, debug print statements, and code cleanliness.
"""
from __future__ import annotations

import re

from ai_code_reviewer.agents.base import BaseReviewAgent
from ai_code_reviewer.schemas import (
    AgentReviewResult,
    CodeSymbolNode,
    EnrichedFileDiff,
    EnrichedPRContext,
    FindingCategory,
    ReviewFinding,
    SeverityLevel,
)

QUALITY_RULES = [
    {
        "id": "QUAL-001",
        "title": "Debug `print()` Statement in Production Code",
        "severity": SeverityLevel.LOW,
        "regex": re.compile(r"""\bprint\s*\("""),
        "message": "Leftover `print()` statements clutter standard output and should be replaced with structured logging.",
        "suggested_fix": "Use standard logging (`logger.info(...)` or `logger.debug(...)`).",
    },
    {
        "id": "QUAL-002",
        "title": "Unresolved `TODO` or `FIXME` Comment",
        "severity": SeverityLevel.INFO,
        "regex": re.compile(r"""#\s*(?:TODO|FIXME|XXX|HACK)\b"""),
        "message": "New or modified `TODO`/`FIXME` comment found in PR. Ensure pending items are tracked in an issue tracker.",
        "suggested_fix": "Address the pending task or link to an official issue tracker ticket.",
    },
]


class QualityAgent(BaseReviewAgent):
    """
    Specialized agent focusing on readability, typing, logging standards,
    and maintainability.
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        super().__init__(
            name="QualityAgent",
            category=FindingCategory.CODE_QUALITY,
            description="Audits codebase for logging practices, documentation, and maintainability.",
            llm_client=llm_client,
        )

    async def analyze(self, pr_context: EnrichedPRContext) -> AgentReviewResult:
        deterministic_findings: list[ReviewFinding] = []

        # 1. Deterministic rule analysis
        for file_diff in pr_context.files:
            file_findings = self._audit_file(file_diff)
            deterministic_findings.extend(file_findings)

        # 2. Semantic LLM reasoning
        llm_summary, llm_findings = await self._call_llm_reasoning(pr_context)

        # 3. Merge & deduplicate
        all_findings = self._merge_findings(deterministic_findings, llm_findings)

        passed = not any(
            f.severity in (SeverityLevel.CRITICAL, SeverityLevel.HIGH)
            for f in all_findings
        )

        if llm_summary and not deterministic_findings:
            summary = llm_summary
        elif passed:
            summary = "Quality Audit passed with no critical concerns."
        else:
            summary = f"Quality Audit highlighted {len(all_findings)} style or maintainability suggestion(s)."

        return AgentReviewResult(
            agent_name=self.name,
            category=self.category,
            findings=all_findings,
            summary=summary,
            passed=passed,
        )

    def _audit_file(self, file_diff: EnrichedFileDiff) -> list[ReviewFinding]:
        findings: list[ReviewFinding] = []
        changed_lines_set = set(file_diff.changed_lines)

        for symbol in file_diff.symbols:
            snippet_lines = symbol.code_snippet.splitlines()

            # Check if public function/class is missing a docstring
            if not symbol.name.startswith("_") and not symbol.docstring:
                # If first line was modified
                if symbol.start_line in changed_lines_set:
                    findings.append(
                        ReviewFinding(
                            file=file_diff.filename,
                            line_start=symbol.start_line,
                            line_end=symbol.start_line,
                            symbol_name=symbol.name,
                            category=self.category,
                            severity=SeverityLevel.INFO,
                            title="Missing Docstring on Public Symbol",
                            message=f"Public symbol `{symbol.name}` does not have a docstring.",
                            suggested_fix=f'Add a brief docstring describing the purpose of `{symbol.name}`.',
                            confidence_score=0.85,
                        )
                    )

            for idx, line_text in enumerate(snippet_lines):
                line_number = symbol.start_line + idx
                if line_number not in changed_lines_set:
                    continue

                for rule in QUALITY_RULES:
                    if rule["regex"].search(line_text):
                        findings.append(
                            ReviewFinding(
                                file=file_diff.filename,
                                line_start=line_number,
                                line_end=line_number,
                                symbol_name=symbol.name,
                                category=self.category,
                                severity=rule["severity"],
                                title=rule["title"],
                                message=rule["message"],
                                suggested_fix=rule["suggested_fix"],
                                confidence_score=0.88,
                            )
                        )

        return findings
