"""
prompts.py — LLM Prompt Templates & Structured Response Parsers
================================================================
Defines domain-specialized system prompts for Security, Performance,
Logic Bugs, and Code Quality agents, with strict JSON output schemas.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from ai_code_reviewer.schemas import (
    EnrichedPRContext,
    FindingCategory,
    ReviewFinding,
    SeverityLevel,
)

logger = logging.getLogger(__name__)

# ── JSON Schema for Structured Output ───────────────────────────────────────

STRUCTURED_FINDINGS_SCHEMA: dict[str, Any] = {
    "name": "code_review_response",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "High-level summary of the code review analysis.",
            },
            "findings": {
                "type": "array",
                "description": "List of granular review findings.",
                "items": {
                    "type": "object",
                    "properties": {
                        "file": {
                            "type": "string",
                            "description": "Repository relative file path.",
                        },
                        "line_start": {
                            "type": "integer",
                            "description": "1-indexed starting line number of the issue in the new file.",
                        },
                        "line_end": {
                            "type": "integer",
                            "description": "1-indexed ending line number of the issue in the new file.",
                        },
                        "symbol_name": {
                            "type": ["string", "null"],
                            "description": "Name of the enclosing function, method, or class (if applicable).",
                        },
                        "severity": {
                            "type": "string",
                            "enum": ["critical", "high", "medium", "low", "info"],
                            "description": "Severity level of the observation.",
                        },
                        "title": {
                            "type": "string",
                            "description": "Concise 1-line title describing the issue.",
                        },
                        "message": {
                            "type": "string",
                            "description": "Clear explanation of why this code is problematic and what risks it introduces.",
                        },
                        "suggested_fix": {
                            "type": ["string", "null"],
                            "description": "Concrete code suggestion or diff snippet resolving the issue.",
                        },
                        "confidence_score": {
                            "type": "number",
                            "description": "Confidence rating from 0.0 to 1.0 that this finding is genuine and actionable.",
                        },
                    },
                    "required": [
                        "file",
                        "line_start",
                        "line_end",
                        "symbol_name",
                        "severity",
                        "title",
                        "message",
                        "suggested_fix",
                        "confidence_score",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["summary", "findings"],
        "additionalProperties": False,
    },
}

# ── Agent-Specific System Prompts ───────────────────────────────────────────

SECURITY_SYSTEM_PROMPT = """You are the Senior Application Security Reviewer Agent in an Autonomous Code Review Pipeline.
Your mission is to perform a rigorous security audit of the modified code and its enclosing AST symbols.

Focus Areas:
1. Injection vulnerabilities (SQLi, Command Injection, NoSQLi, Template Injection, LDAP injection).
2. Hardcoded secrets, API tokens, passwords, private keys, database credentials.
3. Broken Authentication & Authorization (IDOR, missing permission checks, JWT validation flaws).
4. Insecure direct object access & Path Traversal (unsafe file opens, unvalidated paths).
5. Insecure Deserialization (`pickle.loads`, unsafe YAML/XML parsers).
6. Cryptographic weaknesses (broken hashes MD5/SHA1, weak RNG, hardcoded IVs/keys).
7. Cross-Site Scripting (XSS), Server-Side Request Forgery (SSRF), CORS/CSRF vulnerabilities.

Review Guidelines:
- Only report genuine, actionable vulnerabilities with high confidence (score >= 0.75).
- Reference the exact modified file and line numbers provided in the context.
- Provide a clear, actionable code replacement in `suggested_fix`.
- If no security flaws are found, return an empty `findings` list and a reassuring `summary`.
- Output ONLY valid JSON matching the schema.
"""

PERFORMANCE_SYSTEM_PROMPT = """You are the Principal Performance & Scalability Reviewer Agent in an Autonomous Code Review Pipeline.
Your mission is to analyze the modified code and enclosing AST symbols for computational bottlenecks, memory leaks, and scalability anti-patterns.

