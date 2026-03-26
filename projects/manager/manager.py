"""
AI Lab Manager Module - Central Orchestrator

PURPOSE:
    Main entry point and orchestrator for the AI Lab system.
    Coordinates planning, execution, validation, and repair loops.
    Handles goal processing from user input to final answer.

ARCHITECTURE ROLE:
    - Orchestration layer: Coordinates all system components
    - Control flow: Manages execution state machine
    - Side effects: Executes tools, modifies state, logs operations
    - Entry point: Interactive mode and programmatic API

LAYER RESPONSIBILITY:
    - Parse and process user goals
    - Call planner to generate execution plans
    - Validate plans before execution
    - Execute tools and agents from structured plans
    - Handle repair loops for failed tools
    - Enforce plan adherence (prevent drift)
    - Manage execution state and step progression
    - Log all operations for debugging

SYSTEM FLOW:
    1. User Input -> Goal Parsing
    2. Goal -> Planner (structured plan generation)
    3. Plan -> Validation (structure, tools, args, chaining)
    4. Valid Plan -> Execution Loop
       a. Get next step from plan
       b. Execute tool/agent
       c. Handle result (success/failure)
       d. Advance or repair
    5. Completion -> Final Answer

DEPENDENCIES:
    - core.config: Configuration constants
    - core.logger: Logging utilities
    - core.parser: Input tokenization
    - core.argument_resolver: Argument extraction
    - core.chain_resolver: PREVIOUS_RESULT resolution
    - core.planner: Plan generation
    - core.validation: Plan validation
    - core.tool_executor: Tool execution utilities
    - core.llm: LLM interface
"""

import json
import os
import sys
import importlib
import py_compile
import re

# Add the parent folder (MutesHand) to Python's search path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
# ↑ this makes E:\MutesHand visible, so core/ can be found from projects/manager/

from datetime import datetime
from core.config import config
from core.logger import log, log_execution, set_mode
from core.tool_executor import normalize_tool_input, tool_failed, parse_tool_parentheses, execute_tool
from core.parser import parse_tool_input
from core.argument_resolver import resolve_arguments
from core.chain_resolver import resolve_chain
from core.planner import generate_structured_plan
from core.validation import validate_plan

sys.path.append("E:/MutesHand")

from core.llm import ask_llm

# Retry control for planner execution
MAX_RETRIES = 3

def call_model(prompt):
    """
    Wrapper function for LLM calls.
    
    Provides a clean interface to the core LLM functionality.
    Currently a thin wrapper around ask_llm for potential future extensions.
    
    Args:
        prompt (str): The prompt to send to the LLM
        
    Returns:
        str: Generated response from the LLM
    """
    return ask_llm(prompt)

# -------------------
# CONFIGURATION
# -------------------

# Manager operating mode (now controlled via config)
if len(sys.argv) > 1:
    set_mode(sys.argv[1])           # sets config.MODE from command line
else:
    set_mode("debug")               # default to debug if no argument given


# -------------------
# INFRASTRUCTURE AGENTS
# -------------------
# Agents that provide system-level capabilities
# These are protected from modification during repairs

infrastructure_agents = {"tester_agent", 
                         "debug_agent", 
                         "planner_agent", 
                         "system_test_agent"
}


# -------------------
# INFRASTRUCTURE TOOLS
# -------------------
# System-level tools that manage the environment
# These are protected from automatic modification

INFRASTRUCTURE_TOOLS = {
    "rebuild_tool_index",
    "run_system_maintenance",
    "health_check_system",
    "self_test_system",
    "web_search",
    "write_file",
    "read_file",
    "run_python",
    "inspect_manager_section"
}

# -------------------
# MEMORY
# -------------------

