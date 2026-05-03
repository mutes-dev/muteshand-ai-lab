"""Step Chainer Module — Handles result propagation WITHOUT changing behavior.

This module extracts the chaining logic from orchestrator_runtime
to create a clean separation of concerns. BEHAVIOR IS LOCKED.
"""


def propagate_result(step, execution_result, step_result, debug_verbose=False):
    """
    Propagate execution results to step metadata.

    Args:
        step: The step dict to update (modified in-place)
        execution_result: The execution_result dict
        step_result: The raw step result from execute_agent
        debug_verbose: Debug output flag

    Returns:
        The updated step dict (same object, modified in-place)
    """
    # === STEP RESULT PROCESSING ===
    result = step_result if step_result else {"status": "failure", "reason": "no_steps_executed"}
    agent_result = result.get("result")
    tool_call = agent_result.get("reasoning") if isinstance(agent_result, dict) else agent_result

    has_tool_call = (
        isinstance(tool_call, str) and
        tool_call.startswith("USE_TOOL:")
    )

    if debug_verbose:
        print("\n[TOOL OBSERVER]")
        if has_tool_call:
            from system.orchestrator.orchestrator_runtime import observe_tool_call
            obs = observe_tool_call(tool_call)
            print(obs)
        else:
            print({
                "skipped": True,
                "reason": "no_tool_call",
                "value": tool_call
            })
        print("TRACE agent_result:", agent_result)
        print("TRACE result:", result)
        print("TRACE entering propagation block")

    if isinstance(agent_result, dict):
        # execution_result propagation
        if debug_verbose:
            print("TRACE execution_result assigned:", agent_result.get("execution_result") if isinstance(agent_result, dict) else None)
        if agent_result.get("execution_result") is not None:
            step["execution_result"] = agent_result.get("execution_result")

        # output propagation
        exec_res = agent_result.get("execution_result")
        output = agent_result.get("output")
        if debug_verbose:
            print("TRACE output assigned:", output)

        # HARD RULE: execution_result is authoritative
        if exec_res and exec_res.get("status") == "success":
            step["output"] = exec_res.get("result")
        else:
            # Only use LLM output if NO tool executed
            step["output"] = output if output is not None else None

    # Mismatch detection
    exec_res = step.get("execution_result")
    agent_output = step.get("output")

    if exec_res and agent_output:
        expected = str(exec_res.get("result")).strip()
        actual = str(agent_output).strip()
        actual_tokens = actual.split()

        if expected not in actual_tokens:
            step["mismatch"] = True
        else:
            step["mismatch"] = False

    if "mismatch" not in step:
        step["mismatch"] = False

    if debug_verbose:
        print("TRACE step after propagation:", step)

    # Interpretation and decision (advisory only)
    from system.orchestrator.agent_output_interpreter import interpret_agent_output
    from system.orchestrator.decision_hook import evaluate_interpretation

    interpretation = interpret_agent_output(result)
    step["interpreted"] = interpretation

    decision = evaluate_interpretation(interpretation)
    step["decision"] = decision

    # executed_input tracking
    step["executed_input"] = agent_result.get("executed_input") if isinstance(agent_result, dict) else None

    # Ensure execution_result is always on step for governance
    if step.get("execution_result") is None and execution_result is not None:
        step["execution_result"] = execution_result

    return step
