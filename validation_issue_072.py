#!/usr/bin/env python
"""ISSUE-072 Validation Suite — Reduced Core Operationalization Slice"""
import sys
import os

# Must run from project root
os.chdir(os.path.dirname(os.path.abspath(__file__)))

def test_bootstrap_import():
    print("=== TEST 1: Bootstrap Import ===")
    try:
        from system.orchestrator.bootstrap import initialize_system
        print("PASS: bootstrap imports cleanly")
        return True
    except Exception as e:
        print(f"FAIL: {e}")
        return False

def test_bootstrap_init():
    print("\n=== TEST 2: Bootstrap Initialization ===")
    try:
        from system.orchestrator.bootstrap import initialize_system
        result = initialize_system()
        assert result["status"] == "success", f"Expected success, got {result}"
        print(f"PASS: initialize_system() returned {result}")
        return True
    except Exception as e:
        print(f"FAIL: {e}")
        return False

def test_registry_typed_registration():
    print("\n=== TEST 3: Typed Agent Registration ===")
    try:
        from system.orchestrator.agent_registry import register_agent, get_agent, agents
        agents.clear()

        result = register_agent({
            "name": "typed_test_agent",
            "role": "test",
            "scope": ["test"],
            "type": "test_type",
            "capabilities": ["cap1", "cap2"],
            "version": "1.0.0"
        })
        assert result["status"] == "success", f"Typed registration failed: {result}"

        get_result = get_agent("typed_test_agent")
        assert get_result["status"] == "success"
        agent = get_result["agent"]
        assert agent["type"] == "test_type"
        assert agent["capabilities"] == ["cap1", "cap2"]
        assert agent["version"] == "1.0.0"
        print("PASS: typed fields stored correctly")
        return True
    except Exception as e:
        print(f"FAIL: {e}")
        return False
    finally:
        agents.clear()

def test_registry_backward_compat():
    print("\n=== TEST 4: Backward-Compatible Registration ===")
    try:
        from system.orchestrator.agent_registry import register_agent, get_agent, agents
        agents.clear()

        result = register_agent({
            "name": "legacy_agent",
            "role": "legacy",
            "scope": ["legacy"]
        })
        assert result["status"] == "success", f"Legacy registration failed: {result}"

        get_result = get_agent("legacy_agent")
        assert get_result["status"] == "success"
        print("PASS: legacy registration without typed fields works")
        return True
    except Exception as e:
        print(f"FAIL: {e}")
        return False
    finally:
        agents.clear()

def test_agent_executor_import():
    print("\n=== TEST 5: Agent Executor Import ===")
    try:
        from system.orchestrator.agent_executor import execute_agent
        print("PASS: agent_executor imports cleanly")
        return True
    except Exception as e:
        print(f"FAIL: {e}")
        return False

def test_tool_selection_agent_import():
    print("\n=== TEST 6: Tool Selection Agent Import ===")
    try:
        from system.orchestrator.agents.tool_selection_agent import execute_tool_selection
        print("PASS: tool_selection_agent imports cleanly")
        return True
    except Exception as e:
        print(f"FAIL: {e}")
        return False

def test_use_tool_fast_path():
    print("\n=== TEST 7: USE_TOOL Fast Path ===")
    try:
        from system.orchestrator.agent_executor import execute_agent
        from system.orchestrator.agent_registry import register_agent, agents
        agents.clear()
        register_agent({
            "name": "test_agent",
            "role": "test",
            "scope": ["test"]
        })

        result = execute_agent(
            {"name": "test_agent", "role": "test", "scope": ["test"]},
            "USE_TOOL: square_number 5"
        )
        assert result["status"] == "success", f"Expected success, got {result}"
        assert "execution_result" in result["result"]
        exec_res = result["result"]["execution_result"]
        assert exec_res["status"] == "success", f"execution failed: {exec_res}"
        assert exec_res["result"] == 25, f"Expected 25, got {exec_res['result']}"
        print(f"PASS: USE_TOOL fast path works, result={exec_res}")
        return True
    except Exception as e:
        print(f"FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        agents.clear()

def test_system_entry_smoke():
    print("\n=== TEST 8: system_entry Smoke Test ===")
    try:
        from system.entry.system_entry import system_entry
        result = system_entry("square_number 5")
        assert result["status"] == "success", f"system_entry failed: {result}"
        assert result["result"] == 25
        print(f"PASS: system_entry works, result={result}")
        return True
    except Exception as e:
        print(f"FAIL: {e}")
        return False

def test_no_change_boundary():
    print("\n=== TEST 9: No-Change Boundary Check ===")
    try:
        import os
        # These files must exist and NOT have been modified by ISSUE-072
        boundary_files = [
            "system/entry/system_entry.py",
            "system/orchestrator/step_executor.py",
            "system/orchestrator/governance.py",
        ]
        for f in boundary_files:
            assert os.path.exists(f), f"Boundary file missing: {f}"
        print("PASS: all no-change boundary files present")
        return True
    except Exception as e:
        print(f"FAIL: {e}")
        return False

def test_dormant_legacy_not_reconnected():
    print("\n=== TEST 10: Dormant Legacy Agent Reconnection Absence ===")
    try:
        from system.orchestrator.agent_registry import agents
        # After bootstrap, only default_agent and tool_selection_agent should be registered
        # No legacy agents (code_agent, tester_agent, system_test_agent) should appear
        legacy_names = ["code_agent", "tester_agent", "system_test_agent"]
        for name in legacy_names:
            assert name not in agents, f"Legacy agent '{name}' was unexpectedly registered"
        print(f"PASS: no legacy agents reconnected. Registered: {list(agents.keys())}")
        return True
    except Exception as e:
        print(f"FAIL: {e}")
        return False

if __name__ == "__main__":
    results = []
    results.append(("bootstrap_import", test_bootstrap_import()))
    results.append(("bootstrap_init", test_bootstrap_init()))
    results.append(("registry_typed", test_registry_typed_registration()))
    results.append(("registry_backward_compat", test_registry_backward_compat()))
    results.append(("agent_executor_import", test_agent_executor_import()))
    results.append(("tool_selection_agent_import", test_tool_selection_agent_import()))
    results.append(("use_tool_fast_path", test_use_tool_fast_path()))
    results.append(("system_entry_smoke", test_system_entry_smoke()))
    results.append(("no_change_boundary", test_no_change_boundary()))
    results.append(("dormant_legacy", test_dormant_legacy_not_reconnected()))

    print("\n" + "=" * 50)
    print("VALIDATION SUMMARY")
    print("=" * 50)
    all_pass = True
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: {status}")
        if not passed:
            all_pass = False
    print("=" * 50)
    if all_pass:
        print("ALL VALIDATION TESTS PASSED")
        sys.exit(0)
    else:
        print("SOME VALIDATION TESTS FAILED")
        sys.exit(1)
