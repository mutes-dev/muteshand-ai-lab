import json
import os
import tempfile
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
FILE_PATH = os.path.join(_ROOT, "memory", "workflows.json")
ACTIVE_WORKFLOW_DIR = os.path.join(_ROOT, "memory", "active_workflows")

# === ISSUE-060: RETENTION STATE CONSTANTS ===
_VALID_RETENTION_STATES = {"retained", "archived", "dismissed"}
_RETENTION_STATE_DEFAULT = "retained"

# === PHASE XII §5: BOUNDED RETENTION POLICY ===
# Maximum number of completed workflows retained in workflows.json.
# Configurable via environment variable. Oldest entries are evicted first.
# This is archival/historical only — does NOT affect active workflow persistence.
MAX_COMPLETED_WORKFLOWS = int(os.environ.get("MUTESHAND_MAX_COMPLETED_WORKFLOWS", "100"))

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
    # === PHASE VI: INJECT AUTHORITATIVE LIFECYCLE BEFORE PERSISTENCE ===
    # Per AUTHORITY CONSOLIDATION: workflow['status'] is a serialization mirror ONLY.
    # Persistence MUST serialize registry truth, not mutable mirror state.
    workflow_id = workflow.get("id")
    if workflow_id:
        try:
            from system.orchestrator.workflow_control import inject_authoritative_lifecycle_into_workflow
            inject_authoritative_lifecycle_into_workflow(workflow)
        except Exception:
            pass

    # === TERMINAL PERSISTENCE GUARD ===
    # Per WORKFLOW_CANCELLATION_AND_TERMINALIZATION_CONTRACT_V1:
    # CANCELLED is immutable terminal - background execution must not downgrade.
    # After lifecycle injection, enforce terminal state protection.
    status = workflow.get("status")
    if workflow_id and status:
        try:
            from system.orchestrator.workflow_control import _get_workflow_state
            authority_state = _get_workflow_state(workflow_id)
            if authority_state:
                authority_status = authority_state.get("status")
                # Guard against overwriting terminal CANCELLED/COMPLETED states
                if authority_status in ["CANCELLED", "COMPLETED"] and status != authority_status:
                    print("[TERMINAL_PERSIST_GUARD]", {
                        "workflow_id": workflow_id,
                        "incoming_status": status,
                        "authority_status": authority_status,
                        "persisted_status": authority_status,
                        "caller": "save_workflow",
                        "timestamp": __import__("time").time()
                    })
                    workflow["status"] = authority_status
                    status = authority_status
        except Exception:
            pass  # Guard failure must not prevent persistence

    # === COMPLETED workflows: append to legacy list (backward compat) ===
    # Atomic write: build new list in memory, write via tempfile → os.replace
    # to prevent workflows.json corruption on crash mid-write.
    # Per INCIDENT-098A: deduplicate by workflow_id to prevent duplicate entries
    # when terminal save is called more than once for the same workflow.
    if status == "COMPLETED":
        _wf_id = workflow.get("id")
        _existing_index = None
        if _wf_id:
            for _i, _existing in enumerate(workflows):
                if _existing.get("id") == _wf_id:
                    _existing_index = _i
                    break
        if _existing_index is not None:
            workflows[_existing_index] = workflow
        else:
            workflows.append(workflow)
        # === PHASE XII §5: BOUNDED RETENTION ENFORCEMENT ===
        # Evict oldest entries when list exceeds configured maximum.
        # Deterministic FIFO eviction — oldest workflows removed first.
        # Non-authoritative archival cleanup only.
        if len(workflows) > MAX_COMPLETED_WORKFLOWS:
            workflows[:] = workflows[-MAX_COMPLETED_WORKFLOWS:]
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

    Per PHASE VII Authority Hardening:
    - Raw persisted mirror state is NOT operational truth.
    - Authoritative lifecycle is injected from registry before returning.
    - Transitional bootstrap states (ACTIVATING, PENDING_RECOVERY) are sanitized.

    Returns:
        List of workflow dicts with authoritative lifecycle injected.
        Invalid/corrupt files are silently ignored.
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
                # Inject authoritative lifecycle before exposing
                try:
                    from system.orchestrator.workflow_control import inject_authoritative_lifecycle_into_workflow
                    inject_authoritative_lifecycle_into_workflow(data)
                except Exception:
                    pass
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


