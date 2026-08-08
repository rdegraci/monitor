# CHROMA_DB CLI Tool

Current-state reference for the embedded ChromaDB CLI shipped with Monitor.

For day-to-day usage examples, see [`CHROMA-DB-HOWTO.md`](CHROMA-DB-HOWTO.md).

## Purpose

`chroma-db` provides a simple, inspectable interface for viewing and editing
embedded ChromaDB collections from the terminal. It works with arbitrary local
Chroma databases via `chromadb.PersistentClient` (no REST server required).

Install the optional extra first:

```sh
pip install '.[chroma]'
```

That pins `chromadb==1.0.10` under the `chroma` optional dependency (also
included in `.[all]`). It is not a core package dependency.

## Entry points

| Entry | Role |
| --- | --- |
| `chroma-db` | Installed console script (`monitor.lib.chroma_cli:main` in `pyproject.toml`) |
| `./bin/chroma-db` | Thin repo-local launcher that calls the same `main()` |
| `src/monitor/lib/chroma_cli.py` | Argparse CLI and command dispatch |
| `src/monitor/lib/chroma_client.py` | Reusable Chroma operations |

## Command layout

```bash
chroma-db --help
chroma-db -h
chroma-db list-collections
chroma-db inspect-collection --name lore
chroma-db dump-collection --name lore --output-file lore.json
chroma-db query --name lore --text "Marissa"
chroma-db get-by-id --name lore --id 123
chroma-db delete-by-id --name lore --id 123 --yes
chroma-db replace-by-id --name lore --id 123 --file replacement.txt --yes
```

Default database path is `./chromadb` when `--path` is omitted. Collection-specific
commands accept `--name` or a shared `--collection` default.

## Client API (`chroma_client.py`)

Current public operations:

- `list_collections(path)`
- `inspect_collection(path, collection_name)`
- `query_collection(path, collection_name, query_text, n_results=10)`
- `get_documents_by_id(path, collection_name, ids)`
- `dump_collection(path, collection_name)`
- `delete_by_id(path, collection_name, ids)`
- `replace_by_id(path, collection_name, ids, documents, metadatas=None)`
- `write_json(payload, output_path=None)`

There is no `add_documents` helper today. Destructive CLI commands prompt unless
`--yes` is passed. Dump writes JSON to `--output-file` when provided; otherwise
JSON goes to stdout.

LLM-callable tool wrappers around this client are not registered yet; the client
returns plain serializable dicts/lists so that can be added later without
changing the core operations.

## Behavior notes

- `--help` / `-h` print usage and exit without changing data.
- A required subcommand is mandatory; invoking `chroma-db` with no command exits
  with argparse’s “the following arguments are required: command” error (exit 2),
  not a custom help path.
- Missing required flags for a subcommand print that subcommand’s usage and fail.
- Reads and writes stay on the shared client module; CLI parsing stays in
  `chroma_cli.py`.

## Implementation status

Implemented and wired:

- [x] `src/monitor/lib/chroma_client.py`
- [x] `src/monitor/lib/chroma_cli.py`
- [x] `bin/chroma-db` launcher
- [x] `chroma-db` console script in `pyproject.toml`
- [x] `list-collections`, `inspect-collection`, `query`, `get-by-id`
- [x] `dump-collection` with JSON stdout / `--output-file`
- [x] `delete-by-id`, `replace-by-id` with confirmation / `--yes`
- [x] optional `chromadb==1.0.10` via `.[chroma]`
- [ ] LLM tool registration for these operations (not done)

## Related files

- `bin/chroma-db`
- `src/monitor/lib/chroma_client.py`
- `src/monitor/lib/chroma_cli.py`
- `pyproject.toml` (`[project.optional-dependencies].chroma`, `chroma-db` script)
- [`CHROMA-DB-HOWTO.md`](CHROMA-DB-HOWTO.md)
