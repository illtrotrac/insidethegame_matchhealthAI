"""Shared state for agent handoffs.

`InMemoryStore` is used locally and in tests. `CosmosStore` is the Azure
implementation (Cosmos DB free tier) — same interface.
"""

from __future__ import annotations

import os
from typing import Protocol


class StateStore(Protocol):
    def put(self, moment_id: str, stage: str, payload: dict) -> None: ...
    def get(self, moment_id: str) -> dict: ...
    def moments(self) -> list[dict]: ...


class InMemoryStore:
    def __init__(self) -> None:
        self._data: dict[str, dict] = {}

    def put(self, moment_id: str, stage: str, payload: dict) -> None:
        self._data.setdefault(moment_id, {"id": moment_id})[stage] = payload

    def get(self, moment_id: str) -> dict:
        return self._data.get(moment_id, {})

    def moments(self) -> list[dict]:
        # Narrator documents (pre-match, checkpoints, recap) share the store
        # but aren't moments; only trigger-backed docs are.
        return [d for d in self._data.values() if "trigger" in d]


# The latest catch-up snapshot, one document in its own partition, so the
# negotiate service can hand a new viewer the whole match so far with their
# connection token instead of a blank page until the next catch-up.
LIVE_PARTITION = "live"
_container = None


def _live_container():
    global _container
    if _container is None:
        from azure.cosmos import CosmosClient
        from azure.identity import DefaultAzureCredential

        client = CosmosClient(os.environ["COSMOS_ENDPOINT"], DefaultAzureCredential())
        db = client.get_database_client(os.environ.get("COSMOS_DATABASE", "matchhealth"))
        _container = db.get_container_client(os.environ.get("COSMOS_CONTAINER", "moments"))
    return _container


def save_live_snapshot(catchup: dict) -> None:
    import time
    _live_container().upsert_item({"id": "latest", "match_id": LIVE_PARTITION,
                                   "saved_at": time.time(), "catchup": catchup})


def load_live_snapshot() -> dict | None:
    try:
        doc = _live_container().read_item("latest", partition_key=LIVE_PARTITION)
    except Exception:
        return None
    return {"saved_at": doc.get("saved_at"), "catchup": doc.get("catchup")}


class CosmosStore:
    """One document per moment, partitioned by match id. Each stage is a field."""

    def __init__(self, match_id: str) -> None:
        from azure.cosmos import CosmosClient  # optional dependency
        from azure.identity import DefaultAzureCredential

        client = CosmosClient(os.environ["COSMOS_ENDPOINT"], DefaultAzureCredential())
        db = client.get_database_client(os.environ.get("COSMOS_DATABASE", "matchhealth"))
        self._c = db.get_container_client(os.environ.get("COSMOS_CONTAINER", "moments"))
        self._match_id = match_id

    def put(self, moment_id: str, stage: str, payload: dict) -> None:
        doc = self.get(moment_id) or {"id": moment_id, "match_id": self._match_id}
        doc[stage] = payload
        self._c.upsert_item(doc)

    def get(self, moment_id: str) -> dict:
        try:
            return self._c.read_item(moment_id, partition_key=self._match_id)
        except Exception:
            return {}

    def moments(self) -> list[dict]:
        return list(self._c.query_items(
            "SELECT * FROM c WHERE c.match_id = @m AND IS_DEFINED(c.trigger)",
            parameters=[{"name": "@m", "value": self._match_id}],
            partition_key=self._match_id,
        ))
