# CHROMA-DB HOWTO

This guide shows how to use `chroma-db` to inspect the local `./chromadb` ChromaDB database.

## What the tool does

`chroma-db` is a command-line tool for examining and editing embedded ChromaDB databases.
It can:

- list collections
- inspect a collection
- dump a collection to JSON
- query a collection
- fetch documents by ID
- delete documents by ID
- replace documents by ID

## Default database path

If you do not pass `--path`, the tool uses `./chromadb` by default.
That means you can usually inspect the local database with commands like:

```bash
./bin/chroma-db list-collections
```

## Common commands

### 1. List collections

Show every collection in the database.

```bash
./bin/chroma-db list-collections
```

Use this first when you want to see what collections are available.

### 2. Inspect a collection

Inspect a specific collection by name.

```bash
./bin/chroma-db inspect-collection --name lore
```

This shows the collection contents in a structured form, including document IDs, documents, and metadata.

### 3. Dump a collection

Write the full collection to a JSON file for offline inspection.

```bash
./bin/chroma-db dump-collection --name lore --output-file lore.json
```

When `--output-file` is provided, the command writes the JSON to that file and prints nothing.

If you omit `--output-file`, the JSON is printed to stdout instead:

```bash
./bin/chroma-db dump-collection --name lore
```

### 4. Query a collection

Search for matching records using semantic search.

```bash
./bin/chroma-db query --name lore --text "Marissa family"
```

You can control the number of results with `--n-results`:

```bash
./bin/chroma-db query --name lore --text "Marissa family" --n-results 5
```

### 5. Fetch records by ID

Fetch one or more exact IDs.

```bash
./bin/chroma-db get-by-id --name lore --id lore_123
```

You can repeat `--id` to fetch multiple records:

```bash
./bin/chroma-db get-by-id --name lore --id lore_123 --id lore_456
```

### 6. Delete records by ID

Delete one or more exact IDs.

```bash
./bin/chroma-db delete-by-id --name lore --id lore_123 --yes
```

Use `--yes` to skip the confirmation prompt.

### 7. Replace records by ID

Replace one or more exact IDs using text files as the source content.

```bash
./bin/chroma-db replace-by-id --name lore --id lore_123 --file replacement.txt --yes
```

If you are replacing multiple IDs, repeat both `--id` and `--file` in the same order:

```bash
./bin/chroma-db replace-by-id --name lore --id lore_123 --file replacement-123.txt --id lore_456 --file replacement-456.txt --yes
```

## Using a different database path

If your Chroma database is not in `./chromadb`, pass `--path` explicitly.

```bash
./bin/chroma-db --path /Users/rdegraci/Hack/world-builder/chromadb list-collections
```

## Using a different collection

If you want to inspect a different collection, change `--name`.

```bash
./bin/chroma-db --path ./chromadb inspect-collection --name other_collection
```

If you prefer a shared default for multiple commands, you can also use `--collection`:

```bash
./bin/chroma-db --path ./chromadb --collection lore query --text "castle gate"
```

## Recommended workflow

1. List collections.
2. Inspect the collection you care about.
3. Dump the collection if you want a full offline view.
4. Query for specific records.
5. Use delete or replace only when you are sure you want to modify data.

## Help

Show command help with:

```bash
./bin/chroma-db --help
```

Show subcommand help with:

```bash
./bin/chroma-db query --help
```

## Notes

- The tool works with embedded ChromaDB through `chromadb.PersistentClient`.
- It is designed to work with arbitrary Chroma DBs, not only world-builder.
- `dump-collection` writes to a file when `--output-file` is provided.
- `delete-by-id` and `replace-by-id` prompt for confirmation unless `--yes` is used.
