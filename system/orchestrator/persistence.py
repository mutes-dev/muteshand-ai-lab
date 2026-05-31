import json
import os
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
FILE_PATH = os.path.join(_ROOT, "memory", "workflows.json")
ACTIVE_WORKFLOW_DIR = os.path.join(_ROOT, "memory", "active_workflows")

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
    if status == "COMPLETED":
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
                # === PHASE XV-B TRACE LOGGING ===
                print("[PERSIST_SAVE]")
                print(f"  workflow_id={workflow_id}")
                print(f"  status={status}")
                print(f"  path={path}")
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

    # === PHASE XV-B TRACE LOGGING ===
    print("[PERSIST_LOAD]")
    print(f"  dir={ACTIVE_WORKFLOW_DIR}")
    print(f"  files_found={len(os.listdir(ACTIVE_WORKFLOW_DIR) if os.path.exists(ACTIVE_WORKFLOW_DIR) else [])}")

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
                # === PHASE XV-B TRACE LOGGING ===
                print("[PERSIST_LOAD]")
                print(f"  workflow_id={data.get('id')}")
                print(f"  status={data.get('status')}")
                print(f"  path={filepath}")
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
        # === PHASE XV-B TRACE LOGGING ===
        print("[PERSIST_DELETE]")
        print(f"  workflow_id={workflow_id}")
        print(f"  reason=explicit_delete")
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
