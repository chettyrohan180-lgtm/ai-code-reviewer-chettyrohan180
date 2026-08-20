"""
ast_parser.py — Tree-sitter AST Code Symbol Extractor
=====================================================
Uses Tree-sitter to parse source files into Abstract Syntax Trees (AST)
and extract only the enclosing functions, classes, and methods that
overlap with modified lines in a pull request.
"""
from __future__ import annotations

import logging
from typing import Optional

from tree_sitter import Language, Node, Parser

from ai_code_reviewer.schemas import CodeSymbolNode

logger = logging.getLogger(__name__)

# ── Language Initializers ───────────────────────────────────────────────────

_LANGUAGE_CACHE: dict[str, Language] = {}
_PARSER_CACHE: dict[str, Parser] = {}


def _get_parser_for_language(language: str) -> Optional[Parser]:
    """
    Returns a cached Tree-sitter Parser configured for the given language.
    Returns None if the language grammar is unavailable.
    """
    lang_key = language.lower()
    if lang_key in _PARSER_CACHE:
        return _PARSER_CACHE[lang_key]

    ts_lang: Optional[Language] = None

    try:
        if lang_key == "python":
            import tree_sitter_python
            ts_lang = Language(tree_sitter_python.language())
        elif lang_key in ("javascript", "typescript", "jsx", "tsx"):
            import tree_sitter_javascript
            ts_lang = Language(tree_sitter_javascript.language())
    except Exception as exc:
        logger.warning("Failed to initialize Tree-sitter for %s: %s", language, exc)
        return None

    if ts_lang is None:
        return None

    _LANGUAGE_CACHE[lang_key] = ts_lang
    parser = Parser(ts_lang)
    _PARSER_CACHE[lang_key] = parser
    return parser


# ── Docstring & Comment Helpers ─────────────────────────────────────────────

def _extract_python_docstring(node: Node, source_bytes: bytes) -> Optional[str]:
    """Extracts python docstring from a function or class block if present."""
    body = node.child_by_field_name("body")
    if not body:
        return None

    for child in body.children:
        if child.type == "expression_statement":
            expr = child.children[0] if child.children else None
            if expr and expr.type == "string":
                raw = source_bytes[expr.start_byte:expr.end_byte].decode("utf-8", errors="replace")
                return raw.strip("'''\"\"\"").strip()
            break
        elif child.type not in (":", "comment"):
            break
    return None


def _extract_js_docstring(node: Node, source_bytes: bytes) -> Optional[str]:
    """Extracts leading JSDoc comments if present right before the node."""
    prev = node.prev_named_sibling
    if prev and prev.type == "comment":
        comment_text = source_bytes[prev.start_byte:prev.end_byte].decode("utf-8", errors="replace").strip()
        if comment_text.startswith("/**"):
            return comment_text
    return None


# ── Symbol Extractor Traversal ──────────────────────────────────────────────

