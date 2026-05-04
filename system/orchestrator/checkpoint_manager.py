"""
CHECKPOINT MANAGER — Passive Workflow State Persistence (Phase 2C)

Responsibility:
- Persist workflow state AFTER step reaches terminal state
- Enable safe resume from last checkpoint
- Discard invalid/corrupt checkpoints

Architecture Alignment:
- OBSERVATIONAL ONLY — does NOT influence execution, governance, or control flow
- Checkpoint is written AFTER governance decision is applied and step state is terminal
- Checkpoint does NOT store trace, validator signals, planner output, or LLM responses
- Scheduler is runtime-derived — NOT persisted (per EXECUTION_SCHEDULING_CONTRACT_V1)

Rules:
- NO execution logic
- NO governance influence
- NO modification of execution_result
- NO bypass of system_entry
- Atomic writes (write temp → replace)
- Checkpoint failure MUST NOT affect execution

Storage:
- system/checkpoints/<workflow_id>.json
"""

import json
import os
import tempfile
from typing import Optional


_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
CHECKPOINT_DIR = os.path.join(_ROOT, "system", "checkpoints")


def _ensure_checkpoint_dir():
    """Create checkpoint directory if it doesn't exist."""
    if not os.path.exists(CHECKPOINT_DIR):
        os.makedirs(CHECKPOINT_DIR, exist_ok=True)


def _checkpoint_path(workflow_id: str) -> str:
    """Return file path for a workflow checkpoint."""
    # Sanitize workflow_id to prevent path traversal
    safe_id = "".join(c for c in workflow_id if c.isalnum() or c in ("-", "_"))
    if not safe_id:
        safe_id = "unknown"
    return os.path.join(CHECKPOINT_DIR, f"{safe_id}.json")


def _extract_checkpoint_data(workflow: dict) -> dict:
    """
    Extract ONLY authoritative data for checkpoint.

    Stores:
    - workflow_id
    - workflow status
    - steps: id, status, execution_result, retries, blocked_reason
    - last_completed_step_index

    Does NOT store:
    - trace
    - validator signals
    - planner output
    - LLM responses
    - signal analysis
    """
    steps_data = []
    last_completed_index = -1

    for i, step in enumerate(workflow.get("steps", [])):
        step_data = {
            "id": step.get("id"),
            "status": step.get("status", "PENDING"),
            "execution_result": step.get("execution_result"),
            "retries": step.get("retries", 0),
        }
        # Preserve blocked_reason for BLOCKED steps
        if step.get("blocked_reason"):
            step_data["blocked_reason"] = step["blocked_reason"]

        steps_data.append(step_data)

        if step.get("status") == "COMPLETED":
            last_completed_index = i

    return {
        "workflow_id": workflow.get("id", "unknown"),
        "workflow_status": workflow.get("status", "ACTIVE"),
        "steps": steps_data,
        "last_completed_step_index": last_completed_index,
    }


def save_checkpoint(workflow: dict) -> bool:
    """
    Persist current workflow state to checkpoint file.

    Uses atomic write (temp file → rename) to prevent corruption.

    Args:
        workflow: The workflow dict (full runtime state)

    Returns:
        True if checkpoint saved successfully, False otherwise.
        Failure MUST NOT affect execution.
    """
    try:
        _ensure_checkpoint_dir()
        workflow_id = workflow.get("id", "unknown")
        path = _checkpoint_path(workflow_id)
        data = _extract_checkpoint_data(workflow)

        # Atomic write: temp file in same directory → rename
        dir_name = os.path.dirname(path)
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            # Atomic replace
            os.replace(tmp_path, path)
            return True
        except Exception:
            # Clean up temp file on failure
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            return False

    except Exception:
        return False


