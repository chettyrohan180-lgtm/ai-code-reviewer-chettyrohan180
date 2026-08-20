"""
security_agent.py — Security & Vulnerability Review Agent
=========================================================
Audits PR code changes for OWASP Top 10 vulnerabilities, hardcoded credentials,
insecure deserialization, injection risks, and unsafe cryptographic practices.
"""
from __future__ import annotations

import re
from typing import Optional

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

# ── Pattern Rules for Deterministic Security Audits ──────────────────────────

SECURITY_RULES = [
    {
        "id": "SEC-001",
        "title": "Hardcoded Secret / API Token Detected",
        "severity": SeverityLevel.CRITICAL,
        "regex": re.compile(
            r"""(?i)(?:api_key|apikey|secret_key|private_key|auth_token|access_token|password|passwd|client_secret)\s*=\s*['"][a-zA-Z0-9_\-\.]{8,}['"]"""
        ),
        "message": "Potential hardcoded secret or credential found in source code. Credentials must be loaded via environment variables or a secure secret manager.",
        "suggested_fix": "Use `os.getenv('SECRET_NAME')` or Pydantic `BaseSettings` instead of hardcoding credentials.",
    },
    {
        "id": "SEC-002",
        "title": "AWS Access Key Exposed",
        "severity": SeverityLevel.CRITICAL,
        "regex": re.compile(r"""(AKIA[0-9A-Z]{16})"""),
        "message": "Exposed AWS Access Key ID detected. This poses an immediate compromise risk.",
        "suggested_fix": "Revoke this key immediately in AWS IAM and load credentials via AWS IAM Roles or environment variables.",
    },
    {
        "id": "SEC-003",
        "title": "SQL Injection Risk via Dynamic String Interpolation",
        "severity": SeverityLevel.HIGH,
        "regex": re.compile(
            r"""(?i)(?:f["'].*(?:SELECT|INSERT|UPDATE|DELETE|DROP|ALTER)\b|(?:execute|raw|query)\s*\(\s*(?:f["']|["'].*(?:SELECT|INSERT|UPDATE|DELETE)))"""
        ),
        "message": "Raw SQL query constructed using string formatting/interpolation. User input can bypass database authorization and corrupt or exfiltrate data.",
        "suggested_fix": "Use parameterized queries or ORM query bindings (e.g. `cursor.execute('SELECT * FROM users WHERE id = %s', (user_id,))`).",
    },
    {
        "id": "SEC-004",
        "title": "Dangerous `eval` / `exec` Execution",
        "severity": SeverityLevel.HIGH,
        "regex": re.compile(r"""\b(eval|exec)\s*\("""),
        "message": "Dynamic code execution via `eval` or `exec` allows arbitrary remote code execution (RCE) if input is untrusted.",
        "suggested_fix": "Replace `eval`/`exec` with safe parsers such as `ast.literal_eval` or structured serializers (JSON).",
    },
    {
        "id": "SEC-005",
        "title": "Insecure Shell Command Execution (`shell=True` / `os.system`)",
        "severity": SeverityLevel.HIGH,
        "regex": re.compile(r"""(?:subprocess\.(?:run|Popen|call)\s*\(.*shell\s*=\s*True|os\.system\s*\()"""),
        "message": "Spawning a subshell with `shell=True` or `os.system` exposes the host to command injection vulnerabilities.",
        "suggested_fix": "Pass command arguments as a list with `shell=False` (e.g. `subprocess.run(['ls', '-l'], check=True)`).",
    },
    {
        "id": "SEC-006",
        "title": "Insecure Deserialization (`pickle` / unsafe `yaml.load`)",
        "severity": SeverityLevel.HIGH,
        "regex": re.compile(r"""(?:pickle\.loads?\s*\(|yaml\.load\s*\([^,)]*\))"""),
        "message": "Unsafe deserialization allows arbitrary code execution when untrusted data is deserialized.",
        "suggested_fix": "Use `yaml.safe_load(...)` or JSON serialization (`json.loads`) instead of `pickle`.",
    },
    {
        "id": "SEC-007",
        "title": "Weak Cryptographic Hash Algorithm",
        "severity": SeverityLevel.MEDIUM,
        "regex": re.compile(r"""hashlib\.(?:md5|sha1)\s*\("""),
        "message": "MD5 and SHA-1 are cryptographically broken and vulnerable to collision attacks. Do not use them for passwords, signatures, or secure integrity checks.",
        "suggested_fix": "Upgrade to SHA-256 (`hashlib.sha256`), SHA-512, or `bcrypt`/`argon2` for password hashing.",
    },
]


class SecurityAgent(BaseReviewAgent):
    """
    Specialized agent focusing on identifying security vulnerabilities,
    secrets, injection vectors, and cryptographic weaknesses.
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        super().__init__(
            name="SecurityAgent",
            category=FindingCategory.SECURITY,
            description="Audits codebase for OWASP vulnerabilities, secret leaks, and insecure APIs.",
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
            summary = "Security Audit passed with no critical issues."
        else:
            summary = f"Security Audit flagged {len(all_findings)} potential vulnerability(ies)."

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

        # 1. Audit changed AST symbols
        for symbol in file_diff.symbols:
            snippet_lines = symbol.code_snippet.splitlines()
            for idx, line_text in enumerate(snippet_lines):
                line_number = symbol.start_line + idx
                if line_number not in changed_lines_set:
                    continue

                for rule in SECURITY_RULES:
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
                                confidence_score=0.95,
                            )
                        )

        # 2. Audit unscoped diff lines (e.g. top-level config or constants)
        if file_diff.patch:
            # Check diff lines for leaks outside functions
            curr_new_line = 0
            for hunk in file_diff.hunks:
                curr_line = hunk.new_start
                for hunk_line in hunk.lines:
                    if hunk_line.startswith("+") and not hunk_line.startswith("+++"):
                        if curr_line in file_diff.unscoped_diff_lines:
                            line_content = hunk_line[1:]
                            for rule in SECURITY_RULES:
                                if rule["regex"].search(line_content):
                                    findings.append(
                                        ReviewFinding(
                                            file=file_diff.filename,
                                            line_start=curr_line,
                                            line_end=curr_line,
                                            symbol_name=None,
                                            category=self.category,
                                            severity=rule["severity"],
                                            title=rule["title"],
                                            message=rule["message"],
                                            suggested_fix=rule["suggested_fix"],
                                            confidence_score=0.95,
                                        )
                                    )
                        curr_line += 1
                    elif hunk_line.startswith(" "):
                        curr_line += 1

        return findings
