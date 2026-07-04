"""
CATEGORY: PROJECTION
AUTHORITY_LAYER: Advisory Memory Bridge (ISSUE-095B)
VALIDATES:
  - advisory_bridge filtering (source, category, confidence, max_entries)
  - scope/project isolation (GLOBAL + PROJECT, no cross-project leak)
  - prompt safety (advisory warnings, bounded length, precedence)
  - no legacy reactivation (advisory_bridge does not import global_memory, memory_adapter, preference_tracker)
  - AG1 prompt inclusion (tool_selection_agent consumes advisory_memory context)
  - trace metadata (MEMORY_CONTEXT_USED shape, no raw values)
  - backend safety (imports, no circular deps)
ENTRYPOINT: Direct module tests + monkeypatched AG1 prompt capture
DIRECT_INTERNAL_CALLS:
  - system.memory.advisory_bridge
  - system.memory.memory_store
  - system.memory.schema
  - system.orchestrator.agents.tool_selection_agent
MONKEYPATCH_USAGE: YES (execute_llm capture for AG1 prompt test)
MOCKING_POLICY: REAL_EXECUTION for storage/bridge; monkeypatch for LLM call
TEST_INTENT: VALIDATION
ARCHITECTURAL_SCOPE: AG1-only advisory memory bridge
"""

import json
import os
import pytest

from system.memory import memory_store
from system.memory.schema import (
    SCOPE_GLOBAL,
    SCOPE_PROJECT,
    SOURCE_USER,
    SOURCE_SYSTEM,
    SOURCE_AGENT,
    SOURCE_INFERRED,
    CATEGORY_BEHAVIOR,
    CATEGORY_PREFERENCE,
    CATEGORY_CONTEXT,
    CATEGORY_PATTERN,
)

# ─── Helpers ────────────────────────────────────────────────────────────────


def _clean_test_stores():
    """
    NO-OP: Storage isolation is handled by the _isolate_memory fixture.
    Previously called memory_store.reset("ALL") against production storage.
    """
    pass


def _seed_memory():
    """Seed test memory entries across scopes and sources."""
    # GLOBAL user entries (eligible)
    memory_store.write(
        scope=SCOPE_GLOBAL,
        key="pref_math",
        value="Prefer math tools for calculations",
        category=CATEGORY_PREFERENCE,
        source=SOURCE_USER,
        confidence=0.8,
    )
    memory_store.write(
        scope=SCOPE_GLOBAL,
        key="behavior_retry",
        value="Retry tool selection once on ambiguous input",
        category=CATEGORY_BEHAVIOR,
        source=SOURCE_USER,
        confidence=0.6,
    )
    memory_store.write(
        scope=SCOPE_GLOBAL,
        key="context_api",
        value="Use local API endpoint",
        category=CATEGORY_CONTEXT,
        source=SOURCE_USER,
        confidence=0.9,
    )
    # GLOBAL system entry (excluded by source filter)
    memory_store.write(
        scope=SCOPE_GLOBAL,
        key="sys_hint",
        value="System-generated hint",
        category=CATEGORY_PREFERENCE,
        source=SOURCE_SYSTEM,
        confidence=0.8,
    )
    # GLOBAL agent entry (excluded by source filter)
    memory_store.write(
        scope=SCOPE_GLOBAL,
        key="agent_hint",
        value="Agent-generated hint",
        category=CATEGORY_BEHAVIOR,
        source=SOURCE_AGENT,
        confidence=0.8,
    )
    # GLOBAL inferred entry (excluded by source filter)
    memory_store.write(
        scope=SCOPE_GLOBAL,
        key="inferred_hint",
        value="Inferred hint",
        category=CATEGORY_CONTEXT,
        source=SOURCE_INFERRED,
        confidence=0.8,
    )
    # GLOBAL pattern entry (excluded by category filter)
    memory_store.write(
        scope=SCOPE_GLOBAL,
        key="pattern_add",
        value="Pattern: add_numbers usage",
        category=CATEGORY_PATTERN,
        source=SOURCE_USER,
        confidence=0.8,
    )
    # GLOBAL low confidence entry (excluded by confidence filter)
    memory_store.write(
        scope=SCOPE_GLOBAL,
        key="low_conf",
        value="Low confidence hint",
        category=CATEGORY_PREFERENCE,
        source=SOURCE_USER,
        confidence=0.3,
    )
    # PROJECT user entries (eligible for matching project)
    memory_store.write(
        scope=SCOPE_PROJECT,
        project_id="wf_test_001",
        key="proj_pref",
        value="Project-specific tool preference",
        category=CATEGORY_PREFERENCE,
        source=SOURCE_USER,
        confidence=0.75,
    )
    # PROJECT user entry for different project (should not leak)
    memory_store.write(
        scope=SCOPE_PROJECT,
        project_id="wf_other_002",
        key="other_proj_pref",
        value="Other project preference",
        category=CATEGORY_PREFERENCE,
        source=SOURCE_USER,
        confidence=0.75,
    )


