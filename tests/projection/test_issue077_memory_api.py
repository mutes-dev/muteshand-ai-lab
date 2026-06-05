"""
CATEGORY: PROJECTION
AUTHORITY_LAYER: Memory API Validation (ISSUE-077)
VALIDATES:
  - Memory API endpoints call only memory_store primitives
  - Validation errors return HTTP 400
  - Scope isolation (GLOBAL vs PROJECT)
  - Reset ALL requires confirm_all
  - Authority isolation (no orchestrator/governance/projection calls)
ENTRYPOINT: FastAPI TestClient integration tests
DIRECT_INTERNAL_CALLS:
  - ai_lab_gui.backend.api (memory endpoints)
  - system.memory.memory_store
  - system.memory.schema
MONKEYPATCH_USAGE: YES (authority isolation verification)
MOCKING_POLICY: REAL_EXECUTION for memory store; monkeypatch for authority isolation
TEST_INTENT: VALIDATION
ARCHITECTURAL_SCOPE: Memory inspection + edit/reset surface

---

ISSUE-077 — Memory Inspection + Edit/Reset Surface
"""

import json
import os
import pytest
from fastapi.testclient import TestClient

from system.memory import memory_store
from system.memory.schema import (
    SCOPE_GLOBAL,
    SCOPE_PROJECT,
    CATEGORY_BEHAVIOR,
    CATEGORY_PREFERENCE,
    CATEGORY_PATTERN,
    CATEGORY_CONTEXT,
)


def _clean_test_stores():
    """Remove test store files to ensure clean state."""
    from tests._test_safety_guard import guard_delete
    paths = [memory_store.GLOBAL_STORE_PATH]
    for p in paths:
        if os.path.exists(p):
            try:
                guard_delete(p)
            except Exception:
                pass
    if os.path.exists(memory_store.PROJECTS_DIR):
        for fname in os.listdir(memory_store.PROJECTS_DIR):
            if fname.endswith(".json"):
                try:
                    guard_delete(os.path.join(memory_store.PROJECTS_DIR, fname))
                except Exception:
                    pass


@pytest.fixture(autouse=True)
def clean_stores():
    _clean_test_stores()
    yield
    _clean_test_stores()


@pytest.fixture(scope="module")
def client():
    """Create a TestClient for the FastAPI app."""
    from ai_lab_gui.backend.api import app
    # Do NOT trigger startup — it runs initialize_system() which is heavy
    # and not needed for memory-only tests. Use a fresh client per test.
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ─── 1. List Endpoints ──────────────────────────────────────────────────────


class TestMemoryList:

    def test_list_global_empty(self, client):
        res = client.get("/memory/list?scope=GLOBAL")
        assert res.status_code == 200
        assert res.json()["entries"] == []

    def test_list_project_empty(self, client):
        res = client.get("/memory/list?scope=PROJECT&project_id=test-proj")
        assert res.status_code == 200
        assert res.json()["entries"] == []

    def test_list_global_with_entries(self, client):
        memory_store.write(SCOPE_GLOBAL, "g1", "v1", CATEGORY_BEHAVIOR)
        res = client.get("/memory/list?scope=GLOBAL")
        assert res.status_code == 200
        data = res.json()
        assert len(data["entries"]) == 1
        assert data["entries"][0]["key"] == "g1"

    def test_list_project_with_entries(self, client):
        memory_store.write(SCOPE_PROJECT, "p1", "v1", CATEGORY_PREFERENCE, project_id="proj-list")
        res = client.get("/memory/list?scope=PROJECT&project_id=proj-list")
        assert res.status_code == 200
        data = res.json()
        assert len(data["entries"]) == 1
        assert data["entries"][0]["key"] == "p1"

    def test_list_by_category(self, client):
        memory_store.write(SCOPE_GLOBAL, "b", "bv", CATEGORY_BEHAVIOR)
        memory_store.write(SCOPE_GLOBAL, "p", "pv", CATEGORY_PREFERENCE)
        res = client.get("/memory/list?scope=GLOBAL&category=behavior")
        assert res.status_code == 200
        data = res.json()
        assert len(data["entries"]) == 1
        assert data["entries"][0]["key"] == "b"

    def test_list_invalid_scope_returns_400(self, client):
        res = client.get("/memory/list?scope=INVALID")
        assert res.status_code == 400
        assert "invalid_scope" in res.json()["detail"]

    def test_list_global_with_project_id_returns_400(self, client):
        res = client.get("/memory/list?scope=GLOBAL&project_id=some-id")
        assert res.status_code == 400
        assert "project_id must not be provided" in res.json()["detail"]

    def test_list_project_without_project_id_returns_400(self, client):
        res = client.get("/memory/list?scope=PROJECT")
        assert res.status_code == 400
        assert "project_id required" in res.json()["detail"]

    def test_list_invalid_category_returns_400(self, client):
        res = client.get("/memory/list?scope=GLOBAL&category=invalid")
        assert res.status_code == 400
        assert "invalid_category" in res.json()["detail"]


