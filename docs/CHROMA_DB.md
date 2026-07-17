# CHROMA_DB CLI Tool

This document describes a small command-line tool wrapper around embedded ChromaDB.
The tool is intended to provide a simple, inspectable interface for viewing and editing
ChromaDB collections from the terminal. It will use `chromadb==1.0.10` and should work with arbitrary Chroma DBs, not just world-builder.

## Purpose

The tool exists to make it easy to:

- list Chroma collections
- inspect collection metadata and sample entries
- dump collection contents for offline inspection
- query documents in a collection
- fetch documents by ID
- delete documents by ID
- replace existing documents by deleting and reinserting chunks

The tool should be implemented as a command-line program in the `bin/` directory with standard help flags:

- `--help`
- `-h`

Running the tool with either flag should print usage information and exit without making any changes.

## Recommended command layout

A practical CLI shape would look like this:

```bash
chroma-db --help
chroma-db -h
chroma-db list-collections
chroma-db inspect-collection --name lore
chroma-db dump-collection --name lore --output-file lore.json
chroma-db query --name lore --text "Marissa"
chroma-db get-by-id --name lore --id 123
chroma-db delete-by-id --name lore --id 123
chroma-db replace-by-id --name lore --id 123 --file replacement.txt
```

## Suggested capabilities

### 1. List collections

Shows all available Chroma collections and their basic metadata.

Example:

```bash
chroma-db list-collections
```

### 2. Inspect a collection

Displays collection stats such as:

- collection name
- document count
- sample IDs
- sample metadata
- persistence details

Example:

```bash
chroma-db inspect-collection --name lore
```

### 3. Dump a collection

Exports the full collection so it can be inspected offline or compared against a later state.
The dump should include document IDs, documents, and metadata, and it should support writing to a file via `--output-file`. When `--output-file` is provided, the command should write the JSON to that file and print nothing.

Example:

```bash
chroma-db dump-collection --name lore --output-file lore.json
```

### 4. Query a collection

Runs a semantic search against a collection and returns:

- matching document IDs
- documents
- metadata
- distances or similarity scores, if available

Example:

```bash
chroma-db query --name lore --text "Marissa family"
```

### 5. Fetch by ID

Retrieves one or more items by exact ID.

Example:

```bash
chroma-db get-by-id --name lore --id lore_123
```

### 6. Delete by ID

Deletes a specific document or chunk.

Example:

```bash
chroma-db delete-by-id --name lore --id lore_123
```

### 7. Replace by ID

A safe replace flow should generally:

1. fetch the existing entry
2. show what will change
3. delete the old chunks
4. insert the replacement text

Example:

```bash
chroma-db replace-by-id --name lore --id lore_123 --file replacement.txt
```

## Implementation notes

- The tool should talk to embedded ChromaDB through `chromadb.PersistentClient`.
- It should not depend on a REST server or HTTP transport.
- Use clear error messages and non-zero exit codes for failures.
- Keep reads and writes separate where possible.
- Prefer explicit confirmation for destructive edits.
- `--help` and `-h` should always work.

## Proposed client interface

The underlying Python module should be a generic, LLM-friendly Chroma client in `src/monitor/lib/chroma_client.py`.
It should be shaped so it can later be registered into the app's LLM tool subsystem, and the primary implementation should use `chromadb.PersistentClient`.
The LLM-callable wrapper should live in the same `chroma_client.py` file if the feature stays small, as long as it returns plain serializable Python data.

Recommended capabilities:

- `list_collections()` — return available collections
- `inspect_collection(name)` — return collection metadata and sample data
- `query_collection(name, query_text, n_results=10)` — semantic search against a collection
- `get_documents_by_id(name, ids)` — fetch one or more exact IDs
- `delete_documents_by_id(name, ids)` — delete one or more exact IDs
- `replace_documents_by_id(name, ids, documents, metadatas=None)` — delete old docs and insert replacements
- `add_documents(name, documents, ids=None, metadatas=None)` — optional generic insert support

Design goals:

- keep the tool generic, not lore-specific
- return plain Python dictionaries/lists so an LLM tool wrapper can serialize them easily
- validate inputs explicitly and fail with clear messages
- avoid hidden assumptions about schema or metadata beyond what Chroma accepts
- support local ChromaDB access through embedded `PersistentClient`
- keep the wrapper thin so the same Python module can serve both CLI use and LLM tool use if needed

## Implementation plan

1. create `src/monitor/lib/chroma_client.py`
2. implement the `bin/chroma-db` script
3. add `list-collections`
4. add `inspect-collection`
5. add `get-by-id`
6. add `query`
7. add `dump-collection` with JSON output and optional `--output`
8. add `delete-by-id`
9. add `replace-by-id`

Why this order works:

- it front-loads the shared client and the simplest reads
- it proves collection access before adding mutations
- it postpones the more error-prone write operations until the foundation is stable

## Implementation checklist

