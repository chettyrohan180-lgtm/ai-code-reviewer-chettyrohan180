"""
performance_agent.py — Performance & Complexity Review Agent
=============================================================
Audits PR code changes for computational bottlenecks, $O(N^2)$ loops,
N+1 query anti-patterns, blocking calls in async routines, and memory leaks.
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

# ── Pattern Rules for Deterministic Performance Audits ───────────────────────

PERFORMANCE_RULES = [
    {
        "id": "PERF-001",
        "title": "Blocking `time.sleep` in Async Routine",
        "severity": SeverityLevel.HIGH,
        "regex": re.compile(r"""\btime\.sleep\s*\("""),
        "requires_async": True,
        "message": "Using synchronous `time.sleep()` inside an `async def` function blocks the entire event loop, halting all concurrent requests.",
        "suggested_fix": "Replace with `await asyncio.sleep(...)` to allow non-blocking concurrency.",
    },
    {
        "id": "PERF-002",
        "title": "Database Query Inside Loop (Potential N+1 Query Problem)",
        "severity": SeverityLevel.HIGH,
        "regex": re.compile(r"""(?i)(?:db\.query|session\.query|select|find_by|get_user|fetch_one|cursor\.execute)\s*\("""),
        "requires_loop": True,
        "message": "Database query executed inside a loop. This creates an N+1 query bottleneck that scales poorly with dataset size.",
        "suggested_fix": "Batch queries using `WHERE id IN (...)` or eager load relationships (e.g. `joinedload`).",
    },
    {
        "id": "PERF-003",
        "title": "Nested Loop with Potential Quadratic $O(N^2)$ Complexity",
        "severity": SeverityLevel.MEDIUM,
        "regex": re.compile(r"""for\s+.*\s+in\s+.*:\s*$"""),
        "requires_nested_loop": True,
        "message": "Nested iteration detected over collections. If both collections scale with input size, this introduces $O(N^2)$ time complexity.",
        "suggested_fix": "Consider using a `set` or `dict` lookup for $O(1)$ constant-time membership checks instead of nested iteration.",
    },
    {
        "id": "PERF-004",
        "title": "Repeated Regex Compilation Inside Function",
        "severity": SeverityLevel.LOW,
        "regex": re.compile(r"""\bre\.compile\s*\("""),
        "requires_function": True,
        "message": "Compiling regular expressions repeatedly inside a function adds unnecessary CPU overhead on every invocation.",
        "suggested_fix": "Move `re.compile(...)` to module-level scope so it is compiled once during startup.",
    },
]


class PerformanceAgent(BaseReviewAgent):
    """
    Specialized agent focusing on algorithmic efficiency, database query optimization,
    and event-loop responsiveness.
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        super().__init__(
            name="PerformanceAgent",
            category=FindingCategory.PERFORMANCE,
            description="Audits codebase for N+1 queries, async blocking, and algorithmic bottlenecks.",
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
            summary = "Performance Audit passed with no critical bottlenecks."
        else:
            summary = f"Performance Audit flagged {len(all_findings)} potential performance bottleneck(s)."

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
            is_async = symbol.node_type == "async_function_definition" or "async " in symbol.code_snippet
            loop_depth = 0

            for idx, line_text in enumerate(snippet_lines):
                line_number = symbol.start_line + idx
                stripped = line_text.strip()

                # Track basic loop nesting depth
                if stripped.startswith("for ") or stripped.startswith("while "):
                    loop_depth += 1
                elif loop_depth > 0 and len(line_text) - len(line_text.lstrip()) <= 4:
                    # Reset/decrement loop depth on dedent
                    loop_depth = max(0, loop_depth - 1)

                if line_number not in changed_lines_set:
                    continue

                for rule in PERFORMANCE_RULES:
                    # Check conditions
                    if rule.get("requires_async") and not is_async:
                        continue
                    if rule.get("requires_loop") and loop_depth == 0:
                        continue
                    if rule.get("requires_nested_loop") and loop_depth < 2:
                        continue

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
                                confidence_score=0.90,
                            )
                        )

        return findings
