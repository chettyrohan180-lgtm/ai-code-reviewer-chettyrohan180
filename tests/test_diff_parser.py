"""
Unit tests for diff_parser.py
"""
import pytest

from ai_code_reviewer.diff_parser import (
    detect_language,
    parse_diff_patch,
    should_ignore_file,
)


def test_detect_language():
    assert detect_language("src/main.py") == "python"
    assert detect_language("app/index.js") == "javascript"
    assert detect_language("components/Button.tsx") == "typescript"
    assert detect_language("server/main.go") == "go"
    assert detect_language("unknown.xyz123") == "unknown"


def test_should_ignore_file():
    # Lockfiles
    assert should_ignore_file("package-lock.json") is True
    assert should_ignore_file("poetry.lock") is True
    assert should_ignore_file("sub/dir/yarn.lock") is True

    # Binaries & Images
    assert should_ignore_file("assets/logo.png") is True
    assert should_ignore_file("build/app.exe") is True
    assert should_ignore_file("fonts/inter.woff2") is True

    # Minified files
    assert should_ignore_file("dist/bundle.min.js") is True

    # Ignored directories
    assert should_ignore_file("node_modules/express/index.js") is True
    assert should_ignore_file(".venv/lib/site.py") is True

    # Valid code files
    assert should_ignore_file("src/auth.py") is False
    assert should_ignore_file("frontend/src/App.tsx") is False


def test_parse_diff_patch_single_hunk():
    patch = """@@ -1,5 +1,6 @@
 import os
+import sys
 
 def hello():
-    return 1
+    return 2
"""
    hunks, changed_lines, deleted_lines = parse_diff_patch(patch)

    assert len(hunks) == 1
    assert hunks[0].old_start == 1
    assert hunks[0].old_lines == 5
    assert hunks[0].new_start == 1
    assert hunks[0].new_lines == 6

    # Line 2 was added (+import sys)
    # Line 5 was modified (+return 2)
    assert changed_lines == [2, 5]
    # Line 4 was deleted (-return 1)
    assert deleted_lines == [4]


def test_parse_diff_patch_multiple_hunks():
    patch = """@@ -10,3 +10,4 @@
 def first():
+    print("new line")
     return 1
@@ -50,4 +51,5 @@
 def second():
-    old()
+    new_call()
+    extra_line()
"""
    hunks, changed_lines, deleted_lines = parse_diff_patch(patch)

    assert len(hunks) == 2
    assert changed_lines == [11, 52, 53]
    assert deleted_lines == [51]


def test_parse_diff_patch_empty():
    hunks, changed, deleted = parse_diff_patch("")
    assert hunks == []
    assert changed == []
    assert deleted == []