# ─── 2. Read Endpoint ───────────────────────────────────────────────────────


class TestMemoryRead:

    def test_read_existing_global(self, client):
        memory_store.write(SCOPE_GLOBAL, "read-test", "val", CATEGORY_CONTEXT)
        res = client.get("/memory/read?scope=GLOBAL&key=read-test")
        assert res.status_code == 200
        assert res.json()["key"] == "read-test"
        assert res.json()["value"] == "val"

    def test_read_existing_project(self, client):
        memory_store.write(SCOPE_PROJECT, "read-proj", "pv", CATEGORY_PATTERN, project_id="proj-read")
        res = client.get("/memory/read?scope=PROJECT&key=read-proj&project_id=proj-read")
        assert res.status_code == 200
        assert res.json()["key"] == "read-proj"

    def test_read_not_found_returns_404(self, client):
        res = client.get("/memory/read?scope=GLOBAL&key=missing")
        assert res.status_code == 404
        assert "memory_entry_not_found" in res.json()["detail"]

    def test_read_invalid_scope_returns_400(self, client):
        res = client.get("/memory/read?scope=BAD&key=k")
        assert res.status_code == 400
        assert "invalid_scope" in res.json()["detail"]

    def test_read_global_with_project_id_returns_400(self, client):
        res = client.get("/memory/read?scope=GLOBAL&key=k&project_id=p")
        assert res.status_code == 400
        assert "project_id must not be provided" in res.json()["detail"]

    def test_read_project_without_project_id_returns_400(self, client):
        res = client.get("/memory/read?scope=PROJECT&key=k")
        assert res.status_code == 400
        assert "project_id required" in res.json()["detail"]


# ─── 3. Write Endpoint ──────────────────────────────────────────────────────


class TestMemoryWrite:

    def test_write_global(self, client):
        res = client.post("/memory/write", json={
            "scope": "GLOBAL",
            "key": "w1",
            "value": "hello",
            "category": "context",
        })
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert data["entry"]["key"] == "w1"
        assert data["entry"]["scope"] == "GLOBAL"
        assert data["entry"]["source"] == "user"

    def test_write_project(self, client):
        res = client.post("/memory/write", json={
            "scope": "PROJECT",
            "key": "w2",
            "value": "project-val",
            "category": "behavior",
            "project_id": "proj-write",
        })
        assert res.status_code == 200
        assert res.json()["entry"]["project_id"] == "proj-write"

    def test_write_replaces_existing(self, client):
        memory_store.write(SCOPE_GLOBAL, "replace", "old", CATEGORY_CONTEXT)
        res = client.post("/memory/write", json={
            "scope": "GLOBAL",
            "key": "replace",
            "value": "new",
            "category": "context",
        })
        assert res.status_code == 200
        read = memory_store.read(SCOPE_GLOBAL, "replace")
        assert read["value"] == "new"

    def test_write_invalid_scope_returns_400(self, client):
        res = client.post("/memory/write", json={
            "scope": "INVALID",
            "key": "k",
            "value": "v",
            "category": "context",
        })
        assert res.status_code == 400
        assert "invalid_scope" in res.json()["detail"]

    def test_write_invalid_category_returns_400(self, client):
        res = client.post("/memory/write", json={
            "scope": "GLOBAL",
            "key": "k",
            "value": "v",
            "category": "unknown",
        })
        assert res.status_code == 400
        assert "invalid_category" in res.json()["detail"]

    def test_write_invalid_confidence_returns_400(self, client):
        res = client.post("/memory/write", json={
            "scope": "GLOBAL",
            "key": "k",
            "value": "v",
            "category": "context",
            "confidence": 1.5,
        })
        assert res.status_code == 400
        assert "invalid_confidence" in res.json()["detail"]

    def test_write_global_with_project_id_returns_400(self, client):
        res = client.post("/memory/write", json={
            "scope": "GLOBAL",
            "key": "k",
            "value": "v",
            "category": "context",
            "project_id": "p",
        })
        assert res.status_code == 400
        assert "project_id must not be provided" in res.json()["detail"]

    def test_write_project_without_project_id_returns_400(self, client):
        res = client.post("/memory/write", json={
            "scope": "PROJECT",
            "key": "k",
            "value": "v",
            "category": "context",
        })
        assert res.status_code == 400
        assert "project_id required" in res.json()["detail"]

    def test_write_invalid_source_returns_400(self, client):
        res = client.post("/memory/write", json={
            "scope": "GLOBAL",
            "key": "k",
            "value": "v",
            "category": "context",
            "source": "invalid",
        })
        assert res.status_code == 400
        assert "invalid_source" in res.json()["detail"]