def load_memory():
    """
    Load system memory from persistent storage.
    
    Memory contains agent and tool registries for the current session.
    Creates empty structure if memory file doesn't exist.
    
    Returns:
        dict: Memory structure with "agents", "tools", "projects" keys
        Returns empty structure if file not found.
    """
    if not os.path.exists(config.MEMORY_FILE):
        return {"agents": [], "tools": [], "projects": []}

    with open(config.MEMORY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_memory(memory):
    """
    Save system memory to persistent storage.
    
    Persists agent and tool lists for session continuity.
    
    Args:
        memory (dict): Memory structure to save
        
    Side Effects:
        - Writes to config.MEMORY_FILE
    """
    with open(config.MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memory, f, indent=2)


def validate_python_file(file_path):
    """
    Validate Python file syntax by compiling it.
    
    Used to check newly created tools before registration.
    
    Args:
        file_path (str): Path to Python file to validate
        
    Returns:
        bool: True if valid Python syntax
        str: Error message if compilation fails
    """
    try:
        py_compile.compile(file_path, doraise=True)
        return True
    except Exception as e:
        return str(e)        

# -------------------
# REFRESH SYSTEM
# -------------------

def refresh_system():
    """
    Refresh the tool and agent registries from disk.
    
    Reloads all tool and agent modules, updating TOOLS and AGENTS dicts.
    Called after new tools/agents are created to pick up changes.
    
    Side Effects:
        - Clears and repopulates TOOLS dict
        - Clears and repopulates AGENTS dict
        - Updates memory with new tool/agent lists
        - Writes updated memory to disk
    """
    global TOOLS, AGENTS, memory

    importlib.invalidate_caches()

    TOOLS = {}
    AGENTS = {}

    # Load tools from /tools directory
    for file in os.listdir(TOOLS_PATH):
        if file.endswith(".py"):
            tool_name = file[:-3]
            module = importlib.import_module(f"tools.{tool_name}")
            importlib.reload(module)
            TOOLS[tool_name] = module.run

    # Load agents from /agents directory
    if os.path.exists(AGENTS_PATH):
        for file in os.listdir(AGENTS_PATH):
            if file.endswith(".py"):
                agent_name = file[:-3]
                module = importlib.import_module(f"agents.{agent_name}")
                importlib.reload(module)
                AGENTS[agent_name] = module.run

    # Update memory with current tool/agent lists
    memory["tools"] = list(TOOLS.keys())
    memory["agents"] = list(AGENTS.keys())

    save_memory(memory)
    log("System refreshed.")        

TOOLS = {}

AGENT_REGISTRY_PATH = os.path.join(config.BASE_PATH, "memory", "agent_registry.json")

TOOLS_PATH = os.path.join(config.BASE_PATH, "tools")

for file in os.listdir(TOOLS_PATH):

    if file.endswith(".py"):

        tool_name = file[:-3]

        module = importlib.import_module(f"tools.{tool_name}")

        TOOLS[tool_name] = module.run

# -------------------
# AGENT LOADER
# -------------------

AGENTS = {}

AGENTS_PATH = os.path.join(config.BASE_PATH, "agents")

if os.path.exists(AGENTS_PATH):

    for file in os.listdir(AGENTS_PATH):

        if file.endswith(".py"):

            agent_name = file[:-3]

            module = importlib.import_module(f"agents.{agent_name}")

            AGENTS[agent_name] = module.run        

# -------------------
# AGENT CAPABILITY MATCHING
# -------------------

def find_agent_by_capability(capability):
    """
    Find an agent that provides the specified capability.
    
    Searches AGENT_REGISTRY for agents advertising the given capability.
    Returns the first matching agent that is also loaded in AGENTS.
    
    Args:
        capability (str): The capability to search for
        
    Returns:
        str: Agent name if found, None otherwise
    """
    if capability is None:
        return None

    for agent, data in AGENT_REGISTRY.items():
        caps = data.get("capabilities", [])
        if capability in caps and agent in AGENTS:
            return agent

    return None            

# -------------------
# LOAD MEMORY
# -------------------

def load_agent_registry():
    """
    Load the agent capability registry from disk.
    
    Returns:
        dict: Agent registry mapping agent names to their capabilities
        Empty dict if registry file doesn't exist
    """
    if not os.path.exists(AGENT_REGISTRY_PATH):
        return {}
    with open(AGENT_REGISTRY_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

TOOL_INDEX_FILE = os.path.join(config.BASE_PATH, "memory", "tool_index", "tools.json")

def load_tool_index():
    """
    Load the tool metadata index from disk.
    
    The tool index contains metadata for each tool:
    - description: What the tool does
    - inputs: Expected arguments
    - tags: Search keywords
    
    Returns:
        dict: Tool index mapping tool names to metadata
        Empty dict if index file doesn't exist
    """
    if not os.path.exists(TOOL_INDEX_FILE):
        return {}
    with open(TOOL_INDEX_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

tool_index = load_tool_index()

def save_tool_index(index):
    """
    Save the tool metadata index to disk.
    
    Args:
        index (dict): Tool index to persist
        
    Side Effects:
        - Writes to TOOL_INDEX_FILE
    """
    with open(TOOL_INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)

def get_expected_arg_count(tool_name):
    """Get the expected number of arguments for a tool from tool_index.
    
    Args:
        tool_name: Name of the tool
        
    Returns:
        int: Number of expected arguments, or None if tool not in index
    """
    if tool_name not in tool_index:
        return None
    
    inputs = tool_index[tool_name].get("inputs", {})
    
    if not inputs:
        return 0
    
    return len(inputs)

def shape_arguments(tool_name, args, tool_registry):
    """
    Adjust parsed arguments to match tool expectations.
    
    Performs cleanup and transformation:
    - Removes filler tokens (and, comma, period)
    - Joins multiple args into single string if tool expects 1 arg
    
    Args:
        tool_name (str): Name of the tool
        args (list): Parsed arguments from input
        tool_registry (dict): Tool definitions (not currently used)
        
    Returns:
        list: Adjusted arguments ready for tool execution
    """
    if not args:
        return args

    # CLEANUP: remove filler tokens
    cleaned_args = []
    for a in args:
        if isinstance(a, str):
            token = a.strip().lower()
            if token in ["and", ",", ".", ""]:
                continue
        cleaned_args.append(a)

    args = cleaned_args

    expected_args = get_expected_arg_count(tool_name)
    
    # If tool expects exactly 1 argument -> join into string
    if expected_args == 1 and len(args) > 1:
        return [" ".join(str(a) for a in args)]

    return args

def retrieve_relevant_tools(goal, limit=10):
    """
    Find tools relevant to the given goal using keyword matching.
    
    Scores tools based on:
    - Tag matches (3 points)
    - Description matches (2 points)
    - Tool name matches (1 point)
    
    Args:
        goal (str): User goal to match against
        limit (int): Maximum number of tools to return
        
    Returns:
        list: Top-scoring tool names, up to limit
    """
    goal_words = set(re.findall(r"[a-zA-Z_]+", goal.lower()))

    scored = []

    for tool_name, data in tool_index.items():
        description = str(data.get("description", "")).lower()
        tags = " ".join(data.get("tags", [])).lower()

        score = 0

        for word in goal_words:
            if word in description:
                score += 2
            if word in tags:
                score += 3
            if word in tool_name.lower():
                score += 1

        scored.append((score, tool_name))

    scored.sort(reverse=True)

    selected = [tool for score, tool in scored if score > 0]

    if not selected:
        selected = list(tool_index.keys())

    return selected[:limit]  

# -------------------
# Metadata Generator
# -------------------

def generate_tool_metadata(tool_name, tool_code):

    prompt = f"""
Analyze the following Python tool and generate metadata.

Tool name: {tool_name}

Tool code:
{tool_code}

Return ONLY valid JSON in this format:

{{
  "description": "Short sentence describing the tool",
  "tags": ["keyword1","keyword2","keyword3"]
}}
"""

    try:

        response = call_model(prompt)

        match = re.search(r"\{.*\}", response, re.DOTALL)

        if not match:
            raise ValueError("No JSON object found in model response.")

        metadata = json.loads(match.group(0))

        return {
            "description": metadata.get("description", f"Tool {tool_name}"),
            "tags": metadata.get("tags", [])
        }

    except Exception as e:

        log(f"Metadata generation failed for {tool_name}: {e}")

        return {
            "description": f"Tool {tool_name}",
            "tags": []
        }
# -------------------
# TOOL METADATA ENRICHMENT
# -------------------

for tool_name, data in tool_index.items():

    # Skip metadata generation in test mode
    if config.MODE == "test":
        break

    description = data.get("description", "")

    if tool_name in INFRASTRUCTURE_TOOLS:
        continue

    if description.startswith("Tool "):

        tool_file = os.path.join(TOOLS_PATH, f"{tool_name}.py")

        try:

            with open(tool_file, "r", encoding="utf-8") as f:
                tool_code = f.read()

            metadata = generate_tool_metadata(tool_name, tool_code)

            data["description"] = metadata.get("description", description)
            data["tags"] = metadata.get("tags", [])

            log(f"Metadata generated for tool: {tool_name}")

        except Exception as e:

            log(f"Metadata enrichment failed for {tool_name}: {e}")

save_tool_index(tool_index)

memory = load_memory()

AGENT_REGISTRY = load_agent_registry()

refresh_system()

log(f"Memory loaded: {memory}")

# -------------------
# ENFORCE REPAIR LIMIT
# -------------------
def enforce_repair_limit(failed_tool, repair_attempts, MAX_REPAIR_ATTEMPTS, goal, task_state, results, config):
    attempts = repair_attempts.get(failed_tool, 0)
    if attempts >= MAX_REPAIR_ATTEMPTS:
        msg = f"The tool '{failed_tool}' has failed repair {MAX_REPAIR_ATTEMPTS} times. Stop attempting automatic repair."
        log(msg)

        # Set repair_mode off here — single source of truth
        global repair_mode
        repair_mode = False

        failure_msg = (
            f"Repair limit reached - tool '{failed_tool}' could not be fixed. "
            f"Failed after {MAX_REPAIR_ATTEMPTS} repair attempts. "
            f"Original failure persisted."
        )
        print(f"\nFINAL ANSWER: {failure_msg}\n")
        log_execution(goal, task_state, results + [failure_msg])

        if config.MODE == "test":
            exit(1)  # force regression harness to see failure

        return True  # signal caller: terminate loop now
    return False

# -------------------
# TASK PLANNING
# -------------------
# OLD planner (generate_plan) removed - all goals now use NEW planner (generate_structured_plan)

# -------------------
# PLAN PARSER
# -------------------
# OLD planner parser (parse_plan) removed - all goals now use NEW planner which outputs structured plans directly

# -------------------
# Capability Inference Engine
# -------------------

def infer_capability(goal):

    capabilities = []

    for agent, data in AGENT_REGISTRY.items():
        caps = data.get("capabilities", [])
        capabilities.extend(caps)

    capability_list = ", ".join(set(capabilities))

    prompt = f"""Determine which system capability should solve the following goal.

Goal:
{goal}

Available agents and capabilities:
{json.dumps(AGENT_REGISTRY, indent=2)}

Return only the capability name.
Return NONE if no capability is appropriate.
"""

    try:
        response = call_model(prompt).strip()
        return response
    except:
        return None

# -------------------
# COMPLETION HANDLER
# -------------------

def handle_plan_completion(task_state, results, goal, config):
    if not task_state["structured_plan"] or task_state["current_step"] < len(task_state["structured_plan"]):
        return False  # not complete

    log("Plan completed.")

    # Select final answer — prefer last valid result, fallback safe message
    if results:
        last_result = results[-1]
        if not tool_failed(last_result) and "test passed" in str(last_result).lower():
            final_answer = str(last_result).strip()
        else:
            final_answer = "Plan completed - no valid final result propagated."
    else:
        final_answer = "Plan completed - no results."

    log_execution(goal, task_state, results)
    log(f"FINAL ANSWER: {final_answer}")
    print(f"\nFINAL ANSWER: {final_answer}\n")

    if config.MODE == "test":
        exit(0)

    return True  # complete → caller should break

# -------------------
# HEADLESS EXECUTION FUNCTION
# -------------------

def run_goal(goal_text):
    """Execute a goal headlessly and return the final answer.
    
    Args:
        goal_text: The goal to execute
        
    Returns:
        str: The final answer (with "FINAL ANSWER: " prefix)
    """
    import io
    import sys
    
    # Capture output
    captured_output = io.StringIO()
    original_stdout = sys.stdout
    
    try:
        # Redirect stdout to capture prints
        sys.stdout = captured_output
        
        goal = goal_text.strip()
        
        if not goal:
            sys.stdout = original_stdout
            return "FINAL ANSWER: No goal provided."
        
        # The main loop code will execute and print the final answer
        # We'll capture it and return it
        
        # This is a simplified version - the actual execution happens in the main loop
        # For now, return a placeholder that indicates the function needs full implementation
        sys.stdout = original_stdout
        return "FINAL ANSWER: run_goal() requires full execution loop implementation"
        
    finally:
        sys.stdout = original_stdout

# -------------------
# AGENT GOAL DETECTION
# -------------------
# OLD agent goal detection (is_agent_goal) removed - all goals now use NEW planner regardless of keywords

# -------------------
# GOAL PROCESSING FUNCTION
# -------------------

def process_goal(goal):
    """
    Process a single goal and return the result or failure object.
    
    Args:
        goal (str): The user's goal
        
    Returns:
        dict: Either a success result or a failure object
    """
    log(f"GOAL: {goal}")

    capability_guess = infer_capability(goal)

    # Only apply capability routing for explicit capability tasks
    if capability_guess and capability_guess.strip().lower() != "none":
        if "capability" in goal.lower():
            goal = f"Use capability {capability_guess} to accomplish the goal: {goal}"

    # -------------------
    # PLANNING: Bounded retry loop for planner execution
    # -------------------
    
    tool_names = list(memory["tools"])
    
    previous_plan = None
    duplicate_detected = False
    
    # Bounded retry loop - maximum MAX_RETRIES attempts
    for attempt in range(MAX_RETRIES):
        print(f"[PLANNER ATTEMPT {attempt + 1}/{MAX_RETRIES}]")
        log(f"PLANNER ATTEMPT {attempt + 1}/{MAX_RETRIES}")
        
        # Call planner fresh each attempt
        new_plan = generate_structured_plan(goal, tool_index)
        
        if previous_plan is not None and new_plan == previous_plan:
            duplicate_detected = True
            continue
        
        previous_plan = new_plan
        
        # HANDLE PLANNER FAILURE OBJECT
        if isinstance(new_plan, dict) and new_plan.get("type") == "failure":
            # Planner failed - retry on next iteration
            print(f"[PLANNER FAILURE ATTEMPT {attempt + 1}] {new_plan.get('reason')}")
            log(f"PLANNER FAILURE ATTEMPT {attempt + 1}: {new_plan.get('reason')}")
            continue
        
        # Check if planner returned None
        if new_plan is None:
            print(f"[PLANNER FAILURE ATTEMPT {attempt + 1}] Planner returned None")
            log(f"PLANNER FAILURE ATTEMPT {attempt + 1}: Planner returned None")
            continue
        
        structured_plan = new_plan
        
        print("[PLANNER] Using NEW planner")
        log("PLANNER: Using NEW planner")
        log("PLAN GENERATED:")
        
        # Log plan steps
        for idx, step in enumerate(new_plan, 1):
            log(f"{idx}. {step.get('type')}: {step.get('name')} - {step.get('input_text')}")
        
        print("[STRUCTURED PLAN]", structured_plan)
        log(f"STRUCTURED PLAN: {structured_plan}")
        
        # VALIDATION: Check plan before execution
        validation_result = validate_plan(structured_plan, tool_index)
        
        # ENFORCE VALIDATION BLOCKING
        if isinstance(validation_result, dict) and validation_result.get("type") == "failure":
            print(f"[VALIDATION FAILURE ATTEMPT {attempt + 1}] {validation_result.get('reason')}")
            log(f"VALIDATION FAILURE ATTEMPT {attempt + 1}: {validation_result.get('reason')}")
            continue
        
        # Legacy validation format (tuple)
        if isinstance(validation_result, tuple):
            is_valid, error = validation_result
            if not is_valid:
                print(f"[VALIDATION FAILURE ATTEMPT {attempt + 1}] {error}")
                log(f"VALIDATION FAILURE ATTEMPT {attempt + 1}: {error}")
                continue
        
        # Validation passed - break out of retry loop and proceed to execution
        break
    
    # After retry loop - check if we exhausted all retries
    else:
        # All retries exhausted without success
        reason = "planner_retry_exhausted"
        
        if duplicate_detected:
            reason = "planner_stuck_duplicate_output"
        
        failure_result = {
            "status": "failure",
            "reason": reason
        }
        print(f"[PLANNER RETRY EXHAUSTED] Failed after {MAX_RETRIES} attempts")
        log(f"PLANNER RETRY EXHAUSTED: Failed after {MAX_RETRIES} attempts")
        print(f"\nRESULT: {json.dumps(failure_result, indent=2)}")
        return failure_result

    # -------------------
    # TASK STATE ENGINE
    # -------------------

    task_state = {
        "goal": goal,
        "plan": [],  # No longer used (OLD planner removed)
        "structured_plan": structured_plan,
        "original_structured_plan": json.loads(json.dumps(structured_plan)),  # preserve original plan
        "current_step": 0,
        "completed_steps": [],
        "results": [],
        "repair_history": {},
        "expanded": False,
        "system_test_mode": any(
            isinstance(step, dict) and step.get("name") == "system_test_agent"
            for step in structured_plan
        ),
        "planner_source": "NEW"  # All goals use NEW planner
    }

    creation_goal = False

    goal_lower = goal.lower()

    if "create tool" in goal_lower or "create a tool" in goal_lower or "build tool" in goal_lower:
        creation_goal = True

    if "create agent" in goal_lower or "build agent" in goal_lower:
        creation_goal = True

    relevant_tools = retrieve_relevant_tools(goal)

    tool_list = "\n".join(
        f"{name}({', '.join(tool_index.get(name, {}).get('inputs', []))})"
        for name in relevant_tools
    )

    agent_list = "\n".join(AGENTS.keys())

    manager_prompt = f"""
You are an AI manager controlling tools and agents.

AVAILABLE TOOLS:
{tool_list}

AVAILABLE AGENTS:
{agent_list}

AVAILABLE CAPABILITIES

Agents may advertise capabilities.

Instead of calling an agent directly you may request a capability.

Format:

CAPABILITY: capability_name
INPUT: task

The manager will automatically route the capability to the correct agent.

Example:

CAPABILITY: test_tools
INPUT: test tool multiply_numbers with inputs 2 and 3 expected output 6

You can use either a TOOL or an AGENT.

--------------------------------------------------

TOOL FORMAT
TOOL: tool_name
INPUT: arguments

AGENT FORMAT
AGENT: agent_name
INPUT: task

IMPORTANT:
The action line must begin exactly with:

TOOL:
or
AGENT:

Do NOT prefix actions with words like ACTION:, THOUGHT:, or RESULT:.
--------------------------------------------------

Rules:

1. Use tools when a tool is required.
2. Use agents for complex tasks.
3. If an agent already exists, reuse it.

4. If tester_agent reports that a tool test failed, assume the tool implementation is incorrect and call code_agent to fix or recreate the tool.

4. When a goal can be solved directly using an existing tool, call the tool directly.

tester_agent must only be used when:

- The goal explicitly asks to test a tool
- A newly created tool must be validated
- A tool execution failure must be diagnosed

tester_agent must NOT be used for normal question answering.

6. When instructing tester_agent to test a tool, always include the expected output when possible.
Example:
AGENT: tester_agent
INPUT: test tool multiply_numbers with inputs 2 and 3 expected output 6

7. If the goal is testing a tool, do not explore unrelated tools or directories.
Focus only on testing and repairing the specified tool.

8. If a tool or agent must be created, you MUST call the code_agent.

Example:

AGENT: code_agent
INPUT: create tool multiply_numbers

When requesting creation of components, the instruction must explicitly include the name using one of these formats:

create tool tool_name
create agent agent_name

When creating a tool, the request must also describe the tool inputs so that an INPUT_SPEC can be generated.

Example:

AGENT: code_agent
INPUT: create tool multiply_numbers with the following structure:

The tool MUST contain:

INPUT_SPEC = {{
    "a": "number",
    "b": "number"
}}

def run(*args):
    a, b = args
    return a * b

All generated tools MUST define:

INPUT_SPEC = {{ ... }}

and

def run(*args):

Tools that do not define INPUT_SPEC will be rejected by the system.    

Do NOT call a tool to create tools or agents.

Tools must not be executed to verify newly created tools.

If tool validation is required, use tester_agent.

The manager must not attempt to test tools directly using other tools such as run_python or add_numbers.

9. If the goal was to create a tool or agent, the goal is complete once the file is created.

If the tool or agent was created as part of solving a larger goal, continue reasoning using the new component.

10. If a tool produces the final result needed to answer the goal, respond with:

FINAL ANSWER: <result>

Do not call the same tool again after a correct result.

--------------------------------------------------

Goal:
{goal}
"""

# -------------------
# INCLUDE PLAN IN PROMPT
# -------------------
# (OLD planner plan_steps removed - no longer used)

    repair_mode = False
    failed_tool = None
    MAX_STEPS = max(50, len(task_state["structured_plan"]) * 3)

    tool_history = set()

    steps = []

    results = task_state["results"]

    drift_counter = 0

    replan_attempts = 0
    MAX_REPLANS = 2

    # Track repair attempts per tool
    repair_attempts = task_state["repair_history"]
    MAX_REPAIR_ATTEMPTS = 3

    for step in range(MAX_STEPS):

        history = "\n".join(steps[-20:])

        results_text = ""
        for i, r in enumerate(results, start=1):
            results_text += f"result_{i} = {r}\n"

        log("---- TASK STATE ----")
        log(f"STATE current_step: {task_state['current_step']}")

        if task_state["structured_plan"] and task_state["current_step"] < len(task_state["structured_plan"]):
            log(f"STATE next_step: {task_state['structured_plan'][task_state['current_step']]}")
        else:
            log("STATE next_step: None")

        log(f"STATE completed_steps: {task_state['completed_steps']}")
        log(f"STATE repair_history: {task_state['repair_history']}")
        log("--------------------")  

        # -------------------
        # PLAN COMPLETION DETECTION
        # -------------------

        if task_state["structured_plan"] and task_state["current_step"] >= len(task_state["structured_plan"]):

            # Detect failure at end of plan
            if results and tool_failed(results[-1]):

                if replan_attempts < MAX_REPLANS:

                    replan_attempts += 1

                    log("Plan failed. Generating new plan.")

                    failure_reason = results[-1] if results else "Unknown error"
                    
                    enhanced_goal = f"""
Previous plan failed.

Reason:
{failure_reason}

Original goal:
{goal}

Generate a corrected plan. Ensure all required arguments are included.
"""

                    # Try NEW planner only (no fallback to OLD)
                    replan_result = generate_structured_plan(enhanced_goal, tool_names)
                    
                    # HANDLE PLANNER FAILURE OBJECT
                    if isinstance(replan_result, dict) and replan_result.get("type") == "failure":
                        failure_result = {
                            "type": "failure",
                            "stage": "planner",
                            "reason": f"Replan failed: {replan_result.get('reason')}"
                        }
                        print(f"[REPLAN FAILURE] {failure_result}")
                        log(f"REPLAN FAILURE: {json.dumps(failure_result)}")
                        print(f"\nRESULT: {json.dumps(failure_result, indent=2)}")
                        return failure_result
                    
                    if replan_result is not None:
                        structured_plan = replan_result
                        
                        # TYPE GUARD: Ensure replan is a list
                        if not isinstance(structured_plan, list):
                            failure_result = {
                                "type": "failure",
                                "stage": "system",
                                "reason": "Replan is not a list"
                            }
                            print(f"[CRITICAL ERROR] {failure_result}")
                            log(f"CRITICAL ERROR: {json.dumps(failure_result)}")
                            print(f"\nRESULT: {json.dumps(failure_result, indent=2)}")
                            return failure_result
                        
                        print("[PLANNER] REPLAN: Using NEW planner")
                        log("PLANNER: REPLAN: Using NEW planner")
                        
                        task_state["plan"] = []
                        task_state["structured_plan"] = structured_plan
                        task_state["original_structured_plan"] = json.loads(json.dumps(structured_plan))

                        task_state["current_step"] = 0
                        task_state["completed_steps"] = []
                        task_state["results"] = []

                        log("REPLAN GENERATED:")
                        for idx, step in enumerate(structured_plan, 1):
                            log(f"{idx}. {step.get('type')}: {step.get('name')} - {step.get('input_text')}")

                        continue
                    else:
                        print("[PLANNER] REPLAN: NEW planner failed, no fallback available")
                        log("PLANNER: REPLAN: NEW planner failed, no fallback available")
                        log("Maximum replanning attempts reached (NEW planner failure).")
                        
                        final_answer = results[-1] if results else "Replanning failed - NEW planner could not generate valid plan."
                        print(f"\nFINAL ANSWER: {final_answer}\n")
                        log(f"FINAL ANSWER: {final_answer}")
                        log_execution(goal, task_state, results)
                        break

                else:

                    log("Maximum replanning attempts reached.")

                    final_answer = results[-1] if results else "Task failed."

                    log_execution(goal, task_state, results)

                    log(f"FINAL ANSWER: {final_answer}")

                    print(f"\nFINAL ANSWER: {final_answer}\n")

                    if config.MODE == "test":
                        exit(0)

                    break

            log("Plan completed.")

            final_answer = results[-1] if results else "Plan completed."

            log_execution(goal, task_state, results)

            log(f"FINAL ANSWER: {final_answer}")

            print(f"\nFINAL ANSWER: {final_answer}\n")

            if config.MODE == "test":
                exit(0)

            break

        # -------------------
        # EARLY REPAIR SKIP
        # -------------------

        expected_step = None

        if task_state["structured_plan"] and task_state["current_step"] < len(task_state["structured_plan"]):
            expected_step = task_state["structured_plan"][task_state["current_step"]]

        # If next step is code_agent repair but last test passed, skip it
        if (
            expected_step
            and expected_step["type"] == "agent"
            and expected_step["name"] == "code_agent"
        ):

            if results:
                last_result = str(results[-1]).lower()

                if "tool test passed" in last_result:
                    log("SYSTEM: Skipping repair step because test already passed.")
                    print(f"DEBUG-DRIFT: Attempting step advance - current_step={task_state['current_step']}, expected={expected_step}")
                    task_state["current_step"] += 1
                    continue

        prompt_with_history = manager_prompt + f"""
        Previous steps:
        {history}

        Execution state:

        Current plan step index:
        {task_state["current_step"]}

        Next planned step:
        {task_state["structured_plan"][task_state["current_step"]] if task_state["structured_plan"] and task_state["current_step"] < len(task_state["structured_plan"]) else "None"}

        Completed steps:
        {task_state["completed_steps"]}

        Repair history:
        {task_state["repair_history"]}

        Available intermediate results:
        {results_text}
        """

        # Check for forced tool execution from structured plan
        next_step = None
        if task_state["structured_plan"] and task_state["current_step"] < len(task_state["structured_plan"]):
            next_step = task_state["structured_plan"][task_state["current_step"]]
        
        # Force execute tool if next step requires it
        if next_step and next_step.get("type") == "tool":
            tool_name = next_step["name"]
            args = next_step.get("args", [])
            
            # Detect invalid args
            # Guard: Skip fallback if PREVIOUS_RESULT token present
            has_previous_result = "PREVIOUS_RESULT" in args
            
            invalid_args = (
                not has_previous_result and (
                    not args or
                    any(not isinstance(a, (int, float)) for a in args)
                )
            )
            
            if invalid_args:
                print(f"[ARG FALLBACK] Triggered for tool: {tool_name}")
                print(f"[ARG FALLBACK] Original args: {args}")
                
                tokens = parse_tool_input(next_step.get("input_text", ""))
                print(f"[ARG FALLBACK] Tokens: {tokens}")
                
                args = resolve_arguments(tool_name, tokens)
                print(f"[ARG FALLBACK] Resolved args: {args}")
                
                expected_args = get_expected_arg_count(tool_name)
                print(f"[ARG CHECK POST-FALLBACK] Expected: {expected_args}, Actual: {len(args)}")
                
                if len(args) != expected_args:
                    print(f"[ARG WARNING] Argument count mismatch for {tool_name} — execution may fail")
            else:
                print(f"[ARG FALLBACK] Skipped — args already valid: {args}")
            
            # MUST remain after fallback logic — DO NOT MOVE
            args = resolve_chain(args, results)
            
            if tool_name in TOOLS:
                log(f"FORCED EXECUTION: {tool_name} (from structured plan)")
                
                # VALIDATION: intent preservation (soft check)
                goal_lower = goal.lower()
                
                if tool_name not in goal_lower:
                    log(f"VALIDATION WARNING: tool {tool_name} not mentioned in goal")
                
                # VALIDATION: argument completeness
                expected_args = get_expected_arg_count(tool_name)
                
                # Only validate if tool defines expected args
                if expected_args is not None and len(args) != expected_args:
                    log(f"VALIDATION FAILED: {tool_name} expected {expected_args} args, got {len(args)}")
                    
                    # Convert to controlled failure for replan system
                    failed_tool = tool_name
                    log(f"TOOL FAILURE DETECTED: {failed_tool} due to argument mismatch")
                    
                    task_state["repair_history"][failed_tool] = task_state["repair_history"].get(failed_tool, 0)
                    
                    results.append("Tool execution error: invalid argument count")
                    
                    # Advance step safely
                    if task_state["current_step"] < len(task_state["structured_plan"]):
                        if task_state["current_step"] < len(task_state["plan"]):
                            task_state["completed_steps"].append(
                                task_state["plan"][task_state["current_step"]]
                            )
                        task_state["current_step"] += 1
                    
                    continue
                
                # EXECUTION GUARD: Only execute if args is non-empty
                expected = get_expected_arg_count(tool_name)
                if not args and expected is not None and expected > 0:
                    log(f"TOOL FAILURE: {tool_name} missing required arguments")
                    results.append("Tool execution error: missing arguments")
                    # Advance step safely
                    if task_state["current_step"] < len(task_state["structured_plan"]):
                        if task_state["current_step"] < len(task_state["plan"]):
                            task_state["completed_steps"].append(
                                task_state["plan"][task_state["current_step"]]
                            )
                        task_state["current_step"] += 1
                    continue
                else:
                    # Execute tool directly with stored arguments
                    try:
                        expected_count = get_expected_arg_count(tool_name)
                        actual_count = len(args)
                        log(f"TOOL CONTRACT: {tool_name} expects {expected_count} args")
                        log(f"ARG CHECK: {tool_name} expected={expected_count}, actual={actual_count}")
                        if expected_count is not None and expected_count != actual_count:
                            log(f"ARG MISMATCH DETECTED for {tool_name}")
                            failed_tool = tool_name
                            log(f"TOOL FAILURE DETECTED: {failed_tool} due to argument mismatch")
                            task_state["repair_history"][failed_tool] = task_state["repair_history"].get(failed_tool, 0)
                            output = f"Tool execution error: invalid argument count"
                        else:
                            log(f"ACTION: {tool_name}{tuple(args)}")         
                            output = TOOLS[tool_name](*args)
                        
                        results.append(output)
                        log(f"OBSERVATION: {output}")
                        
                        # Advance step after forced execution
                        if task_state["current_step"] < len(task_state["structured_plan"]):
                            if task_state["current_step"] < len(task_state["plan"]):
                                task_state["completed_steps"].append(
                                    task_state["plan"][task_state["current_step"]]
                                )
                            task_state["current_step"] += 1
                        
                        drift_counter = 0
                        manager_prompt += f"\nSYSTEM: Tool {tool_name} executed as required by plan.\n"
                        continue  # Skip LLM parsing for forced execution
                        
                    except Exception as e:
                        output = f"Tool execution error: {e}"
                        results.append(output)
                        log(f"FORCED EXECUTION ERROR: {output}")
                        manager_prompt += f"\nSYSTEM: Tool execution failed: {output}\n"
                        # Advance step to prevent infinite loop
                        if task_state["current_step"] < len(task_state["structured_plan"]):
                            task_state["current_step"] += 1
                        continue
        
        # Force execute agent if next step requires it
        if next_step and next_step.get("type") == "agent":
            agent_name = next_step["name"]
            args = next_step.get("args", [])
            
            log(f"FORCED EXECUTION: {agent_name} (from structured plan)")
            
            if agent_name in AGENTS:
                try:
                    # Execute agent with args
                    if args:
                        output = AGENTS[agent_name](*args)
                    else:
                        # For agents with no args, call with empty input
                        output = AGENTS[agent_name]("")
                    
                    results.append(output)
                    log(f"AGENT RESULT: {output}")
                    
                    # Advance step after forced execution
                    if task_state["current_step"] < len(task_state["structured_plan"]):
                        if task_state["current_step"] < len(task_state["plan"]):
                            task_state["completed_steps"].append(
                                task_state["plan"][task_state["current_step"]]
                            )
                        task_state["current_step"] += 1
                    
                    manager_prompt += f"\nSYSTEM: Agent {agent_name} executed as required by plan.\n"
                    continue  # Skip LLM parsing for forced execution
                    
                except Exception as e:
                    output = f"Agent execution error: {e}"
                    results.append(output)
                    log(f"FORCED AGENT EXECUTION ERROR: {output}")
                    manager_prompt += f"\nSYSTEM: Agent execution failed: {output}\n"
                    # Advance step to prevent infinite loop
                    if task_state["current_step"] < len(task_state["structured_plan"]):
                        task_state["current_step"] += 1
                    continue
            else:
                output = f"Invalid agent: {agent_name}"
                results.append(output)
                log(f"AGENT NOT FOUND: {agent_name}")
                manager_prompt += f"\nSYSTEM: Agent '{agent_name}' does not exist.\n"
                # Advance step to prevent infinite loop
                if task_state["current_step"] < len(task_state["structured_plan"]):
                    task_state["current_step"] += 1
                continue

        result = ask_llm(prompt_with_history)

        # ── FORCE TERMINATION IF REPAIR LIMIT ALREADY REACHED ────────────────
        if failed_tool and repair_attempts.get(failed_tool, 0) >= 3:
            failure_msg = (
                f"Repair limit reached - tool '{failed_tool}' could not be fixed. "
                f"Failed after 3 repair attempts. Original failure persisted."
            )
            print(f"\nFINAL ANSWER: {failure_msg}\n")
            log(f"ENFORCED TERMINATION after repair limit: {failure_msg}")
            log_execution(goal, task_state, results + [failure_msg])
            break

        # Prevent multiple actions in one response
        lines = result.split("\n")

        action_index = None

        for i, line in enumerate(lines):
            if line.startswith("AGENT:") or line.startswith("TOOL:") or line.startswith("CAPABILITY:"):
                action_index = i
                break

        if action_index is not None:

            end_index = action_index + 1

            while (
                end_index < len(lines)
                and not lines[end_index].startswith("AGENT:")
                and not lines[end_index].startswith("TOOL:")
                and not lines[end_index].startswith("CAPABILITY:")
            ):
                end_index += 1

            result = "\n".join(lines[action_index:end_index])

        # Normalize LLM output

        result = result.replace("THOUGHT: THOUGHT:", "THOUGHT:")
        result = result.replace("THOUGHT: TOOL:", "TOOL:")
        result = result.replace("ACTION:", "")
        result = result.replace("Action:", "")
        result = result.replace("action:", "")
        result = result.replace("\r", "").strip()

        # Convert raw tool calls like web_search(...) into TOOL format
        if re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*\s*\(", result):
            tool = result.split("(",1)[0].strip()
            args = result.split("(",1)[1].rsplit(")",1)[0]
            result = f"TOOL: {tool}\nINPUT: {args}"

        log(f"THOUGHT: {result}")
        steps.append(f"THOUGHT: {result}")

        # -------------------
        # FINAL ANSWER
        # -------------------

        if "FINAL ANSWER:" in result:

            # Check if plan is complete before accepting FINAL ANSWER
            if task_state["structured_plan"] and task_state["current_step"] < len(task_state["structured_plan"]):
                # Plan not complete - reject FINAL ANSWER
                log(f"SYSTEM: FINAL ANSWER rejected - plan incomplete (step {task_state['current_step']} of {len(task_state['structured_plan'])})")
                manager_prompt += "\nSYSTEM: You must complete all plan steps before giving FINAL ANSWER.\n"
                continue

            final_answer = result.split("FINAL ANSWER:",1)[1].strip()

            # Ensure final step is recorded
            if task_state["current_step"] < len(task_state["plan"]):
                task_state["completed_steps"].append(
                    task_state["plan"][task_state["current_step"]]
                )

            results.append(final_answer)

            log_execution(goal, task_state, results)

            log(f"FINAL ANSWER: {final_answer}")

            print(f"\nFINAL ANSWER: {final_answer}\n")

            if config.MODE == "test":
                exit(0)

            break

        if not ("TOOL:" in result or "AGENT:" in result or "CAPABILITY:" in result):

            log("SYSTEM: Model returned no executable action. Ignoring response and continuing.")

            manager_prompt += """
        SYSTEM: Your previous response did not contain a valid action.

        You must respond with one of the following formats:

        TOOL: tool_name
        INPUT: arguments

        AGENT: agent_name
        INPUT: task

        CAPABILITY: capability_name
        INPUT: task
        """

            continue

        lines = result.split("\n")

        tool_name = None
        tool_input = ""

        agent_name = None
        agent_input = ""

        capability = None

        for i, line in enumerate(lines):

            if line.strip().startswith("CAPABILITY:"):

                capability = line.split("CAPABILITY:", 1)[1].strip()

                if i + 1 < len(lines) and "INPUT:" in lines[i+1]:

                    agent_input = lines[i+1].split("INPUT:", 1)[1].strip()

                    j = i + 2

                    while j < len(lines) and not lines[j].startswith("TOOL:") and not lines[j].startswith("AGENT:") and not lines[j].startswith("CAPABILITY:"):
                        agent_input += "\n" + lines[j]
                        j += 1

                break 

            if line.strip().startswith("TOOL:"):

                tool_name = line.split("TOOL:", 1)[1].strip()

                # Normalize parentheses invocation
                if tool_name.endswith("()"):
                    tool_name = tool_name[:-2].strip()

                if i + 1 < len(lines) and "INPUT:" in lines[i+1]:

                    tool_input = lines[i+1].split("INPUT:", 1)[1].strip()

                    j = i + 2

                    while j < len(lines) and not lines[j].startswith("TOOL:") and not lines[j].startswith("AGENT:"):
                        tool_input += "\n" + lines[j]
                        j += 1

                break


            if line.strip().startswith("AGENT:"):

                agent_name = line.split("AGENT:", 1)[1].strip()

                if i + 1 < len(lines) and "INPUT:" in lines[i+1]:

                    agent_input = lines[i+1].split("INPUT:", 1)[1].strip()

                    j = i + 2

                    while (
                        j < len(lines)
                        and not lines[j].startswith("TOOL:")
                        and not lines[j].startswith("AGENT:")
                        and not lines[j].startswith("CAPABILITY:")
                        and not lines[j].startswith("SYSTEM:")
                        and not lines[j].startswith("THOUGHT:")
                        and not lines[j].startswith("OBSERVATION:")
                    ):
                        agent_input += "\n" + lines[j]
                        j += 1

                # Track which tool is being tested
                if agent_name == "tester_agent":

                    match = re.search(r"test\s+tool\s+([a-zA-Z_][a-zA-Z0-9_]*)", agent_input.lower())

                    if match:

                        tested_tool = match.group(1)

                        # Enforce correct tool according to plan
                        expected_step = None

                        if task_state["structured_plan"] and task_state["current_step"] < len(task_state["structured_plan"]):
                            expected_step = task_state["structured_plan"][task_state["current_step"]]

                        if expected_step and expected_step["name"] == "tester_agent":

                            expected_tool = None

                            if task_state["current_step"] < len(task_state["plan"]):
                                plan_text = task_state["plan"][task_state["current_step"]].lower()
                            else:
                                plan_text = ""

                            match2 = re.search(r"test\s+(?:the\s+)?([a-zA-Z_][a-zA-Z0-9_]*)\s+tool", plan_text, re.IGNORECASE)

                            if not match2:
                                match2 = re.search(r"test\s+tool\s+([a-zA-Z_][a-zA-Z0-9_]*)", plan_text, re.IGNORECASE)

                            if match2:
                                expected_tool = match2.group(1)

                            if expected_tool and tested_tool != expected_tool:

                                msg = f"SYSTEM: You must test tool {expected_tool}, not {tested_tool}."

                                log(msg)
                                manager_prompt += f"\n{msg}\n"

                                continue

                        # Only assign AFTER validation succeeds
                        failed_tool = tested_tool

                break

        # Correct misclassified agent calls
        if tool_name and tool_name in AGENTS:
            agent_name = tool_name
            agent_input = tool_input
            tool_name = None

        # -------------------
        # CAPABILITY PLAN ENFORCEMENT
        # -------------------

        if capability:

            # Enforce structured plan before resolving capability
            expected_step = None

            if task_state["structured_plan"] and task_state["current_step"] < len(task_state["structured_plan"]):
                expected_step = task_state["structured_plan"][task_state["current_step"]]

            if expected_step:

                expected_type = expected_step["type"]
                expected_name = expected_step["name"]

                # Capability attempting to execute a tool
                if capability in TOOLS:

                    if expected_type != "tool" or capability != expected_name:

                        msg = f"SYSTEM: The next required step in the plan is {expected_type.upper()}: {expected_name}. Do not execute capability {capability}."

                        log(msg)
                        manager_prompt += f"\n{msg}\n"

                        drift_counter += 1
                        continue

                # Capability attempting to resolve to agent
                resolved_agent = find_agent_by_capability(capability)

                if resolved_agent:

                    if expected_type != "agent" or resolved_agent != expected_name:

                        msg = f"SYSTEM: The next required step in the plan is {expected_type.upper()}: {expected_name}. Do not execute capability {capability}."

                        log(msg)
                        manager_prompt += f"\n{msg}\n"

                        drift_counter += 1
                        continue

            # -------------------
            # CAPABILITY → AGENT RESOLUTION
            # -------------------

            # Reject invalid capability strings
            if " " in capability:
                log(f"SYSTEM: Invalid capability '{capability}'. Capabilities must be single identifiers.")
                manager_prompt += "\nSYSTEM: Invalid capability name. Use a valid tool or agent.\n"
                continue

            # Capability maps directly to tool
            if capability in TOOLS:

                log(f"Capability '{capability}' is a tool. Redirecting to tool execution.")

                tool_name = capability
                tool_input = agent_input
                capability = None
                agent_name = None

                action_type = "tool"

            else:

                resolved_agent = find_agent_by_capability(capability)

                if resolved_agent:

                    agent_name = resolved_agent
                    log(f"Resolved capability '{capability}' to agent '{agent_name}'")

                else:

                    log(f"No agent found for capability '{capability}'")

                    manager_prompt += (
                        f"\nSYSTEM: '{capability}' is not a valid capability. "
                        "Use a valid tool or capability.\n"
                    )

                    continue


        # -------------------
        # ACTION VALIDATOR
        # -------------------

        # -------------------
        # PLAN STEP ENFORCEMENT
        # -------------------

        expected_step = None

        if task_state["structured_plan"] and task_state["current_step"] < len(task_state["structured_plan"]):
            expected_step = task_state["structured_plan"][task_state["current_step"]]

        # Allow repair actions even if they deviate from the original plan
        if repair_mode:
            expected_step = None

        # -------------------
        # CONDITIONAL PLAN STEP HANDLING
        # -------------------

        # Skip repair step if previous tester_agent succeeded
        if (
            expected_step
            and expected_step["type"] == "agent"
            and expected_step["name"] == "code_agent"
        ):

            if results:
                last_result = str(results[-1]).lower()

                if "tool test passed" in last_result:

                    log("Skipping repair step because the tool test succeeded.")

                    print(f"DEBUG-DRIFT: Attempting step advance - current_step={task_state['current_step']}, expected={expected_step}")
                    task_state["current_step"] += 1
                    continue    

        if expected_step:

            expected_type = expected_step["type"]
            expected_name = expected_step["name"]

            # Tool expected but agent proposed
            if expected_type == "tool" and agent_name:

                drift_counter += 1

                msg = f"SYSTEM: The next required step in the plan is TOOL: {expected_name}. Execute the correct step."

                log(msg)
                manager_prompt += f"\n{msg}\n"

                if drift_counter >= 3:
                    drift_msg = "SYSTEM: Execution appears to be deviating from the structured plan."
                    log(drift_msg)
                    manager_prompt += f"\n{drift_msg}\n"

                continue

            # Agent expected but tool proposed
            if expected_type == "agent" and tool_name:

                drift_counter += 1

                msg = f"SYSTEM: The next required step in the plan is AGENT: {expected_name}. Execute the correct step."

                log(msg)
                manager_prompt += f"\n{msg}\n"

                if drift_counter >= 3:
                    drift_msg = "SYSTEM: Execution appears to be deviating from the structured plan."
                    log(drift_msg)
                    manager_prompt += f"\n{drift_msg}\n"

                continue

            # Wrong tool
            if expected_type == "tool" and tool_name and tool_name != expected_name:

                drift_counter += 1

                msg = f"SYSTEM: The next required step in the plan is TOOL: {expected_name}. Do not execute {tool_name}."

                log(msg)
                manager_prompt += f"\n{msg}\n"

                if drift_counter >= 3:
                    drift_msg = "SYSTEM: Execution appears to be deviating from the structured plan."
                    log(drift_msg)
                    manager_prompt += f"\n{drift_msg}\n"

                continue

            # Wrong agent
            if expected_type == "agent" and agent_name and agent_name != expected_name:

                drift_counter += 1

                msg = f"SYSTEM: The next required step in the plan is AGENT: {expected_name}. Do not execute {agent_name}."

                log(msg)
                manager_prompt += f"\n{msg}\n"

                if drift_counter >= 3:
                    drift_msg = "SYSTEM: Execution appears to be deviating from the structured plan."
                    log(drift_msg)
                    manager_prompt += f"\n{drift_msg}\n"

                continue

            # -------------------
            # CORRECT STEP EXECUTED
            # -------------------

            if expected_step:

                step_match = False

                if expected_type == "agent" and agent_name == expected_name:
                    step_match = True

                if expected_type == "tool" and tool_name == expected_name:
                    step_match = True

                # Do NOT advance step here - this is just validation
                # Step advancement happens AFTER actual execution in agent/tool sections

            # Validate tool actions
            if tool_name:

                tool_input = normalize_tool_input(tool_input)

                # Ensure tool_input remains a string
                if isinstance(tool_input, dict):
                    tool_input = ""

                if tool_name not in TOOLS:
                    msg = "Invalid action. Choose a valid tool or agent."
                    log(msg)
                    steps.append(f"SYSTEM: {msg}")
                    continue

                # If INPUT missing, default to {}
                if tool_input == "":
                    tool_input = "{}"

        # Validate agent actions
        if agent_name:

            if agent_name not in AGENTS:
                msg = "Invalid action. Choose a valid tool or agent."
                log(msg)
                steps.append(f"SYSTEM: {msg}")
                continue

            if agent_input == "":
                msg = "Invalid action. AGENT requires INPUT."
                log(msg)
                steps.append(f"SYSTEM: {msg}")
                continue

        # -------------------
        # TOOL EXECUTION — REMOVED
        # -------------------
        # LLM-driven tool execution has been removed to enforce single execution pipeline.
        # All tool execution must now go through structured_plan → validation → forced execution.
        
        if tool_name and tool_name in TOOLS:
            log(f"BLOCKED: LLM attempted to trigger tool execution: {tool_name}")
            log("ENFORCEMENT: Tool execution only allowed through validated structured_plan")
            manager_prompt += f"\nSYSTEM: Direct tool execution is disabled. Tools must be executed through the planner.\n"
            continue


        # -------------------
        # CAPABILITY PARSER
        # -------------------

        # Detect capability request embedded in agent_name
        # Example: CAPABILITY: test_tools

        if agent_name and agent_name.startswith("CAPABILITY:"):

            capability = agent_name.split(":",1)[1].strip()

            log(f"Parsed capability request: {capability}")

            agent_name = find_agent_by_capability(capability)

            if agent_name:
                log(f"Resolved capability '{capability}' to agent '{agent_name}'")
            else:
                log(f"No agent found for capability '{capability}'")

        # -------------------
        # PREVENT TOOL RECREATION
        # -------------------

        if agent_name == "code_agent" and agent_input:

            lowered = agent_input.lower()

            # Prevent recreating an already existing tool
            if "create tool" in lowered:

                # Extract candidate tool name
                match = re.search(r"create\s+tool\s+([a-zA-Z_][a-zA-Z0-9_]*)", lowered)

                if match:
                    tool_candidate = match.group(1)

                    if tool_candidate in TOOLS:
                        msg = f"Tool '{tool_candidate}' already exists. Use repair instead."

                        log(msg)

                        manager_prompt += f"""
                        SYSTEM: {msg}

                        You must NOT attempt to create this tool again.

                        The correct action is:

                        AGENT: code_agent
                        INPUT: repair tool {tool_candidate}
                        """

                        repair_mode = True

                        continue

                parts = lowered.split()

                if "tool" in parts:

                    idx = parts.index("tool")

                    if idx + 1 < len(parts):

                        tool_candidate = parts[idx + 1].replace("()", "").replace(".py","").replace(",", "").strip()

                        if tool_candidate in TOOLS and not repair_mode:

                            msg = f"Tool '{tool_candidate}' already exists. Repair the existing tool instead of recreating it."

                            log(msg)

                            steps.append(f"SYSTEM: {msg}")

                            manager_prompt += f"""
                            SYSTEM: {msg}

                            You must call code_agent to repair the existing tool.

                            AGENT: code_agent
                            INPUT: repair tool {tool_candidate}
                            """

                            repair_mode = True

                            continue
        # -------------------
        # REPAIR GUARD
        # -------------------

        if agent_name == "code_agent" and repair_mode == "awaiting_test":

            msg = "SYSTEM: You must test the repaired tool using tester_agent before attempting another repair."

            log(msg)

            manager_prompt += f"\n{msg}\n"

            # Force correct step instead of looping
            agent_name = "tester_agent"
            
            if failed_tool:
                agent_input = f"test tool {failed_tool} with inputs {tool_input}"
            else:
                log("SYSTEM: Repair guard triggered but failed_tool unknown.")
                continue

            repair_mode = False
        
        # -------------------
        # AGENT EXECUTION
        # -------------------

        if agent_name and agent_name in AGENTS:

            # -------------------
            # REPAIR ATTEMPT TRACKING
            # -------------------

            if agent_name == "code_agent" and agent_input:

                # Enforce repair limit if a tool is already failing
                if failed_tool:

                    attempts = repair_attempts.get(failed_tool, 0)

                    if enforce_repair_limit(
                        failed_tool,
                        repair_attempts,
                        MAX_REPAIR_ATTEMPTS,
                        goal,
                        task_state,
                        results,
                        config
                    ):
                        break  # exit while True loop immediately

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

                        continue

                    if candidate in TOOLS:

                        failed_tool = candidate

                        attempts = repair_attempts.get(failed_tool, 0)

                        if enforce_repair_limit(
                            failed_tool,
                            repair_attempts,
                            MAX_REPAIR_ATTEMPTS,
                            goal,
                            task_state,
                            results,
                            config
                        ):
                            break  # exit while True loop immediately

            # Prevent modification or recreation of infrastructure agents
            if agent_name == "code_agent" and agent_input:

                lowered = agent_input.lower()

                for infra in infrastructure_agents:

                    if infra in lowered and ("create" in lowered or "modify" in lowered):

                        msg = f"{infra} is an infrastructure agent and cannot be modified automatically."

                        log(msg)

                        manager_prompt += f"\nSYSTEM: {msg}\n"

                        repair_mode = False

                        break

            # Normalize multiline input into one string
            agent_input = agent_input.strip()

            log(f"BLOCKED: LLM attempted to trigger agent execution: {agent_name}")
            log("ENFORCEMENT: Agent execution only allowed through validated structured_plan")
            manager_prompt += f"\nSYSTEM: Direct agent execution is disabled. Agents must be executed through the planner.\n"
            continue

            # -------------------
            # AGENT PLAN EXPANSION
            # -------------------

            if isinstance(output, str):

                lines = output.strip().split("\n")

                action_blocks = []
                current_block = []

                for line in lines:

                    line = line.strip()

                    if line.startswith("AGENT:") or line.startswith("TOOL:") or line.startswith("CAPABILITY:"):

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

                        print(f"DEBUG-DRIFT: Attempting step advance - current_step={task_state['current_step']}, expected={expected_step}")
                        # Move execution past the agent that generated the expansion
                        task_state["current_step"] += 1

                        log(f"Inserted {len(expanded_steps)} new plan steps from agent.")

                    continue

            # Refresh system if a new file was created
            if agent_name == "code_agent" and isinstance(output, str) and "File created:" in output:

                created_path = output.split("File created:")[-1].strip()

                # Only treat this as a tool creation if the file is inside /tools/
                if "/tools/" not in created_path and "\\tools\\" not in created_path:
                    steps.append(f"AGENT RESULT: {output}")
                    continue

                # -------------------
                # SYNTAX VALIDATION
                # -------------------

                validation = validate_python_file(created_path)

                if validation is not True:
                    log(f"Syntax validation failed: {validation}")
                    manager_prompt += f"\nSYSTEM: The generated tool contains invalid Python syntax. Error: {validation}\n"
                    continue

                # -------------------
                # REGISTER TOOL IN INDEX
                # -------------------

                if "/tools/" in created_path or "\\tools\\" in created_path:

                    tool_name = os.path.basename(created_path).replace(".py", "")

                    try:
                        module = importlib.import_module(f"tools.{tool_name}")
                        input_spec = getattr(module, "INPUT_SPEC", {})
                        inputs = input_spec
                    except:
                        inputs = {}

                    tool_index[tool_name] = {
                        "description": f"Tool {tool_name}",
                        "inputs": inputs,
                        "tags": []
                    }

                    save_tool_index(tool_index)   

                refresh_system()

                steps.append("SYSTEM: Tool updated. Retesting required.")

                # Force retest step
                task_state["structured_plan"].append({"type": "agent", "name": "tester_agent"})

                # Force test before allowing another repair
                repair_mode = "awaiting_test"

                # Force verification of the repaired tool
                manager_prompt += """
                SYSTEM: The tool was updated.

                You must now verify the tool works.

                Call tester_agent to test the tool again before attempting further repairs.
                """

                # Force verification of repaired tool
                manager_prompt += "\nSYSTEM: The tool has been updated. You must now test or execute the tool to verify the repair.\n"

                if creation_goal and "test" not in goal_lower:
                    log(f"FINAL ANSWER: {output}")

                    print(f"\nFINAL ANSWER: {output}\n")

                    break

            steps.append(f"AGENT RESULT: {output}")

            # -------------------
            # PLAN STEP PROGRESSION
            # -------------------

            output_text = str(output).lower()

            agent_failed = (
                "tool test failed" in output_text
                or "test failed" in output_text
            )

            # ------------------------------------------------
            # REPAIR STEP SKIP (tester_agent PASS)
            # ------------------------------------------------
            # If tester_agent succeeded and the next step is
            # a repair step (code_agent), skip it.
            # This preserves verification loops but avoids
            # unnecessary repairs.

            if (
                agent_name == "tester_agent"
                and not agent_failed
                and not task_state.get("system_test_mode")
            ):

                next_index = task_state["current_step"] + 1

                if (
                    next_index < len(task_state["structured_plan"])
                    and task_state["structured_plan"][next_index]["type"] == "agent"
                    and task_state["structured_plan"][next_index]["name"] == "code_agent"
                ):
                    log("SYSTEM: Skipping repair step because tester_agent reported PASS.")
                    print(f"DEBUG-DRIFT: Attempting step advance - current_step={task_state['current_step']}, expected={expected_step}")
                    task_state["current_step"] += 1

            # Always advance during system test runs
            task_state["system_test_mode"] = "system_test_agent" in str(task_state["plan"]).lower()

            if not agent_failed or task_state["system_test_mode"]:

                results.append(output)  # ← propagate tester "Tool test passed. Result: X" so handle_plan_completion sees it

                # CRITICAL #1 FIX v2: Enforce exact plan fidelity (name + task match for tester_agent)
                expected_step = None
                if task_state.get("structured_plan") and task_state["current_step"] < len(task_state["structured_plan"]):
                    expected_step = task_state["structured_plan"][task_state["current_step"]]

                matches = False
                if expected_step:
                    if expected_step.get("type") == "agent" and expected_step.get("name") == agent_name:
                        if agent_name == "tester_agent":
                            # Extract expected tool from original plan text (most reliable source)
                            plan_text_step = ""
                            if task_state["current_step"] < len(task_state.get("plan", [])):
                                plan_text_step = task_state["plan"][task_state["current_step"]]

                            expected_tool_match = re.search(
                                r"test\s+(?:the\s+)?(?:tool\s+)?([a-zA-Z_][a-zA-Z0-9_]*)",
                                plan_text_step.lower()
                            )
                            expected_tool = expected_tool_match.group(1) if expected_tool_match else None

                            # Require tester_agent input to mention the exact tool being tested
                            if expected_tool and expected_tool.lower() in agent_input.lower():
                                matches = True
                            else:
                                matches = False
                        else:
                            # Other agents: name match sufficient for now
                            matches = True
                    elif expected_step.get("type") == "tool" and expected_step.get("name") == tool_name:
                        matches = True  # tool branch already checked name

                if not matches:
                    manager_prompt += (
                        f"\nSYSTEM: Action mismatch! Executed '{agent_name}' "
                        f"with input '{agent_input[:120]}...' does NOT match required step: "
                        f"{expected_step}. Must follow plan exactly. Retry the correct tool/agent. "
                        f"(current_step NOT advanced)"
                    )
                else:
                    # ── ONLY HERE: safe to advance step ──
                    if failed_tool and repair_attempts.get(failed_tool, 0) >= MAX_REPAIR_ATTEMPTS:
                        upper_out = str(output).upper()
                        lower_out = str(output).lower()
                        if "FINAL ANSWER" in upper_out or any(word in lower_out for word in ["success", "passed", "fixed", "completed", "correct"]):
                            log(f"Hard veto: LLM tried success after repair limit for '{failed_tool}'")
                            failure_msg = f"Repair limit reached - tool '{failed_tool}' could not be fixed. Failed after {MAX_REPAIR_ATTEMPTS} attempts."
                            print(f"\nFINAL ANSWER: {failure_msg}\n")
                            log_execution(goal, task_state, results + [failure_msg])
                            break

                    # The block you pasted — now protected
                    if task_state["current_step"] < len(task_state["structured_plan"]):
                        if task_state["current_step"] < len(task_state.get("plan", [])):
                            task_state["completed_steps"].append(
                                task_state["plan"][task_state["current_step"]]
                            )

                        if not task_state.get("expanded"):
                            print(f"DEBUG-DRIFT: Attempting step advance - current_step={task_state['current_step']}, expected={expected_step}")
                            task_state["current_step"] += 1

                        if handle_plan_completion(task_state, results, goal, config):
                            break

                        task_state["expanded"] = False

            # Reject hallucinated success messages
            if "created successfully" in str(output).lower() and "File created:" not in str(output):
                manager_prompt += "\nSYSTEM: The tool was not actually created. A valid creation must return 'File created: <path>'.\n"

            # Feed result back into reasoning
            manager_prompt += f"\nSYSTEM RESULT: {output}\n"

            # Provide structured repair guidance if a tool test failed
            if "tool test failed:" in str(output).lower() and not task_state["system_test_mode"]:

                repair_mode = True

                # -------------------------
                # FAILURE DIAGNOSIS ENGINE
                # -------------------------

                failure_message = str(output)
                diagnosis = "unknown failure"

                lower_failure = failure_message.lower()

                if "expected" in lower_failure and "but got" in lower_failure:
                    diagnosis = "logical error: tool returned incorrect output"

                elif "execution error" in lower_failure:
                    diagnosis = "runtime error: tool raised an exception"

                elif "input_spec" in lower_failure:
                    diagnosis = "tool interface error: INPUT_SPEC missing or invalid"    

                elif "typeerror" in lower_failure:
                    diagnosis = "type mismatch or incorrect argument usage"

                elif "indexerror" in lower_failure:
                    diagnosis = "index out of range or missing argument"

                elif "nameerror" in lower_failure:
                    diagnosis = "undefined variable or missing import"

                elif "attributeerror" in lower_failure:
                    diagnosis = "invalid attribute access"

                elif "division by zero" in lower_failure:
                    diagnosis = "division by zero"

                log(f"Diagnosis: {diagnosis}")

                # Detect failed tool from tester_agent structured message
                match = re.search(
                    r"tool test failed:\s*([a-zA-Z_][a-zA-Z0-9_]*)",
                    str(output).lower()
                )

                if match:
                    candidate = match.group(1)

                    if candidate in TOOLS:
                        failed_tool = candidate

                if failed_tool:

                    task_state["repair_history"][failed_tool] = repair_attempts.get(failed_tool, 0)

                    if repair_attempts.get(failed_tool, 0) > MAX_REPAIR_ATTEMPTS:

                        log(f"Maximum repair attempts reached for tool '{failed_tool}'.")

                        manager_prompt += f"""
                SYSTEM: The tool '{failed_tool}' has failed repair {MAX_REPAIR_ATTEMPTS} times.

                Stop attempting automatic repair.

                Report the failure and provide the best possible answer without further repairs.
                """

                        repair_mode = False
                        continue

                manager_prompt += "\nSYSTEM: The tool already exists. You must repair the existing tool instead of recreating it.\n"

                # Lock original test case to prevent input drift
                manager_prompt += f"""
                SYSTEM: IMPORTANT - REPAIR CONSTRAINT
                Always test the repaired tool with the EXACT SAME failing inputs that caused the original failure:
                Inputs: a and t (strings, not numbers)
                Expected output: exactly 999999

                Do NOT use numeric inputs like 999999 and 3 in tests.
                The repair only succeeds if the tool returns 999999 when given strings 'a' and 't'.
                Repeat this constraint in every future tester_agent call during repair.
                """

                manager_prompt += f"""
                        SYSTEM: A tool test has failed.

                        Failure details:
                        {output}

                        Diagnosis:
                        {diagnosis}

                        The existing tool implementation is incorrect and must be repaired.

                        You must call code_agent to repair the existing tool.

                        Important repair instructions:

                        - Analyze the failure details and diagnosis carefully.
                        - Identify the exact cause of the error.
                        - Modify the tool implementation to correct the error.
                        - Do NOT recreate the same broken implementation.
                        - Ensure required imports are included.
                        - Ensure the tool uses positional arguments consistent with run(*args).
                        - Ensure INPUT_SPEC matches the parameters expected by run().
                        - Always redefine INPUT_SPEC when repairing a tool.
                        - If the failure message contains expected and actual values, correct the tool logic.

                        Example repair request:

                        AGENT: code_agent
                        INPUT: repair tool <tool_name>

                        Failure details:
                        Tool test failed: <tool_name> <failure description>

                        Diagnosis:
                        <diagnosis>

                        The repaired tool must:

                        - Define INPUT_SPEC
                        - Define run(*args)
                        - Correct the specific failure described above.
                        """

            if "error" in str(output).lower():
                manager_prompt += "\nSYSTEM: The previous action failed. You must correct the error.\n"

                # Prevent duplicate tester_agent runs
                manager_prompt += """
            SYSTEM: The tool test succeeded.

            Do NOT test the tool again.

            If the goal is satisfied, produce FINAL ANSWER now.
            """  

            # Detect repeated agent results — STRICTLY disable during repair mode
            recent_results = [s for s in steps if s.startswith("AGENT RESULT:")]

            # Detect repeated agent results — but veto during/after repair limit
            recent_results = [s for s in steps if s.startswith("AGENT RESULT:")]

            repeated = len(recent_results) >= 2 and recent_results[-1] == recent_results[-2]

            if repeated and agent_name != "tester_agent":
                if repair_mode or repair_attempts.get(failed_tool, 0) >= MAX_REPAIR_ATTEMPTS:
                    log("Repeated results during/after repair — ignoring (still in failure state)")
                    manager_prompt += "\nSYSTEM: Repeated results detected during failure state. Do NOT terminate or assume success.\n"
                    continue  # Force loop to continue or exit safely

                # Safe to terminate only outside repair context
                log("Repeated agent result detected. Assuming task complete (safe to terminate).")
                log(f"FINAL ANSWER: {output}")
                print(f"\nFINAL ANSWER: {output}\n")
                break

            elif repair_mode and len(recent_results) >= 2 and recent_results[-1] == recent_results[-2]:
                log("Repeated tester_agent failure during repair — ignoring, continue loop")
                manager_prompt += "\nSYSTEM: Repeated tester_agent failure detected. Do NOT terminate. Continue repair.\n"
                continue

            # ── MANAGER HARD VETO: NO SUCCESS OR FINAL ANSWER AFTER REPAIR LIMIT ────────
            if failed_tool and repair_attempts.get(failed_tool, 0) >= MAX_REPAIR_ATTEMPTS:
                upper_out = str(output).upper()
                lower_out = str(output).lower()

                # Block any attempt to claim success or final answer
                if "FINAL ANSWER" in upper_out or any(word in lower_out for word in ["success", "passed", "fixed", "completed", "correct", "999999"]):
                    log(f"Hard veto enforced: LLM tried to terminate after repair limit for tool '{failed_tool}'")
                    failure_msg = (
                        f"Repair limit reached - tool '{failed_tool}' could not be fixed. "
                        f"Failed after {MAX_REPAIR_ATTEMPTS} repair attempts. "
                        f"Original failure persisted."
                    )
                    print(f"\nFINAL ANSWER: {failure_msg}\n")
                    log_execution(goal, task_state, results + [failure_msg])
                    break  # Manager forces termination here - no further LLM calls

            # ── BLOCK LLM WRITING FINAL ANSWER DURING REPAIR ─────────────────
            if repair_mode and "FINAL ANSWER" in str(output).upper():
                log("Blocked LLM attempting FINAL ANSWER during active repair")
                manager_prompt += f"""
                SYSTEM: You wrote FINAL ANSWER in your response while repair_mode is still active.
                tester_agent is still failing the tool — the repair has NOT succeeded.

                DO NOT output FINAL ANSWER yet.
                Continue calling code_agent to fix the tool.
                Only output FINAL ANSWER when tester_agent passes OR when repair limit is reached.

                If limit reached, output:
                FINAL ANSWER: Repair limit reached - tool could not be fixed.

                Current attempt: {repair_attempts.get(failed_tool, 0)} / {MAX_REPAIR_ATTEMPTS}
                """
                continue

            # ── BLOCK LLM FABRICATED FINAL ANSWER AFTER REPAIR LIMIT ────────
            print(f"DEBUG: repair_mode={repair_mode}, attempts={repair_attempts.get(failed_tool, 'None')}, MAX={MAX_REPAIR_ATTEMPTS}, output starts with: {str(output)[:100]}")

            if repair_attempts.get(failed_tool, 0) >= MAX_REPAIR_ATTEMPTS and "FINAL ANSWER" in str(output):
                log("Blocked LLM-fabricated FINAL ANSWER after repair limit")
                final_msg = "Repair limit reached - tool could not be fixed. Original failure: runtime error."
                print(f"\nFINAL ANSWER: {final_msg}\n")
                log_execution(goal, task_state, results)
                break

        else:
            log("Unknown tool or agent requested.")
            break

# -------------------
# MANAGER MAIN LOOP
# -------------------

while True:
    print("\nEnter goal (end with an empty line):")
    
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            # Regression harness closed stdin
            exit(0)
        
        if line.strip() == "":
            break
        lines.append(line)
    
    goal = "\n".join(lines).strip()
    
    if not goal:
        continue
    
    # Process the goal and get result
    result = process_goal(goal)
    
    # If result is a failure object, it's already been printed
    # Continue to next goal
    if isinstance(result, dict) and result.get("type") == "failure":
        continue
