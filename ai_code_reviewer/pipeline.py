"""
pipeline.py — Multi-Agent Review Pipeline Orchestrator
======================================================
Executes specialized review agents in parallel via asyncio, aggregates and
deduplicates findings, calculates the overall PR verdict, and renders formatted
GitHub review summaries.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from ai_code_reviewer.agents import (
    BaseReviewAgent,
    LogicBugAgent,
    PerformanceAgent,
    QualityAgent,
    SecurityAgent,
)
from ai_code_reviewer.schemas import (
    AgentReviewResult,
    AggregatedPRReview,
    EnrichedPRContext,
    FindingCategory,
    ReviewFinding,
    ReviewVerdict,
    SeverityLevel,
)

logger = logging.getLogger(__name__)


class ReviewPipelineOrchestrator:
    """
    Coordinates concurrent execution of review agents, deduplicates findings,
    and formats comprehensive PR review reports.
    """

    def __init__(self, agents: Optional[list[BaseReviewAgent]] = None):
        self.agents: list[BaseReviewAgent] = agents or [
            SecurityAgent(),
            PerformanceAgent(),
            LogicBugAgent(),
            QualityAgent(),
        ]

    async def run_review(self, pr_context: EnrichedPRContext) -> AggregatedPRReview:
        """
        Runs all registered agents concurrently against the enriched PR context.
        """
        start_time = time.perf_counter()
        logger.info(
            "Starting multi-agent review for PR #%d (%d agents registered)",
            pr_context.review_context.pr_number,
            len(self.agents),
        )

        # Run all agents in parallel
        tasks = [agent.execute(pr_context) for agent in self.agents]
        agent_results: list[AgentReviewResult] = await asyncio.gather(*tasks)

        # Aggregate and deduplicate findings
        all_findings: list[ReviewFinding] = []
        seen_keys: set[tuple[str, int, str, str]] = set()

        for res in agent_results:
            for finding in res.findings:
                dedup_key = (finding.file, finding.line_start, finding.category.value, finding.title)
                if dedup_key not in seen_keys:
                    seen_keys.add(dedup_key)
                    all_findings.append(finding)

        # Sort findings by severity priority: CRITICAL -> HIGH -> MEDIUM -> LOW -> INFO
        severity_order = {
            SeverityLevel.CRITICAL: 0,
            SeverityLevel.HIGH: 1,
            SeverityLevel.MEDIUM: 2,
            SeverityLevel.LOW: 3,
            SeverityLevel.INFO: 4,
        }
        all_findings.sort(key=lambda f: (severity_order.get(f.severity, 5), f.file, f.line_start))

        # Determine overall verdict
        verdict = self._calculate_verdict(all_findings)

        # Build formatted GitHub summary markdown
        total_time_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        summary_markdown = self._format_markdown_report(
            pr_context=pr_context,
            agent_results=agent_results,
            all_findings=all_findings,
            verdict=verdict,
            total_time_ms=total_time_ms,
        )

        logger.info(
            "Completed multi-agent review for PR #%d: verdict=%s, findings=%d, duration=%.1f ms",
            pr_context.review_context.pr_number,
            verdict.value,
            len(all_findings),
            total_time_ms,
        )

        return AggregatedPRReview(
            review_context=pr_context.review_context,
            agent_results=agent_results,
            all_findings=all_findings,
            verdict=verdict,
            summary_markdown=summary_markdown,
            total_findings=len(all_findings),
        )

    def _calculate_verdict(self, findings: list[ReviewFinding]) -> ReviewVerdict:
        """
        Calculates review verdict:
        - REQUEST_CHANGES if any CRITICAL or HIGH findings exist.
        - COMMENT if only MEDIUM, LOW, or INFO findings exist.
        - APPROVE if zero findings exist.
        """
        if not findings:
            return ReviewVerdict.APPROVE

        if any(f.severity in (SeverityLevel.CRITICAL, SeverityLevel.HIGH) for f in findings):
            return ReviewVerdict.REQUEST_CHANGES

        return ReviewVerdict.COMMENT

    def _format_markdown_report(
        self,
        pr_context: EnrichedPRContext,
        agent_results: list[AgentReviewResult],
        all_findings: list[ReviewFinding],
        verdict: ReviewVerdict,
        total_time_ms: float,
    ) -> str:
        """
        Formats an aesthetic, structured markdown summary report suitable
        for posting to GitHub PR comments or Check Runs.
        """
        verdict_badge = {
            ReviewVerdict.APPROVE: "**APPROVED**",
            ReviewVerdict.COMMENT: "**COMMENT / FEEDBACK**",
            ReviewVerdict.REQUEST_CHANGES: "**CHANGES REQUESTED**",
        }.get(verdict, "**REVIEW COMPLETE**")

        severity_emojis = {
            SeverityLevel.CRITICAL: "`CRITICAL`",
            SeverityLevel.HIGH: "`HIGH`",
            SeverityLevel.MEDIUM: "`MEDIUM`",
            SeverityLevel.LOW: "`LOW`",
            SeverityLevel.INFO: "`INFO`",
        }

        category_emojis = {
            FindingCategory.SECURITY: "Security",
            FindingCategory.PERFORMANCE: "Performance",
            FindingCategory.BUG_RISK: "Bug Risk",
            FindingCategory.CODE_QUALITY: "Quality",
        }

        lines = [
            f"## Autonomous AI Code Review — {verdict_badge}",
            "",
            f"**PR #{pr_context.review_context.pr_number}:** {pr_context.review_context.pr_title}  ",
            f"**Author:** @{pr_context.review_context.author_login} | **Commit:** `{pr_context.review_context.head_sha[:8]}` | **Analysis Time:** `{total_time_ms} ms`",
            "",
            "### Review Overview",
            "| Agent | Category | Findings | Status |",
            "|---|---|:---:|:---:|",
        ]

        for res in agent_results:
            status_icon = "Pass" if res.passed else "Issues Found"
            cat_label = category_emojis.get(res.category, res.category.value)
            lines.append(f"| **{res.agent_name}** | {cat_label} | {len(res.findings)} | {status_icon} |")

        lines.append("")

        if not all_findings:
            lines.extend([
                "> [!TIP]",
                "> **All checks passed!** No security vulnerabilities, performance bottlenecks, or logic risks were detected in the modified code.",
                "",
            ])
        else:
            lines.extend([
                "### Detailed Findings",
                "",
            ])

            for idx, finding in enumerate(all_findings, 1):
                sev_badge = severity_emojis.get(finding.severity, finding.severity.value)
                cat_label = category_emojis.get(finding.category, finding.category.value)
                sym_info = f" in `{finding.symbol_name}`" if finding.symbol_name else ""

                lines.extend([
                    f"#### {idx}. {sev_badge} **{finding.title}** ({cat_label})",
                    f"- **Location:** `{finding.file}:{finding.line_start}`{sym_info}",
                    f"- **Details:** {finding.message}",
                ])

                if finding.suggested_fix:
                    lines.extend([
                        f"- **Recommendation:**",
                        f"  ```suggestion",
                        f"  {finding.suggested_fix}",
                        f"  ```",
                    ])
                lines.append("")

        lines.extend([
            "---",
            "*Generated autonomously by AI Code Reviewer Agent Pipeline.*",
        ])

        return "\n".join(lines)
