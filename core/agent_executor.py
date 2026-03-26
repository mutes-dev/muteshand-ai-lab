import re
import os
import json
import importlib


def execute_agent(
    agent_name,
    agent_input,
    AGENTS,
    TOOLS,
    tool_index,
    INFRASTRUCTURE_TOOLS,
    infrastructure_agents,
    task_state,
    steps,
    results,
    manager_prompt,
    repair_mode,
    failed_tool,
    repair_attempts,
    MAX_REPAIR_ATTEMPTS,
    drift_counter,
    creation_goal,
    goal_lower,
    TOOLS_PATH,
    AGENTS_PATH,
    memory,
    log,
    validate_python_file,
    refresh_system,
    save_tool_index,
    MODE
):

    # -------------------
    # AGENT ACTION
    # -------------------

    agent_input = agent_input.strip()

    # -------------------
    # REPAIR ATTEMPT TRACKING
    # -------------------

    if agent_name == "code_agent" and agent_input:

        # Enforce repair limit if a tool is already failing
        if failed_tool:

            attempts = repair_attempts.get(failed_tool, 0)

            if attempts >= MAX_REPAIR_ATTEMPTS:

                msg = f"SYSTEM: The tool '{failed_tool}' has failed repair {MAX_REPAIR_ATTEMPTS} times. Stop attempting automatic repair."

                log(msg)

                manager_prompt += f"\n{msg}\n"

                repair_mode = False

                return None, manager_prompt, repair_mode, failed_tool, drift_counter

        lowered = agent_input.lower()

        repair_match = re.search(r"(repair|create)\s+tool\s+([a-zA-Z_][a-zA-Z0-9_]*)", lowered)

        if repair_match:

            candidate = repair_match.group(2)

            # Block modification of infrastructure tools
            if candidate in INFRASTRUCTURE_TOOLS:

                msg = f"{candidate} is an infrastructure tool and cannot be modified automatically."

                log(msg)

                manager_prompt += f"\nSYSTEM: {msg}\n"

                repair_mode = False

                return None, manager_prompt, repair_mode, failed_tool, drift_counter

            if candidate in TOOLS:

                failed_tool = candidate

                attempts = repair_attempts.get(failed_tool, 0)

                if attempts >= MAX_REPAIR_ATTEMPTS:

                    msg = f"SYSTEM: The tool '{failed_tool}' has failed repair {MAX_REPAIR_ATTEMPTS} times. Stop attempting automatic repair."

                    log(msg)

                    manager_prompt += f"\n{msg}\n"

                    repair_mode = False

                    return None, manager_prompt, repair_mode, failed_tool, drift_counter

                repair_attempts[failed_tool] = attempts + 1


    log(f"AGENT ACTION: {agent_name}({agent_input})")

    try:
        output = AGENTS[agent_name](agent_input)
        drift_counter = 0
    except Exception as e:
        output = f"Agent execution error: {e}"

    log(f"AGENT RESULT: {output}")

    # -------------------
    # TOOL RELOAD AFTER REPAIR (CRITICAL FIX)
    # -------------------

    if agent_name == "code_agent" and failed_tool:

        try:
            module = importlib.import_module(f"tools.{failed_tool}")
            importlib.reload(module)

            TOOLS[failed_tool] = module.run

            log(f"SYSTEM: Reloaded tool '{failed_tool}' after repair.")

        except Exception as e:
            log(f"SYSTEM: Failed to reload tool '{failed_tool}': {e}")

    # ✅ ADVANCE STEP ONLY IF CORRECT STEP EXECUTED
    if task_state["structured_plan"] and task_state["current_step"] < len(task_state["structured_plan"]):
        expected = task_state["structured_plan"][task_state["current_step"]]

        if expected["type"] == "agent" and agent_name == expected["name"]:
            # PHASE 1 OVERRIDE — step progression controlled by manager
            pass

        results.append(output)

    # -------------------
    # PLAN STEP PROGRESSION (MINIMAL — DO NOT MOVE FULL LOGIC)
    # -------------------

    output_text = str(output).lower()

    agent_failed = (
        "tool test failed" in output_text
        or "test failed" in output_text
    )

    # -------------------
    # REPAIR TRACKING SYNC (RESTORE ORIGINAL BEHAVIOR)
    # -------------------

    if agent_failed and failed_tool:

        if failed_tool not in repair_attempts:
            repair_attempts[failed_tool] = 0

    # -------------------
    # FAILURE SIGNAL (RESTORE MANAGER BEHAVIOR)
    # -------------------

    if agent_failed and not failed_tool:

        # Try to extract tool name from output
        match = re.search(r"tool test failed:\s*([a-zA-Z_][a-zA-Z0-9_]*)", str(output), re.IGNORECASE)

        if match:
            failed_tool = match.group(1).strip()

    # -------------------
    # RESULT FEEDBACK
    # -------------------

    return output, manager_prompt, repair_mode, failed_tool, drift_counter


def handle_agent_plan_expansion(output, task_state, log):

    expanded = False

    # -------------------
    # AGENT PLAN EXPANSION
    # -------------------

    if isinstance(output, str):

        lines = output.strip().split("\n")

        action_blocks = []
        current_block = []

        for line in lines:

            line = line.strip()

            if (
                line.startswith("AGENT:")
                or line.startswith("TOOL:")
                or line.startswith("CAPABILITY:")
            ):

                if current_block:
                    action_blocks.append("\n".join(current_block))
                    current_block = []

                current_block.append(line)

            elif line.startswith("INPUT:"):

                current_block.append(line)

            else:
                continue

        if current_block:
            action_blocks.append("\n".join(current_block))

        if action_blocks:

            log("Agent returned executable actions. Expanding structured plan.")

            expanded_steps = []

            for block in action_blocks:

                try:

                    header, input_line = block.split("\n", 1)

                    action_type, name = header.split(":", 1)
                    name = name.strip()

                    input_value = input_line.replace("INPUT:", "").strip()

                    expanded_steps.append({
                        "type": action_type.lower(),
                        "name": name,
                        "input": input_value
                    })

                except Exception as e:

                    log(f"Failed to parse agent action block: {block} | Error: {e}")

            if expanded_steps:

                current_index = task_state["current_step"]

                task_state["structured_plan"] = (
                    task_state["structured_plan"][:current_index + 1]
                    + expanded_steps
                    + task_state["structured_plan"][current_index + 1:]
                )

                task_state["expanded"] = True

                # PHASE 1 OVERRIDE — step progression controlled by manager
                pass

                log(f"Inserted {len(expanded_steps)} new plan steps from agent.")

                expanded = True

    return task_state, expanded
