"""Tests for PLAN_SYMBOLD Phase 1 file outlines and Phase 2 find_symbol."""

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
    """Temp dir that is a real git repo; cwd set there."""
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
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
    assert "find_symbol" in AVAILABLE_TOOLS
    assert AVAILABLE_TOOLS["find_symbol"] is cs.find_symbol
    assert "find_symbol" in TOOL_GROUPS[CORE_READ_GROUP]
    names = {
        entry["function"]["name"]
        for entry in TOOL_DESCRIPTIONS
        if entry.get("type") == "function" and "function" in entry
    }
    assert "file_outline" in names
    assert "find_symbol" in names


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


# --- Phase 2: find_symbol -------------------------------------------------


@pytest.fixture()
def symbol_cache_isolation(tmp_path, monkeypatch):
    """Point disk cache at a temp dir and clear memory between tests."""
    cache_root = tmp_path / "cache"
    cache_root.mkdir()

    class _FakeAppdirs:
        @staticmethod
        def user_cache_dir(_name):
            return str(cache_root)

    monkeypatch.setattr("monitor._stubs.appdirs", _FakeAppdirs)
    cs.clear_symbol_cache()
    yield cache_root
    cs.clear_symbol_cache()


def test_find_symbol_ranks_exact_before_prefix_and_substring(repo_tmp, symbol_cache_isolation):
    _write(
        repo_tmp,
        "a.py",
        "def execute_tool_call():\n    pass\n\ndef execute_tool():\n    pass\n\ndef tool_call_helper():\n    pass\n",
    )
    _write(repo_tmp, "b.py", "def execute_tool_call_extra():\n    pass\n")
    result = cs.find_symbol("execute_tool_call", path=".")
    assert result["ok"] is True
    names = [m["name"] for m in result["matches"]]
    assert names[0] == "execute_tool_call"
    assert "execute_tool_call_extra" in names
    # exact before prefix; substring (tool_call_helper) last among matches if present
    exact_idx = names.index("execute_tool_call")
    prefix_idx = names.index("execute_tool_call_extra")
    assert exact_idx < prefix_idx


def test_find_symbol_kind_and_path_scope(repo_tmp, symbol_cache_isolation):
    _write(repo_tmp, "pkg/alpha.py", "class Alpha:\n    def meth(self):\n        pass\n\ndef alpha_fn():\n    pass\n")
    _write(repo_tmp, "pkg/beta.py", "def alpha_fn():\n    pass\n")
    _write(repo_tmp, "other/gamma.py", "def alpha_fn():\n    pass\n")

    scoped = cs.find_symbol("alpha_fn", path="pkg")
    assert scoped["ok"] is True
    paths = {m["path"] for m in scoped["matches"]}
    assert any(p.endswith("pkg/alpha.py") or p.endswith("pkg\\alpha.py") for p in paths)
    assert not any("other" in p for p in paths)

    classes = cs.find_symbol("Alpha", path=".", kind="class")
    assert classes["ok"] is True
    assert classes["count"] >= 1
    assert all(m["kind"] == "class" for m in classes["matches"])


def test_find_symbol_skips_gitignored_and_excluded_dirs(repo_tmp, symbol_cache_isolation):
    _write(repo_tmp, ".gitignore", "ignored_dir/\nsecret.py\nnode_modules/\n")
    _write(repo_tmp, "visible.py", "def keep_me():\n    pass\n")
    _write(repo_tmp, "secret.py", "def keep_me():\n    pass\n")
    _write(repo_tmp, "ignored_dir/hidden.py", "def keep_me():\n    pass\n")
    _write(repo_tmp, "node_modules/lib.py", "def keep_me():\n    pass\n")

    result = cs.find_symbol("keep_me", path=".")
    assert result["ok"] is True
    paths = {m["path"].replace("\\", "/") for m in result["matches"]}
    assert any(p.endswith("visible.py") for p in paths)
    assert not any(p.endswith("secret.py") for p in paths)
    assert not any("ignored_dir/" in p for p in paths)
    assert not any("node_modules/" in p for p in paths)


def test_find_symbol_cache_hit_on_second_query(repo_tmp, symbol_cache_isolation):
    _write(repo_tmp, "cached.py", "def cache_target():\n    pass\n")
    cs.clear_symbol_cache()
    first = cs.find_symbol("cache_target", path=".")
    assert first["ok"] is True
    assert first["cache_hits"] == 0
    stats_after_miss = cs.symbol_cache_stats()
    assert stats_after_miss["misses"] >= 1

    second = cs.find_symbol("cache_target", path=".")
    assert second["ok"] is True
    assert second["cache_hits"] >= 1
    assert second["count"] == first["count"]


def test_find_symbol_cache_invalidates_on_mtime_change(repo_tmp, symbol_cache_isolation):
    path = _write(repo_tmp, "mutable.py", "def old_name():\n    pass\n")
    cs.clear_symbol_cache()
    before = cs.find_symbol("old_name", path=".")
    assert before["count"] >= 1

    path.write_text("def new_name():\n    pass\n", encoding="utf-8")
    # Ensure mtime changes on coarse filesystems.
    import os
    import time

    os.utime(path, (time.time() + 2, time.time() + 2))

    after_old = cs.find_symbol("old_name", path=".")
    after_new = cs.find_symbol("new_name", path=".")
    assert after_old["count"] == 0
    assert after_new["count"] >= 1


def test_find_symbol_empty_query_and_outside_repo(repo_tmp, symbol_cache_isolation, tmp_path_factory):
    bad = cs.find_symbol("  ", path=".")
    assert bad["ok"] is False
    assert "query" in bad["error"]

    outside = tmp_path_factory.mktemp("outside")
    (outside / "x.py").write_text("def f():\n    pass\n", encoding="utf-8")
    blocked = cs.find_symbol("f", path=str(outside))
    assert blocked["ok"] is False
    assert "outside" in blocked["error"]


def test_symbols_command_reports_languages_and_cache(capsys, monkeypatch):
    from monitor.lib.built_in_commands import symbols_command

    monkeypatch.setattr(
        cs,
        "symbol_dependency_status",
        lambda: {"tree_sitter": True, "tree_sitter_swift": True},
    )
    symbols_command("")
    out = capsys.readouterr().out
    assert "Symbol tools: ready" in out
    assert "swift: .swift" in out
    assert "Symbol cache (process)" in out
    assert "Session symbols:" in out


def test_system_prompt_guides_symbols_without_injecting_a_map():
    from monitor.lib.system_prompt import SYSTEM_PROMPT_TEMPLATE

    assert "use find_symbol" in SYSTEM_PROMPT_TEMPLATE
    assert "use file_outline" in SYSTEM_PROMPT_TEMPLATE
    assert "textual references" in SYSTEM_PROMPT_TEMPLATE
    assert "repository symbol map:" not in SYSTEM_PROMPT_TEMPLATE.lower()
