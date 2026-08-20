"""
Unit tests for ast_parser.py
"""
import pytest

from ai_code_reviewer.ast_parser import extract_symbols_from_source


def test_python_function_extraction():
    code = """import sys

def add(a: int, b: int) -> int:
    \"\"\"Add two numbers.\"\"\"
    return a + b

def multiply(a: int, b: int) -> int:
    return a * b
"""
    # Line 5 is inside `add`
    symbols, unscoped = extract_symbols_from_source(code, "python", [5])

    assert len(symbols) == 1
    assert symbols[0].name == "add"
    assert symbols[0].node_type == "function_definition"
    assert symbols[0].start_line == 3
    assert symbols[0].end_line == 5
    assert symbols[0].docstring == "Add two numbers."
    assert symbols[0].modified_lines == [5]
    assert unscoped == []


def test_python_class_and_method_extraction():
    code = """class UserService:
    \"\"\"Service managing user accounts.\"\"\"

    def __init__(self, db):
        self.db = db

    def register(self, email: str, password: str):
        if not email:
            raise ValueError("Email required")
        return self.db.create_user(email, password)

def helper():
    return True
"""
    # Line 9 (inside register method)
    symbols, unscoped = extract_symbols_from_source(code, "python", [9])

    assert len(symbols) == 1
    assert symbols[0].name == "UserService.register"
    assert symbols[0].parent_symbol == "UserService"
    assert symbols[0].node_type == "function_definition"
    assert symbols[0].start_line == 7
    assert symbols[0].end_line == 10
    assert symbols[0].modified_lines == [9]
    assert unscoped == []


def test_python_unscoped_and_scoped_mixed():
    code = """import os
import json

DEFAULT_TIMEOUT = 30

def fetch(url: str):
    return True
"""
    # Line 1 (import os) is unscoped, Line 6 (inside fetch) is scoped
    symbols, unscoped = extract_symbols_from_source(code, "python", [1, 6])

    assert len(symbols) == 1
    assert symbols[0].name == "fetch"
    assert symbols[0].modified_lines == [6]
    assert unscoped == [1]


def test_javascript_functions_and_classes():
    code = """class PaymentGateway {
  processPayment(amount) {
    return true;
  }
}

const formatCurrency = (val) => {
  return `$${val}`;
};

function init() {
  console.log("ready");
}
"""
    # Line 3 (processPayment) and Line 8 (formatCurrency)
    symbols, unscoped = extract_symbols_from_source(code, "javascript", [3, 8])

    assert len(symbols) == 2
    sym_names = [s.name for s in symbols]
    assert "PaymentGateway.processPayment" in sym_names
    assert "formatCurrency" in sym_names
    assert unscoped == []


def test_unsupported_language_graceful_fallback():
    code = "fn main() { println!(\"hello\"); }"
    symbols, unscoped = extract_symbols_from_source(code, "rust", [1])

    assert symbols == []
    assert unscoped == [1]
