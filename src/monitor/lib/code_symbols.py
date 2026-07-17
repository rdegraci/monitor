"""On-demand source-file symbol outlines (PLAN_SYMBOLD Phase 1).

``file_outline`` uses optional tree-sitter grammars to return a compact,
line-addressable structural outline of one source file. Extraction runs only
when the LLM (or a caller) invokes the tool — nothing is injected into the
system prompt.
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from monitor.lib.optional_deps import OptionalDependencyError, import_optional

logger = logging.getLogger(__name__)

# Hard caps keep tool output token-bounded for the model.
DEFAULT_MAX_RESULTS = 100
MAX_MAX_RESULTS = 500
MAX_OUTLINE_CHARS = 12_000

VALID_KINDS = frozenset({"all", "class", "function", "method", "type"})

# Extension → language id used for grammar selection and unsupported messages.
EXTENSION_TO_LANGUAGE: Dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".rs": "rust",
}

SUPPORTED_LANGUAGES = frozenset(EXTENSION_TO_LANGUAGE.values())

# Map language id → (pip module name, language() accessor attribute or None for .language()).
_LANGUAGE_MODULES: Dict[str, Tuple[str, Optional[str]]] = {
    "python": ("tree_sitter_python", None),
    "javascript": ("tree_sitter_javascript", None),
    "typescript": ("tree_sitter_typescript", "language_typescript"),
    "tsx": ("tree_sitter_typescript", "language_tsx"),
    "go": ("tree_sitter_go", None),
    "rust": ("tree_sitter_rust", None),
}


@dataclass(frozen=True)
class SymbolRecord:
    """Provider-neutral symbol row used by outline and (later) search tools."""

    name: str
    kind: str  # class | function | method | type
    line: int  # 1-based
    path: str
    signature: str = ""
    language: str = ""

    def format_line(self) -> str:
        """Return a single compact outline line for model consumption."""
        sig = self.signature.strip()
        if sig:
            return f"{self.path}:{self.line}  {sig}"
        return f"{self.path}:{self.line}  {self.kind} {self.name}"


def detect_language(path: str | os.PathLike[str]) -> Optional[str]:
    """Return the language id for ``path``, or None when unsupported."""
    suffix = Path(path).suffix.lower()
    return EXTENSION_TO_LANGUAGE.get(suffix)


def _repo_root() -> Optional[str]:
    """Nearest directory containing ``.git``, walking up from cwd; else None."""
    d = os.path.realpath(os.getcwd())
    while True:
        if os.path.isdir(os.path.join(d, ".git")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def resolve_outline_path(path: str) -> Tuple[Optional[str], Optional[str]]:
    """Resolve ``path`` and enforce project-scope / file checks.

    Returns:
        ``(resolved_absolute_path, error_message)``. On success error is None.
    """
    if not isinstance(path, str) or not path.strip():
        return None, "path must be a non-empty string"
    expanded = os.path.realpath(os.path.expanduser(path.strip()))
    if not os.path.exists(expanded):
        return None, f"path does not exist: {path}"
    if not os.path.isfile(expanded):
        return None, f"path is not a file: {path}"
    root = _repo_root()
    if root and expanded != root and not expanded.startswith(root + os.sep):
        return None, f"path is outside the repository working tree: {path}"
    return expanded, None


def _load_language(language_id: str):
    """Load a tree-sitter Language for ``language_id`` or raise OptionalDependencyError."""
    tree_sitter = import_optional("tree_sitter", feature="code symbols / file outlines")
    Language = tree_sitter.Language

    if language_id not in _LANGUAGE_MODULES:
        raise ValueError(f"unsupported language: {language_id}")

    module_name, accessor = _LANGUAGE_MODULES[language_id]
    mod = import_optional(module_name, feature="code symbols / file outlines")
    if accessor:
        language_fn = getattr(mod, accessor)
        return Language(language_fn())
    return Language(mod.language())


def _node_text(source: bytes, node) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _first_child_of_type(node, type_names: Sequence[str]):
    wanted = set(type_names)
    for child in node.children:
        if child.type in wanted:
            return child
    return None


def _python_signature(source: bytes, node, kind: str, name: str) -> str:
    params = _first_child_of_type(node, ("parameters",))
    params_text = _node_text(source, params) if params else "()"
    ret = ""
    seen_params = False
    for child in node.children:
        if child.type == "parameters":
            seen_params = True
            continue
        if not seen_params:
            continue
        if child.type == "->":
            continue
        if child.type in (
            "type",
            "type_identifier",
            "generic_type",
            "binary_operator",
        ):
            ret = f" -> {_node_text(source, child)}"
            break
        if child.type == ":":
            break
    if kind == "class":
        return f"class {name}"
    prefix = "async def" if node.type == "async_function_definition" else "def"
    return f"{prefix} {name}{params_text}{ret}"


def _js_like_signature(source: bytes, node, kind: str, name: str) -> str:
    params = _first_child_of_type(node, ("formal_parameters", "parameters"))
    params_text = _node_text(source, params) if params else "()"
    if kind == "class":
        return f"class {name}"
    if kind == "method":
        return f"{name}{params_text}"
    return f"function {name}{params_text}"


def _go_signature(source: bytes, node, kind: str, name: str) -> str:
    if kind == "type":
        return f"type {name}"
    # function_declaration / method_declaration: keep a short first-line slice.
    line = _node_text(source, node).splitlines()[0].strip()
    if len(line) > 120:
        line = line[:117] + "..."
    return line or f"func {name}"


def _rust_signature(source: bytes, node, kind: str, name: str) -> str:
    if kind in ("type", "class"):
        # struct / enum / trait / impl
        line = _node_text(source, node).splitlines()[0].strip()
        if len(line) > 120:
            line = line[:117] + "..."
        return line or f"{kind} {name}"
    params = _first_child_of_type(node, ("parameters",))
    params_text = _node_text(source, params) if params else "()"
    return f"fn {name}{params_text}"


def _extract_name(source: bytes, node, name_types: Sequence[str]) -> Optional[str]:
    child = _first_child_of_type(node, name_types)
    if child is None:
        # Some nodes nest the name (e.g. type_spec in Go).
        for grandchild in node.children:
            nested = _first_child_of_type(grandchild, name_types)
            if nested is not None:
                return _node_text(source, nested)
        return None
    return _node_text(source, child)


def _python_symbols(source: bytes, root, path: str) -> List[SymbolRecord]:
    records: List[SymbolRecord] = []

    def walk(node, parent_class: Optional[str] = None) -> None:
        ntype = node.type
        if ntype == "class_definition":
            name = _extract_name(source, node, ("identifier",))
            if name:
                records.append(
                    SymbolRecord(
                        name=name,
                        kind="class",
                        line=node.start_point[0] + 1,
                        path=path,
                        signature=_python_signature(source, node, "class", name),
                        language="python",
                    )
                )
            for child in node.children:
                walk(child, parent_class=name or parent_class)
            return
        if ntype in ("function_definition", "async_function_definition"):
            name = _extract_name(source, node, ("identifier",))
            if name:
                kind = "method" if parent_class else "function"
                records.append(
                    SymbolRecord(
                        name=name,
                        kind=kind,
                        line=node.start_point[0] + 1,
                        path=path,
                        signature=_python_signature(source, node, kind, name),
                        language="python",
                    )
                )
            return
        for child in node.children:
            walk(child, parent_class=parent_class)

    walk(root)
    return records


def _js_symbols(source: bytes, root, path: str, language: str) -> List[SymbolRecord]:
    records: List[SymbolRecord] = []

    def walk(node, parent_class: Optional[str] = None) -> None:
        ntype = node.type
        if ntype in ("class_declaration", "class"):
            name = _extract_name(source, node, ("identifier", "type_identifier"))
            if name:
                records.append(
                    SymbolRecord(
                        name=name,
                        kind="class",
                        line=node.start_point[0] + 1,
                        path=path,
                        signature=_js_like_signature(source, node, "class", name),
                        language=language,
                    )
                )
            for child in node.children:
                walk(child, parent_class=name or parent_class)
            return
        if ntype in ("function_declaration", "generator_function_declaration"):
            name = _extract_name(source, node, ("identifier",))
            if name:
                kind = "method" if parent_class else "function"
                records.append(
                    SymbolRecord(
                        name=name,
                        kind=kind,
                        line=node.start_point[0] + 1,
                        path=path,
                        signature=_js_like_signature(source, node, kind, name),
                        language=language,
                    )
                )
            return
        if ntype == "method_definition":
            name = _extract_name(source, node, ("property_identifier", "identifier"))
            if name:
                records.append(
                    SymbolRecord(
                        name=name,
                        kind="method",
                        line=node.start_point[0] + 1,
                        path=path,
                        signature=_js_like_signature(source, node, "method", name),
                        language=language,
                    )
                )
            return
        if ntype == "lexical_declaration" and parent_class is None:
            # const foo = (...) => ... or function expression
            for child in node.children:
                if child.type != "variable_declarator":
                    continue
                name = _extract_name(source, child, ("identifier",))
                value = None
                for gc in child.children:
                    if gc.type in ("arrow_function", "function", "function_expression"):
                        value = gc
                if name and value is not None:
                    records.append(
                        SymbolRecord(
                            name=name,
                            kind="function",
                            line=node.start_point[0] + 1,
                            path=path,
                            signature=_js_like_signature(source, value, "function", name),
                            language=language,
                        )
                    )
        for child in node.children:
            walk(child, parent_class=parent_class)

    walk(root)
    return records


def _go_symbols(source: bytes, root, path: str) -> List[SymbolRecord]:
    records: List[SymbolRecord] = []

    def walk(node) -> None:
        ntype = node.type
        if ntype in ("function_declaration", "method_declaration"):
            name = _extract_name(source, node, ("identifier", "field_identifier"))
            if name:
                kind = "method" if ntype == "method_declaration" else "function"
                records.append(
                    SymbolRecord(
                        name=name,
                        kind=kind,
                        line=node.start_point[0] + 1,
                        path=path,
                        signature=_go_signature(source, node, kind, name),
                        language="go",
                    )
                )
            return
        if ntype == "type_declaration":
            for child in node.children:
                if child.type != "type_spec":
                    continue
                name = _extract_name(source, child, ("type_identifier",))
                if name:
                    records.append(
                        SymbolRecord(
                            name=name,
                            kind="type",
                            line=child.start_point[0] + 1,
                            path=path,
                            signature=_go_signature(source, child, "type", name),
                            language="go",
                        )
                    )
            return
        for child in node.children:
            walk(child)

    walk(root)
    return records


def _rust_symbols(source: bytes, root, path: str) -> List[SymbolRecord]:
    records: List[SymbolRecord] = []

    def walk(node, in_impl: bool = False) -> None:
        ntype = node.type
        if ntype == "function_item":
            name = _extract_name(source, node, ("identifier",))
            if name:
                kind = "method" if in_impl else "function"
                records.append(
                    SymbolRecord(
                        name=name,
                        kind=kind,
                        line=node.start_point[0] + 1,
                        path=path,
                        signature=_rust_signature(source, node, kind, name),
                        language="rust",
                    )
                )
            return
        if ntype in ("struct_item", "enum_item", "trait_item", "type_item"):
            name = _extract_name(source, node, ("type_identifier",))
            if name:
                records.append(
                    SymbolRecord(
                        name=name,
                        kind="type",
                        line=node.start_point[0] + 1,
                        path=path,
                        signature=_rust_signature(source, node, "type", name),
                        language="rust",
                    )
                )
            if ntype == "trait_item":
                for child in node.children:
                    walk(child, in_impl=True)
            return
        if ntype == "impl_item":
            # Surface the impl target as a type-ish anchor, then methods inside.
            name_node = _first_child_of_type(node, ("type_identifier", "generic_type"))
            name = _node_text(source, name_node) if name_node else "impl"
            records.append(
                SymbolRecord(
                    name=name,
                    kind="type",
                    line=node.start_point[0] + 1,
                    path=path,
                    signature=_rust_signature(source, node, "type", name),
                    language="rust",
                )
            )
            for child in node.children:
                walk(child, in_impl=True)
            return
        for child in node.children:
            walk(child, in_impl=in_impl)

    walk(root)
    return records


def extract_symbols_from_source(
    source: bytes,
    *,
    language: str,
    path: str,
) -> List[SymbolRecord]:
    """Parse ``source`` and return ordered symbol records for ``language``."""
    tree_sitter = import_optional("tree_sitter", feature="code symbols / file outlines")
    Parser = tree_sitter.Parser
    language_obj = _load_language(language)
    parser = Parser(language_obj)
    tree = parser.parse(source)
    root = tree.root_node
    if language == "python":
        return _python_symbols(source, root, path)
    if language in ("javascript", "typescript", "tsx"):
        return _js_symbols(source, root, path, language)
    if language == "go":
        return _go_symbols(source, root, path)
    if language == "rust":
        return _rust_symbols(source, root, path)
    return []


def _filter_kind(records: Iterable[SymbolRecord], kind: str) -> List[SymbolRecord]:
    if kind == "all":
        return list(records)
    return [r for r in records if r.kind == kind]


def _display_path(resolved: str) -> str:
    """Prefer a repo-relative path for outline lines when possible."""
    root = _repo_root()
    if root and resolved.startswith(root + os.sep):
        return os.path.relpath(resolved, root)
    cwd = os.path.realpath(os.getcwd())
    if resolved.startswith(cwd + os.sep):
        return os.path.relpath(resolved, cwd)
    return resolved


def _clamp_max_results(max_results: Optional[int]) -> int:
    if max_results is None:
        return DEFAULT_MAX_RESULTS
    try:
        value = int(max_results)
    except (TypeError, ValueError):
        return DEFAULT_MAX_RESULTS
    if value < 1:
        return 1
    return min(value, MAX_MAX_RESULTS)


def format_outline_lines(records: Sequence[SymbolRecord]) -> str:
    """Join symbol records into the compact text outline format."""
    return "\n".join(r.format_line() for r in records)


def file_outline(
    path: str,
    kind: str = "all",
    max_results: int | None = None,
) -> Dict[str, Any]:
    """Return a structural outline of one source file.

    Args:
        path: File to outline (relative or absolute).
        kind: ``all``, ``class``, ``function``, ``method``, or ``type``.
        max_results: Cap on returned symbols (default 100, hard max 500).

    Returns:
        Dict with ``ok``, ``path``, ``language``, ``outline``, ``symbols``,
        ``count``, ``truncated``, and optional ``error``.
    """
    try:
        resolved, path_error = resolve_outline_path(path)
        if path_error:
            return {"ok": False, "error": path_error, "path": path}

        assert resolved is not None
        language = detect_language(resolved)
        if language is None:
            supported = ", ".join(sorted({f"*{ext}" for ext in EXTENSION_TO_LANGUAGE}))
            return {
                "ok": False,
                "error": (
                    f"unsupported language for file outline: {Path(resolved).suffix or '(no extension)'}. "
                    f"Supported extensions: {supported}. Install is not the issue — "
                    "this path's language is not wired yet."
                ),
                "path": _display_path(resolved),
            }

        kind_norm = (kind or "all").strip().lower()
        if kind_norm not in VALID_KINDS:
            return {
                "ok": False,
                "error": (
                    f"invalid kind {kind!r}; expected one of: "
                    + ", ".join(sorted(VALID_KINDS))
                ),
                "path": _display_path(resolved),
            }

        limit = _clamp_max_results(max_results)
        display = _display_path(resolved)

        try:
            with open(resolved, "rb") as handle:
                source = handle.read()
        except OSError as exc:
            return {"ok": False, "error": f"failed to read file: {exc}", "path": display}

        if b"\x00" in source[:8192]:
            return {"ok": False, "error": "refusing to outline binary file", "path": display}

        records = extract_symbols_from_source(source, language=language, path=display)
        filtered = _filter_kind(records, kind_norm)
        truncated = len(filtered) > limit
        limited = filtered[:limit]

        outline = format_outline_lines(limited)
        if len(outline) > MAX_OUTLINE_CHARS:
            # Truncate by lines to stay under the character budget.
            lines: List[str] = []
            size = 0
            for line in outline.splitlines():
                add = len(line) + (1 if lines else 0)
                if size + add > MAX_OUTLINE_CHARS:
                    truncated = True
                    break
                lines.append(line)
                size += add
            outline = "\n".join(lines)
            limited = limited[: len(lines)]

        return {
            "ok": True,
            "path": display,
            "language": language,
            "kind": kind_norm,
            "outline": outline,
            "symbols": [asdict(r) for r in limited],
            "count": len(limited),
            "truncated": truncated,
            "total_matched": len(filtered),
        }
    except OptionalDependencyError as exc:
        return {"ok": False, "error": str(exc), "path": path}
    except Exception as exc:
        logger.exception("file_outline failed for %s", path)
        return {"ok": False, "error": f"file_outline failed: {exc}", "path": path}
