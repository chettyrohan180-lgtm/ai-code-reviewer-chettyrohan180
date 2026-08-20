"""
Unit tests for specialized review agents (Security, Performance, Logic, Quality).
"""
import pytest

from ai_code_reviewer.agents import (
    LogicBugAgent,
    PerformanceAgent,
    QualityAgent,
    SecurityAgent,
)
from ai_code_reviewer.schemas import (
    CodeSymbolNode,
    EnrichedFileDiff,
    EnrichedPRContext,
    FindingCategory,
    ReviewContext,
    SeverityLevel,
)


def _make_dummy_context(file_diffs: list[EnrichedFileDiff]) -> EnrichedPRContext:
    review_context = ReviewContext(
        installation_id=1,
        repo_full_name="org/repo",
        repo_clone_url="https://github.com/org/repo.git",
        pr_number=1,
        pr_title="Test PR",
        head_sha="12345678",
        head_branch="feature",
        base_branch="main",
        author_login="octocat",
        additions=10,
        deletions=0,
        changed_files=len(file_diffs),
    )
    return EnrichedPRContext(
        review_context=review_context,
        files=file_diffs,
        total_symbols_modified=sum(len(f.symbols) for f in file_diffs),
    )


@pytest.mark.asyncio
async def test_security_agent_detects_secrets_and_sqli():
    agent = SecurityAgent()

    code_snippet = """def query_user(user_id):
    api_key = "secret_1234567890abcdef"
    query = f"SELECT * FROM users WHERE id = {user_id}"
    cursor.execute(query)
"""
    symbol = CodeSymbolNode(
        name="query_user",
        node_type="function_definition",
        start_line=1,
        end_line=5,
        code_snippet=code_snippet,
        modified_lines=[2, 3],
    )
    file_diff = EnrichedFileDiff(
        filename="src/user.py",
        status="modified",
        language="python",
        changed_lines=[2, 3],
        symbols=[symbol],
    )

    ctx = _make_dummy_context([file_diff])
    result = await agent.execute(ctx)

    assert result.passed is False
    assert len(result.findings) >= 2
    titles = [f.title for f in result.findings]
    assert any("Secret" in t for t in titles)
    assert any("SQL" in t for t in titles)


@pytest.mark.asyncio
async def test_performance_agent_detects_blocking_async_and_n_plus_one():
    agent = PerformanceAgent()

    code_snippet = """async def process_batch(items):
    time.sleep(5)
    for item in items:
        db.query(f"SELECT * FROM orders WHERE item_id = {item.id}")
"""
    symbol = CodeSymbolNode(
        name="process_batch",
        node_type="async_function_definition",
        start_line=10,
        end_line=15,
        code_snippet=code_snippet,
        modified_lines=[11, 13],
    )
    file_diff = EnrichedFileDiff(
        filename="src/batch.py",
        status="modified",
        language="python",
        changed_lines=[11, 13],
        symbols=[symbol],
    )

    ctx = _make_dummy_context([file_diff])
    result = await agent.execute(ctx)

    assert result.passed is False
    assert len(result.findings) >= 2
    titles = [f.title for f in result.findings]
    assert any("Blocking" in t for t in titles)
    assert any("N+1" in t for t in titles)


@pytest.mark.asyncio
async def test_logic_agent_detects_mutable_default_and_bare_except():
    agent = LogicBugAgent()

    code_snippet = """def append_item(item, storage=[]):
    try:
        storage.append(item)
    except:
        pass
    return storage
"""
    symbol = CodeSymbolNode(
        name="append_item",
        node_type="function_definition",
        start_line=1,
        end_line=7,
        code_snippet=code_snippet,
        modified_lines=[1, 4],
    )
    file_diff = EnrichedFileDiff(
        filename="src/utils.py",
        status="modified",
        language="python",
        changed_lines=[1, 4],
        symbols=[symbol],
    )

    ctx = _make_dummy_context([file_diff])
    result = await agent.execute(ctx)

    assert result.passed is False
    assert len(result.findings) >= 2
    titles = [f.title for f in result.findings]
    assert any("Mutable Default" in t for t in titles)
    assert any("Silent" in t for t in titles)


@pytest.mark.asyncio
async def test_quality_agent_detects_debug_print():
    agent = QualityAgent()

    code_snippet = """def calculate_total(a, b):
    print(f"Debug: {a}, {b}")
    return a + b
"""
    symbol = CodeSymbolNode(
        name="calculate_total",
        node_type="function_definition",
        start_line=20,
        end_line=23,
        code_snippet=code_snippet,
        docstring="Compute sum",
        modified_lines=[21],
    )
    file_diff = EnrichedFileDiff(
        filename="src/calc.py",
        status="modified",
        language="python",
        changed_lines=[21],
        symbols=[symbol],
    )

    ctx = _make_dummy_context([file_diff])
    result = await agent.execute(ctx)

    assert result.passed is True  # Low severity doesn't fail pass status
    assert len(result.findings) >= 1
    assert any("print" in f.title.lower() for f in result.findings)
