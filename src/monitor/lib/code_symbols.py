"""On-demand source-file symbol outlines and repository symbol search.

Phase 1: ``file_outline`` — structural outline of one source file.
Phase 2: ``find_symbol`` — ranked name lookup across a file or directory.

Both use optional tree-sitter grammars and run only when invoked — nothing is
injected into the system prompt.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from monitor.lib.optional_deps import OptionalDependencyError, import_optional

logger = logging.getLogger(__name__)

# Hard caps keep tool output token-bounded for the model.
DEFAULT_MAX_RESULTS = 100
DEFAULT_FIND_MAX_RESULTS = 50
MAX_MAX_RESULTS = 500
MAX_OUTLINE_CHARS = 12_000
MAX_FIND_CHARS = 12_000
MAX_FILES_TO_PARSE = 10_000

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
    ".swift": "swift",
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
    "swift": ("tree_sitter_swift", None),
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
        sig = " ".join(self.signature.split()) if self.signature else ""
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


def _swift_first_line(source: bytes, node) -> str:
    line = _node_text(source, node).splitlines()[0].strip()
    if len(line) > 120:
        return line[:117] + "..."
    return line


def _swift_type_keyword(node) -> Optional[str]:
    """Return class/struct/enum/extension keyword child for a class_declaration."""
    for child in node.children:
        if child.type in ("class", "struct", "enum", "extension"):
            return child.type
    return None


def _swift_symbols(source: bytes, root, path: str) -> List[SymbolRecord]:
    """Extract Swift classes, structs, enums, protocols, extensions, and funcs."""
    records: List[SymbolRecord] = []

    def walk(node, parent_type: Optional[str] = None) -> None:
        ntype = node.type
        if ntype == "class_declaration":
            keyword = _swift_type_keyword(node) or "class"
            if keyword == "extension":
                name_node = _first_child_of_type(node, ("user_type", "type_identifier"))
                if name_node and name_node.type == "user_type":
                    name = _extract_name(source, name_node, ("type_identifier",)) or _node_text(
                        source, name_node
                    )
                else:
                    name = _node_text(source, name_node) if name_node else "extension"
                kind = "type"
            else:
                name = _extract_name(source, node, ("type_identifier",))
                kind = "class" if keyword == "class" else "type"
            if name:
                prefix = keyword
                records.append(
                    SymbolRecord(
                        name=name,
                        kind=kind,
                        line=node.start_point[0] + 1,
                        path=path,
                        signature=_swift_first_line(source, node) or f"{prefix} {name}",
                        language="swift",
                    )
                )
            for child in node.children:
                walk(child, parent_type=name or parent_type)
            return
        if ntype == "protocol_declaration":
            name = _extract_name(source, node, ("type_identifier",))
            if name:
                records.append(
                    SymbolRecord(
                        name=name,
                        kind="type",
                        line=node.start_point[0] + 1,
                        path=path,
                        signature=_swift_first_line(source, node) or f"protocol {name}",
                        language="swift",
                    )
                )
            for child in node.children:
                walk(child, parent_type=name or parent_type)
            return
        if ntype in ("function_declaration", "protocol_function_declaration"):
            name = _extract_name(source, node, ("simple_identifier",))
            if name:
                kind = "method" if parent_type else "function"
                records.append(
                    SymbolRecord(
                        name=name,
                        kind=kind,
                        line=node.start_point[0] + 1,
                        path=path,
                        signature=_swift_first_line(source, node) or f"func {name}",
                        language="swift",
                    )
                )
            return
        for child in node.children:
            walk(child, parent_type=parent_type)

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
    if language == "swift":
        return _swift_symbols(source, root, path)
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


# ---------------------------------------------------------------------------
# Phase 2 — repository symbol search
# ---------------------------------------------------------------------------

# In-process cache: abspath -> entry dict. Disk cache mirrors this per repo.
_MEMORY_SYMBOL_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_STATS = {"hits": 0, "misses": 0}


def clear_symbol_cache() -> None:
    """Clear the in-memory symbol cache (tests / diagnostics)."""
    _MEMORY_SYMBOL_CACHE.clear()
    _CACHE_STATS["hits"] = 0
    _CACHE_STATS["misses"] = 0


def symbol_cache_stats() -> Dict[str, int]:
    """Return payload-free cache hit/miss counters."""
    return dict(_CACHE_STATS)


def symbol_dependency_status() -> Dict[str, bool]:
    """Return module-presence flags without raising or loading repository data."""
    from monitor.lib.optional_deps import load_optional

    modules = {"tree_sitter"}
    modules.update(module_name for module_name, _accessor in _LANGUAGE_MODULES.values())
    return {module: load_optional(module) is not None for module in sorted(modules)}


def _symbol_cache_dir() -> Path:
    from monitor._stubs import appdirs

    base = Path(appdirs.user_cache_dir("monitor")) / "symbols"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _disk_cache_path(repo_root: Optional[str]) -> Path:
    key = repo_root or os.path.realpath(os.getcwd())
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return _symbol_cache_dir() / f"{digest}.json"


def _load_disk_cache(repo_root: Optional[str]) -> Dict[str, Dict[str, Any]]:
    path = _disk_cache_path(repo_root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("files"), dict):
            return data["files"]
    except (OSError, json.JSONDecodeError, TypeError):
        logger.debug("Failed to load symbol disk cache %s", path, exc_info=True)
    return {}


def _save_disk_cache(repo_root: Optional[str], files: Dict[str, Dict[str, Any]]) -> None:
    path = _disk_cache_path(repo_root)
    try:
        payload = {
            "version": 1,
            "repo_root": repo_root,
            "updated_at": time.time(),
            "files": files,
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        logger.debug("Failed to save symbol disk cache %s", path, exc_info=True)


def _file_stat_key(abspath: str) -> Optional[Tuple[int, int]]:
    try:
        st = os.stat(abspath)
        return (int(st.st_mtime_ns), int(st.st_size))
    except OSError:
        return None


def _records_from_cache_entry(entry: Dict[str, Any], display_path: str) -> List[SymbolRecord]:
    records = []
    for item in entry.get("symbols") or []:
        if not isinstance(item, dict):
            continue
        records.append(
            SymbolRecord(
                name=str(item.get("name", "")),
                kind=str(item.get("kind", "function")),
                line=int(item.get("line", 1) or 1),
                path=display_path,
                signature=str(item.get("signature", "")),
                language=str(item.get("language", "")),
            )
        )
    return records


def _symbols_for_absolute_file(
    abspath: str,
    *,
    display_path: str,
    disk_cache: Dict[str, Dict[str, Any]],
) -> Tuple[List[SymbolRecord], bool]:
    """Return symbols for one file, using memory/disk cache when fresh.

    Returns:
        ``(records, cache_hit)``.
    """
    language = detect_language(abspath)
    if language is None:
        return [], False

    stat_key = _file_stat_key(abspath)
    if stat_key is None:
        return [], False
    mtime_ns, size = stat_key

    mem = _MEMORY_SYMBOL_CACHE.get(abspath)
    if (
        mem
        and mem.get("mtime_ns") == mtime_ns
        and mem.get("size") == size
        and mem.get("language") == language
    ):
        _CACHE_STATS["hits"] += 1
        return _records_from_cache_entry(mem, display_path), True

    disk = disk_cache.get(abspath)
    if (
        disk
        and disk.get("mtime_ns") == mtime_ns
        and disk.get("size") == size
        and disk.get("language") == language
    ):
        _MEMORY_SYMBOL_CACHE[abspath] = disk
        _CACHE_STATS["hits"] += 1
        return _records_from_cache_entry(disk, display_path), True

    _CACHE_STATS["misses"] += 1
    try:
        with open(abspath, "rb") as handle:
            source = handle.read()
    except OSError:
        return [], False
    if b"\x00" in source[:8192]:
        return [], False

    try:
        records = extract_symbols_from_source(source, language=language, path=display_path)
    except OptionalDependencyError:
        raise
    except Exception:
        logger.debug("Symbol extract failed for %s", abspath, exc_info=True)
        return [], False

    entry = {
        "mtime_ns": mtime_ns,
        "size": size,
        "language": language,
        "symbols": [
            {
                "name": r.name,
                "kind": r.kind,
                "line": r.line,
                "signature": r.signature,
                "language": r.language,
            }
            for r in records
        ],
    }
    _MEMORY_SYMBOL_CACHE[abspath] = entry
    disk_cache[abspath] = entry
    return records, False


def _git_tracked_files(repo_root: str) -> Optional[List[str]]:
    """Return repo-relative source paths via git, respecting ``.gitignore``.

    Uses ``git ls-files --cached --others --exclude-standard`` so tracked and
    untracked-but-not-ignored files are included. Returns None when git fails.
    """
    try:
        from git import Repo

        repo = Repo(repo_root, search_parent_directories=False)
        out = repo.git.ls_files("--cached", "--others", "--exclude-standard")
    except Exception:
        logger.debug("git ls-files unavailable under %s", repo_root, exc_info=True)
        return None
    if not out.strip():
        return []
    return [line for line in out.splitlines() if line.strip()]


def _walk_source_files(scope_root: str) -> List[str]:
    """Fallback enumeration when git is unavailable."""
    from monitor.lib.find_files import DEFAULT_EXCLUDED_DIRS

    results: List[str] = []
    for dirpath, dirnames, filenames in os.walk(scope_root, followlinks=False):
        dirnames[:] = [
            d
            for d in dirnames
            if d not in DEFAULT_EXCLUDED_DIRS and not d.startswith(".")
        ]
        for filename in filenames:
            if filename.startswith("."):
                continue
            full = os.path.join(dirpath, filename)
            if detect_language(full) is None:
                continue
            results.append(full)
    return results


def resolve_search_scope(path: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Resolve a search scope to ``(scope_abs, error, mode)``.

    ``mode`` is ``file`` or ``directory``.
    """
    if not isinstance(path, str) or not path.strip():
        return None, "path must be a non-empty string", None
    expanded = os.path.realpath(os.path.expanduser(path.strip()))
    if not os.path.exists(expanded):
        return None, f"path does not exist: {path}", None
    repo = _repo_root()
    if repo and expanded != repo and not expanded.startswith(repo + os.sep):
        return None, f"path is outside the repository working tree: {path}", None
    if os.path.isfile(expanded):
        return expanded, None, "file"
    if os.path.isdir(expanded):
        return expanded, None, "directory"
    return None, f"path is neither a file nor a directory: {path}", None