Focus Areas:
1. Algorithmic complexity: Nested loops ($O(N^2)$ or worse) over unbounded or scaling collections.
2. Database bottlenecks: N+1 query loops, missing batching, unindexed filters, lack of pagination.
3. Concurrency & Async: Blocking synchronous calls (e.g. `time.sleep`, synchronous I/O, CPU-bound work) inside `async def` routines.
4. Memory inefficiencies: Unbounded cache growth, large in-memory list allocations, unclosed file/network handles.
5. Redundant operations: Repeated parsing, redundant serialization, compiling regexes inside hot loops.

Review Guidelines:
- Only report genuine performance concerns with meaningful real-world impact.
- Reference the exact modified file and line numbers from the context.
- Provide optimized alternative code in `suggested_fix`.
- If no performance bottlenecks exist, return an empty `findings` list and a concise `summary`.
- Output ONLY valid JSON matching the schema.
"""

LOGIC_BUG_SYSTEM_PROMPT = """You are the Principal Software Correctness & Bug Hunter Agent in an Autonomous Code Review Pipeline.
Your mission is to inspect the modified code and enclosing AST symbols for subtle runtime defects, logic errors, and unexpected edge cases.

Focus Areas:
1. Null/None safety: Dereferencing variables without prior `None`/null checks, optional chaining oversights.
2. Control flow anomalies: Off-by-one errors in loops/slices, unreachable code, identical if/else branches.
3. Error handling: Silent exception swallowing, catching `Exception` without logging/re-raising, missing transaction rollbacks.
4. Mutable defaults: Functions with `def f(data=[])` or `def f(cache={})` leading to shared state bugs.
5. Boolean/Conditional errors: Inverted logic, incorrect operator precedence (`and`/`or`), incorrect truthiness checks.
6. Race conditions: Unsynchronized shared state access across async tasks or threads.

Review Guidelines:
- Prioritize high-impact defects and logic flaws.
- Reference the exact modified file and line numbers from the context.
- Provide correct code in `suggested_fix`.
- If the code is logically sound, return an empty `findings` list and a concise `summary`.
- Output ONLY valid JSON matching the schema.
"""

QUALITY_SYSTEM_PROMPT = """You are the Lead Code Quality & Maintainability Reviewer Agent in an Autonomous Code Review Pipeline.
Your mission is to evaluate the modified code and enclosing AST symbols for readability, idiomatic conventions, typing safety, and maintainability.

Focus Areas:
1. Type safety: Missing or inconsistent type annotations on public functions/classes.
2. Documentation: Missing or outdated docstrings on exported/public interfaces.
3. Clean Code & Idioms: Overly complex functions (high cyclomatic complexity), deeply nested blocks, non-idiomatic constructs.
4. Code hygiene: Leftover debug `print()` statements, unresolved `TODO`/`FIXME` markers, dead/unreachable code.
5. Modularity & Naming: Ambiguous variable/function names, violation of Single Responsibility Principle.