@pytest.fixture(autouse=True)
def _isolate_memory(monkeypatch, tmp_path):
    """Redirect memory storage to temp paths so tests never touch production."""
    test_memory_dir = str(tmp_path / "memory")
    test_global = os.path.join(test_memory_dir, "memory_store.json")
    test_projects = os.path.join(test_memory_dir, "projects")
    os.makedirs(test_projects, exist_ok=True)
    monkeypatch.setattr(memory_store, "MEMORY_DIR", test_memory_dir)
    monkeypatch.setattr(memory_store, "GLOBAL_STORE_PATH", test_global)
    monkeypatch.setattr(memory_store, "PROJECTS_DIR", test_projects)
    yield


# ─── 1. advisory_bridge filtering ───────────────────────────────────────────


class TestAdvisoryBridgeFiltering:
    def test_source_user_included(self):
        _seed_memory()
        from system.memory.advisory_bridge import build_advisory_memory_context
        result = build_advisory_memory_context()
        assert result["metadata"]["bridge_status"] == "used"
        assert result["formatted_text"] is not None
        # Should include pref_math, behavior_retry, context_api
        assert "pref_math" in result["formatted_text"]

    def test_source_system_excluded(self):
        _seed_memory()
        from system.memory.advisory_bridge import build_advisory_memory_context
        result = build_advisory_memory_context()
        assert "sys_hint" not in (result["formatted_text"] or "")

    def test_source_agent_excluded(self):
        _seed_memory()
        from system.memory.advisory_bridge import build_advisory_memory_context
        result = build_advisory_memory_context()
        assert "agent_hint" not in (result["formatted_text"] or "")

    def test_source_inferred_excluded(self):
        _seed_memory()
        from system.memory.advisory_bridge import build_advisory_memory_context
        result = build_advisory_memory_context()
        assert "inferred_hint" not in (result["formatted_text"] or "")

    def test_category_pattern_excluded(self):
        _seed_memory()
        from system.memory.advisory_bridge import build_advisory_memory_context
        result = build_advisory_memory_context()
        assert "pattern_add" not in (result["formatted_text"] or "")

    def test_categories_behavior_preference_context_included(self):
        _seed_memory()
        from system.memory.advisory_bridge import build_advisory_memory_context
        result = build_advisory_memory_context()
        text = result["formatted_text"] or ""
        assert "pref_math" in text
        assert "behavior_retry" in text
        assert "context_api" in text

    def test_confidence_below_threshold_excluded(self):
        _seed_memory()
        from system.memory.advisory_bridge import build_advisory_memory_context
        result = build_advisory_memory_context()
        assert "low_conf" not in (result["formatted_text"] or "")

    def test_max_entries_enforced(self):
        _seed_memory()
        from system.memory.advisory_bridge import build_advisory_memory_context
        result = build_advisory_memory_context(max_entries=2)
        assert result["metadata"]["count"] == 2
        # Highest confidence first: context_api (0.9), pref_math (0.8)
        text = result["formatted_text"] or ""
        assert "context_api" in text
        assert "pref_math" in text
        assert "behavior_retry" not in text

    def test_empty_eligible_returns_no_context(self):
        # temp store is already empty via _isolate_memory fixture
        from system.memory.advisory_bridge import build_advisory_memory_context
        result = build_advisory_memory_context()
        assert result["metadata"]["bridge_status"] == "empty"
        assert result["formatted_text"] is None