def enumerate_source_files(scope_abs: str, mode: str) -> Tuple[List[str], bool]:
    """List absolute source files under scope.

    Returns:
        ``(files, truncated)`` where truncated means the file cap was hit.
    """
    if mode == "file":
        if detect_language(scope_abs) is None:
            return [], False
        return [scope_abs], False

    def _in_scope(abspath: str) -> bool:
        if abspath == scope_abs:
            return True
        prefix = scope_abs.rstrip(os.sep) + os.sep
        return abspath.startswith(prefix)

    files: List[str] = []
    truncated = False
    repo = _repo_root()

    if repo is not None:
        tracked = _git_tracked_files(repo)
        if tracked is not None:
            for rel in tracked:
                abspath = os.path.realpath(os.path.join(repo, rel))
                if not _in_scope(abspath):
                    continue
                if detect_language(abspath) is None:
                    continue
                if not os.path.isfile(abspath):
                    continue
                files.append(abspath)
                if len(files) >= MAX_FILES_TO_PARSE:
                    truncated = True
                    break
            return files, truncated

    for abspath in _walk_source_files(scope_abs):
        files.append(abspath)
        if len(files) >= MAX_FILES_TO_PARSE:
            truncated = True
            break
    return files, truncated


def _match_rank(name: str, query: str) -> Optional[int]:
    """Return 0 exact / 1 prefix / 2 substring / None no match (case-insensitive)."""
    if not query:
        return None
    n = name.lower()
    q = query.lower()
    if n == q:
        return 0
    if n.startswith(q):
        return 1
    if q in n:
        return 2
    return None


