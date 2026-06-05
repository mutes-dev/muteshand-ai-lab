"""
CATEGORY: PROJECTION
AUTHORITY_LAYER: Memory Storage Validation (ISSUE-076)
VALIDATES:
  - Memory schema validation
  - GLOBAL and PROJECT storage primitives
  - Persistence, separation, and reset behavior
  - Advisory-only safety (no authority leakage)
  - Legacy module isolation
ENTRYPOINT: Direct module tests
DIRECT_INTERNAL_CALLS:
  - system.memory.schema
  - system.memory.memory_store
MONKEYPATCH_USAGE: NONE
MOCKING_POLICY: REAL_EXECUTION
TEST_INTENT: VALIDATION
ARCHITECTURAL_SCOPE: Memory storage foundation

---

ISSUE-076 — Memory Authority + Storage Contract Alignment
"""

import json
import os
import pytest

from system.memory.schema import (
    build_entry,
    validate_entry,
    validate_scope,
    validate_category,
    validate_confidence,
    validate_key,
    validate_id,
    validate_project_id,
    validate_source,
    validate_boolean,
    MemoryValidationError,
    SCOPE_GLOBAL,
    SCOPE_PROJECT,
    CATEGORY_BEHAVIOR,
    CATEGORY_PREFERENCE,
    CATEGORY_PATTERN,
    CATEGORY_CONTEXT,
    SOURCE_USER,
    SOURCE_SYSTEM,
    SOURCE_AGENT,
    SOURCE_INFERRED,
)

from system.memory import memory_store


# ─── Helpers ────────────────────────────────────────────────────────────────


def _clean_test_stores():
    """Remove test store files to ensure clean state."""
    from tests._test_safety_guard import guard_delete, guard_rmtree
    paths = [
        memory_store.GLOBAL_STORE_PATH,
    ]
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


# ─── 1. Schema Validation ───────────────────────────────────────────────────


