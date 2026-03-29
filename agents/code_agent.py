import os
import re
from core.llm import ask_llm

BASE_PATH = "E:/MutesHand"

    
def clean_code(code):

    code = code.replace("```python", "")
    code = code.replace("```", "")

    return code.strip()

def extract_name(task):

    # capture name after 'tool' or 'agent'
    match = re.search(r"(tool|agent)\s+([a-zA-Z_][a-zA-Z0-9_]*)", task.lower())

    if match:
        return match.group(2)

    return None

def run(task):

    # Load existing tool code if we are fixing a tool
    existing_code = ""

    if "fix tool" in task.lower() or "repair tool" in task.lower():

        name = extract_name(task)

        if name:
            tool_path = os.path.join(BASE_PATH, "tools", f"{name}.py")

            if os.path.exists(tool_path):
                with open(tool_path, "r", encoding="utf-8") as f:
                    existing_code = f.read()

    prompt = f"""
You are a coding agent inside an AI system.

You create Python files for tools and agents.

--------------------------------

TOOL TEMPLATE

All tools must define INPUT_SPEC describing the parameters expected by run().

Tools must follow this structure:

    INPUT_SPEC = {{
        "param_name": "type"
    }}

    def run(*args):
        try:
            # Access parameters by position
            # Example:
            # num1 = args[0]
            # num2 = args[1]

            result = None
            return result

        except Exception as e:
            raise Exception(str(e))

Rules for tools:
- Tools must define a run(*args) function.
- All execution logic must exist inside run().
- Tools may define metadata variables (e.g., INPUT_SPEC).
- Tools must not define additional executable functions.
- If the failure details indicate a missing import (e.g. "name 'os' is not defined"), the tool MUST include the required import.
- ERROR HANDLING RULE

    Tools must NOT return error messages as strings.

    If an error occurs, the tool must raise an exception:

    raise Exception("error message")

    Never return error messages like:

    return "error"
    return "file not found"
    return "invalid input"

When repairing a tool, you MUST analyze the failure details included in the task.

Use the failure details to determine the root cause of the failure and modify the implementation accordingly.

Typical repairs include:
- Adding missing imports
- Correcting argument indexing
- Fixing incorrect calculations
- Handling incorrect input types
- Correcting file or directory operations

Do NOT recreate the same broken implementation.

Tools must perform a single operation.

Tools must not orchestrate other tools or agents.

Tools must not dynamically discover or execute system tools.

Tools may only use standard Python libraries and their input parameters.

--------------------------------

AGENT RULES

Agents must define a function:

def run(task)

This function is the entry point used by the manager.

Agents may contain:
- additional helper functions
- classes
- imports
- internal logic
- tool usage
- agent-to-agent communication

Agents may assume the project root path is:
BASE_PATH = "E:/AI_Lab - Copy"

The internal structure of the agent is NOT restricted.

Requirements:
- run(task) must return a result that describes the outcome of the task.
- errors should be handled safely

Agents should return meaningful output describing the result of the task.

Agents must implement the requirements described in the task.

CRITICAL:
If the task requires interacting with tools, files, or agents,
the implementation MUST perform real dynamic discovery.

Examples of correct behavior:

- Discover tools using os.listdir()
- Import tools dynamically using importlib
- Execute the discovered tool functions
- Handle exceptions safely

INCORRECT behavior (NEVER DO THIS):

- Hardcoded example logic
- Fake tool execution
- Example calculations like 1+2
- Conditional placeholder responses

Agents must interact with the real system environment when required.

When discovering tools, the agent must:

- read the tools directory
- dynamically import tool modules
- call tool.run()

Do not simulate tool behavior.

Example pattern for dynamic tool usage:

import os
import importlib

def run(task):

    BASE_PATH = "E:/AI_Lab - Copy"
    tools_dir = os.path.join(BASE_PATH, "tools")

    # Extract tool name from task
    parts = task.split()
    tool_name = parts[-1]

    for file in os.listdir(tools_dir):

        if file.endswith(".py"):

            name = file[:-3]

            # Only run the requested tool
            if name != tool_name:
                continue

            importlib.invalidate_caches()
            module = importlib.import_module("tools." + name)

            module.run()

    return "done" 

--------------------------------

All file system access must use the absolute project path:

E:/AI_Lab - Copy

Example:

tools_dir = "E:/AI_Lab - Copy/tools"
files = os.listdir(tools_dir)

--------------------------------

All generated agents must be self-contained and runnable immediately.
Do not rely on undefined variables.

--------------------------------

Rules:
- Return ONLY valid Python code when generating files.
- No markdown.
- No explanations.

When the file is successfully written, the agent MUST return exactly:

File created: <absolute_path>

Example:

File created: E:/AI_Lab - Copy/tools/multiply_numbers.py

No additional text is allowed in the response.

Generated code must not print debug output unless required by the task.

Existing implementation (if any):

{existing_code if existing_code else "No existing implementation found."}

Task:
{task}
"""

    print("\n===== TOOL GENERATION PROMPT =====")
    print(prompt)
    print("==================================\n")

    code = ask_llm(prompt)

    print("\n===== TOOL GENERATION LLM OUTPUT =====")
    print(code)
    print("======================================\n")

    code = clean_code(code)

    # Remove accidental labels like 'tool_code'
    lines = code.split("\n")

    while lines and not (
        lines[0].startswith("INPUT_SPEC")
        or lines[0].startswith("def ")
        or lines[0].startswith("#")
        or lines[0].startswith('"""')
    ):
        lines.pop(0)

    code = "\n".join(lines)

    code = code.strip()

    # Remove accidental success messages from generated code
    if "File created:" in code:
        lines = code.split("\n")
        lines = [line for line in lines if not line.strip().startswith("File created:")]
        code = "\n".join(lines)

    # Ensure output looks like Python code
    if "def " not in code:
        return "Code Agent error: Generated output was not valid Python code."

    name = extract_name(task)

    if not name:
        return "Code Agent could not determine file name."
    
    # Enforce agent naming convention
    if "agent" in task.lower() and not name.endswith("_agent"):
        return "Code Agent error: Agent names must end with _agent."
    
    # Determine destination
    if name.endswith("_agent"):
        filename = os.path.join(BASE_PATH, "agents", f"{name}.py")
        is_agent = True
    else:
        filename = os.path.join(BASE_PATH, "tools", f"{name}.py")
        is_agent = False

    # Validate tool structure
    if not is_agent:

        # -------------------
        # EXECUTABLE VALIDATION PIPELINE
        # -------------------

        # STEP 1 — COMPILE CHECK
        try:
            compile(code, "<tool>", "exec")
        except Exception as e:
            print("\n❌ TOOL VALIDATION FAILED — COMPILE ERROR")
            print(str(e))
            return f"Tool generation failed: compile error — {str(e)}"

        # STEP 2 — SAFE EXECUTION
        namespace = {}

        try:
            exec(code, namespace)
        except Exception as e:
            print("\n❌ TOOL VALIDATION FAILED — EXEC ERROR")
            print(str(e))
            return f"Tool generation failed: execution error — {str(e)}"

        # STEP 3 — STRUCTURE VALIDATION
        if "INPUT_SPEC" not in namespace:
            return "Tool generation failed: INPUT_SPEC missing"

        if not isinstance(namespace["INPUT_SPEC"], dict):
            return "Tool generation failed: INPUT_SPEC must be a dict"

        if "run" not in namespace:
            return "Tool generation failed: run() missing"

        if not callable(namespace["run"]):
            return "Tool generation failed: run must be callable"

        # STEP 4 — INPUT_SPEC VALIDATION
        for key, value in namespace["INPUT_SPEC"].items():
            if not isinstance(key, str):
                return "Tool generation failed: INPUT_SPEC keys must be strings"
            if not isinstance(value, str):
                return "Tool generation failed: INPUT_SPEC values must be strings"

        lines = code.split("\n")
        def_count = sum(1 for line in lines if line.strip().startswith("def "))

        if def_count > 1:
            return "Code Agent error: Tools must contain only one function: run()."
        
    # Validate agent structure
    if is_agent:

        if "def run(" not in code:
            return "Code Agent error: Agent must define run(task)."

        # Detect obvious placeholder logic
        if "1 + 2" in code or "5 * 10" in code:
            return "Code Agent error: Placeholder logic detected."

        # If testing tools, require dynamic imports
        if "test" in task.lower() and "tool" in task.lower():
            if "importlib" not in code:
                return "Code Agent error: Tool-testing agents must use importlib."        
    
    try:

        with open(filename, "w", encoding="utf-8") as f:
            f.write(code)

        print("\n===== GENERATED TOOL FILE (FROM DISK) =====")
        print(f"Path: {filename}")
        print("\nContents:")
        with open(filename, "r", encoding="utf-8") as f:
            print(f.read())
        print("===========================================\n")

        return f"File created: {filename}"

    except Exception as e:

        return f"Code Agent error: {e}"