- [ ] create `src/monitor/lib/chroma_client.py`
- [ ] implement the `chroma-db` script
- [ ] add `list-collections`
- [ ] add `inspect-collection`
- [ ] add `query`
- [ ] add `get-by-id`
- [ ] add `dump-collection` with JSON output and optional `--output`
- [ ] add `delete-by-id`
- [ ] add `replace-by-id`
- [ ] keep the client/wrapper surface reusable for a later LLM tool

## Relevant code locations

- `bin/chroma-db` — CLI script entrypoint
- `src/monitor/lib/chroma_client.py` — shared Chroma client logic and LLM-callable wrapper
- `src/monitor/lib/chroma_cli.py` — future shared CLI main module for the installed entrypoint and repo-local script
- `pyproject.toml` — pinned `chromadb` dependency and future console script entrypoint
- `bootstrap.py` in world-builder — existing embedded Chroma bootstrap example
- `cli.py` and `commands/` in world-builder — existing CLI dispatch pattern for reference
- `tests/` in world-builder — existing test locations for reference and future coverage

## Packaging and install notes

- `pip install -e .` can expose `chroma-db` on PATH if the project declares a console script entrypoint in `pyproject.toml`.
- The repository-local `bin/chroma-db` script and the installed `chroma-db` command should both call the same Python `main()` function.
- The CLI logic should stay separate from the core Chroma client logic so the future LLM-callable wrapper can import and reuse the same Chroma operations directly.
- Keeping the layers separate will not interfere with future LLM integration; it should make that integration cleaner.

File responsibilities:

- `src/monitor/lib/chroma_client.py` should contain the reusable Chroma operations, including list, inspect, query, get, dump, delete, replace, and the future thin LLM-callable wrappers.
- `src/monitor/lib/chroma_cli.py` should hold the shared CLI `main()` function and command parsing/dispatch so both the repo-local script and the installed command can call the same entrypoint.
- `bin/chroma-db` should be a thin repo-local launcher that invokes the shared CLI entrypoint.
- `pyproject.toml` should expose the installed `chroma-db` command via a console script entrypoint.

## Open decisions

- make `--path` optional with a sensible default unless strict path selection is needed for safety
- default `--path` to `./chromadb` when omitted
- require or default `--collection` on read/write commands, while allowing `list-collections` to operate without it
- require `--collection` for collection-specific commands unless a command explicitly documents a broader scope
- use a stable JSON dump structure with collection name, count, records, and optional embeddings
- write `dump-collection` JSON to the file named by `--output-file` and print JSON to stdout when no output file is provided
- require explicit confirmation or `--yes` / `--force` for destructive operations
- keep the tool generic so it assumes no world-builder-specific metadata or schema
- implement the LLM-callable wrapper as thin, direct functions in `chroma_client.py`
- build the tool as a standalone utility first and defer tighter world-builder integration until later

## Final spec

`chroma-db` should be a direct repo script in `bin/` that works against arbitrary embedded ChromaDB databases via `chromadb.PersistentClient`. It should support generic collection inspection and editing with `--path` and `--collection` options, provide read commands (`list-collections`, `inspect-collection`, `query`, `get-by-id`, `dump-collection`), and write commands (`delete-by-id`, `replace-by-id`) with safe destructive-operation handling. The implementation should live mainly in `src/monitor/lib/chroma_client.py`, which can also host thin LLM-callable wrapper functions for later tool registration. The design should stay schema-agnostic so it works for world-builder and any other Chroma DB, with JSON-based dump output and a simple, reusable code path.

## Checklist

- [x] use embedded `chromadb.PersistentClient`
- [x] refer to `pyproject.toml` for the pinned dependency
- [x] keep the document aligned with the embedded Chroma design
- [x] use the `chroma-db` command name
- [x] keep the implementation as a direct repo script rather than a Python package entrypoint
- [x] scope the first implementation to v1+v2 together

## Expected help behavior

The help output should include:

- tool name
- a short description
- available subcommands
- common flags
- database path and collection selection options such as a default collection name

Example:

```bash
Usage: chroma-db [OPTIONS] COMMAND [ARGS]...

Options:
  -h, --help        Show this message and exit.
  --path TEXT       Path to the Chroma database directory.
  --collection TEXT Collection name to use by default.

Commands:
  list-collections
  inspect-collection
  dump-collection
  query
  get-by-id
  delete-by-id
  replace-by-id
```

## Suggested default behavior

If no command is supplied, the tool should print help.

If a command is supplied without required arguments, the tool should print the relevant command help and exit with an error.

## Notes for this project

This repo currently uses embedded Chroma through `chromadb.PersistentClient(...)` in `bootstrap.py`.
The collection is created with `client.get_or_create_collection("lore", embedding_function=embedder)` and stored in `context['chroma_collection']`.
Lore operations in `lore.py` expect collection methods such as `add`, `get`, `query`, and `delete`, with result dictionaries that include keys like `documents`, `metadatas`, and `ids`.
The local project pins `chromadb==1.0.10` in `pyproject.toml`.
This tool is intended to work with embedded Chroma via `chromadb.PersistentClient(...)`.
That makes it easier to inspect and edit the database from inside the main app.