class TestSchemaValidation:

    def test_valid_global_entry(self):
        entry = build_entry(
            scope=SCOPE_GLOBAL,
            key="test-global-key",
            value={"hint": "global hint"},
            category=CATEGORY_BEHAVIOR,
            source=SOURCE_USER,
            confidence=0.8,
            editable=True,
            deletable=True,
        )
        assert entry["scope"] == SCOPE_GLOBAL
        assert entry["key"] == "test-global-key"
        assert entry["category"] == CATEGORY_BEHAVIOR
        assert entry["confidence"] == 0.8
        assert entry["source"] == SOURCE_USER
        assert entry["editable"] is True
        assert entry["deletable"] is True
        assert entry["project_id"] is None
        assert "id" in entry
        assert "created_at" in entry
        assert "updated_at" in entry

    def test_valid_project_entry(self):
        entry = build_entry(
            scope=SCOPE_PROJECT,
            key="test-project-key",
            value={"hint": "project hint"},
            category=CATEGORY_PREFERENCE,
            project_id="proj-001",
            source=SOURCE_SYSTEM,
            confidence=0.6,
            editable=False,
            deletable=False,
        )
        assert entry["scope"] == SCOPE_PROJECT
        assert entry["project_id"] == "proj-001"
        assert entry["editable"] is False
        assert entry["deletable"] is False

    def test_invalid_scope_rejected(self):
        with pytest.raises(MemoryValidationError):
            validate_scope("INVALID")
        with pytest.raises(MemoryValidationError):
            validate_scope(123)
        with pytest.raises(MemoryValidationError):
            validate_scope(None)

    def test_invalid_category_rejected(self):
        with pytest.raises(MemoryValidationError):
            validate_category("unknown")
        with pytest.raises(MemoryValidationError):
            validate_category(123)

    def test_invalid_confidence_rejected(self):
        with pytest.raises(MemoryValidationError):
            validate_confidence(1.5)
        with pytest.raises(MemoryValidationError):
            validate_confidence(-0.1)
        with pytest.raises(MemoryValidationError):
            validate_confidence("high")

    def test_missing_project_id_rejected_for_project(self):
        with pytest.raises(MemoryValidationError):
            build_entry(
                scope=SCOPE_PROJECT,
                key="k",
                value="v",
                category=CATEGORY_CONTEXT,
            )

    def test_project_id_not_required_for_global(self):
        entry = build_entry(
            scope=SCOPE_GLOBAL,
            key="k",
            value="v",
            category=CATEGORY_PATTERN,
        )
        assert entry["project_id"] is None

    def test_invalid_project_id_rejected(self):
        with pytest.raises(MemoryValidationError):
            validate_project_id(123, required=True)
        with pytest.raises(MemoryValidationError):
            validate_project_id("", required=True)

    def test_invalid_key_rejected(self):
        with pytest.raises(MemoryValidationError):
            validate_key("")
        with pytest.raises(MemoryValidationError):
            validate_key(123)

    def test_invalid_id_rejected(self):
        with pytest.raises(MemoryValidationError):
            validate_id("")
        with pytest.raises(MemoryValidationError):
            validate_id(123)

    def test_invalid_source_rejected(self):
        with pytest.raises(MemoryValidationError):
            validate_source("unknown")
        with pytest.raises(MemoryValidationError):
            validate_source(123)

    def test_invalid_boolean_rejected(self):
        with pytest.raises(MemoryValidationError):
            validate_boolean("editable", "yes")
        with pytest.raises(MemoryValidationError):
            validate_boolean("deletable", 1)

    def test_scope_case_insensitive(self):
        assert validate_scope("global") == SCOPE_GLOBAL
        assert validate_scope("PROJECT") == SCOPE_PROJECT

    def test_category_case_insensitive(self):
        assert validate_category("Behavior") == CATEGORY_BEHAVIOR
        assert validate_category("PREFERENCE") == CATEGORY_PREFERENCE

    def test_validate_entry_complete(self):
        entry = build_entry(
            scope=SCOPE_GLOBAL,
            key="complete",
            value={"a": 1},
            category=CATEGORY_PATTERN,
            source=SOURCE_AGENT,
            confidence=0.5,
            editable=True,
            deletable=True,
        )
        validated = validate_entry(entry)
        assert validated["scope"] == SCOPE_GLOBAL
        assert validated["key"] == "complete"

    def test_validate_entry_missing_field(self):
        with pytest.raises(MemoryValidationError):
            validate_entry({"scope": SCOPE_GLOBAL, "key": "k"})

    def test_build_entry_generates_uuid(self):
        entry1 = build_entry(SCOPE_GLOBAL, "k1", "v", CATEGORY_CONTEXT)
        entry2 = build_entry(SCOPE_GLOBAL, "k2", "v", CATEGORY_CONTEXT)
        assert entry1["id"] != entry2["id"]
        assert len(entry1["id"]) == 36

    def test_project_id_rejected_for_global(self):
        with pytest.raises(MemoryValidationError):
            build_entry(
                scope=SCOPE_GLOBAL,
                key="k",
                value="v",
                category=CATEGORY_CONTEXT,
                project_id="proj-001",
            )


# ─── 2. Persistence ─────────────────────────────────────────────────────────


