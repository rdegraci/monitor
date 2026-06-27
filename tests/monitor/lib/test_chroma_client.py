"""Tests for the shared ChromaDB client helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from monitor.lib import chroma_client


class FakeCollection:
    """Minimal fake Chroma collection for tests."""

    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        self.payload = payload or {
            "ids": ["doc-1"],
            "documents": ["document one"],
            "metadatas": [{"kind": "test"}],
        }
        self.updated_payload: dict[str, Any] | None = None
        self.deleted_ids: list[str] = []

    def get(self, ids: list[str] | None = None) -> dict[str, Any]:
        if ids is None:
            return self.payload
        filtered_ids: list[str] = []
        filtered_documents: list[str] = []
        filtered_metadatas: list[dict[str, Any]] = []
        for index, doc_id in enumerate(self.payload.get("ids", [])):
            if doc_id in ids:
                filtered_ids.append(doc_id)
                filtered_documents.append(self.payload.get("documents", [])[index])
                filtered_metadatas.append(self.payload.get("metadatas", [])[index])
        return {
            "ids": filtered_ids,
            "documents": filtered_documents,
            "metadatas": filtered_metadatas,
        }

    def query(self, query_texts: list[str], n_results: int) -> dict[str, Any]:
        return {
            "ids": [["doc-1"]],
            "documents": [["matched document"]],
            "metadatas": [[{"kind": "match"}]],
            "distances": [[0.123]],
        }

    def delete(self, ids: list[str]) -> None:
        self.deleted_ids = ids

    def update(self, **payload: Any) -> None:
        self.updated_payload = payload

    def add(self, **payload: Any) -> None:
        self.updated_payload = payload


class FakeClient:
    """Minimal fake Chroma client for tests."""

    def __init__(self, collections: dict[str, FakeCollection]) -> None:
        self.collections = collections
        self.created_names: list[str] = []

    def list_collections(self) -> list[Any]:
        return [type("Collection", (), {"name": name})() for name in self.collections]

    def get_collection(self, name: str) -> FakeCollection:
        return self.collections[name]

    def get_or_create_collection(self, name: str) -> FakeCollection:
        self.created_names.append(name)
        return self.collections.setdefault(name, FakeCollection())


@pytest.fixture()
def fake_collection(monkeypatch: pytest.MonkeyPatch) -> FakeCollection:
    """Provide a fake collection and patch the client factory."""
    collection = FakeCollection()
    fake_client = FakeClient({"lore": collection})
    monkeypatch.setattr(chroma_client, "create_client", lambda path: fake_client)
    return collection


def test_list_collections_returns_serializable_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """List collections should return a serializable payload."""
    fake_client = FakeClient({"lore": FakeCollection()})
    monkeypatch.setattr(chroma_client, "create_client", lambda path: fake_client)

    payload = chroma_client.list_collections("./chromadb")

    assert payload["path"].endswith("chromadb")
    assert payload["collections"] == [{"name": "lore"}]


def test_inspect_collection_returns_records(fake_collection: FakeCollection) -> None:
    """Inspecting a collection should return record details."""
    payload = chroma_client.inspect_collection("./chromadb", "lore")

    assert payload["collection"] == "lore"
    assert payload["count"] == 1
    assert payload["records"][0]["id"] == "doc-1"
    assert payload["records"][0]["document"] == "document one"


def test_query_collection_returns_matches(fake_collection: FakeCollection) -> None:
    """Querying should serialize query results."""
    payload = chroma_client.query_collection("./chromadb", "lore", "hello", 5)

    assert payload["collection"] == "lore"
    assert payload["results"][0]["id"] == "doc-1"
    assert payload["results"][0]["document"] == "matched document"
    assert payload["results"][0]["distance"] == 0.123


def test_get_documents_by_id_returns_records(fake_collection: FakeCollection) -> None:
    """Fetching by ID should serialize fetched records."""
    payload = chroma_client.get_documents_by_id("./chromadb", "lore", ["doc-1"])

    assert payload["ids"] == ["doc-1"]
    assert payload["records"][0]["id"] == "doc-1"


def test_dump_collection_returns_full_payload(fake_collection: FakeCollection) -> None:
    """Dumping a collection should return the full serialized payload."""
    payload = chroma_client.dump_collection("./chromadb", "lore")

    assert payload["count"] == 1
    assert payload["records"][0]["id"] == "doc-1"


def test_delete_by_id_deletes_requested_ids(fake_collection: FakeCollection) -> None:
    """Deleting by ID should call delete on the collection."""
    payload = chroma_client.delete_by_id("./chromadb", "lore", ["doc-1"])

    assert payload["deleted_ids"] == ["doc-1"]
    assert fake_collection.deleted_ids == ["doc-1"]


def test_replace_by_id_updates_existing_documents(fake_collection: FakeCollection) -> None:
    """Replacing by ID should update existing documents safely."""
    payload = chroma_client.replace_by_id(
        "./chromadb",
        "lore",
        ["doc-1"],
        ["replacement text"],
        [{"kind": "replacement"}],
    )

    assert payload["replaced_ids"] == ["doc-1"]
    assert fake_collection.updated_payload == {
        "ids": ["doc-1"],
        "documents": ["replacement text"],
        "metadatas": [{"kind": "replacement"}],
    }


def test_replace_by_id_rejects_missing_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replacing a missing ID should raise a clear error."""
    collection = FakeCollection({"ids": ["doc-1"], "documents": ["document one"], "metadatas": [{}]})
    fake_client = FakeClient({"lore": collection})
    monkeypatch.setattr(chroma_client, "create_client", lambda path: fake_client)

    with pytest.raises(chroma_client.ChromaClientError, match="Cannot replace missing document ID"):
        chroma_client.replace_by_id("./chromadb", "lore", ["doc-2"], ["replacement"])


def test_write_json_writes_file(tmp_path: Path) -> None:
    """Writing JSON should persist to a file when requested."""
    output_file = tmp_path / "dump.json"
    text = chroma_client.write_json({"hello": "world"}, output_file)

    assert output_file.read_text(encoding="utf-8").strip() == text
    assert '"hello": "world"' in text
