"""Shared ChromaDB client helpers for inspection and editing.

This module provides a generic, serializable interface for working with
embedded ChromaDB databases through ``chromadb.PersistentClient``. It is
intended to serve both the CLI tool and, later, LLM-callable wrappers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from monitor.lib.optional_deps import import_optional


class ChromaClientError(RuntimeError):
    """Raised when a Chroma operation cannot be completed."""


def create_client(path: str | Path) -> Any:
    """Create a persistent Chroma client for the given database path.

    Args:
        path: Path to the Chroma database directory.

    Returns:
        A configured persistent Chroma client.
    """
    chromadb = import_optional("chromadb", feature="ChromaDB")
    db_path = Path(path).expanduser()
    return chromadb.PersistentClient(path=str(db_path))


def list_collections(path: str | Path) -> dict[str, Any]:
    """List available collections in the target database.

    Args:
        path: Path to the Chroma database directory.

    Returns:
        A serializable dictionary describing the collections.
    """
    client = create_client(path)
    collections = client.list_collections()
    return {
        "path": str(Path(path).expanduser()),
        "collections": [_serialize_collection(collection) for collection in collections],
    }


def inspect_collection(path: str | Path, collection_name: str) -> dict[str, Any]:
    """Inspect a collection and return basic metadata and samples.

    Args:
        path: Path to the Chroma database directory.
        collection_name: Collection to inspect.

    Returns:
        A serializable dictionary with collection details.
    """
    collection = _get_collection(path, collection_name)
    payload = collection.get()
    records = _serialize_records(payload)
    return {
        "path": str(Path(path).expanduser()),
        "collection": collection_name,
        "count": len(records),
        "records": records,
    }


def query_collection(
    path: str | Path,
    collection_name: str,
    query_text: str,
    n_results: int = 10,
) -> dict[str, Any]:
    """Run a semantic query against a collection.

    Args:
        path: Path to the Chroma database directory.
        collection_name: Collection to query.
        query_text: Query text to search for.
        n_results: Maximum number of results to return.

    Returns:
        A serializable dictionary with query matches.
    """
    collection = _get_collection(path, collection_name)
    result = collection.query(query_texts=[query_text], n_results=n_results)
    return {
        "path": str(Path(path).expanduser()),
        "collection": collection_name,
        "query_text": query_text,
        "n_results": n_results,
        "results": _serialize_query_result(result),
    }


def get_documents_by_id(
    path: str | Path,
    collection_name: str,
    ids: list[str],
) -> dict[str, Any]:
    """Fetch documents from a collection by exact ID.

    Args:
        path: Path to the Chroma database directory.
        collection_name: Collection to query.
        ids: Collection IDs to fetch.

    Returns:
        A serializable dictionary with fetched records.
    """
    collection = _get_collection(path, collection_name)
    result = collection.get(ids=ids)
    return {
        "path": str(Path(path).expanduser()),
        "collection": collection_name,
        "ids": ids,
        "records": _serialize_records(result),
    }


def dump_collection(
    path: str | Path,
    collection_name: str,
) -> dict[str, Any]:
    """Dump a collection in a JSON-serializable structure.

    Args:
        path: Path to the Chroma database directory.
        collection_name: Collection to dump.

    Returns:
        A serializable dictionary with the full collection contents.
    """
    collection = _get_collection(path, collection_name)
    result = collection.get()
    return {
        "path": str(Path(path).expanduser()),
        "collection": collection_name,
        "count": len(result.get("ids", [])),
        "records": _serialize_records(result),
    }


def delete_by_id(
    path: str | Path,
    collection_name: str,
    ids: list[str],
) -> dict[str, Any]:
    """Delete documents from a collection by exact ID.

    Args:
        path: Path to the Chroma database directory.
        collection_name: Collection to modify.
        ids: Collection IDs to delete.

    Returns:
        A serializable dictionary describing the deletion.
    """
    collection = _get_collection(path, collection_name)
    collection.delete(ids=ids)
    return {
        "path": str(Path(path).expanduser()),
        "collection": collection_name,
        "deleted_ids": ids,
    }


def replace_by_id(
    path: str | Path,
    collection_name: str,
    ids: list[str],
    documents: list[str],
    metadatas: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Replace documents in a collection by exact ID.

    Args:
        path: Path to the Chroma database directory.
        collection_name: Collection to modify.
        ids: IDs to replace.
        documents: Replacement documents.
        metadatas: Optional replacement metadata.

    Returns:
        A serializable dictionary describing the replacement.
    """
    if len(ids) != len(documents):
        raise ChromaClientError("ids and documents must have the same length.")
    if metadatas is not None and len(metadatas) != len(ids):
        raise ChromaClientError("metadatas must match ids length when provided.")

    collection = _get_collection(path, collection_name)
    existing = collection.get(ids=ids)
    existing_ids = existing.get("ids", []) or []
    if len(existing_ids) != len(ids):
        missing_ids = sorted(set(ids) - set(existing_ids))
        raise ChromaClientError(
            f"Cannot replace missing document ID(s): {', '.join(missing_ids)}"
        )

    updated_payload: dict[str, Any] = {
        "ids": ids,
        "documents": documents,
    }
    if metadatas is not None:
        updated_payload["metadatas"] = metadatas

    collection.update(**updated_payload)
    return {
        "path": str(Path(path).expanduser()),
        "collection": collection_name,
        "replaced_ids": ids,
    }


