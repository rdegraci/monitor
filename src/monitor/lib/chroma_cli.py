"""Shared CLI entrypoint for the chroma-db tool."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from monitor.lib import chroma_client


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level command-line parser.

    Returns:
        Configured argument parser for the chroma-db CLI.
    """
    parser = argparse.ArgumentParser(
        prog="chroma-db",
        description="Inspect and edit embedded ChromaDB databases.",
    )
    parser.add_argument(
        "--path",
        default="./chromadb",
        help="Path to the Chroma database directory.",
    )
    parser.add_argument(
        "--collection",
        help="Collection name to use by default.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list-collections", help="List available collections.")

    inspect_parser = subparsers.add_parser("inspect-collection", help="Inspect a collection.")
    inspect_parser.add_argument("--name", help="Collection name to inspect.")

    dump_parser = subparsers.add_parser("dump-collection", help="Dump a collection as JSON.")
    dump_parser.add_argument("--name", help="Collection name to dump.")
    dump_parser.add_argument("--output-file", help="Write JSON output to a file.")

    query_parser = subparsers.add_parser("query", help="Query a collection semantically.")
    query_parser.add_argument("--name", help="Collection name to query.")
    query_parser.add_argument("--text", required=True, help="Query text.")
    query_parser.add_argument(
        "--n-results",
        type=int,
        default=10,
        help="Maximum number of results.",
    )

    get_parser = subparsers.add_parser("get-by-id", help="Fetch documents by ID.")
    get_parser.add_argument("--name", help="Collection name to query.")
    get_parser.add_argument(
        "--id",
        dest="ids",
        action="append",
        required=True,
        help="Document ID to fetch. Repeat for multiple IDs.",
    )

    delete_parser = subparsers.add_parser("delete-by-id", help="Delete documents by ID.")
    delete_parser.add_argument("--name", help="Collection name to modify.")
    delete_parser.add_argument(
        "--id",
        dest="ids",
        action="append",
        required=True,
        help="Document ID to delete. Repeat for multiple IDs.",
    )
    delete_parser.add_argument("--yes", action="store_true", help="Skip confirmation prompts.")

    replace_parser = subparsers.add_parser("replace-by-id", help="Replace documents by ID.")
    replace_parser.add_argument("--name", help="Collection name to modify.")
    replace_parser.add_argument(
        "--id",
        dest="ids",
        action="append",
        required=True,
        help="Document ID to replace. Repeat for multiple IDs.",
    )
    replace_parser.add_argument(
        "--file",
        dest="files",
        action="append",
        required=True,
        help="Replacement document file. Repeat for multiple IDs.",
    )
    replace_parser.add_argument("--yes", action="store_true", help="Skip confirmation prompts.")

    return parser


def resolve_collection_name(args: argparse.Namespace) -> str:
    """Resolve the effective collection name from CLI arguments.

    Args:
        args: Parsed CLI arguments.

    Returns:
        The effective collection name.

    Raises:
        SystemExit: If no collection name is available.
    """
    if args.name:
        return args.name
    if args.collection:
        return args.collection
    raise SystemExit("A collection name is required. Use --collection or --name.")


def confirm_destructive_action(message: str, skip_confirmation: bool) -> None:
    """Confirm a destructive action unless confirmation is skipped.

    Args:
        message: Prompt message to display.
        skip_confirmation: Whether to skip the confirmation prompt.
    """
    if skip_confirmation:
        return
    response = input(f"{message} [y/N]: ").strip().lower()
    if response not in {"y", "yes"}:
        raise SystemExit("Aborted.")


def load_documents_from_files(files: list[str]) -> list[str]:
    """Load replacement documents from text files.

    Args:
        files: File paths containing replacement content.

    Returns:
        A list of document strings.
    """
    documents: list[str] = []
    for file_path in files:
        documents.append(Path(file_path).read_text(encoding="utf-8"))
    return documents


def run_command(args: argparse.Namespace) -> dict[str, Any] | None:
    """Execute the selected CLI command.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Optional serializable payload for commands that emit structured data.
    """
    path = args.path
    if args.command == "list-collections":
        return chroma_client.list_collections(path)

    collection_name = resolve_collection_name(args)
    if args.command == "inspect-collection":
        return chroma_client.inspect_collection(path, collection_name)
    if args.command == "dump-collection":
        payload = chroma_client.dump_collection(path, collection_name)
        if args.output_file:
            chroma_client.write_json(payload, args.output_file)
            return None
        return payload
    if args.command == "query":
        return chroma_client.query_collection(path, collection_name, args.text, args.n_results)
    if args.command == "get-by-id":
        return chroma_client.get_documents_by_id(path, collection_name, args.ids)
    if args.command == "delete-by-id":
        confirm_destructive_action(
            f"Delete {len(args.ids)} document(s) from '{collection_name}'?",
            args.yes,
        )
        return chroma_client.delete_by_id(path, collection_name, args.ids)
    if args.command == "replace-by-id":
        if len(args.ids) != len(args.files):
            raise SystemExit("--id and --file must be provided the same number of times.")
        confirm_destructive_action(
            f"Replace {len(args.ids)} document(s) in '{collection_name}'?",
            args.yes,
        )
        documents = load_documents_from_files(args.files)
        return chroma_client.replace_by_id(path, collection_name, args.ids, documents)
    raise SystemExit(f"Unknown command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    """Run the chroma-db command-line interface.

    Args:
        argv: Optional argument vector.

    Returns:
        Process exit code.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = run_command(args)
    except chroma_client.ChromaClientError as exc:
        raise SystemExit(str(exc)) from exc
    except Exception as exc:
        from monitor.lib.optional_deps import OptionalDependencyError

        if isinstance(exc, OptionalDependencyError):
            raise SystemExit(str(exc)) from exc
        raise
    if payload is not None:
        print(chroma_client.write_json(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