# ─── 4. Update Endpoint ─────────────────────────────────────────────────────


class TestMemoryUpdate:

    def test_update_existing(self, client):
        memory_store.write(SCOPE_GLOBAL, "up", "old", CATEGORY_CONTEXT, editable=True)
        res = client.post("/memory/update", json={
            "scope": "GLOBAL",
            "key": "up",
            "value": "new",
        })
        assert res.status_code == 200
        assert res.json()["entry"]["value"] == "new"

    def test_update_not_found_returns_400(self, client):
        res = client.post("/memory/update", json={
            "scope": "GLOBAL",
            "key": "missing",
            "value": "new",
        })
        assert res.status_code == 400
        assert "memory_update_failed" in res.json()["detail"]

    def test_update_non_editable_returns_400(self, client):
        memory_store.write(SCOPE_GLOBAL, "locked", "orig", CATEGORY_CONTEXT, editable=False)
        res = client.post("/memory/update", json={
            "scope": "GLOBAL",
            "key": "locked",
            "value": "new",
        })
        assert res.status_code == 400
        assert "memory_update_failed" in res.json()["detail"]

    def test_update_invalid_scope_returns_400(self, client):
        res = client.post("/memory/update", json={
            "scope": "BAD",
            "key": "k",
            "value": "v",
        })
        assert res.status_code == 400
        assert "invalid_scope" in res.json()["detail"]

    def test_update_project_without_project_id_returns_400(self, client):
        res = client.post("/memory/update", json={
            "scope": "PROJECT",
            "key": "k",
            "value": "v",
        })
        assert res.status_code == 400
        assert "project_id required" in res.json()["detail"]


# ─── 5. Delete Endpoint ───────────────────────────────────────────────────────


class TestMemoryDelete:

    def test_delete_existing(self, client):
        memory_store.write(SCOPE_GLOBAL, "del", "v", CATEGORY_CONTEXT, deletable=True)
        res = client.post("/memory/delete", json={
            "scope": "GLOBAL",
            "key": "del",
        })
        assert res.status_code == 200
        assert res.json()["deleted"] is True
        assert memory_store.read(SCOPE_GLOBAL, "del") is None

    def test_delete_not_found_returns_400(self, client):
        res = client.post("/memory/delete", json={
            "scope": "GLOBAL",
            "key": "missing",
        })
        assert res.status_code == 400
        assert "memory_delete_failed" in res.json()["detail"]

    def test_delete_non_deletable_returns_400(self, client):
        memory_store.write(SCOPE_GLOBAL, "sticky", "v", CATEGORY_CONTEXT, deletable=False)
        res = client.post("/memory/delete", json={
            "scope": "GLOBAL",
            "key": "sticky",
        })
        assert res.status_code == 400
        assert "memory_delete_failed" in res.json()["detail"]

    def test_delete_invalid_scope_returns_400(self, client):
        res = client.post("/memory/delete", json={
            "scope": "BAD",
            "key": "k",
        })
        assert res.status_code == 400
        assert "invalid_scope" in res.json()["detail"]


# ─── 6. Reset Endpoint ────────────────────────────────────────────────────────