def write_json(payload: dict[str, Any], output_path: str | Path | None = None) -> str:
    """Serialize a payload to JSON or write it to disk.

    Args:
        payload: Serializable payload to emit.
        output_path: Optional output file path.

    Returns:
        The formatted JSON string.
    """
    text = json.dumps(payload, indent=2, sort_keys=True)
    if output_path is not None:
        Path(output_path).expanduser().write_text(text + "\n", encoding="utf-8")
    return text


def _get_collection(path: str | Path, collection_name: str):
    """Return a Chroma collection for the given path and name.

    Args:
        path: Path to the Chroma database directory.
        collection_name: Collection name to open.

    Returns:
        The requested Chroma collection.
    """
    client = create_client(path)
    return client.get_collection(collection_name)


def _serialize_collection(collection: Any) -> dict[str, Any]:
    """Serialize a Chroma collection object.

    Args:
        collection: Chroma collection object.

    Returns:
        A serializable dictionary.
    """
    name = getattr(collection, "name", None)
    return {"name": name}


def _serialize_records(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Serialize Chroma result records into plain dictionaries.

    Args:
        result: Chroma get/query result dictionary.

    Returns:
        A list of serializable record dictionaries.
    """
    ids = result.get("ids", []) or []
    documents = result.get("documents", []) or []
    metadatas = result.get("metadatas", []) or []
    embeddings = result.get("embeddings", []) or []
    records: list[dict[str, Any]] = []
    for index, doc_id in enumerate(ids):
        record: dict[str, Any] = {"id": doc_id}
        if index < len(documents):
            record["document"] = documents[index]
        if index < len(metadatas):
            record["metadata"] = metadatas[index]
        if index < len(embeddings):
            record["embedding"] = embeddings[index]
        records.append(record)
    return records


def _serialize_query_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Serialize Chroma query results into plain dictionaries.

    Args:
        result: Chroma query result dictionary.

    Returns:
        A list of serializable query result dictionaries.
    """
    ids = result.get("ids", []) or []
    documents = result.get("documents", []) or []
    metadatas = result.get("metadatas", []) or []
    distances = result.get("distances", []) or []
    if not ids:
        return []

    doc_rows = documents[0] if documents else []
    metadata_rows = metadatas[0] if metadatas else []
    distance_rows = distances[0] if distances else []
    query_results: list[dict[str, Any]] = []
    for index, doc_id in enumerate(ids[0]):
        record: dict[str, Any] = {"id": doc_id}
        if index < len(doc_rows):
            record["document"] = doc_rows[index]
        if index < len(metadata_rows):
            record["metadata"] = metadata_rows[index]
        if index < len(distance_rows):
            record["distance"] = distance_rows[index]
        query_results.append(record)
    return query_results