# ─── 2. scope/project isolation ─────────────────────────────────────────────


class TestScopeProjectIsolation:
    def test_global_entries_included(self):
        _seed_memory()
        from system.memory.advisory_bridge import build_advisory_memory_context
        result = build_advisory_memory_context()
        assert "GLOBAL" in result["metadata"]["scopes_used"]
        assert "pref_math" in (result["formatted_text"] or "")

    def test_project_entries_included_for_matching_project(self):
        _seed_memory()
        from system.memory.advisory_bridge import build_advisory_memory_context
        result = build_advisory_memory_context(project_id="wf_test_001")
        text = result["formatted_text"] or ""
        assert "proj_pref" in text
        assert "PROJECT" in result["metadata"]["scopes_used"]

    def test_project_entries_from_other_project_do_not_leak(self):
        _seed_memory()
        from system.memory.advisory_bridge import build_advisory_memory_context
        result = build_advisory_memory_context(project_id="wf_test_001")
        text = result["formatted_text"] or ""
        assert "other_proj_pref" not in text

    def test_no_project_id_means_global_only(self):
        _seed_memory()
        from system.memory.advisory_bridge import build_advisory_memory_context
        result = build_advisory_memory_context()
        assert result["metadata"]["project_id_present"] is False
        text = result["formatted_text"] or ""
        assert "proj_pref" not in text  # PROJECT entries should not appear
        assert "pref_math" in text  # GLOBAL should appear


# ─── 3. prompt safety ───────────────────────────────────────────────────────


class TestPromptSafety:
    def test_advisory_only_warning_present(self):
        _seed_memory()
        from system.memory.advisory_bridge import build_advisory_memory_context
        result = build_advisory_memory_context()
        text = result["formatted_text"] or ""
        assert "ADVISORY MEMORY CONTEXT" in text
        assert "operator-managed historical context" in text

    def test_current_instruction_precedence_warning_present(self):
        _seed_memory()
        from system.memory.advisory_bridge import build_advisory_memory_context
        result = build_advisory_memory_context()
        text = result["formatted_text"] or ""
        assert "ALWAYS overrides memory" in text

    def test_memory_as_data_not_instructions_warning_present(self):
        _seed_memory()
        from system.memory.advisory_bridge import build_advisory_memory_context
        result = build_advisory_memory_context()
        text = result["formatted_text"] or ""
        assert "NOT executable instructions" in text

    def test_tool_selection_rules_precedence_warning_present(self):
        _seed_memory()
        from system.memory.advisory_bridge import build_advisory_memory_context
        result = build_advisory_memory_context()
        text = result["formatted_text"] or ""
        assert "Tool-selection contract and rules remain authoritative" in text

    def test_output_length_bounded(self):
        _seed_memory()
        from system.memory.advisory_bridge import build_advisory_memory_context
        result = build_advisory_memory_context()
        text = result["formatted_text"] or ""
        assert len(text) <= 1000

    def test_truncation_on_overflow(self):
        # Create many large values to force total section over 1000 chars
        for i in range(10):
            memory_store.write(
                scope=SCOPE_GLOBAL,
                key=f"large_{i}",
                value="y" * 200,
                category=CATEGORY_PREFERENCE,
                source=SOURCE_USER,
                confidence=0.9,
            )
        from system.memory.advisory_bridge import build_advisory_memory_context
        result = build_advisory_memory_context(max_entries=10)
        text = result["formatted_text"] or ""
        assert len(text) <= 1000
        assert "... [additional content omitted]" in text


