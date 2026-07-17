"""Tests for PLAN_SYMBOLD Phase 1 file outlines."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from monitor import config  # noqa: F401 — establish config before profile imports
from monitor.lib.tool_definitions import AVAILABLE_TOOLS, TOOL_DESCRIPTIONS
from monitor.lib.tool_profiles import CORE_READ_GROUP, TOOL_GROUPS
from monitor.lib import code_symbols as cs
from monitor.lib.optional_deps import OptionalDependencyError


SAMPLE_PY = '''\
class Greeter:
    def hello(self, name: str) -> str:
        return f"hi {name}"

def top_level(a, b=1):
    return a + b

async def agen():
    return 1
'''

SAMPLE_JS = '''\
export function foo(a) {
  return a;
}
class Bar {
  baz() { return 1; }
}
const arrow = (x) => x;
'''

SAMPLE_GO = '''\
package main

func Hello(x int) string { return "" }

type Foo struct{}
'''

SAMPLE_RS = '''\
pub fn hello(x: i32) -> i32 { x }

struct Foo { x: i32 }

impl Foo {
    fn bar(&self) {}
}
'''

SAMPLE_SWIFT = '''\
import Foundation

public class Greeter {
    public func hello(name: String) -> String {
        return "hi \\(name)"
    }
}

struct Foo {
    var x: Int
    func bar() {}
}

enum Kind {
    case a
}

protocol P {
    func f()
}

func topLevel(_ x: Int) -> Int { x }

extension Greeter {
    func extra() {}
}
'''


@pytest.fixture()
def repo_tmp(tmp_path, monkeypatch):
    """Temp dir that looks like a git repo; cwd set there."""
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _write(repo: Path, rel: str, content: str) -> Path:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_file_outline_registered_in_tools_and_core_read():
    assert "file_outline" in AVAILABLE_TOOLS
    assert AVAILABLE_TOOLS["file_outline"] is cs.file_outline
    assert "file_outline" in TOOL_GROUPS[CORE_READ_GROUP]
    names = {
        entry["function"]["name"]
        for entry in TOOL_DESCRIPTIONS
        if entry.get("type") == "function" and "function" in entry
    }
    assert "file_outline" in names


def test_detect_language_by_extension():
    assert cs.detect_language("a.py") == "python"
    assert cs.detect_language("a.ts") == "typescript"
    assert cs.detect_language("a.tsx") == "tsx"
    assert cs.detect_language("a.go") == "go"
    assert cs.detect_language("a.rs") == "rust"
    assert cs.detect_language("a.swift") == "swift"
    assert cs.detect_language("a.txt") is None


def test_python_outline_extracts_classes_functions_methods(repo_tmp):
    _write(repo_tmp, "sample.py", SAMPLE_PY)
    result = cs.file_outline("sample.py")
    assert result["ok"] is True
    assert result["language"] == "python"
    names = {s["name"] for s in result["symbols"]}
    assert names == {"Greeter", "hello", "top_level", "agen"}
    kinds = {s["name"]: s["kind"] for s in result["symbols"]}
    assert kinds["Greeter"] == "class"
    assert kinds["hello"] == "method"
    assert kinds["top_level"] == "function"
    assert kinds["agen"] == "function"
    assert "sample.py:" in result["outline"]
    assert "def top_level" in result["outline"]
    assert "class Greeter" in result["outline"]
    hello = next(s for s in result["symbols"] if s["name"] == "hello")
    assert "-> str" in hello["signature"]


def test_kind_and_max_results_bounds(repo_tmp):
    _write(repo_tmp, "sample.py", SAMPLE_PY)
    only_fns = cs.file_outline("sample.py", kind="function")
    assert only_fns["ok"] is True
    assert {s["kind"] for s in only_fns["symbols"]} == {"function"}

    capped = cs.file_outline("sample.py", max_results=2)
    assert capped["ok"] is True
    assert capped["count"] == 2
    assert capped["truncated"] is True
    assert capped["total_matched"] >= 2

    bad_kind = cs.file_outline("sample.py", kind="widget")
    assert bad_kind["ok"] is False
    assert "invalid kind" in bad_kind["error"]


def test_javascript_go_rust_outlines(repo_tmp):
    _write(repo_tmp, "a.js", SAMPLE_JS)
    js = cs.file_outline("a.js")
    assert js["ok"] is True
    js_names = {s["name"] for s in js["symbols"]}
    assert "foo" in js_names
    assert "Bar" in js_names
    assert "baz" in js_names

    _write(repo_tmp, "a.go", SAMPLE_GO)
    go = cs.file_outline("a.go")
    assert go["ok"] is True
    go_names = {s["name"] for s in go["symbols"]}
    assert "Hello" in go_names
    assert "Foo" in go_names

    _write(repo_tmp, "a.rs", SAMPLE_RS)
    rs = cs.file_outline("a.rs")
    assert rs["ok"] is True
    rs_names = {s["name"] for s in rs["symbols"]}
    assert "hello" in rs_names
    assert "Foo" in rs_names
    assert "bar" in rs_names


def test_swift_outline_extracts_ios_shapes(repo_tmp):
    _write(repo_tmp, "Greeter.swift", SAMPLE_SWIFT)
    result = cs.file_outline("Greeter.swift")
    assert result["ok"] is True
    assert result["language"] == "swift"
    by_name = {s["name"]: s for s in result["symbols"]}
    greeter_class = next(
        s for s in result["symbols"] if s["name"] == "Greeter" and s["kind"] == "class"
    )
    assert "class Greeter" in greeter_class["signature"] or greeter_class["signature"].startswith(
        "public class Greeter"
    )
    assert by_name["Foo"]["kind"] == "type"  # struct
    assert by_name["Kind"]["kind"] == "type"  # enum
    assert by_name["P"]["kind"] == "type"  # protocol
    assert by_name["hello"]["kind"] == "method"
    assert by_name["bar"]["kind"] == "method"
    assert by_name["f"]["kind"] == "method"
    assert by_name["topLevel"]["kind"] == "function"
    assert by_name["extra"]["kind"] == "method"
    assert any(s["name"] == "Greeter" and "extension" in s["signature"] for s in result["symbols"])
    assert "hello" in result["outline"]


def test_unsupported_language_message(repo_tmp):
    _write(repo_tmp, "notes.md", "# hi\n")
    result = cs.file_outline("notes.md")
    assert result["ok"] is False
    assert "unsupported language" in result["error"]


def test_missing_path_and_outside_repo(repo_tmp, tmp_path_factory):
    missing = cs.file_outline("nope.py")
    assert missing["ok"] is False
    assert "does not exist" in missing["error"]

    outside = tmp_path_factory.mktemp("outside")
    outsider = outside / "x.py"
    outsider.write_text("def f():\n    pass\n", encoding="utf-8")
    blocked = cs.file_outline(str(outsider))
    assert blocked["ok"] is False
    assert "outside the repository" in blocked["error"]


def test_missing_dependency_returns_install_hint(repo_tmp):
    _write(repo_tmp, "sample.py", SAMPLE_PY)

    def boom(module_name, *, feature=None):
        raise OptionalDependencyError(
            "Missing optional dependency for code symbols / file outlines. "
            "Install the 'symbols' extra with: pip install 'monitor_rdegraci2025[symbols]'"
        )

    with patch.object(cs, "import_optional", side_effect=boom):
        # extract path goes through import_optional inside extract/load
        with patch("monitor.lib.code_symbols.import_optional", side_effect=boom):
            result = cs.file_outline("sample.py")
    assert result["ok"] is False
    assert "symbols" in result["error"]
    assert "pip install" in result["error"]


def test_symbol_record_schema_round_trip():
    record = cs.SymbolRecord(
        name="top_level",
        kind="function",
        line=6,
        path="sample.py",
        signature="def top_level(a, b=1)",
        language="python",
    )
    line = record.format_line()
    assert line == "sample.py:6  def top_level(a, b=1)"
