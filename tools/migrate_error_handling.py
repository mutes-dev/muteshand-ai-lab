INPUT_SPEC = {}

def run():

    import os
    from core.config import BASE_PATH
    import pathlib

    tools_dir = BASE_PATH / "tools"

    INFRASTRUCTURE_TOOLS = {
        "rebuild_tool_index",
        "run_system_maintenance",
        "health_check_system",
        "self_test_system",
        "web_search",
        "write_file",
        "read_file",
        "run_python"
    }

    updated = []

    for file in os.listdir(tools_dir):

        if not file.endswith(".py"):
            continue

        name = file[:-3]

        # skip migration tool itself
        if name == "migrate_error_handling":
            continue

        # skip infrastructure tools
        if name in INFRASTRUCTURE_TOOLS:
            continue

        path = str(tools_dir / file)

        with open(path, "r", encoding="utf-8") as f:
            code = f.read()

        if "return str(e)" in code:

            new_code = code.replace(
                "return str(e)",
                "raise Exception(str(e))"
            )

            with open(path, "w", encoding="utf-8") as f:
                f.write(new_code)

            updated.append(name)

    return {
        "updated_tools": updated
    }