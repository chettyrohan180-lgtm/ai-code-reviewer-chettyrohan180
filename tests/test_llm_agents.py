"""
Unit tests for dual-layer review agent execution with mocked LLM reasoning.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_code_reviewer.agents import (
    LogicBugAgent,
    PerformanceAgent,
    QualityAgent,
    SecurityAgent,
)
from ai_code_reviewer.llm.client import LLMClient
from ai_code_reviewer.schemas import (
    CodeSymbolNode,
    EnrichedFileDiff,
    EnrichedPRContext,
    ReviewContext,
    SeverityLevel,
)


def _make_dummy_ctx() -> EnrichedPRContext:
    review_context = ReviewContext(
        installation_id=1,
        repo_full_name="acme/repo",
        repo_clone_url="https://github.com/acme/repo.git",
        pr_number=50,
        pr_title="Refactor auth",
        head_sha="11223344",
        head_branch="feature",
        base_branch="main",
        author_login="bob",
        additions=15,
        deletions=2,
        changed_files=1,
    )
    symbol = CodeSymbolNode(
        name="authenticate",
        node_type="function_definition",
        start_line=1,
        end_line=10,
        code_snippet="""def authenticate(token):
    # Valid code without regex rule matches
    return verify_jwt(token)
""",
        modified_lines=[2],
    )
    file_diff = EnrichedFileDiff(
        filename="src/auth.py",
        status="modified",
        language="python",
        changed_lines=[2],
        symbols=[symbol],
    )
    return EnrichedPRContext(
        review_context=review_context,
        files=[file_diff],
        total_symbols_modified=1,
    )


@pytest.mark.asyncio
async def test_dual_layer_security_agent_with_llm():
    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.is_configured = True
    mock_llm.complete_structured = AsyncMock(
        return_value={
            "summary": "LLM identified an unverified JWT signature issue.",
            "findings": [
                {
                    "file": "src/auth.py",
                    "line_start": 2,
                    "line_end": 2,
                    "symbol_name": "authenticate",
                    "severity": "high",
                    "title": "Unverified JWT Algorithm",
                    "message": "The verify_jwt call does not enforce algorithm whitelist, allowing alg:none attacks.",
                    "suggested_fix": "verify_jwt(token, algorithms=['RS256'])",
                    "confidence_score": 0.95,
                }
            ],
        }
    )

    agent = SecurityAgent(llm_client=mock_llm)
    ctx = _make_dummy_ctx()
    result = await agent.execute(ctx)

    assert result.passed is False
    assert len(result.findings) == 1
    assert result.findings[0].title == "Unverified JWT Algorithm"
    assert result.findings[0].severity == SeverityLevel.HIGH


@pytest.mark.asyncio
async def test_dual_layer_merging_deduplication():
    # Code snippet triggers deterministic rule (SEC-001 hardcoded secret)
    code_snippet = """def get_config():
    api_key = "secret_1234567890abcdef"
    return api_key
"""
    symbol = CodeSymbolNode(
        name="get_config",
        node_type="function_definition",
        start_line=1,
        end_line=4,
        code_snippet=code_snippet,
        modified_lines=[2],
    )
    file_diff = EnrichedFileDiff(
        filename="src/config.py",
        status="modified",
        language="python",
        changed_lines=[2],
        symbols=[symbol],
    )

    ctx = EnrichedPRContext(
        review_context=ReviewContext(
            installation_id=1,
            repo_full_name="acme/repo",
            repo_clone_url="https://github.com/acme/repo.git",
            pr_number=50,
            pr_title="Refactor config",
            head_sha="11223344",
            head_branch="feature",
            base_branch="main",
            author_login="bob",
            additions=5,
            deletions=1,
            changed_files=1,
        ),
        files=[file_diff],
        total_symbols_modified=1,
    )

    # LLM also returns finding on line 2
    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.is_configured = True
    mock_llm.complete_structured = AsyncMock(
        return_value={
            "summary": "Found secret",
            "findings": [
                {
                    "file": "src/config.py",
                    "line_start": 2,
                    "line_end": 2,
                    "severity": "critical",
                    "title": "Hardcoded Secret",
                    "message": "Secret in code",
                    "suggested_fix": None,
                    "confidence_score": 0.99,
                }
            ],
        }
    )

    agent = SecurityAgent(llm_client=mock_llm)
    result = await agent.execute(ctx)

    # Should deduplicate on (file, line_start) so only 1 finding exists
    assert len(result.findings) == 1