class _SymbolCollector:
    def __init__(self, source_bytes: bytes, language: str, changed_lines: set[int]):
        self.source_bytes = source_bytes
        self.language = language
        self.changed_lines = changed_lines
        self.symbols: list[CodeSymbolNode] = []
        self.covered_lines: set[int] = set()

    def collect(self, root_node: Node) -> None:
        if self.language == "python":
            self._visit_python(root_node, parent_class=None)
        elif self.language in ("javascript", "typescript", "jsx", "tsx"):
            self._visit_javascript(root_node, parent_class=None)

    def _visit_python(self, node: Node, parent_class: Optional[str]) -> None:
        for child in node.children:
            if child.type in ("function_definition", "async_function_definition"):
                name_node = child.child_by_field_name("name")
                func_name = (
                    source_text(self.source_bytes, name_node)
                    if name_node
                    else "anonymous_function"
                )
                full_name = f"{parent_class}.{func_name}" if parent_class else func_name

                start_line = child.start_point[0] + 1
                end_line = child.end_point[0] + 1

                # Check intersection with changed lines
                mod_lines = [
                    ln for ln in sorted(self.changed_lines)
                    if start_line <= ln <= end_line
                ]
                if mod_lines:
                    docstring = _extract_python_docstring(child, self.source_bytes)
                    snippet = source_text(self.source_bytes, child)
                    self.symbols.append(
                        CodeSymbolNode(
                            name=full_name,
                            node_type=child.type,
                            start_line=start_line,
                            end_line=end_line,
                            code_snippet=snippet,
                            docstring=docstring,
                            parent_symbol=parent_class,
                            modified_lines=mod_lines,
                        )
                    )
                    self.covered_lines.update(mod_lines)

            elif child.type == "class_definition":
                name_node = child.child_by_field_name("name")
                class_name = (
                    source_text(self.source_bytes, name_node)
                    if name_node
                    else "AnonymousClass"
                )
                full_class_name = f"{parent_class}.{class_name}" if parent_class else class_name

                start_line = child.start_point[0] + 1
                end_line = child.end_point[0] + 1

                mod_lines = [
                    ln for ln in sorted(self.changed_lines)
                    if start_line <= ln <= end_line
                ]

                # Recurse into class body to capture methods first
                body_node = child.child_by_field_name("body")
                if body_node:
                    self._visit_python(body_node, parent_class=full_class_name)

                # Check if there are modified lines inside class definition not covered by inner methods
                # (e.g. class attributes, class decorators, inheritance list)
                uncovered_class_lines = [ln for ln in mod_lines if ln not in self.covered_lines]
                if uncovered_class_lines:
                    docstring = _extract_python_docstring(child, self.source_bytes)
                    snippet = source_text(self.source_bytes, child)
                    self.symbols.append(
                        CodeSymbolNode(
                            name=full_class_name,
                            node_type="class_definition",
                            start_line=start_line,
                            end_line=end_line,
                            code_snippet=snippet,
                            docstring=docstring,
                            parent_symbol=parent_class,
                            modified_lines=uncovered_class_lines,
                        )
                    )
                    self.covered_lines.update(uncovered_class_lines)

            elif child.type in ("decorated_definition", "block", "module"):
                self._visit_python(child, parent_class=parent_class)

    def _visit_javascript(self, node: Node, parent_class: Optional[str]) -> None:
        for child in node.children:
            if child.type == "function_declaration":
                name_node = child.child_by_field_name("name")
                func_name = source_text(self.source_bytes, name_node) if name_node else "anonymous"
                full_name = f"{parent_class}.{func_name}" if parent_class else func_name

                self._check_and_add_symbol(
                    child, full_name, "function_declaration", parent_class,
                    _extract_js_docstring(child, self.source_bytes)
                )

            elif child.type == "method_definition":
                name_node = child.child_by_field_name("name")
                method_name = source_text(self.source_bytes, name_node) if name_node else "method"
                full_name = f"{parent_class}.{method_name}" if parent_class else method_name

                self._check_and_add_symbol(
                    child, full_name, "method_definition", parent_class,
                    _extract_js_docstring(child, self.source_bytes)
                )

            elif child.type in ("lexical_declaration", "variable_declaration"):
                # Check for const fn = () => ... or let fn = function() ...
                for declarator in child.children:
                    if declarator.type == "variable_declarator":
                        val = declarator.child_by_field_name("value")
                        if val and val.type in ("arrow_function", "function_expression"):
                            name_node = declarator.child_by_field_name("name")
                            var_name = source_text(self.source_bytes, name_node) if name_node else "anonymous"
                            full_name = f"{parent_class}.{var_name}" if parent_class else var_name
                            self._check_and_add_symbol(
                                child, full_name, val.type, parent_class,
                                _extract_js_docstring(child, self.source_bytes)
                            )

            elif child.type == "class_declaration":
                name_node = child.child_by_field_name("name")
                class_name = source_text(self.source_bytes, name_node) if name_node else "AnonymousClass"
                full_class_name = f"{parent_class}.{class_name}" if parent_class else class_name

                start_line = child.start_point[0] + 1
                end_line = child.end_point[0] + 1
                mod_lines = [
                    ln for ln in sorted(self.changed_lines)
                    if start_line <= ln <= end_line
                ]

                body_node = child.child_by_field_name("body")
                if body_node:
                    self._visit_javascript(body_node, parent_class=full_class_name)

                uncovered_class_lines = [ln for ln in mod_lines if ln not in self.covered_lines]
                if uncovered_class_lines:
                    docstring = _extract_js_docstring(child, self.source_bytes)
                    snippet = source_text(self.source_bytes, child)
                    self.symbols.append(
                        CodeSymbolNode(
                            name=full_class_name,
                            node_type="class_declaration",
                            start_line=start_line,
                            end_line=end_line,
                            code_snippet=snippet,
                            docstring=docstring,
                            parent_symbol=parent_class,
                            modified_lines=uncovered_class_lines,
                        )
                    )
                    self.covered_lines.update(uncovered_class_lines)

            elif child.type in ("program", "statement_block", "export_statement"):
                self._visit_javascript(child, parent_class=parent_class)

    def _check_and_add_symbol(
        self,
        node: Node,
        name: str,
        node_type: str,
        parent_symbol: Optional[str],
        docstring: Optional[str],
    ) -> None:
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1

        mod_lines = [
            ln for ln in sorted(self.changed_lines)
            if start_line <= ln <= end_line
        ]
        if mod_lines:
            snippet = source_text(self.source_bytes, node)
            self.symbols.append(
                CodeSymbolNode(
                    name=name,
                    node_type=node_type,
                    start_line=start_line,
                    end_line=end_line,
                    code_snippet=snippet,
                    docstring=docstring,
                    parent_symbol=parent_symbol,
                    modified_lines=mod_lines,
                )
            )
            self.covered_lines.update(mod_lines)