def load_checkpoint(workflow_id: str) -> Optional[dict]:
    """
    Load checkpoint for a workflow.

    Args:
        workflow_id: The workflow ID to load checkpoint for

    Returns:
        Checkpoint dict if valid, None if not found or corrupt.
        Invalid checkpoints are discarded (deleted).
    """
    try:
        path = _checkpoint_path(workflow_id)
        if not os.path.exists(path):
            return None

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Validate checkpoint structure
        if not _validate_checkpoint(data):
            # Corrupt checkpoint — discard
            delete_checkpoint(workflow_id)
            return None

        return data

    except (json.JSONDecodeError, OSError, KeyError):
        # Corrupt or unreadable — discard
        delete_checkpoint(workflow_id)
        return None


def delete_checkpoint(workflow_id: str) -> bool:
    """
    Delete checkpoint for a workflow.

    Args:
        workflow_id: The workflow ID to delete checkpoint for

    Returns:
        True if deleted (or didn't exist), False on error.
    """
    try:
        path = _checkpoint_path(workflow_id)
        if os.path.exists(path):
            os.remove(path)
        return True
    except OSError:
        return False


def _validate_checkpoint(data: dict) -> bool:
    """
    Validate checkpoint structural integrity.

    Returns True only if all required fields are present and well-formed.
    Invalid checkpoints are discarded, not repaired.
    """
    if not isinstance(data, dict):
        return False

    # Required top-level fields
    required = ("workflow_id", "workflow_status", "steps", "last_completed_step_index")
    for field in required:
        if field not in data:
            return False

    if not isinstance(data["steps"], list):
        return False

    if not isinstance(data["last_completed_step_index"], int):
        return False

    # Validate each step entry
    for step in data["steps"]:
        if not isinstance(step, dict):
            return False
        if "id" not in step:
            return False
        if "status" not in step:
            return False
        # Status must be a known value
        if step["status"] not in ("PENDING", "ACTIVE", "COMPLETED", "FAILED", "BLOCKED"):
            return False

    return True


def restore_workflow_from_checkpoint(workflow: dict, checkpoint: dict) -> dict:
    """
    Apply checkpoint state to a workflow for resume.

    Rules (per Phase 2C spec):
    - COMPLETED → skip (do not re-execute)
    - FAILED → allow governance retry (reset to PENDING for re-evaluation)
    - BLOCKED → remain BLOCKED
    - ACTIVE (interrupted) → mark FAILED (was interrupted mid-execution)

    This function modifies the workflow's step states only.
    It does NOT influence governance, scheduler, or execution logic.

    Args:
        workflow: The workflow dict (freshly initialized)
        checkpoint: Loaded checkpoint data

    Returns:
        The modified workflow dict with restored state.
    """
    checkpoint_steps = {s["id"]: s for s in checkpoint.get("steps", [])}
    restored_count = 0

    for step in workflow.get("steps", []):
        step_id = step.get("id")
        if step_id not in checkpoint_steps:
            continue

        cp_step = checkpoint_steps[step_id]
        cp_status = cp_step.get("status")

        if cp_status == "COMPLETED":
            # COMPLETED → skip (preserve execution_result)
            step["status"] = "COMPLETED"
            step["execution_result"] = cp_step.get("execution_result")
            step["retries"] = cp_step.get("retries", 0)
            restored_count += 1

        elif cp_status == "FAILED":
            # FAILED → reset to PENDING for governance re-evaluation
            step["status"] = "PENDING"
            step["retries"] = cp_step.get("retries", 0)
            restored_count += 1

        elif cp_status == "BLOCKED":
            # BLOCKED → remain BLOCKED
            step["status"] = "BLOCKED"
            step["retries"] = cp_step.get("retries", 0)
            if cp_step.get("blocked_reason"):
                step["blocked_reason"] = cp_step["blocked_reason"]
            restored_count += 1

        elif cp_status == "ACTIVE":
            # ACTIVE (interrupted) → mark FAILED
            step["status"] = "PENDING"
            step["retries"] = cp_step.get("retries", 0)
            restored_count += 1

        elif cp_status == "PENDING":
            # PENDING → keep as PENDING (no change needed)
            step["retries"] = cp_step.get("retries", 0)
            restored_count += 1

    return workflow
