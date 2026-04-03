def resolve(plan: list) -> list:
    resolved_plan = []

    for i, step in enumerate(plan):
        tool = step["tool"]
        args = step["args"]

        if i > 0:
            if len(args) == 1:
                args = ["PREVIOUS_RESULT", args[0]]

        resolved_plan.append({
            "tool": tool,
            "args": args
        })

    return resolved_plan