# ─── 4. no legacy reactivation ───────────────────────────────────────────────


class TestNoLegacyReactivation:
    def _get_import_lines(self):
        import system.memory.advisory_bridge as bridge_mod
        import inspect
        source_lines = inspect.getsourcelines(bridge_mod)[0]
        return [line for line in source_lines if line.strip().startswith(("import ", "from "))]

    def test_advisory_bridge_does_not_import_global_memory(self):
        imports = self._get_import_lines()
        for line in imports:
            assert "global_memory" not in line, f"Unexpected import: {line.strip()}"

    def test_advisory_bridge_does_not_import_memory_adapter(self):
        imports = self._get_import_lines()
        for line in imports:
            assert "memory_adapter" not in line, f"Unexpected import: {line.strip()}"

    def test_advisory_bridge_does_not_import_preference_tracker(self):
        imports = self._get_import_lines()
        for line in imports:
            assert "preference_tracker" not in line, f"Unexpected import: {line.strip()}"


# ─── 5. AG1 prompt inclusion ──────────────────────────────────────────────


class TestAG1PromptInclusion:
    def test_advisory_memory_included_when_present(self, monkeypatch):
        _seed_memory()
        captured_prompts = []

        def _capture_execute_llm(provider, prompt, _perf_caller="unknown", workflow_id=None):
            captured_prompts.append(prompt)
            return {"status": "success", "result": "USE_TOOL: finalize_output \"ok\""}

        monkeypatch.setattr(
            "system.orchestrator.agents.tool_selection_agent.execute_llm",
            _capture_execute_llm,
        )
        monkeypatch.setattr(
            "system.orchestrator.llm_executor.execute_llm",
            _capture_execute_llm,
        )

        from system.memory.advisory_bridge import build_advisory_memory_context
        from system.orchestrator.agents.tool_selection_agent import execute_tool_selection

        bridge = build_advisory_memory_context()
        assert bridge["formatted_text"] is not None

        context = {"workflow_id": "wf_test", "advisory_memory": bridge["formatted_text"]}
        result = execute_tool_selection(
            agent={"name": "generic_agent", "role": "tool_executor", "scope": ["tools"]},
            input_data="test",
            context=context,
        )
        assert result["status"] == "success"
        assert len(captured_prompts) >= 1
        prompt = captured_prompts[0]
        assert "ADVISORY MEMORY CONTEXT" in prompt
        assert "pref_math" in prompt

    def test_advisory_memory_excluded_when_absent(self, monkeypatch):
        captured_prompts = []

        def _capture_execute_llm(provider, prompt, _perf_caller="unknown", workflow_id=None):
            captured_prompts.append(prompt)
            return {"status": "success", "result": "USE_TOOL: finalize_output \"ok\""}

        monkeypatch.setattr(
            "system.orchestrator.agents.tool_selection_agent.execute_llm",
            _capture_execute_llm,
        )
        monkeypatch.setattr(
            "system.orchestrator.llm_executor.execute_llm",
            _capture_execute_llm,
        )

        from system.orchestrator.agents.tool_selection_agent import execute_tool_selection

        context = {"workflow_id": "wf_test"}  # no advisory_memory
        result = execute_tool_selection(
            agent={"name": "generic_agent", "role": "tool_executor", "scope": ["tools"]},
            input_data="test",
            context=context,
        )
        assert result["status"] == "success"
        assert len(captured_prompts) >= 1
        prompt = captured_prompts[0]
        assert "ADVISORY MEMORY CONTEXT" not in prompt

    def test_user_step_context_remains_present(self, monkeypatch):
        _seed_memory()
        captured_prompts = []

        def _capture_execute_llm(provider, prompt, _perf_caller="unknown", workflow_id=None):
            captured_prompts.append(prompt)
            return {"status": "success", "result": "USE_TOOL: finalize_output \"ok\""}

        monkeypatch.setattr(
            "system.orchestrator.agents.tool_selection_agent.execute_llm",
            _capture_execute_llm,
        )
        monkeypatch.setattr(
            "system.orchestrator.llm_executor.execute_llm",
            _capture_execute_llm,
        )

        from system.memory.advisory_bridge import build_advisory_memory_context
        from system.orchestrator.agents.tool_selection_agent import execute_tool_selection

        bridge = build_advisory_memory_context()
        context = {"workflow_id": "wf_test", "advisory_memory": bridge["formatted_text"]}
        result = execute_tool_selection(
            agent={"name": "generic_agent", "role": "tool_executor", "scope": ["tools"]},
            input_data="Current step: add 2 and 3",
            context=context,
        )
        assert result["status"] == "success"
        prompt = captured_prompts[0]
        assert "Current step:" in prompt
        assert "ADVISORY MEMORY CONTEXT" in prompt


