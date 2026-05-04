import json
import os
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
FILE_PATH = os.path.join(_ROOT, "memory", "workflows.json")
ACTIVE_WORKFLOW_DIR = os.path.join(_ROOT, "memory", "active_workflows")

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


def _ensure_active_dir():
    """Create active workflow directory if it doesn't exist."""
    if not os.path.exists(ACTIVE_WORKFLOW_DIR):
        os.makedirs(ACTIVE_WORKFLOW_DIR, exist_ok=True)


def _active_workflow_path(workflow_id: str) -> str:
    """Return file path for an active workflow."""
    safe_id = "".join(c for c in workflow_id if c.isalnum() or c in ("-", "_"))
    if not safe_id:
        safe_id = "unknown"
    return os.path.join(ACTIVE_WORKFLOW_DIR, f"{safe_id}.json")


def save_workflow(workflow: dict) -> dict:
    status = workflow.get("status")

    # === COMPLETED workflows: append to legacy list (backward compat) ===
    if status == "COMPLETED":
        workflows.append(workflow)
        try:
            with open(FILE_PATH, "w", encoding="utf-8") as f:
                json.dump(workflows, f, ensure_ascii=False, indent=2)
        except Exception:
            return {"status": "failure", "reason": "write_failed"}
        return {"status": "success"}

    # === ACTIVE / BLOCKED / PAUSED workflows: per-workflow JSON file ===
    if status in ("ACTIVE", "BLOCKED", "PAUSED"):
        try:
            _ensure_active_dir()
            workflow_id = workflow.get("id", "unknown")
            path = _active_workflow_path(workflow_id)

            # Atomic write: temp file → replace
            dir_name = os.path.dirname(path)
            fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(workflow, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, path)
                return {"status": "success"}
            except Exception:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
                return {"status": "failure", "reason": "write_failed"}
        except Exception:
            return {"status": "failure", "reason": "write_failed"}

    return {"status": "ignored"}


def load_active_workflows() -> list:
    """
    Load all persisted active workflows from disk.

    Returns:
        List of workflow dicts. Invalid/corrupt files are silently ignored.
    """
    result = []
    if not os.path.exists(ACTIVE_WORKFLOW_DIR):
        return result

    for filename in os.listdir(ACTIVE_WORKFLOW_DIR):
        if not filename.endswith(".json"):
            continue
        filepath = os.path.join(ACTIVE_WORKFLOW_DIR, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "id" in data and "steps" in data:
                result.append(data)
            else:
                # Invalid structure — remove silently
                try:
                    os.remove(filepath)
                except OSError:
                    pass
        except (json.JSONDecodeError, OSError):
            # Corrupt file — remove silently
            try:
                os.remove(filepath)
            except OSError:
                pass

    return result


def delete_workflow(workflow_id: str) -> bool:
    """
    Delete a persisted active workflow file.

    Returns:
        True if deleted (or didn't exist), False on error.
    """
    try:
        path = _active_workflow_path(workflow_id)
        if os.path.exists(path):
            os.remove(path)
        return True
    except OSError:
        return False


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
