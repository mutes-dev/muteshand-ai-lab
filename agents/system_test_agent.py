INPUT_SPEC = {
    "goal": "string"
}

def run(goal):

    import json
    import os

    BASE_PATH = "E:/AI_Lab - Copy"

    tool_index_file = os.path.join(
        BASE_PATH,
        "memory",
        "tool_index",
        "tools.json"
    )

    INFRASTRUCTURE_TOOLS = {
        "rebuild_tool_index",
        "run_system_maintenance",
        "health_check_system",
        "self_test_system"
    }

    with open(tool_index_file, "r", encoding="utf-8") as f:
        tool_index = json.load(f)

    commands = []

    for tool_name, data in tool_index.items():

        if tool_name in INFRASTRUCTURE_TOOLS:
            continue

        inputs = data.get("inputs", {})

        args = []

        for param, param_type in inputs.items():

            param_type = str(param_type).lower()

            if "number" in param_type or "int" in param_type:
                args.append(f"{param}=1")

            elif "float" in param_type:
                args.append(f"{param}=1.0")

            elif "directory" in param.lower():
                args.append(f'{param}="E:/AI_Lab - Copy/tools"')

            elif "url" in param.lower():
                args.append(f'{param}="https://example.com"')

            elif "string" in param_type:
                args.append(f'{param}="test"')

            elif "file" in param.lower():
                args.append(f'{param}="E:/AI_Lab - Copy/test.txt"')    

            else:
                args.append(f"{param}=1")

        arg_string = " ".join(args)

        if arg_string:
            test_command = f"test tool {tool_name} with input {arg_string}"
        else:
            test_command = f"test tool {tool_name}"

        commands.append(test_command)

    report = []

    for cmd in commands:

        report.append("AGENT: tester_agent")
        report.append(f"INPUT: {cmd}")
        report.append("")

    return "\n".join(report)