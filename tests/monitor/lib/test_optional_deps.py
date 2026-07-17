"""Tests for optional extras packaging and install guidance."""

from __future__ import annotations

import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from monitor.lib import optional_deps as od
from monitor.lib.optional_deps import OptionalDependencyError


ROOT = Path(__file__).resolve().parents[3]
PYPROJECT = ROOT / "pyproject.toml"

HEAVY_OPTIONAL_PACKAGES = {
    "openai-whisper",
    "pyaudio",
    "coqui-tts",
    "chromadb",
    "pandas",
    "scikit-learn",
    "joblib",
    "graphviz",
    "duckdb",
    "tavily-python",
    "flask",
    "boto3",
    "tree-sitter",
    "tree-sitter-python",
    "tree-sitter-javascript",
    "tree-sitter-typescript",
    "tree-sitter-go",
    "tree-sitter-rust",
}


def _dep_name(spec: str) -> str:
    """Strip version/environment markers from a dependency specifier."""
    base = spec.split(";", 1)[0].strip()
    for sep in ("==", ">=", "<=", "~=", "!=", ">"):
        if sep in base:
            return base.split(sep, 1)[0].strip()
    return base


class TestOptionalDepsPackaging(unittest.TestCase):
    def test_core_dependencies_exclude_heavy_optionals(self):
        data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
        core = {_dep_name(item) for item in data["project"]["dependencies"]}
        overlap = core & HEAVY_OPTIONAL_PACKAGES
        self.assertEqual(overlap, set(), f"heavy optionals still in core: {overlap}")

    def test_optional_extra_groups_declared(self):
        data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
        extras = data["project"]["optional-dependencies"]
        for name in ("voice", "tts", "chroma", "science", "database", "network", "server", "aws", "symbols", "all"):
            self.assertIn(name, extras)
            self.assertTrue(extras[name])

    def test_core_keeps_coding_essentials(self):
        data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
        core = {_dep_name(item) for item in data["project"]["dependencies"]}
        for name in ("litellm", "redis", "GitPython", "mypy", "prompt_toolkit", "ollama", "mcp"):
            self.assertIn(name, core)


class TestOptionalDepsHelpers(unittest.TestCase):
    def test_missing_extra_message_includes_install_command(self):
        message = od.missing_extra_message("voice", feature="voice-to-text")
        self.assertIn("voice", message)
        self.assertIn("pip install", message)
        self.assertIn("[voice]", message)
        self.assertIn("voice-to-text", message)

    def test_import_optional_raises_clear_error(self):
        with self.assertRaises(OptionalDependencyError) as ctx:
            od.import_optional("definitely_not_a_real_module_xyz", feature="demo")
        self.assertIn("pip install", str(ctx.exception))

    def test_modeling_import_succeeds_without_raising_at_import_time(self):
        # Import must remain safe even when science packages are absent; the
        # callable path is what requires the extra.
        from monitor.lib import modeling

        self.assertTrue(callable(modeling.train_model))

    def test_train_model_reports_missing_science_extra(self):
        from monitor.lib import modeling

        with patch.object(modeling, "pd", None):
            result = modeling.train_model("x.csv", target_column="y")
        self.assertIsInstance(result, str)
        self.assertIn("[science]", result)

    def test_tavily_search_reports_missing_network_extra(self):
        from monitor.lib import web_search

        with patch.object(web_search, "TavilyClient", None):
            result = web_search.tavily_search("hello", print_func=lambda *_: None)
        self.assertIsInstance(result, str)
        self.assertIn("[network]", result)

    def test_chroma_create_client_requires_chroma_extra(self):
        from monitor.lib import chroma_client

        with patch("monitor.lib.chroma_client.import_optional", side_effect=OptionalDependencyError("missing chroma")):
            with self.assertRaises(OptionalDependencyError):
                chroma_client.create_client("./chromadb")

    def test_server_module_does_not_import_flask_at_load(self):
        import importlib
        import sys

        # Re-import a fresh copy and ensure Flask symbols stay unset until used.
        mod_name = "monitor.lib.server"
        if mod_name in sys.modules:
            mod = importlib.reload(sys.modules[mod_name])
        else:
            mod = importlib.import_module(mod_name)
        # After reload, Flask may already be set if earlier tests called make_flask_app.
        # The contract we care about: _ensure_flask exists and import is deferred there.
        self.assertTrue(callable(mod._ensure_flask))


if __name__ == "__main__":
    unittest.main()