class TestMemoryReset:

    def test_reset_global(self, client):
        memory_store.write(SCOPE_GLOBAL, "g", "v", CATEGORY_CONTEXT)
        res = client.post("/memory/reset", json={"scope": "GLOBAL"})
        assert res.status_code == 200
        assert res.json()["scope"] == "GLOBAL"
        assert memory_store.read(SCOPE_GLOBAL, "g") is None

    def test_reset_project(self, client):
        memory_store.write(SCOPE_PROJECT, "p", "v", CATEGORY_CONTEXT, project_id="proj-reset")
        res = client.post("/memory/reset", json={
            "scope": "PROJECT",
            "project_id": "proj-reset",
        })
        assert res.status_code == 200
        assert res.json()["scope"] == "PROJECT"
        assert memory_store.read(SCOPE_PROJECT, "p", project_id="proj-reset") is None

    def test_reset_all_with_confirm(self, client):
        memory_store.write(SCOPE_GLOBAL, "g", "v", CATEGORY_CONTEXT)
        memory_store.write(SCOPE_PROJECT, "p", "v", CATEGORY_CONTEXT, project_id="proj-all")
        res = client.post("/memory/reset", json={
            "scope": "ALL",
            "confirm_all": True,
        })
        assert res.status_code == 200
        assert res.json()["scope"] == "ALL"
        assert memory_store.read(SCOPE_GLOBAL, "g") is None
        assert memory_store.read(SCOPE_PROJECT, "p", project_id="proj-all") is None

    def test_reset_all_without_confirm_returns_400(self, client):
        res = client.post("/memory/reset", json={"scope": "ALL"})
        assert res.status_code == 400
        assert "reset ALL requires confirm_all=true" in res.json()["detail"]

    def test_reset_project_without_project_id_returns_400(self, client):
        res = client.post("/memory/reset", json={"scope": "PROJECT"})
        assert res.status_code == 400
        assert "project_id required" in res.json()["detail"]

    def test_reset_invalid_scope_returns_400(self, client):
        res = client.post("/memory/reset", json={"scope": "BAD"})
        assert res.status_code == 400
        assert "invalid_scope" in res.json()["detail"]


# ─── 7. Authority Isolation ───────────────────────────────────────────────────


class TestAuthorityIsolation:
    """
    Verify memory endpoints do not invoke orchestrator, governance,
    lifecycle, projection, trace, or planner functions.
    """

    def _get_endpoint_source(self, func_name: str) -> str:
        """Return source code of a named function in api.py."""
        import inspect
        from ai_lab_gui.backend import api as api_module
        func = getattr(api_module, func_name)
        return inspect.getsource(func)

    def test_memory_list_no_orchestrator_calls(self, client):
        src = self._get_endpoint_source("memory_list")
        assert "workflow_control" not in src
        assert "orchestrator_runtime" not in src
        assert "governance" not in src
        assert "projection_manager" not in src
        assert "trace_collector" not in src
        assert "execute_from_input" not in src
        assert "run_workflow" not in src
        assert "pause_workflow" not in src
        assert "resume_workflow" not in src
        assert "retry_step" not in src
        assert "cancel_workflow" not in src

    def test_memory_write_no_orchestrator_calls(self, client):
        src = self._get_endpoint_source("memory_write")
        assert "workflow_control" not in src
        assert "orchestrator_runtime" not in src
        assert "governance" not in src
        assert "projection_manager" not in src
        assert "trace_collector" not in src
        assert "execute_from_input" not in src
        assert "run_workflow" not in src

    def test_memory_update_no_orchestrator_calls(self, client):
        src = self._get_endpoint_source("memory_update")
        assert "workflow_control" not in src
        assert "orchestrator_runtime" not in src
        assert "governance" not in src
        assert "projection_manager" not in src
        assert "trace_collector" not in src

    def test_memory_delete_no_orchestrator_calls(self, client):
        src = self._get_endpoint_source("memory_delete")
        assert "workflow_control" not in src
        assert "orchestrator_runtime" not in src
        assert "governance" not in src
        assert "projection_manager" not in src
        assert "trace_collector" not in src

    def test_memory_reset_no_orchestrator_calls(self, client):
        src = self._get_endpoint_source("memory_reset")
        assert "workflow_control" not in src
        assert "orchestrator_runtime" not in src
        assert "governance" not in src
        assert "projection_manager" not in src
        assert "trace_collector" not in src

    def test_memory_read_no_orchestrator_calls(self, client):
        src = self._get_endpoint_source("memory_read")
        assert "workflow_control" not in src
        assert "orchestrator_runtime" not in src
        assert "governance" not in src
        assert "projection_manager" not in src
        assert "trace_collector" not in src