# ─── 6. trace metadata ──────────────────────────────────────────────────────


class TestTraceMetadata:
    def test_memory_context_used_event_metadata_shape(self):
        from system.memory.advisory_bridge import build_advisory_memory_context
        _seed_memory()
        result = build_advisory_memory_context(project_id="wf_test_001")
        meta = result["metadata"]
        assert "count" in meta
        assert "scopes_used" in meta
        assert "categories_used" in meta
        assert "project_id_present" in meta
        assert "memory_ids" in meta
        assert "bridge_status" in meta
        assert meta["bridge_status"] == "used"

    def test_no_raw_values_in_metadata(self):
        from system.memory.advisory_bridge import build_advisory_memory_context
        _seed_memory()
        result = build_advisory_memory_context()
        meta = result["metadata"]
        # metadata must not contain raw memory values
        assert "value" not in meta
        assert "formatted_text" not in meta
        for key in meta:
            assert key in {
                "count",
                "scopes_used",
                "categories_used",
                "project_id_present",
                "memory_ids",
                "bridge_status",
            }

    def test_empty_result_does_not_block(self):
        # temp store is already empty via _isolate_memory fixture
        from system.memory.advisory_bridge import build_advisory_memory_context
        result = build_advisory_memory_context()
        assert result["metadata"]["bridge_status"] == "empty"
        assert result["formatted_text"] is None


# ─── 7. backend safety ────────────────────────────────────────────────────


class TestBackendSafety:
    def test_advisory_bridge_imports_cleanly(self):
        import system.memory.advisory_bridge as bridge_mod
        assert bridge_mod is not None
        assert callable(bridge_mod.build_advisory_memory_context)

    def test_no_circular_imports(self):
        # advisory_bridge imports memory_store and schema only
        # If circular imports existed, the import above would fail
        import system.memory.advisory_bridge
        assert system.memory.advisory_bridge is not None

    def test_tool_selection_agent_imports_cleanly(self):
        import system.orchestrator.agents.tool_selection_agent as ag1
        assert ag1 is not None
        assert callable(ag1.execute_tool_selection)

    def test_step_executor_imports_cleanly(self):
        import system.orchestrator.step_executor as se
        assert se is not None
        assert callable(se.execute_step)


# ─── 8. storage isolation regression ────────────────────────────────────────


class TestStorageIsolation:
    def test_global_store_path_is_not_production(self):
        production = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "memory", "memory_store.json"))
        assert memory_store.GLOBAL_STORE_PATH != production

    def test_writes_go_to_temp_not_production(self):
        memory_store.write(
            scope=SCOPE_GLOBAL,
            key="isolation_probe",
            value="probe",
            category=CATEGORY_CONTEXT,
            source=SOURCE_USER,
            confidence=0.5,
        )
        assert os.path.exists(memory_store.GLOBAL_STORE_PATH)
        # Verify temp path was used
        assert "tmp" in memory_store.GLOBAL_STORE_PATH.lower() or "pytest" in memory_store.GLOBAL_STORE_PATH.lower()
        # Verify production is untouched
        prod_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "memory", "memory_store.json"))
        if os.path.exists(prod_path):
            with open(prod_path) as f:
                content = f.read()
            assert "isolation_probe" not in content
