import json
import os

FILE_PATH = "memory/workflows.json"

try:
    if os.path.exists(FILE_PATH):
        with open(FILE_PATH, "r", encoding="utf-8") as f:
            workflows = json.load(f)
            if not isinstance(workflows, list):
                workflows = []
    else:
        workflows = []
except Exception:
    workflows = []


def save_workflow(workflow: dict) -> dict:
    if workflow.get("status") != "COMPLETED":
        return {"status": "ignored"}

    workflows.append(workflow)

    try:
        with open(FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(workflows, f, ensure_ascii=False, indent=2)
    except Exception:
        return {"status": "failure", "reason": "write_failed"}

    return {"status": "success"}


def get_workflows() -> dict:
    return {
        "status": "success",
        "workflows": workflows
    }


def get_last_workflow() -> dict:
    if not workflows:
        return {
            "status": "failure",
            "reason": "no_workflows"
        }

    return {
        "status": "success",
        "workflow": workflows[-1]
    }