Review Guidelines:
- Keep feedback constructive, concise, and focused on maintainability.
- Avoid subjective nitpicks; focus on standards that improve team velocity and code clarity.
- Reference the exact modified file and line numbers from the context.
- If the code adheres to high quality standards, return an empty `findings` list and a concise `summary`.
- Output ONLY valid JSON matching the schema.
"""

CATEGORY_PROMPT_MAP = {
    FindingCategory.SECURITY: SECURITY_SYSTEM_PROMPT,
    FindingCategory.PERFORMANCE: PERFORMANCE_SYSTEM_PROMPT,
    FindingCategory.BUG_RISK: LOGIC_BUG_SYSTEM_PROMPT,
    FindingCategory.CODE_QUALITY: QUALITY_SYSTEM_PROMPT,
}


# ── Prompt Builder ──────────────────────────────────────────────────────────

def build_agent_prompt(
    category: FindingCategory,
    pr_context: EnrichedPRContext,
) -> tuple[str, str]:
    """
    Builds the (system_prompt, user_prompt) pair for a given agent category
    and enriched PR context.
    """
    system_prompt = CATEGORY_PROMPT_MAP.get(category, QUALITY_SYSTEM_PROMPT)

    user_sections = [
        f"# Pull Request: #{pr_context.review_context.pr_number} — {pr_context.review_context.pr_title}",
        f"**Repository:** {pr_context.review_context.repo_full_name}",
        f"**Author:** @{pr_context.review_context.author_login}",
        f"**Base Branch:** `{pr_context.review_context.base_branch}` | **Head Branch:** `{pr_context.review_context.head_branch}`",
        f"**Changes:** +{pr_context.review_context.additions} / -{pr_context.review_context.deletions} across {len(pr_context.files)} file(s)",
        "",
        "## Modified Files & Enclosing AST Context:",
    ]

    for file_diff in pr_context.files:
        user_sections.append(
            f"### File: `{file_diff.filename}` (Status: {file_diff.status}, Language: {file_diff.language})"
        )
        user_sections.append(f"**Changed line numbers in new file:** `{file_diff.changed_lines}`")

        if file_diff.symbols:
            user_sections.append("#### Enclosing AST Symbols (Functions / Classes):")
            for sym in file_diff.symbols:
                user_sections.append(
                    f"```symbol:{sym.name} (Type: {sym.node_type}, Lines {sym.start_line}-{sym.end_line}, Modified Lines: {sym.modified_lines})\n"
                    f"{sym.code_snippet}\n"
                    "```"
                )

        if file_diff.unscoped_diff_lines:
            user_sections.append(f"**Unscoped modified lines (e.g. imports, global config):** `{file_diff.unscoped_diff_lines}`")

        if file_diff.patch:
            user_sections.append(f"#### Git Unified Patch:\n```diff\n{file_diff.patch}\n```")

        user_sections.append("---")

    user_sections.append(
        "Analyze the changes above according to your specialized role. "
        "Return your structured evaluation in JSON adhering to the required schema."
    )

    user_prompt = "\n".join(user_sections)
    return system_prompt, user_prompt


# ── Response Parser ─────────────────────────────────────────────────────────

def parse_llm_findings(
    raw_json_or_dict: str | dict[str, Any],
    default_category: FindingCategory,
) -> tuple[str, list[ReviewFinding]]:
    """
    Parses LLM JSON response into a summary string and validated ReviewFinding list.
    Filters out findings with low confidence score (< 0.70).
    """
    if isinstance(raw_json_or_dict, str):
        try:
            data = json.loads(raw_json_or_dict)
        except json.JSONDecodeError as exc:
            logger.warning("Failed to decode LLM response JSON: %s", exc)
            return "Failed to parse LLM response.", []
    else:
        data = raw_json_or_dict

    summary = data.get("summary", "")
    raw_findings = data.get("findings", [])
    valid_findings: list[ReviewFinding] = []

    for item in raw_findings:
        try:
            # Parse severity
            raw_sev = str(item.get("severity", "medium")).lower()
            try:
                sev = SeverityLevel(raw_sev)
            except ValueError:
                sev = SeverityLevel.MEDIUM

            conf = float(item.get("confidence_score", 1.0))
            if conf < 0.70:
                logger.debug("Discarding low confidence finding (%s): %s", conf, item.get("title"))
                continue

            finding = ReviewFinding(
                file=str(item.get("file", "unknown")),
                line_start=int(item.get("line_start", 1)),
                line_end=int(item.get("line_end", item.get("line_start", 1))),
                symbol_name=item.get("symbol_name"),
                category=default_category,
                severity=sev,
                title=str(item.get("title", "Review Finding")),
                message=str(item.get("message", "")),
                suggested_fix=item.get("suggested_fix"),
                confidence_score=conf,
            )
            valid_findings.append(finding)
        except Exception as exc:
            logger.warning("Error parsing individual LLM finding: %s (raw: %s)", exc, item)

    return summary, valid_findings