class TestPersistence:

    def test_global_memory_persists(self):
        written = memory_store.write(
            scope=SCOPE_GLOBAL,
            key="persist-key",
            value={"data": 42},
            category=CATEGORY_BEHAVIOR,
            confidence=0.7,
        )
        assert written is not None

        # Simulate reload by reading from disk directly
        with open(memory_store.GLOBAL_STORE_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
        assert len(raw) == 1
        assert raw[0]["key"] == "persist-key"

    def test_memory_survives_reload(self):
        memory_store.write(SCOPE_GLOBAL, "survive", "val", CATEGORY_PREFERENCE, confidence=0.6)

        # Force re-instantiation by clearing in-memory caches (none exist, so just re-read)
        read_back = memory_store.read(SCOPE_GLOBAL, "survive")
        assert read_back is not None
        assert read_back["value"] == "val"
        assert read_back["confidence"] == 0.6

    def test_reset_global_clears_only_global(self):
        memory_store.write(SCOPE_GLOBAL, "g1", "global", CATEGORY_CONTEXT)
        memory_store.write(SCOPE_PROJECT, "p1", "project", CATEGORY_CONTEXT, project_id="proj-a")

        assert memory_store.reset(SCOPE_GLOBAL) is True
        assert memory_store.read(SCOPE_GLOBAL, "g1") is None
        assert memory_store.read(SCOPE_PROJECT, "p1", project_id="proj-a") is not None

    def test_reset_project_clears_only_that_project(self):
        memory_store.write(SCOPE_PROJECT, "p-a", "val-a", CATEGORY_BEHAVIOR, project_id="proj-a")
        memory_store.write(SCOPE_PROJECT, "p-b", "val-b", CATEGORY_BEHAVIOR, project_id="proj-b")

        assert memory_store.reset(SCOPE_PROJECT, project_id="proj-a") is True
        assert memory_store.read(SCOPE_PROJECT, "p-a", project_id="proj-a") is None
        assert memory_store.read(SCOPE_PROJECT, "p-b", project_id="proj-b") is not None

    def test_reset_all_clears_all_memory(self):
        memory_store.write(SCOPE_GLOBAL, "g1", "global", CATEGORY_PATTERN)
        memory_store.write(SCOPE_PROJECT, "p1", "project", CATEGORY_PATTERN, project_id="proj-all")

        assert memory_store.reset("all") is True
        assert memory_store.read(SCOPE_GLOBAL, "g1") is None
        assert memory_store.read(SCOPE_PROJECT, "p1", project_id="proj-all") is None

    def test_delete_removes_targeted_entry_only(self):
        memory_store.write(SCOPE_GLOBAL, "keep", "keep-val", CATEGORY_BEHAVIOR)
        memory_store.write(SCOPE_GLOBAL, "remove", "remove-val", CATEGORY_BEHAVIOR)

        assert memory_store.delete(SCOPE_GLOBAL, "remove") is True
        assert memory_store.read(SCOPE_GLOBAL, "remove") is None
        assert memory_store.read(SCOPE_GLOBAL, "keep") is not None

    def test_update_changes_updated_at(self):
        entry = memory_store.write(SCOPE_GLOBAL, "update-me", "old", CATEGORY_CONTEXT)
        original_updated = entry["updated_at"]

        updated = memory_store.update(SCOPE_GLOBAL, "update-me", "new")
        assert updated is not None
        assert updated["value"] == "new"
        assert updated["updated_at"] != original_updated


# ─── 3. Separation ─────────────────────────────────────────────────────────


class TestSeparation:

    def test_global_and_project_memory_separated(self):
        memory_store.write(SCOPE_GLOBAL, "shared-key", "global-val", CATEGORY_PATTERN)
        memory_store.write(SCOPE_PROJECT, "shared-key", "project-val", CATEGORY_PATTERN, project_id="sep-proj")

        global_entry = memory_store.read(SCOPE_GLOBAL, "shared-key")
        project_entry = memory_store.read(SCOPE_PROJECT, "shared-key", project_id="sep-proj")

        assert global_entry["value"] == "global-val"
        assert project_entry["value"] == "project-val"

    def test_project_a_does_not_leak_into_project_b(self):
        memory_store.write(SCOPE_PROJECT, "key", "a", CATEGORY_BEHAVIOR, project_id="proj-a")
        memory_store.write(SCOPE_PROJECT, "key", "b", CATEGORY_BEHAVIOR, project_id="proj-b")

        assert memory_store.read(SCOPE_PROJECT, "key", project_id="proj-a")["value"] == "a"
        assert memory_store.read(SCOPE_PROJECT, "key", project_id="proj-b")["value"] == "b"

    def test_list_entries_by_scope(self):
        memory_store.write(SCOPE_GLOBAL, "g", "gv", CATEGORY_CONTEXT)
        memory_store.write(SCOPE_PROJECT, "p", "pv", CATEGORY_CONTEXT, project_id="list-proj")

        global_list = memory_store.list_entries(scope=SCOPE_GLOBAL)
        project_list = memory_store.list_entries(scope=SCOPE_PROJECT, project_id="list-proj")

        assert len(global_list) == 1
        assert global_list[0]["key"] == "g"
        assert len(project_list) == 1
        assert project_list[0]["key"] == "p"

    def test_list_all_scopes(self):
        memory_store.reset("all")
        memory_store.write(SCOPE_GLOBAL, "g", "gv", CATEGORY_CONTEXT)
        memory_store.write(SCOPE_PROJECT, "p", "pv", CATEGORY_CONTEXT, project_id="all-proj")

        all_entries = memory_store.list_entries()
        assert len(all_entries) == 2

    def test_list_by_category(self):
        memory_store.write(SCOPE_GLOBAL, "b", "bv", CATEGORY_BEHAVIOR)
        memory_store.write(SCOPE_GLOBAL, "p", "pv", CATEGORY_PREFERENCE)

        behavior_only = memory_store.list_entries(scope=SCOPE_GLOBAL, category=CATEGORY_BEHAVIOR)
        assert len(behavior_only) == 1
        assert behavior_only[0]["key"] == "b"


# ─── 4. Advisory-Only Safety ────────────────────────────────────────────────


class TestAdvisoryOnlySafety:

    def test_memory_write_does_not_affect_execution_result(self):
        """Memory write returns a dict — it does not modify any execution state."""
        result = memory_store.write(SCOPE_GLOBAL, "safe", "val", CATEGORY_CONTEXT)
        assert isinstance(result, dict)
        assert "status" not in result  # Not an execution result
        assert "execution_result" not in result

    def test_memory_read_does_not_affect_execution_result(self):
        memory_store.write(SCOPE_GLOBAL, "read-safe", "val", CATEGORY_CONTEXT)
        result = memory_store.read(SCOPE_GLOBAL, "read-safe")
        assert isinstance(result, dict)
        assert "status" not in result

    def _get_import_lines(self, module) -> str:
        """Return only import/from lines from a module source."""
        source = open(module.__file__, "r", encoding="utf-8").read()
        lines = [line for line in source.splitlines() if line.strip().startswith(("import ", "from "))]
        return "\n".join(lines).lower()

    def test_memory_store_no_governance_import(self):
        """Verify memory_store does not import governance modules."""
        import system.memory.memory_store as ms
        imports = self._get_import_lines(ms)
        assert "governance" not in imports
        assert "decide_next_action" not in imports

    def test_memory_store_no_lifecycle_import(self):
        """Verify memory_store does not import lifecycle authority modules."""
        import system.memory.memory_store as ms
        imports = self._get_import_lines(ms)
        assert "workflow_control" not in imports
        assert "lifecycle" not in imports

    def test_memory_store_no_system_entry_import(self):
        """Verify memory_store does not import system_entry execution path."""
        import system.memory.memory_store as ms
        imports = self._get_import_lines(ms)
        assert "system_entry" not in imports

    def test_memory_store_no_retry_import(self):
        """Verify memory_store does not import retry/replay/recovery modules."""
        import system.memory.memory_store as ms
        imports = self._get_import_lines(ms)
        assert "escalation" not in imports
        assert "recovery" not in imports
        assert "replay" not in imports

    def test_memory_store_no_projection_import(self):
        """Verify memory_store does not import projection truth modules."""
        import system.memory.memory_store as ms
        imports = self._get_import_lines(ms)
        assert "projection_manager" not in imports
        assert "projection_schema" not in imports

    def test_memory_store_no_trace_import(self):
        """Verify memory_store does not import trace modules."""
        import system.memory.memory_store as ms
        imports = self._get_import_lines(ms)
        assert "trace_collector" not in imports
        assert "trace_model" not in imports

    def test_memory_operations_failure_isolated(self):
        """Invalid reads/writes return None or False, never raise."""
        assert memory_store.read("INVALID", "key") is None
        assert memory_store.write("INVALID", "key", "val", CATEGORY_CONTEXT) is None
        assert memory_store.update("INVALID", "key", "val") is None
        assert memory_store.delete("INVALID", "key") is False
        assert memory_store.reset("INVALID") is False


# ─── 5. Legacy Safety ───────────────────────────────────────────────────────


class TestLegacySafety:

    def test_global_memory_py_unchanged(self):
        """Verify legacy global_memory.py still loads and functions."""
        from system.memory.global_memory import write_entry, get_by_key, reset_all
        reset_all()
        entry = write_entry("legacy-key", {"test": True}, category="pattern", confidence=0.5)
        assert entry is not None
        read = get_by_key("legacy-key")
        assert read is not None
        assert read["key"] == "legacy-key"
        reset_all()

    def test_memory_adapter_unchanged(self):
        """Verify legacy memory_adapter.py still loads."""
        from system.memory.memory_adapter import get_memory_context, enrich_agent_context
        ctx = get_memory_context("add_numbers", "EXECUTE_API")
        assert isinstance(ctx, dict)

    def test_preference_tracker_unchanged(self):
        """Verify legacy preference_tracker.py still loads and counts."""
        from system.memory.preference_tracker import reset_counts, get_occurrence_count
        reset_counts()
        assert get_occurrence_count("add_numbers", "EXECUTE_API") == 0

    def test_legacy_global_memory_json_not_overwritten(self):
        """
        Verify legacy global_memory.json is not overwritten by memory_store writes.
        They use separate files.
        """
        from system.memory.global_memory import write_entry, get_by_key, reset_all
        reset_all()
        write_entry("legacy-only", "legacy-val", category="pattern")

        memory_store.write(SCOPE_GLOBAL, "store-only", "store-val", CATEGORY_PATTERN)

        # Legacy should see its own entry
        assert get_by_key("legacy-only") is not None
        # Legacy should NOT see memory_store entry
        assert get_by_key("store-only") is None

        # memory_store should see its own entry
        assert memory_store.read(SCOPE_GLOBAL, "store-only") is not None
        # memory_store should NOT see legacy entry
        assert memory_store.read(SCOPE_GLOBAL, "legacy-only") is None

        reset_all()


# ─── 6. Editable / Deletable Guards ─────────────────────────────────────────


class TestEditableDeletable:

    def test_non_editable_entry_cannot_update(self):
        memory_store.write(
            SCOPE_GLOBAL, "locked", "orig", CATEGORY_CONTEXT,
            editable=False, deletable=True,
        )
        result = memory_store.update(SCOPE_GLOBAL, "locked", "new")
        assert result is None

    def test_non_deletable_entry_cannot_delete(self):
        memory_store.write(
            SCOPE_GLOBAL, "sticky", "orig", CATEGORY_CONTEXT,
            editable=True, deletable=False,
        )
        assert memory_store.delete(SCOPE_GLOBAL, "sticky") is False
        # Entry still exists
        assert memory_store.read(SCOPE_GLOBAL, "sticky") is not None

    def test_deletable_entry_can_delete(self):
        memory_store.write(
            SCOPE_GLOBAL, "removable", "orig", CATEGORY_CONTEXT,
            editable=True, deletable=True,
        )
        assert memory_store.delete(SCOPE_GLOBAL, "removable") is True
        assert memory_store.read(SCOPE_GLOBAL, "removable") is None

    def test_editable_entry_can_update(self):
        memory_store.write(
            SCOPE_GLOBAL, "mutable", "orig", CATEGORY_CONTEXT,
            editable=True, deletable=True,
        )
        result = memory_store.update(SCOPE_GLOBAL, "mutable", "new")
        assert result is not None
        assert result["value"] == "new"