def rank_symbol_matches(
    records: Iterable[SymbolRecord],
    query: str,
) -> List[Tuple[int, SymbolRecord]]:
    """Filter and rank records for ``query``; lower rank is better."""
    ranked: List[Tuple[int, SymbolRecord]] = []
    for record in records:
        rank = _match_rank(record.name, query)
        if rank is None:
            continue
        ranked.append((rank, record))
    ranked.sort(key=lambda item: (item[0], item[1].path.lower(), item[1].line, item[1].name.lower()))
    return ranked


def _clamp_find_max_results(max_results: Optional[int]) -> int:
    if max_results is None:
        return DEFAULT_FIND_MAX_RESULTS
    try:
        value = int(max_results)
    except (TypeError, ValueError):
        return DEFAULT_FIND_MAX_RESULTS
    if value < 1:
        return 1
    return min(value, MAX_MAX_RESULTS)


def find_symbol(
    query: str,
    path: str = ".",
    kind: str = "all",
    max_results: int | None = None,
) -> Dict[str, Any]:
    """Find symbols by name across a file or directory tree.

    Args:
        query: Symbol name or fragment to match (exact, then prefix, then substring).
        path: File or directory scope (default cwd / ``.``).
        kind: ``all``, ``class``, ``function``, ``method``, or ``type``.
        max_results: Cap on returned hits (default 50, hard max 500).

    Returns:
        Dict with ``ok``, ``query``, ``path``, ``matches`` / ``outline``,
        ``count``, ``truncated``, cache stats, and optional ``error``.
    """
    try:
        if not isinstance(query, str) or not query.strip():
            return {"ok": False, "error": "query must be a non-empty string", "query": query}

        query_clean = query.strip()
        scope_abs, scope_error, mode = resolve_search_scope(path)
        if scope_error:
            return {"ok": False, "error": scope_error, "query": query_clean, "path": path}
        assert scope_abs is not None and mode is not None

        kind_norm = (kind or "all").strip().lower()
        if kind_norm not in VALID_KINDS:
            return {
                "ok": False,
                "error": (
                    f"invalid kind {kind!r}; expected one of: "
                    + ", ".join(sorted(VALID_KINDS))
                ),
                "query": query_clean,
                "path": path,
            }

        limit = _clamp_find_max_results(max_results)
        repo = _repo_root()
        disk_cache = _load_disk_cache(repo)
        files, files_truncated = enumerate_source_files(scope_abs, mode)

        ranked: List[Tuple[int, SymbolRecord]] = []
        files_scanned = 0
        cache_hits = 0
        for abspath in files:
            display = _display_path(abspath)
            try:
                records, hit = _symbols_for_absolute_file(
                    abspath, display_path=display, disk_cache=disk_cache
                )
            except OptionalDependencyError:
                raise
            files_scanned += 1
            if hit:
                cache_hits += 1
            filtered = _filter_kind(records, kind_norm)
            ranked.extend(rank_symbol_matches(filtered, query_clean))

        # Persist any newly filled cache entries outside the repo.
        _save_disk_cache(repo, disk_cache)

        ranked.sort(key=lambda item: (item[0], item[1].path.lower(), item[1].line, item[1].name.lower()))
        total_matched = len(ranked)
        limited_records = [rec for _rank, rec in ranked[:limit]]
        truncated = total_matched > limit or files_truncated

        outline = format_outline_lines(limited_records)
        if len(outline) > MAX_FIND_CHARS:
            lines: List[str] = []
            size = 0
            for line in outline.splitlines():
                add = len(line) + (1 if lines else 0)
                if size + add > MAX_FIND_CHARS:
                    truncated = True
                    break
                lines.append(line)
                size += add
            outline = "\n".join(lines)
            limited_records = limited_records[: len(lines)]

        return {
            "ok": True,
            "query": query_clean,
            "path": _display_path(scope_abs) if mode == "directory" else _display_path(scope_abs),
            "kind": kind_norm,
            "outline": outline,
            "matches": [asdict(r) for r in limited_records],
            "symbols": [asdict(r) for r in limited_records],
            "count": len(limited_records),
            "truncated": truncated,
            "total_matched": total_matched,
            "files_scanned": files_scanned,
            "cache_hits": cache_hits,
            "files_truncated": files_truncated,
        }
    except OptionalDependencyError as exc:
        return {"ok": False, "error": str(exc), "query": query, "path": path}
    except Exception as exc:
        logger.exception("find_symbol failed for query=%r path=%r", query, path)
        return {"ok": False, "error": f"find_symbol failed: {exc}", "query": query, "path": path}
