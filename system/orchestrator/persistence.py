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
    # Atomic write: build new list in memory, write via tempfile → os.replace
    # to prevent workflows.json corruption on crash mid-write.
    if status == "COMPLETED":
        workflows.append(workflow)
        try:
            dir_name = os.path.dirname(FILE_PATH) or "."
            os.makedirs(dir_name, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(workflows, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, FILE_PATH)
            except Exception:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
                return {"status": "failure", "reason": "write_failed"}
        except Exception:
            return {"status": "failure", "reason": "write_failed"}
        return {"status": "success"}

    # === ALL non-COMPLETED workflows with a valid id: per-workflow JSON file ===
    # Previously only ACTIVE/BLOCKED/PAUSED were written here. The status whitelist
    # was the root cause of validate_runtime_activation() never finding a persistence
    # file — ACTIVATING/PERSISTED states were silently ignored. Any workflow with a
    # valid id is now written so persistence checks are reliable.
    workflow_id = workflow.get("id", "")
    if workflow_id:
        try:
            _ensure_active_dir()
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


def workflow_persistence_exists(workflow_id: str) -> bool:
    """
    Fast O(1) check: does this workflow have a persistence file?

    MUST be used in all hot-path guards (stream_active, stream_workflow_id,
    projection endpoint, _update_workflow_state hard guard).
    MUST NOT call load_active_workflows() — that scans all files.

    Returns True if the file exists and workflow_id is valid, False otherwise.
    """
    if not workflow_id or not isinstance(workflow_id, str):
        return False
    path = _active_workflow_path(workflow_id)
    return os.path.exists(path)


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
