"""
Unit tests for github_diff_fetcher.py with mocked GitHub API objects
"""
from unittest.mock import MagicMock

import pytest

from ai_code_reviewer.github_diff_fetcher import fetch_enriched_pr_context
from ai_code_reviewer.schemas import ReviewContext


def test_fetch_enriched_pr_context_mocked():
    context = ReviewContext(
        installation_id=123456,
        repo_full_name="org/repo",
        repo_clone_url="https://github.com/org/repo.git",
        pr_number=42,
        pr_title="Add new auth validation",
        head_sha="abc1234567890",
        head_branch="feature/auth",
        base_branch="main",
        author_login="octocat",
        additions=10,
        deletions=2,
        changed_files=2,
    )

    # Mock File 1: Python file with patch
    mock_file1 = MagicMock()
    mock_file1.filename = "src/auth.py"
    mock_file1.status = "modified"
    mock_file1.additions = 3
    mock_file1.deletions = 1
    mock_file1.patch = """@@ -1,4 +1,6 @@
 def login(user, password):
+    if not user:
+        raise ValueError("Invalid user")
     return True
"""

    # Mock File 2: Ignored lockfile
    mock_file2 = MagicMock()
    mock_file2.filename = "poetry.lock"
    mock_file2.status = "modified"
    mock_file2.additions = 100
    mock_file2.deletions = 50
    mock_file2.patch = "@@ -1,1 +1,1 @@\n-old\n+new"

    # Mock PyGithub PR and Repo
    mock_pr = MagicMock()
    mock_pr.get_files.return_value = [mock_file1, mock_file2]

    # Mock raw file content returned for src/auth.py
    mock_content = MagicMock()
    mock_content.decoded_content = b"""def login(user, password):
    if not user:
        raise ValueError("Invalid user")
    return True
"""

    mock_repo = MagicMock()
    mock_repo.get_pull.return_value = mock_pr
    mock_repo.get_contents.return_value = mock_content

    mock_gh_client = MagicMock()
    mock_gh_client.get_repo.return_value = mock_repo

    enriched_pr = fetch_enriched_pr_context(context, github_client=mock_gh_client)

    assert enriched_pr.review_context.pr_number == 42
    # Lockfile should be filtered out
    assert len(enriched_pr.files) == 1
    file_diff = enriched_pr.files[0]
    assert file_diff.filename == "src/auth.py"
    assert file_diff.language == "python"
    assert len(file_diff.symbols) == 1
    assert file_diff.symbols[0].name == "login"
    assert file_diff.symbols[0].node_type == "function_definition"
    assert enriched_pr.total_symbols_modified == 1
