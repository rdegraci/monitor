# CHROMA-DB HOWTO

This guide shows how to use `chroma-db` to inspect a local embedded ChromaDB
database (default path `./chromadb`).

## Prerequisites

Install the optional Chroma extra so `chromadb` and the `chroma-db` entrypoint
are available:

```sh
pip install '.[chroma]'
```

Then either use the installed command or the repo launcher:

```bash
chroma-db list-collections
# or, from the repo root:
./bin/chroma-db list-collections
```

Both call `monitor.lib.chroma_cli:main`. Without the `chroma` extra, imports fail
with an install hint.

## What the tool does

`chroma-db` examines and edits embedded ChromaDB databases. It can:

- list collections
- inspect a collection
- dump a collection to JSON
- query a collection
- fetch documents by ID
- delete documents by ID
- replace documents by ID

## Default database path

If you do not pass `--path`, the tool uses `./chromadb` by default.

```bash
chroma-db list-collections
```

## Common commands

### 1. List collections

```bash
chroma-db list-collections
```

### 2. Inspect a collection

```bash
chroma-db inspect-collection --name lore
```

Shows collection contents in a structured form, including document IDs,
documents, and metadata.

### 3. Dump a collection

```bash
chroma-db dump-collection --name lore --output-file lore.json
```

When `--output-file` is provided, the command writes JSON to that file and prints
nothing. Omit it to print JSON to stdout:

```bash
chroma-db dump-collection --name lore
```

### 4. Query a collection

```bash
chroma-db query --name lore --text "Marissa family"
chroma-db query --name lore --text "Marissa family" --n-results 5
```

### 5. Fetch records by ID

```bash
chroma-db get-by-id --name lore --id lore_123
chroma-db get-by-id --name lore --id lore_123 --id lore_456
```

### 6. Delete records by ID

```bash
chroma-db delete-by-id --name lore --id lore_123 --yes
```

Use `--yes` to skip the confirmation prompt.

### 7. Replace records by ID

```bash
chroma-db replace-by-id --name lore --id lore_123 --file replacement.txt --yes
```

For multiple IDs, repeat `--id` and `--file` in the same order:

```bash
chroma-db replace-by-id --name lore --id lore_123 --file replacement-123.txt --id lore_456 --file replacement-456.txt --yes
```

## Using a different database path

```bash
chroma-db --path /path/to/chromadb list-collections
```

## Using a different collection

```bash
chroma-db --path ./chromadb inspect-collection --name other_collection
```

Or set a shared default with `--collection`:

```bash
chroma-db --path ./chromadb --collection lore query --text "castle gate"
```

## Recommended workflow

1. List collections.
2. Inspect the collection you care about.
3. Dump the collection if you want a full offline view.
4. Query for specific records.
5. Use delete or replace only when you intend to modify data.

## Help

```bash
chroma-db --help
chroma-db query --help
```

Invoking `chroma-db` with no subcommand fails with an argparse required-argument
error (exit 2). Use `--help` for usage.

## Notes

- Uses embedded ChromaDB through `chromadb.PersistentClient`.
- Schema-agnostic: works with any local Chroma DB directory.
- `dump-collection` writes to a file when `--output-file` is provided.
- `delete-by-id` and `replace-by-id` prompt unless `--yes` is used.
- Implementation reference: [`CHROMA_DB.md`](CHROMA_DB.md).
