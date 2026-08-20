"""
diff_parser.py — Unified Git Diff Parser & File Filtering
===========================================================
Parses unified diff patches into structured hunks and calculates exact
1-indexed target line numbers for modified and deleted lines in PRs.
Filters out binary files, minified bundles, and lockfiles.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from ai_code_reviewer.schemas import DiffHunk


# ── Ignored and Binary File Patterns ────────────────────────────────────────

IGNORED_FILENAMES = frozenset({
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "pipfile.lock",
    "cargo.lock",
    "composer.lock",
    "go.sum",
    "flake.lock",
})

IGNORED_EXTENSIONS = frozenset({
    # Binaries & Images
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp", ".bmp", ".tiff",
    ".pdf", ".zip", ".tar", ".gz", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".iso",
    # Fonts
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    # Media
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".webm",
    # Source Maps & Minified bundles
    ".map",
})

# Extension to language mapping
EXTENSION_LANGUAGE_MAP: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".cpp": "cpp",
    ".c": "c",
    ".h": "c",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".scala": "scala",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".sql": "sql",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    ".md": "markdown",
}

# Regex to match unified diff hunk header: @@ -old_start,old_count +new_start,new_count @@ header
HUNK_HEADER_RE = re.compile(
    r"^@@\s+-(?P<old_start>\d+)(?:,(?P<old_count>\d+))?\s+\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))?\s+@@(?:\s+(?P<header>.*))?$"
)


def detect_language(filename: str) -> str:
    """
    Detect the programming language based on file extension.
    Returns 'unknown' if not recognized.
    """
    ext = Path(filename).suffix.lower()
    return EXTENSION_LANGUAGE_MAP.get(ext, "unknown")


def should_ignore_file(filename: str) -> bool:
    """
    Determines if a file should be skipped during automated code review.
    Skips lockfiles, binary files, minified bundles, and vendor files.
    """
    path = Path(filename)
    basename = path.name.lower()

    if basename in IGNORED_FILENAMES:
        return True

    ext = path.suffix.lower()
    if ext in IGNORED_EXTENSIONS:
        return True

    # Check for minified files like bundle.min.js or style.min.css
    if basename.endswith(".min.js") or basename.endswith(".min.css"):
        return True

    # Check for vendor or generated directories
    parts = [p.lower() for p in path.parts]
    ignored_dirs = {"node_modules", "vendor", ".venv", "venv", "__pycache__", "dist", "build", ".next", ".git"}
    if any(part in ignored_dirs for part in parts):
        return True

    return False


def parse_diff_patch(patch: Optional[str]) -> tuple[list[DiffHunk], list[int], list[int]]:
    """
    Parses a unified diff patch string into structured DiffHunk objects,
    and returns:
      1. List of parsed DiffHunk objects
      2. List of 1-indexed line numbers added/modified in the new file
      3. List of 1-indexed line numbers removed from the old file

    Args:
        patch: Unified diff string (from GitHub API or git diff).

    Returns:
        (hunks, changed_lines, deleted_lines)
    """
    if not patch or not patch.strip():
        return [], [], []

    hunks: list[DiffHunk] = []
    all_changed_lines: list[int] = []
    all_deleted_lines: list[int] = []

    current_hunk: Optional[DiffHunk] = None
    curr_old_line = 0
    curr_new_line = 0

    lines = patch.splitlines()

    for line in lines:
        match = HUNK_HEADER_RE.match(line)
        if match:
            if current_hunk is not None:
                hunks.append(current_hunk)

            old_start = int(match.group("old_start"))
            old_count = int(match.group("old_count")) if match.group("old_count") is not None else 1
            new_start = int(match.group("new_start")) if match.group("new_start") is not None else 1
            new_count = int(match.group("new_count")) if match.group("new_count") is not None else 1
            header = (match.group("header") or "").strip()

            curr_old_line = old_start
            curr_new_line = new_start

            current_hunk = DiffHunk(
                old_start=old_start,
                old_lines=old_count,
                new_start=new_start,
                new_lines=new_count,
                header=header,
                lines=[line],
                modified_new_lines=[],
            )
            continue

        if current_hunk is None:
            # Preamble line before the first hunk (e.g. diff --git ...)
            continue

        current_hunk.lines.append(line)

        if line.startswith("+") and not line.startswith("+++"):
            current_hunk.modified_new_lines.append(curr_new_line)
            all_changed_lines.append(curr_new_line)
            curr_new_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            all_deleted_lines.append(curr_old_line)
            curr_old_line += 1
        elif line.startswith(" "):
            curr_old_line += 1
            curr_new_line += 1
        elif line.startswith("\\"):
            # "\ No newline at end of file"
            pass
        else:
            # Unprefixed or unusual line - treat as context
            curr_old_line += 1
            curr_new_line += 1

    if current_hunk is not None:
        hunks.append(current_hunk)

    return hunks, all_changed_lines, all_deleted_lines