def load_workflow(workflow_id: str) -> dict | None:
    """
    Load a single persisted active workflow by ID.

    Returns:
        Workflow dict if found and valid, None otherwise.
    """
    if not workflow_id or not isinstance(workflow_id, str):
        return None
    path = _active_workflow_path(workflow_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "id" in data and "steps" in data:
            try:
                from system.orchestrator.workflow_control import inject_authoritative_lifecycle_into_workflow
                inject_authoritative_lifecycle_into_workflow(data)
            except Exception:
                pass
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return None


def workflow_persistence_exists(workflow_id: str) -> bool:
    """
    Fast O(1) check: does this workflow have a persistence file?

    MUST be used in all hot-path guards (stream_active, stream_workflow_id,
    projection endpoint, _update_workflow_state hard guard).
    MUST NOT call load_active_workflows() — that scans all files.

    Returns True if the file exists and workflow_id is valid, False otherwise.
    Also checks workflows.json for COMPLETED workflows.
    """
    if not workflow_id or not isinstance(workflow_id, str):
        return False
    path = _active_workflow_path(workflow_id)
    if os.path.exists(path):
        return True
    # === ISSUE-098KY: COMPLETED workflows live in workflows.json ===
    if os.path.exists(FILE_PATH):
        try:
            with open(FILE_PATH, "r", encoding="utf-8") as f:
                completed_list = json.load(f)
            if isinstance(completed_list, list):
                return any(wf.get("id") == workflow_id for wf in completed_list)
        except Exception:
            pass
    return False


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


# === ISSUE-060: RETENTION STATE HELPERS ===

def get_retention_state(workflow_id: str) -> str:
    """
    Load persisted workflow and return its retention_state.

    Per ISSUE-060 design decision:
    - retention_state lives in persisted workflow JSON
    - missing retention_state defaults to "retained"
    - _workflow_state_registry is NOT the retention authority

    Returns:
        retention_state string (retained | archived | dismissed)
    """
    wf = load_workflow(workflow_id)
    if wf is None:
        return _RETENTION_STATE_DEFAULT
    return wf.get("retention_state", _RETENTION_STATE_DEFAULT)


def set_retention_state(workflow_id: str, state: str) -> dict:
    """
    Update retention_state on a persisted workflow.

    Per WORKFLOW_RETENTION_AND_ARCHIVAL_CONTRACT_V1:
    - retention actions do NOT alter lifecycle truth
    - lifecycle state remains unchanged
    - workflow record is preserved (not deleted)

    Args:
        workflow_id: target workflow id
        state: one of retained | archived | dismissed

    Returns:
        {"status": "success"} or {"status": "failure", "reason": ...}
    """
    if state not in _VALID_RETENTION_STATES:
        return {
            "status": "failure",
            "reason": f"invalid_retention_state: {state}. allowed: {_VALID_RETENTION_STATES}"
        }

    wf = load_workflow(workflow_id)
    if wf is None:
        return {"status": "failure", "reason": "workflow_not_found"}

    # Update retention metadata only
    wf["retention_state"] = state
    wf["retention_updated_at"] = time.time()
    if state == "archived":
        wf["archived_at"] = time.time()
    elif state == "dismissed":
        wf["dismissed_at"] = time.time()

    # Per ISSUE-060: retention_state must be discoverable via load_workflow.
    # save_workflow writes COMPLETED workflows to workflows.json only,
    # skipping the active_workflows file. We explicitly persist to the
    # active_workflows file so that subsequent get_retention_state calls
    # read the updated value.
    _ensure_active_dir()
    path = _active_workflow_path(workflow_id)
    try:
        dir_name = os.path.dirname(path)
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(wf, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    except Exception:
        pass

    # Also call save_workflow so COMPLETED workflows are updated in
    # workflows.json and non-COMPLETED workflows get lifecycle injection.
    return save_workflow(wf)


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
