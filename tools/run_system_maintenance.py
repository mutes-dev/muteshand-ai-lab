import importlib

INPUT_SPEC = {}

TOOLS = {
    "health_check_system": "infrastructure",
    "self_test_system": "functional_tests"
}

REPAIR_MAP = {
    "tool_index": "rebuild_tool_index",
    "tool_index_json": "rebuild_tool_index"
}


def run():
    results = {
        "status": "ok",
        "infrastructure": {},
        "functional_tests": {},
        "recommended_repairs": []
    }

    # Run health_check_system
    try:
        health = importlib.import_module("tools.health_check_system")
        r = health.run()

        results["infrastructure"] = r.get("checks", {})

        if r.get("status") != "ok":
            results["status"] = "warning"

            for k, v in r.get("checks", {}).items():
                if v != "ok" and k in REPAIR_MAP:
                    results["recommended_repairs"].append(REPAIR_MAP[k])

    except:
        results["status"] = "warning"
        results["infrastructure"] = {"health_check_system": "fail"}

    # Run self_test_system
    try:
        test = importlib.import_module("tools.self_test_system")
        r = test.run()

        results["functional_tests"] = r.get("tests", {})

        if r.get("status") != "ok":
            results["status"] = "warning"

            for k, v in r.get("tests", {}).items():
                if v != "pass" and k in REPAIR_MAP:
                    results["recommended_repairs"].append(REPAIR_MAP[k])

    except:
        results["status"] = "warning"
        results["functional_tests"] = {"self_test_system": "fail"}

    # remove duplicates
    results["recommended_repairs"] = list(set(results["recommended_repairs"]))

    return results