def source_text(source_bytes: bytes, node: Optional[Node]) -> str:
    """Extracts decoded text corresponding to an AST node."""
    if node is None:
        return ""
    return source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


# ── Public API ──────────────────────────────────────────────────────────────

def extract_symbols_from_source(
    source_code: str | bytes,
    language: str,
    changed_lines: list[int],
) -> tuple[list[CodeSymbolNode], list[int]]:
    """
    Parses source code with Tree-sitter and extracts all AST symbols
    (functions, classes, methods) containing lines in `changed_lines`.

    Args:
        source_code: Full content of the source file.
        language: Programming language identifier ('python', 'javascript', etc.).
        changed_lines: 1-indexed line numbers modified in the file.

    Returns:
        (symbols, unscoped_lines)
        - `symbols`: List of `CodeSymbolNode` objects enclosing modified lines.
        - `unscoped_lines`: List of modified lines that fell outside any symbol.
    """
    if not changed_lines:
        return [], []

    source_bytes = source_code.encode("utf-8") if isinstance(source_code, str) else source_code
    if not source_bytes.strip():
        return [], list(changed_lines)

    parser = _get_parser_for_language(language)
    if parser is None:
        # Fallback: language unsupported or grammar not loaded
        return [], list(changed_lines)

    try:
        tree = parser.parse(source_bytes)
    except Exception as exc:
        logger.warning("Tree-sitter parse error for %s: %s", language, exc)
        return [], list(changed_lines)

    changed_lines_set = set(changed_lines)
    collector = _SymbolCollector(source_bytes, language, changed_lines_set)
    collector.collect(tree.root_node)

    # Sort extracted symbols by start_line
    collector.symbols.sort(key=lambda s: s.start_line)

    # Unscoped lines: changed lines that didn't fall into any function/class
    unscoped_lines = [ln for ln in sorted(changed_lines_set) if ln not in collector.covered_lines]

    return collector.symbols, unscoped_lines
