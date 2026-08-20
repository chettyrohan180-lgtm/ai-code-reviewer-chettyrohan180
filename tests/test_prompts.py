"""
Unit tests for prompts.py (prompt formatting and structured response parsing).
"""
import pytest

from ai_code_reviewer.llm.prompts import (
    build_agent_prompt,
    parse_llm_findings,
)
from ai_code_reviewer.schemas import (
    CodeSymbolNode,
    EnrichedFileDiff,
    EnrichedPRContext,
    FindingCategory,
    ReviewContext,
    SeverityLevel,
)


def _make_sample_context() -> EnrichedPRContext:
    review_context = ReviewContext(
        installation_id=1,
        repo_full_name="acme/api",
        repo_clone_url="https://github.com/acme/api.git",
        pr_number=99,
        pr_title="Add payment validation",
        head_sha="deadbeef1234",
        head_branch="feature/payments",
        base_branch="main",
        author_login="alice",
        additions=20,
        deletions=5,
        changed_files=1,
    )
    symbol = CodeSymbolNode(
        name="PaymentService.charge",
        node_type="function_definition",
        start_line=10,
        end_line=25,
        code_snippet="""def charge(self, amount, token):
    if amount <= 0:
        raise ValueError("Invalid amount")
    return self.gateway.charge(amount, token)
""",
        docstring="Charge customer card.",
        modified_lines=[12],
    )
    file_diff = EnrichedFileDiff(
        filename="services/payment.py",
        status="modified",
        language="python",
        changed_lines=[12],
        symbols=[symbol],
        patch="@@ -10,3 +10,4 @@\n def charge(self, amount, token):\n+    if amount <= 0:\n",
    )
    return EnrichedPRContext(
        review_context=review_context,
        files=[file_diff],
        total_symbols_modified=1,
    )


def test_build_agent_prompt_all_categories():
    ctx = _make_sample_context()

    for category in [
        FindingCategory.SECURITY,
        FindingCategory.PERFORMANCE,
        FindingCategory.BUG_RISK,
        FindingCategory.CODE_QUALITY,
    ]:
        sys_prompt, user_prompt = build_agent_prompt(category, ctx)
        assert len(sys_prompt) > 50
        assert "PaymentService.charge" in user_prompt
        assert "services/payment.py" in user_prompt
        assert "# Pull Request: #99" in user_prompt


def test_parse_llm_findings_valid_json():
    raw_response = """{
        "summary": "Found 1 security vulnerability in authorization logic.",
        "findings": [
            {
                "file": "services/payment.py",
                "line_start": 12,
                "line_end": 14,
                "symbol_name": "PaymentService.charge",
                "severity": "high",
                "title": "Missing Permission Check",
                "message": "The charge endpoint does not check if user has active billing permissions.",
                "suggested_fix": "verify_billing_permission(user)",
                "confidence_score": 0.95
            }
        ]
    }"""
    summary, findings = parse_llm_findings(raw_response, FindingCategory.SECURITY)

    assert "authorization logic" in summary
    assert len(findings) == 1
    assert findings[0].file == "services/payment.py"
    assert findings[0].line_start == 12
    assert findings[0].severity == SeverityLevel.HIGH
    assert findings[0].confidence_score == 0.95


def test_parse_llm_findings_low_confidence_filtered():
    raw_response = {
        "summary": "Review complete.",
        "findings": [
            {
                "file": "services/payment.py",
                "line_start": 12,
                "line_end": 12,
                "severity": "low",
                "title": "Subjective Naming Nitpick",
                "message": "Maybe rename token to payment_token.",
                "suggested_fix": None,
                "confidence_score": 0.50,  # Below 0.70 threshold
            }
        ],
    }
    summary, findings = parse_llm_findings(raw_response, FindingCategory.CODE_QUALITY)

    # Low confidence finding should be filtered out
    assert len(findings) == 0
