"""
logic_agent.py — Logic & Bug Flaw Review Agent
==============================================
Audits PR code changes for runtime exceptions, mutable defaults,
broad exception suppression, unhandled None types, and incorrect boolean logic.
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

LOGIC_RULES = [
    {
        "id": "LOGIC-001",
        "title": "Mutable Default Argument in Function Definition",
        "severity": SeverityLevel.HIGH,
        "regex": re.compile(r"""def\s+\w+\s*\(.*=\s*(?:\[\]|\{\}|set\(\))\s*[\),:]"""),
        "message": "Using a mutable default argument (e.g. `[]` or `{}`) creates a shared instance across all function invocations, causing unexpected state mutations across calls.",
        "suggested_fix": "Use `None` as the default argument (e.g. `items: list = None`) and initialize inside the function body (`if items is None: items = []`).",
    },
    {
        "id": "LOGIC-002",
        "title": "Silent / Bare Exception Catch Block",
        "severity": SeverityLevel.MEDIUM,
        "regex": re.compile(r"""^\s*except(?:\s*:\s*(?:#.*)?|\s+Exception\s*:\s*(?:pass|\.\.\.)\s*(?:#.*)?)$"""),
        "message": "Catching and silently ignoring all exceptions hides critical errors, bugs, and keyboard interrupts.",
        "suggested_fix": "Catch specific exceptions (e.g. `except ValueError:`) and log the error (`logger.exception(...)`).",
    },
    {
        "id": "LOGIC-003",
        "title": "Comparison using `== None` or `!= None`",
        "severity": SeverityLevel.LOW,
        "regex": re.compile(r"""(?:==\s*None|!=\s*None)"""),
        "message": "Comparisons against singletons like `None` should use the `is` or `is not` identity operator instead of equality `==`.",
        "suggested_fix": "Replace `x == None` with `x is None` (or `x != None` with `x is not None`).",
    },
    {
        "id": "LOGIC-004",
        "title": "Shadowing Python Built-in Identifier",
        "severity": SeverityLevel.LOW,
        "regex": re.compile(r"""(?:\bdef\s+|\b)(?:id|type|list|dict|set|str|int|filter|map|input|format)\s*="""),
        "message": "Variable or parameter assignment shadows a Python built-in function or type.",
        "suggested_fix": "Rename variable to avoid overriding Python built-ins (e.g. `item_id` instead of `id`).",
    },
]


class LogicBugAgent(BaseReviewAgent):
    """
    Specialized agent focusing on subtle bugs, unhandled exceptions,
    and incorrect control flow.
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        super().__init__(
            name="LogicBugAgent",
            category=FindingCategory.BUG_RISK,
            description="Audits codebase for mutable defaults, silent exception handling, and boolean flaws.",
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
            summary = "Logic Audit passed with no critical bug risks."
        else:
            summary = f"Logic Audit flagged {len(all_findings)} potential bug risk(s)."

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

            for idx, line_text in enumerate(snippet_lines):
                line_number = symbol.start_line + idx
                if line_number not in changed_lines_set:
                    continue

                for rule in LOGIC_RULES:
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
                                confidence_score=0.92,
                            )
                        )

        return findings
