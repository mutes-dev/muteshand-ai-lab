#!/usr/bin/env python
"""ISSUE-072 Agent Executor Refactor Regression Tests"""
import sys
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

def test_normal_llm_use_tool_path():
    print("=== REGRESSION TEST 1: Normal LLM USE_TOOL Output ===")
    try:
        from unittest.mock import patch, MagicMock
        from system.orchestrator.agent_executor import execute_agent
        from system.orchestrator.agent_registry import register_agent, agents
        agents.clear()
        register_agent({"name": "test_agent", "role": "test", "scope": ["test"]})

        mock_provider = MagicMock()
        mock_get_llm = MagicMock(return_value={"status": "success", "provider": mock_provider})
        mock_execute_llm = MagicMock(return_value={"status": "success", "result": "USE_TOOL: square_number 5"})

        with patch("system.orchestrator.agents.tool_selection_agent.get_llm", mock_get_llm), \
             patch("system.orchestrator.agents.tool_selection_agent.execute_llm", mock_execute_llm):
            result = execute_agent({"name": "test_agent", "role": "test", "scope": ["test"]}, "square 5")

        assert result["status"] == "success", f"Expected success, got {result}"
        assert "execution_result" in result["result"]
        exec_res = result["result"]["execution_result"]
        assert exec_res["status"] == "success" and exec_res["result"] == 25, f"Expected 25, got {exec_res}"
        print(f"PASS: normal LLM path works, result={exec_res}")
        return True
    except Exception as e:
        print(f"FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        agents.clear()

def test_multiple_use_tool_enforcement():
    print("\n=== REGRESSION TEST 2: Multiple USE_TOOL Enforcement ===")
    try:
        from unittest.mock import patch, MagicMock
        from system.orchestrator.agent_executor import execute_agent
        from system.orchestrator.agent_registry import register_agent, agents
        agents.clear()
        register_agent({"name": "test_agent", "role": "test", "scope": ["test"]})

        mock_provider = MagicMock()
        mock_get_llm = MagicMock(return_value={"status": "success", "provider": mock_provider})
        mock_execute_llm = MagicMock(return_value={"status": "success", "result": "USE_TOOL: square_number 5\nUSE_TOOL: cube_number 3"})

        with patch("system.orchestrator.agents.tool_selection_agent.get_llm", mock_get_llm), \
             patch("system.orchestrator.agents.tool_selection_agent.execute_llm", mock_execute_llm):
            result = execute_agent({"name": "test_agent", "role": "test", "scope": ["test"]}, "square 5 and cube 3")

        assert result["status"] == "failure" and result.get("reason") == "multiple_tool_calls_not_allowed"
        print("PASS: multiple USE_TOOL lines correctly rejected")
        return True
    except Exception as e:
        print(f"FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        agents.clear()

def test_no_use_tool_fallback():
    print("\n=== REGRESSION TEST 3: No USE_TOOL Fallback / finalize_output ===")
    try:
        from unittest.mock import patch, MagicMock
        from system.orchestrator.agent_executor import execute_agent
        from system.orchestrator.agent_registry import register_agent, agents
        agents.clear()
        register_agent({"name": "test_agent", "role": "test", "scope": ["test"]})

        mock_provider = MagicMock()
        mock_get_llm = MagicMock(return_value={"status": "success", "provider": mock_provider})
        mock_execute_llm = MagicMock(return_value={"status": "success", "result": "Hello world, no tool needed"})

        with patch("system.orchestrator.agents.tool_selection_agent.get_llm", mock_get_llm), \
             patch("system.orchestrator.agents.tool_selection_agent.execute_llm", mock_execute_llm):
            result = execute_agent({"name": "test_agent", "role": "test", "scope": ["test"]}, "say hello")

        assert result["status"] == "success" and "execution_result" in result["result"]
        assert result["result"]["execution_result"]["status"] == "success"
        print(f"PASS: no USE_TOOL fallback works")
        return True
    except Exception as e:
        print(f"FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        agents.clear()

def test_llm_error_handling():
    print("\n=== REGRESSION TEST 4: LLM_ERROR Handling ===")
    try:
        from unittest.mock import patch, MagicMock
        from system.orchestrator.agent_executor import execute_agent
        from system.orchestrator.agent_registry import register_agent, agents
        agents.clear()
        register_agent({"name": "test_agent", "role": "test", "scope": ["test"]})

        mock_provider = MagicMock()
        mock_get_llm = MagicMock(return_value={"status": "success", "provider": mock_provider})
        mock_execute_llm = MagicMock(return_value={"status": "failure", "reason": "llm_timeout"})

        with patch("system.orchestrator.agents.tool_selection_agent.get_llm", mock_get_llm), \
             patch("system.orchestrator.agents.tool_selection_agent.execute_llm", mock_execute_llm):
            result = execute_agent({"name": "test_agent", "role": "test", "scope": ["test"]}, "square 5")

        assert result["status"] == "failure" and result["result"]["output"] is None and result["result"]["execution_result"] is None
        print("PASS: LLM_ERROR handled correctly")
        return True
    except Exception as e:
        print(f"FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        agents.clear()

def test_all_execution_routes_through_system_entry():
    print("\n=== REGRESSION TEST 5: All Execution Routes Through system_entry ===")
    try:
        from unittest.mock import patch, MagicMock
        from system.orchestrator.agent_executor import execute_agent
        from system.orchestrator.agent_registry import register_agent, agents
        agents.clear()
        register_agent({"name": "test_agent", "role": "test", "scope": ["test"]})

        mock_system_entry = MagicMock(return_value={"status": "success", "result": 25})
        mock_provider = MagicMock()
        mock_get_llm = MagicMock(return_value={"status": "success", "provider": mock_provider})
        mock_execute_llm = MagicMock(return_value={"status": "success", "result": "USE_TOOL: square_number 5"})

        with patch("system.orchestrator.agents.tool_selection_agent.system_entry", mock_system_entry), \
             patch("system.orchestrator.agents.tool_selection_agent.get_llm", mock_get_llm), \
             patch("system.orchestrator.agents.tool_selection_agent.execute_llm", mock_execute_llm):
            result = execute_agent({"name": "test_agent", "role": "test", "scope": ["test"]}, "square 5")

        assert mock_system_entry.called, "system_entry was NOT called"
        print(f"PASS: system_entry called")
        return True
    except Exception as e:
        print(f"FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        agents.clear()

def test_execution_result_from_system_entry():
    print("\n=== REGRESSION TEST 6: execution_result from system_entry ===")
    try:
        from unittest.mock import patch, MagicMock
        from system.orchestrator.agent_executor import execute_agent
        from system.orchestrator.agent_registry import register_agent, agents
        agents.clear()
        register_agent({"name": "test_agent", "role": "test", "scope": ["test"]})

        mock_system_entry = MagicMock(return_value={"status": "success", "result": 42})
        mock_provider = MagicMock()
        mock_get_llm = MagicMock(return_value={"status": "success", "provider": mock_provider})
        mock_execute_llm = MagicMock(return_value={"status": "success", "result": "USE_TOOL: square_number 5"})

        with patch("system.orchestrator.agents.tool_selection_agent.system_entry", mock_system_entry), \
             patch("system.orchestrator.agents.tool_selection_agent.get_llm", mock_get_llm), \
             patch("system.orchestrator.agents.tool_selection_agent.execute_llm", mock_execute_llm):
            result = execute_agent({"name": "test_agent", "role": "test", "scope": ["test"]}, "square 5")

        exec_res = result["result"]["execution_result"]
        assert exec_res == {"status": "success", "result": 42}, f"execution_result mismatch: {exec_res}"
        print(f"PASS: execution_result comes from system_entry")
        return True
    except Exception as e:
        print(f"FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        agents.clear()

def test_invalid_agent_input_still_rejected():
    print("\n=== REGRESSION TEST 7: Invalid Agent Input Still Rejected ===")
    try:
        from system.orchestrator.agent_executor import execute_agent
        result = execute_agent({"name": "bad_agent"}, "square 5")
        assert result["status"] == "failure"
        print("PASS: invalid agent input correctly rejected")
        return True
    except Exception as e:
        print(f"FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    results = []
    results.append(("normal_llm_use_tool", test_normal_llm_use_tool_path()))
    results.append(("multiple_use_tool", test_multiple_use_tool_enforcement()))
    results.append(("no_use_tool_fallback", test_no_use_tool_fallback()))
    results.append(("llm_error", test_llm_error_handling()))
    results.append(("routes_through_system_entry", test_all_execution_routes_through_system_entry()))
    results.append(("execution_result_source", test_execution_result_from_system_entry()))
    results.append(("invalid_agent_input", test_invalid_agent_input_still_rejected()))

    print("\n" + "=" * 50)
    print("REGRESSION SUMMARY")
    print("=" * 50)
    all_pass = True
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: {status}")
        if not passed:
            all_pass = False
    print("=" * 50)
    if all_pass:
        print("ALL REGRESSION TESTS PASSED")
        sys.exit(0)
    else:
        print("SOME REGRESSION TESTS FAILED")
        sys.exit(1)
