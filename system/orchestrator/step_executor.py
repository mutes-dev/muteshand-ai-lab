"""Step Executor Module — Handles step execution WITHOUT changing behavior.

This module extracts the execution logic from orchestrator_runtime
to create a clean separation of concerns. BEHAVIOR IS LOCKED.
"""
import json
import os
import shlex
from system.orchestrator import signal_interpreter

from system.entry.system_entry import system_entry
from system.orchestrator.agent_executor import execute_agent
from system.orchestrator.intent_validator import evaluate_intent
from system.orchestrator.workflow_validator import validate_step_schema

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_TOOL_INDEX_PATH = os.path.join(_ROOT, "system", "tool_index", "tools.json")
with open(_TOOL_INDEX_PATH, "r", encoding="utf-8") as _f:
    _tool_index = json.load(_f)


def _structured_log(event_type, workflow_id, step_id, data):
    """Structured debug logger for runtime trace evidence."""
    import json
    log_entry = {
        "EVENT": event_type,
        "workflow_id": workflow_id,
        "step_id": step_id,
        "timestamp": __import__('datetime').datetime.now().isoformat(),
        "data": data
    }
    print(f"[RUNTIME_TRACE] {json.dumps(log_entry, default=str)}")


def _safe_extract_tool_name(executed_input):
    """Safely extract tool name from executed_input string without mutation."""
    if not executed_input or not isinstance(executed_input, str):
        return None
    cleaned = executed_input.strip()
    if cleaned.startswith("USE_TOOL:"):
        cleaned = cleaned.split("USE_TOOL:", 1)[1].strip()
    parts = cleaned.split()
    return parts[0] if parts else None


def _is_deterministic_source_grounded(step_result, step):
    if not isinstance(step_result, dict):
        return False
    result = step_result.get("result")
    if not isinstance(result, dict):
        return False
    if result.get("deterministic_synthesis") is not True:
        return False
    if result.get("deterministic_synthesis_reason") != "single_dependency_presentation":
        return False
    cap = step.get("capability_metadata") if isinstance(step, dict) else None
    if cap and cap.get("allowed_tool") != "finalize_output":
        return False
    return True


# === PDIAG-008B2: File-path restoration helpers ===

_FILE_READ_TOOLS = frozenset(["read_file", "list_files"])
_FILE_APPEND_TOOLS = frozenset(["append_file"])
_FILE_WRITE_TOOLS = frozenset(["write_file", "edit_file", "append_file"])

# === PDIAG-008B7: User path grounding ===
# All local-file tools eligible for purpose-path grounding correction.
_FILE_PATH_TOOLS = frozenset(["write_file", "read_file", "edit_file", "append_file", "list_files"])


def _extract_quoted_path_from_executed_input(executed_input: str):
    """
    Extract the first quoted string argument from a tool executed_input.

    e.g. 'write_file "pdiag008_write.txt" "alpha beta gamma"' -> 'pdiag008_write.txt'
         'edit_file "path/file.txt" "old" "new" 0 0'           -> 'path/file.txt'

    Returns the path string, or None if not parseable.
    Failure-isolated: never raises.
    """
    if not executed_input or not isinstance(executed_input, str):
        return None
    try:
        import shlex as _shlex
        cleaned = executed_input.strip()
        if cleaned.startswith("USE_TOOL:"):
            cleaned = cleaned.split("USE_TOOL:", 1)[1].strip()
        tokens = _shlex.split(cleaned)
        if len(tokens) >= 2:
            return tokens[1]
        return None
    except Exception:
        return None


def _attempt_user_path_grounding(step, execution_result, executed_input):
    """
    PDIAG-008B7: Bounded deterministic correction for first-step AG1 filename typo.

    When AG1 produces a tool call with a path that differs from the single unambiguous
    path in the step purpose, re-execute with the purpose path.

    Activation conditions (ALL must be true):
      1. selected tool is write_file, read_file, edit_file, append_file, or list_files
      2. step purpose contains exactly ONE extractable local file path
      3. executed_input contains a parseable quoted path (tokens[1])
      4. the purpose path differs from the executed_input path (case/slash normalized)
      5. the purpose path is not URL-like and not an internet TLD domain
      6. step has not already had grounding attempted (_user_path_grounding_attempted)
      7. Fires regardless of whether original execution succeeded or failed
         (false-success on typo path is the primary target)

    Correction behavior:
      - Rebuild tool call replacing only tokens[1] with the purpose path
      - All other tokens (old_text, new_text, content, flags) are preserved exactly
      - Call system_entry(corrected_call)
      - Return corrected result and metadata

    NEVER alters content/old_text/new_text arguments.
    NEVER fires when purpose has zero or multiple paths.
    NEVER fires on URL/domain-like paths.
    NEVER bypasses system_entry.
    NEVER loops (one attempt maximum per step lifetime).
    Failure-isolated: any exception returns None.
    """
    try:
        from system.orchestrator.planning_compiler import (
            _extract_local_file_paths,
            _normalize_local_file_path,
        )

        current_tool = _safe_extract_tool_name(executed_input)
        if current_tool not in _FILE_PATH_TOOLS:
            return None

        if step.get("_user_path_grounding_attempted"):
            return None

        purpose = step.get("purpose", "") or ""
        if not purpose:
            return None

        purpose_paths = _extract_local_file_paths(purpose)
        if len(purpose_paths) != 1:
            return None

        # Secondary safety: count ALL bare filename patterns in purpose regardless of
        # keyword anchoring. If raw count > 1 the purpose is ambiguous (e.g. copy A to B)
        # and grounding must not fire even if _extract_local_file_paths only found one.
        import re as _re
        _all_filenames = _re.findall(
            r'(?<!\w)([a-zA-Z0-9_.-]+\.[a-zA-Z0-9]{1,10})(?=\s|$|[,;.!?\)])',
            purpose
        )
        _INTERNET_TLDS = frozenset([
            "com", "org", "net", "io", "edu", "gov", "co", "uk", "de", "fr", "au",
            "ca", "ru", "jp", "cn", "br", "in", "mx", "nl", "se", "no", "fi",
            "html", "htm",
        ])
        _valid_raw = [
            fn for fn in _all_filenames
            if "/" not in fn and "\\" not in fn
            and not _re.match(r'(?i)^https?', fn)
            and fn.rsplit(".", 1)[-1].lower() not in _INTERNET_TLDS
            and len(fn.rsplit(".", 1)[0]) >= 2
        ]
        if len(_valid_raw) != 1:
            return None

        purpose_path_raw = purpose_paths[0]
        purpose_path_norm = _normalize_local_file_path(purpose_path_raw)
        if not purpose_path_norm:
            return None

        executed_path_raw = _extract_quoted_path_from_executed_input(executed_input)
        if not executed_path_raw:
            return None

        executed_path_norm = _normalize_local_file_path(executed_path_raw)
        if not executed_path_norm:
            return None

        if purpose_path_norm == executed_path_norm:
            return None

        try:
            import shlex as _shlex
            cleaned = executed_input.strip()
            if cleaned.startswith("USE_TOOL:"):
                cleaned = cleaned.split("USE_TOOL:", 1)[1].strip()
            tokens = _shlex.split(cleaned)
        except Exception:
            return None

        if len(tokens) < 2:
            return None

        # Rebuild by replacing only the path token (tokens[1]).
        # Preserve the original suffix (tokens[2:]) in its original raw form
        # by slicing the cleaned string after the first two shlex tokens,
        # so that numeric flags like '0 0' are not incorrectly re-quoted.
        try:
            import shlex as _shlex2
            # Re-parse to find where tokens[1] ends in the cleaned string
            _lex = _shlex2.shlex(cleaned, posix=True)
            _lex.whitespace_split = False
            _lex.whitespace = ' \t\n'
            _first = _lex.get_token()   # tool name
            _second = _lex.get_token()  # original path token
            _suffix = cleaned[_lex.instream.tell():].lstrip() if hasattr(_lex.instream, 'tell') else ""
            if not _suffix and len(tokens) > 2:
                # Fallback: re-join remaining tokens with original quoting by
                # finding the raw suffix after the first two quoted segments
                _after_tool = cleaned[len(tokens[0]):].lstrip()
                _found = False
                if _after_tool.startswith('"'):
                    _end = _after_tool.find('"', 1)
                    if _end != -1:
                        _suffix = _after_tool[_end + 1:].lstrip()
                        _found = True
                if not _found:
                    _suffix = " ".join(tokens[2:])
        except Exception:
            _suffix = " ".join(tokens[2:])
        corrected_call = f'{tokens[0]} "{purpose_path_raw}"'
        if _suffix:
            corrected_call = f'{corrected_call} {_suffix}'

        corrected_result = system_entry(corrected_call)

        grounding_meta = {
            "user_path_grounding_attempted": True,
            "purpose_path": purpose_path_raw,
            "original_executed_input": executed_input,
            "grounded_executed_input": corrected_call,
            "original_path": executed_path_raw,
            "grounded_path": purpose_path_raw,
            "grounding_result_status": corrected_result.get("status"),
        }

        return {
            "execution_result": corrected_result,
            "executed_input": corrected_call,
            "metadata": grounding_meta,
        }
    except Exception:
        return None


def _extract_quoted_content_from_executed_input(executed_input: str):
    """
    Extract the second quoted string argument (content) from a tool executed_input.

    e.g. 'append_file "wrong_path.txt" "second line"' -> 'second line'

    Returns the content string, or None if not parseable or absent.
    Failure-isolated: never raises.
    """
    if not executed_input or not isinstance(executed_input, str):
        return None
    try:
        import shlex as _shlex
        cleaned = executed_input.strip()
        if cleaned.startswith("USE_TOOL:"):
            cleaned = cleaned.split("USE_TOOL:", 1)[1].strip()
        tokens = _shlex.split(cleaned)
        if len(tokens) >= 3:
            return tokens[2]
        return None
    except Exception:
        return None


def _attempt_file_path_restoration(step, execution_result, executed_input, dependency_outputs, workflow):
    """
    Bounded deterministic correction for file_not_found caused by AG1 path typo.

    Covers two restore-eligible target tools:
      A. read_file / list_files  (Patch B2) — corrected call: tool "dep_path"
      B. append_file             (Patch B6) — corrected call: append_file "dep_path" "content"
         Content is extracted from the current (failed) append_file executed_input.
         If content is not parseable, correction is skipped (safety: no content loss).

    Activation conditions (ALL must be true):
      1. execution_result.status == 'failure'
      2. reason == 'file_not_found'
      3. selected tool is read_file, list_files, or append_file
      4. step has explicit depends_on (non-empty)
      5. step has not already had a restoration attempted (_file_path_restoration_attempted)
      6. a dependency step completed successfully with selected_tool in write_file/edit_file/append_file
      7. that dependency's executed_input has a parseable quoted path
      8. the corrected path differs from the current path OR current path does not exist
      9. for append_file: the current executed_input has a parseable quoted content argument

    Returns:
      dict with 'execution_result', 'executed_input', 'metadata' if correction was made
      None if conditions not met (caller uses original result unchanged)

    NEVER bypasses system_entry. NEVER marks failure as success artificially.
    NEVER converts append_file to write_file. NEVER creates missing files silently.
    NEVER loops (one attempt maximum per step lifetime).
    Failure-isolated: any exception returns None.
    """
    try:
        if not execution_result or execution_result.get("status") != "failure":
            return None
        if execution_result.get("reason") != "file_not_found":
            return None

        current_tool = _safe_extract_tool_name(executed_input)
        _is_read_restore = current_tool in _FILE_READ_TOOLS
        _is_append_restore = current_tool in _FILE_APPEND_TOOLS
        if not _is_read_restore and not _is_append_restore:
            return None

        depends_on = step.get("depends_on") or []
        if not depends_on:
            return None

        if step.get("_file_path_restoration_attempted"):
            return None

        steps = workflow.get("steps", [])
        step_map = {s.get("id"): s for s in steps if s.get("id")}

        source_step = None
        source_path = None
        for dep_id in depends_on:
            dep_step = step_map.get(dep_id)
            if not dep_step:
                continue
            if dep_step.get("status") != "COMPLETED":
                continue
            dep_tool = (
                (dep_step.get("_agent_metadata") or {}).get("selected_tool")
                or _safe_extract_tool_name(dep_step.get("executed_input"))
            )
            if dep_tool not in _FILE_WRITE_TOOLS:
                continue
            dep_exec_input = dep_step.get("executed_input")
            candidate_path = _extract_quoted_path_from_executed_input(dep_exec_input)
            if not candidate_path:
                continue
            source_step = dep_step
            source_path = candidate_path
            break

        if not source_step or not source_path:
            return None

        current_path = _extract_quoted_path_from_executed_input(executed_input)
        if current_path == source_path:
            import os as _os
            try:
                from system.security.path_validator import validate_path as _vp
                _base = _os.path.abspath("E:/MutesHand")
                _resolved = _vp(source_path, _base).get("resolved_path", "")
                if not _resolved or not _os.path.exists(_resolved):
                    return None
            except Exception:
                return None

        if _is_append_restore:
            append_content = _extract_quoted_content_from_executed_input(executed_input)
            if append_content is None:
                return None
            corrected_call = f'{current_tool} "{source_path}" "{append_content}"'
        else:
            corrected_call = f'{current_tool} "{source_path}"'
        corrected_result = system_entry(corrected_call)

        restoration_meta = {
            "file_path_restoration_attempted": True,
            "file_path_restoration_source_step": source_step.get("id"),
            "original_executed_input": executed_input,
            "restored_executed_input": corrected_call,
            "original_failure_reason": "file_not_found",
            "restoration_result_status": corrected_result.get("status"),
        }

        return {
            "execution_result": corrected_result,
            "executed_input": corrected_call,
            "metadata": restoration_meta,
        }
    except Exception:
        return None


# === PDIAG-008B4: Empty-file content write restoration helper ===

_WRITE_INTENT_PHRASES = (
    "write", "insert", "add content", "add bullet", "put content",
    "open the file and write", "write content", "write into",
    "write bullet", "add to", "add text",
)


def _attempt_empty_file_write_restoration(step, execution_result, executed_input, workflow):
    """
    Bounded deterministic correction for edit_file empty_old_text when the intent
    is to write content into a newly-created (empty) file.

    Activation conditions (ALL must be true):
      1. execution_result.status == 'failure'
      2. reason == 'empty_old_text'
      3. current tool is edit_file (from executed_input)
      4. step has explicit depends_on (non-empty)
      5. executed_input parses to >= 4 tokens: [edit_file, path, old_text, new_text, ...]
      6. old_text token is empty string
      7. new_text token is non-empty
      8. step has not already had this restoration attempted (_empty_file_write_restoration_attempted)

    Does NOT require purpose-phrase matching (old_text=="" is sufficient signal —
    edit_file with empty old_text is always semantically wrong; write_file is correct).

    Returns:
      dict with 'execution_result', 'executed_input', 'metadata' if correction made
      None if conditions not met

    NEVER bypasses system_entry. NEVER marks failure as success artificially.
    NEVER loops (one attempt maximum). Failure-isolated.
    """
    try:
        if not execution_result or execution_result.get("status") != "failure":
            return None
        if execution_result.get("reason") != "empty_old_text":
            return None

        current_tool = _safe_extract_tool_name(executed_input)
        if current_tool != "edit_file":
            return None

        depends_on = step.get("depends_on") or []
        if not depends_on:
            return None

        if step.get("_empty_file_write_restoration_attempted"):
            return None

        try:
            import shlex as _shlex
            cleaned = (executed_input or "").strip()
            if cleaned.startswith("USE_TOOL:"):
                cleaned = cleaned.split("USE_TOOL:", 1)[1].strip()
            tokens = _shlex.split(cleaned)
        except Exception:
            return None

        if len(tokens) < 4:
            return None

        path_token    = tokens[1]
        old_text_token = tokens[2]
        new_text_token = tokens[3]

        if old_text_token != "":
            return None

        if not new_text_token or not new_text_token.strip():
            return None

        corrected_call = f'write_file "{path_token}" "{new_text_token}"'
        corrected_result = system_entry(corrected_call)

        restoration_meta = {
            "empty_file_write_restoration_attempted": True,
            "original_selected_tool": "edit_file",
            "restored_selected_tool": "write_file",
            "original_executed_input": executed_input,
            "restored_executed_input": corrected_call,
            "original_failure_reason": "empty_old_text",
            "restoration_result_status": corrected_result.get("status"),
        }

        return {
            "execution_result": corrected_result,
            "executed_input": corrected_call,
            "metadata": restoration_meta,
        }
    except Exception:
        return None


def _build_agent_metadata(executed_input):
    """Build advisory-only agent metadata. Failure-isolated and absent-safe."""
    selected_tool = _safe_extract_tool_name(executed_input)
    return {
        "selected_agent": "tool_selection_agent",
        "selected_agent_type": "tool_selection",
        "selected_agent_version": "1.0.0",
        "selected_agent_capabilities": ["select_tool", "route_to_system_entry"],
        "selected_tool": selected_tool,
        "routing_source": "agent_executor",
        "system_entry_routed": True,
        "agent_authority": "advisory_only"
    }


def execute_step(step, workflow, retry_guidance=None, debug_verbose=False, dependency_outputs=None):
    """
    Execute a single step.

    Args:
        step: The step dict with tool_call, input, purpose, etc.
        workflow: The parent workflow dict
        retry_guidance: Optional retry guidance string
        debug_verbose: Debug output flag

    Returns:
        dict with keys:
            - execution_result: The execution result dict
            - validator_output: The validator output dict
            - executed_input: The executed input string
            - last_result: The last result value (for chaining)
            - step_result: The raw step result from execute_agent
    """
    workflow_id = workflow.get("id", "unknown")
    step_id = step.get("id", "unknown")
    retry_count = step.get("retries", 0)

    # === RESOLUTION ORDER FIX (Phase 4B.2.5) ===
    # Per STEP_RESOLUTION_CONTRACT_V1:
    # - Resolution MUST occur before validation
    # - Resolution produces tool_call from purpose
    # Per STEP_SCHEMA_CONTRACT_V1:
    # - Only resolved steps may be validated and executed
    
    # === STEP INPUT PREPARATION ===
    # Agent receives purpose/input to resolve into tool_call
    agent_input = step.get("tool_call") or step.get("purpose") or step.get("input")

    # RUNTIME TRACE: Step entry state
    _structured_log("STEP_ENTRY", workflow_id, step_id, {
        "agent_input": agent_input,
        "step_purpose": step.get("purpose"),
        "step_input": step.get("input"),
        "step_tool_call": step.get("tool_call"),
        "retry_count": retry_count,
        "step_status": step.get("status"),
        "existing_execution_result": step.get("execution_result"),
        "existing_validator_signals": step.get("_validator_signals"),
        "existing_extracted_constraints": step.get("_extracted_constraints")
    })

    # === RUNTIME SAFETY: STATE DIVERGENCE DETECTION ===
    # CRITICAL: Detect if purpose/input changed but tool_call still references stale arguments.
    # This is a SERIOUS BUG - execution artifacts MUST be invalidated when semantic intent changes.
    tool_call = step.get("tool_call")
    purpose = step.get("purpose", "")
    step_input = step.get("input", "")
    if tool_call:
        # Extract numeric arguments from tool_call for comparison
        import re
        tool_args = re.findall(r'\d+', str(tool_call))
        purpose_nums = re.findall(r'\d+', str(purpose))
        input_nums = re.findall(r'\d+', str(step_input))
        
        # If purpose/input specify different numbers than tool_call, ALERT
        if purpose_nums and tool_args:
            if purpose_nums != tool_args:
                pass  # divergence detected but execution proceeds per contract
        elif input_nums and tool_args:
            if input_nums != tool_args:
                pass  # divergence detected but execution proceeds per contract

    if not agent_input:
        return {
            "execution_result": {
                "status": "failure",
                "reason": "missing_tool_call_and_purpose"
            },
            "validator_output": {},
            "executed_input": None,
            "step_result": {
                "status": "failure",
                "result": {
                    "execution_result": {
                        "status": "failure",
                        "reason": "missing_tool_call_and_purpose"
                    }
                }
            }
        }

    # === USER APPROVAL GATE (Phase 1D — Governance-Aligned) ===
    # Governance is the SOLE authority for approval decisions.
    # step_executor ONLY handles the approval interaction when
    # governance has already decided BLOCK with blocked_reason=approval_required.
    # Runtime MUST NOT independently decide approval requirement.
    if step.get("status") == "BLOCKED" and step.get("blocked_reason") == "approval_required":
        from system.orchestrator.user_approval import request_approval
        approved = request_approval(step)

        if not approved:
            return {
                "execution_result": None,
                "validator_output": {},
                "executed_input": None,
                "step_result": None,
                "blocked": True,
                "blocked_reason": "User denied approval"
            }
        # Approved — continue to execution below
        from system.orchestrator.workflow_control import request_step_transition as _rst_se
        _rst_se(step, "ACTIVE", "approval_granted", _internal=True)

    # Phase 1: Use governance-approved retry_guidance if available
    # Check step for governance-approved guidance from escalation_controller
    if retry_guidance is None and step.get("_governance_retry_guidance"):
        retry_guidance = step.get("_governance_retry_guidance")
        _structured_log("RETRY_GUIDANCE_FROM_STEP", workflow_id, step_id, {
            "source": "step._governance_retry_guidance",
            "retry_guidance": retry_guidance
        })

    # === STEP IO: BUILD AGENT CONTEXT FROM DEPENDENCY OUTPUTS ONLY ===
    # Per STEP_IO_CONTRACT_V1 Section 3: agent receives ONLY outputs from
    # declared dependencies. No global state, no implicit access.
    # ISSUE-098KR: Added step_id for external-call user-control enforcement
    _agent_context = {
        "workflow_id": workflow_id,
        "step_id": step_id,
        "purpose": step.get("purpose", ""),
        "user_path_grounding_attempted": step.get("_user_path_grounding_attempted", False),
    }

    if dependency_outputs:
        _agent_context["dependency_outputs"] = dependency_outputs

    # === AGENT-001B: Capability metadata allowed_tool narrowing ===
    # Inject capability-specific tool narrowing BEFORE SAME retry so SAME retry can overwrite.
    _capability_meta = step.get("capability_metadata")
    if _capability_meta and isinstance(_capability_meta, dict):
        _agent_context["capability_metadata"] = _capability_meta
        _cap_allowed = _capability_meta.get("allowed_tool")
        if _cap_allowed:
            _agent_context["allowed_tool"] = _cap_allowed
            _structured_log("CAPABILITY_ALLOWED_TOOL", workflow_id, step_id, {
                "allowed_tool": _cap_allowed,
                "capability_id": _capability_meta.get("capability_id"),
            })

    # === Sprint 7C ISSUE-098A: SAME retry enforcement ===
    if step.get("_same_retry_enforced"):
        _prior_tool = None
        # Preferred order: _agent_metadata, agent_metadata, executed_input, tool_call
        if step.get("_agent_metadata") and step["_agent_metadata"].get("selected_tool"):
            _prior_tool = step["_agent_metadata"]["selected_tool"]
        elif step.get("agent_metadata") and step["agent_metadata"].get("selected_tool"):
            _prior_tool = step["agent_metadata"]["selected_tool"]
        elif step.get("executed_input"):
            _prior_tool = _safe_extract_tool_name(step["executed_input"])
        elif step.get("tool_call"):
            _prior_tool = _safe_extract_tool_name(step["tool_call"])

        if _prior_tool:
            _agent_context["allowed_tool"] = _prior_tool
            _structured_log("SAME_RETRY_ALLOWED_TOOL", workflow_id, step_id, {
                "allowed_tool": _prior_tool,
                "source": "step metadata"
            })
        else:
            _structured_log("SAME_RETRY_MISSING_PRIOR_TOOL", workflow_id, step_id, {
                "reason": "same_retry_missing_prior_tool"
            })
            return {
                "execution_result": {
                    "status": "failure",
                    "reason": "same_retry_missing_prior_tool"
                },
                "validator_output": {},
                "executed_input": None,
                "step_result": {
                    "status": "failure",
                    "result": {
                        "execution_result": {
                            "status": "failure",
                            "reason": "same_retry_missing_prior_tool"
                        }
                    }
                }
            }

    # === ISSUE-095B: Operator-managed advisory memory context (AG1-only) ===
    # Per MEMORY_STORAGE_CONTRACT_V1: memory is advisory only.
    # Per AUTHORITY_MODEL: memory MUST NOT influence execution_result.
    # Reads only from memory_store (operator-managed), NOT global_memory or memory_adapter.
    # Failure-isolated: any error leaves _agent_context unchanged.
    try:
        from system.memory.advisory_bridge import build_advisory_memory_context
        _bridge_result = build_advisory_memory_context(
            project_id=workflow_id,
            max_entries=5,
            min_confidence=0.5,
            categories=("behavior", "preference", "context"),
        )
        if _bridge_result and _bridge_result.get("formatted_text"):
            _agent_context["advisory_memory"] = _bridge_result["formatted_text"]
            # Trace advisory context usage (failure-isolated)
            try:
                from system.orchestrator import trace_collector as _tc
                _tc.record_memory_event(
                    event="MEMORY_CONTEXT_USED",
                    key=None,
                    data=_bridge_result.get("metadata", {}),
                )
            except Exception:
                pass
            # Emit to event bus for UI Events visibility (failure-isolated)
            try:
                from system.interface import event_emitter as _ee
                _ee.emit_event(
                    "MEMORY_CONTEXT_USED",
                    workflow_id,
                    {"step_id": step_id, "metadata": _bridge_result.get("metadata", {})},
                )
            except Exception:
                pass
    except Exception:
        pass

    # === RESOLUTION: AGENT EXECUTES TO PRODUCE tool_call ===
    # Per STEP_RESOLUTION_CONTRACT_V1: Agent resolves purpose → tool_call

    # RUNTIME TRACE: Pre-execution
    _structured_log("PRE_AGENT_EXECUTION", workflow_id, step_id, {
        "agent_input": agent_input,
        "retry_guidance": retry_guidance,
        "dependency_outputs": dependency_outputs
    })

    step_result = execute_agent(
        agent={
            "name": "generic_agent",
            "role": "tool_executor",
            "scope": ["tools"]
        },
        input_data=agent_input,
        retry_guidance=retry_guidance,
        context=_agent_context
    )
    
    # === POST-RESOLUTION: EXTRACT tool_call FROM AGENT RESULT ===
    _result_val = step_result.get("result")
    resolved_tool_call = (
        (_result_val.get("executed_input") if isinstance(_result_val, dict) else None)
        or step_result.get("executed_input")
    )

    # Inject resolved tool_call into step for validation
    if resolved_tool_call:
        step["tool_call"] = resolved_tool_call

    _deterministic_source_grounded = _is_deterministic_source_grounded(step_result, step)

    # === ISSUE-098A: finalize_output error-string defense ===
    # Replaced over-broad intermediate-step guard with targeted defense:
    # error-looking strings wrapped in finalize_output must NOT become success.
    # Legitimate non-error finalize_output (e.g. text summaries) is allowed
    # for ANY step, including intermediate steps with dependents.
    if resolved_tool_call and resolved_tool_call.strip().startswith("finalize_output") and not _deterministic_source_grounded:
        _fo_output = (
            step_result.get("result", {}).get("output", "")
            if isinstance(step_result.get("result"), dict)
            else ""
        )
        if not _fo_output and execution_result and execution_result.get("status") == "success":
            _fo_output = execution_result.get("result", "")
        _fo_output_lower = str(_fo_output).lower()
        _error_indicators = (
            "execution error",
            "tool execution error",
            "execution failed with",
            "execution failed:",
            "division by zero",
            "error:",
            "not allowed",
        )
        if any(ind in _fo_output_lower for ind in _error_indicators):
            _guard_reason = "finalize_output_contains_error"
            _structured_log("FINALIZE_OUTPUT_ERROR_DEFENSE", workflow_id, step_id, {
                "tool_call": resolved_tool_call,
                "reason": _guard_reason,
                "output_preview": str(_fo_output)[:200],
            })
            if isinstance(step_result, dict):
                _sr = step_result.get("result", {}) if isinstance(step_result.get("result"), dict) else {}
                _sr["execution_result"] = {"status": "failure", "reason": _guard_reason}
                _sr["output"] = None
                step_result["result"] = _sr
                step_result["status"] = "failure"
            else:
                step_result = {
                    "status": "failure",
                    "result": {
                        "execution_result": {"status": "failure", "reason": _guard_reason},
                        "output": None,
                    }
                }

    # === ISSUE-073: AG1 ADVISORY METADATA ATTACHMENT ===
    # Per AGENT_GOVERNANCE_CONTRACT_V1: agents are advisory-only semantic infrastructure.
    # Metadata is attached AFTER execute_agent returns and BEFORE governance/trace processing.
    # Metadata MUST NOT influence: retry, completion, failure, escalation, lifecycle,
    # mutation legality, projection truth, execution identity, prompt construction,
    # or tool selection behavior.
    try:
        step["_agent_metadata"] = _build_agent_metadata(resolved_tool_call)
    except Exception:
        # Failure-isolated: metadata attachment failure must not affect execution
        step["_agent_metadata"] = {
            "selected_agent": "tool_selection_agent",
            "selected_agent_type": "tool_selection",
            "selected_agent_version": "1.0.0",
            "selected_agent_capabilities": ["select_tool", "route_to_system_entry"],
            "selected_tool": None,
            "routing_source": "agent_executor",
            "system_entry_routed": True,
            "agent_authority": "advisory_only"
        }

    # === POST-RESOLUTION STEP_SCHEMA VALIDATION ===
    # Per STEP_SCHEMA_CONTRACT_V1: Validate ONLY after resolution
    schema_validation = validate_step_schema(step)
    if schema_validation["status"] == "failure":
        return {
            "execution_result": {
                "status": "failure",
                "reason": f"step_schema_validation_failed:{schema_validation.get('reason')}"
            },
            "validator_output": {},
            "executed_input": resolved_tool_call,
            "step_result": {
                "status": "failure",
                "result": {
                    "execution_result": {
                        "status": "failure",
                        "reason": f"step_schema_validation_failed:{schema_validation.get('reason')}"
                    }
                }
            }
        }

    # === EXECUTION using resolved step ===
    # At this point, step has been resolved and validated
    # tool_call MUST be present per STEP_SCHEMA validation above
    _result_val = step_result.get("result")
    executed_input = (
        (_result_val.get("executed_input") if isinstance(_result_val, dict) else None)
        or step_result.get("executed_input")
    )
    execution_result = step_result.get("result", {}).get("execution_result") if isinstance(step_result.get("result"), dict) else None
    output = step.get("output")

    # If no execution_result and no prior output, synthesize failure for governance
    if execution_result is None:
        if not (output and str(output).strip()):
            execution_result = {"status": "failure", "reason": "no_output"}

    # RUNTIME TRACE: Post-execution
    _structured_log("POST_AGENT_EXECUTION", workflow_id, step_id, {
        "execution_result": execution_result,
        "executed_input": executed_input,
        "output": output,
        "step_result_status": step_result.get("status") if isinstance(step_result, dict) else None
    })

    # === PDIAG-008B8: Pre-dispatch user-path grounding ===
    # Grounding now fires pre-system_entry inside tool_selection_agent.py.
    # Post-dispatch correction is removed to prevent wrong-path side effects.
    # B2/B4/B6 restoration remains as post-failure fallback for dependency-path mismatches.

    # === PDIAG-008B2: Bounded file-path restoration ===
    # When a read_file/list_files/append_file step fails with file_not_found and has an
    # explicit dependency on a completed write_file/edit_file step, attempt exactly ONE
    # deterministic correction using the prior step's exact executed path.
    # All corrected execution still routes through system_entry.
    # No lifecycle, governance, or prompt changes.
    _restoration = _attempt_file_path_restoration(
        step, execution_result, executed_input, dependency_outputs, workflow
    )
    if _restoration is not None:
        _restored_result    = _restoration["execution_result"]
        _restored_input     = _restoration["executed_input"]
        _restoration_meta   = _restoration["metadata"]
        step["_file_path_restoration_attempted"] = True
        _structured_log("FILE_PATH_RESTORATION", workflow_id, step_id, _restoration_meta)
        # Update authoritative values from the corrected system_entry call
        execution_result = _restored_result
        executed_input   = _restored_input
        step["executed_input"] = _restored_input
        step["tool_call"]      = _restored_input
        # Propagate result into step_result so downstream handling is consistent
        if isinstance(step_result, dict) and isinstance(step_result.get("result"), dict):
            step_result["result"]["execution_result"] = _restored_result
            step_result["result"]["executed_input"]   = _restored_input
            if _restored_result.get("status") == "success":
                step_result["result"]["output"] = _restored_result.get("result", "")
                step_result["status"] = "success"

    # === PDIAG-008B4: Bounded empty-file content write restoration ===
    # When edit_file fails with empty_old_text and the step has an explicit dependency,
    # convert to write_file using the exact path and new_text from the failed edit_file call.
    # edit_file contract is NOT changed — this fires after system_entry rejects the call.
    # All corrected execution still routes through system_entry.
    if not step.get("_empty_file_write_restoration_attempted"):
        _d_restoration = _attempt_empty_file_write_restoration(
            step, execution_result, executed_input, workflow
        )
        if _d_restoration is not None:
            _d_result  = _d_restoration["execution_result"]
            _d_input   = _d_restoration["executed_input"]
            _d_meta    = _d_restoration["metadata"]
            step["_empty_file_write_restoration_attempted"] = True
            _structured_log("EMPTY_FILE_WRITE_RESTORATION", workflow_id, step_id, _d_meta)
            execution_result = _d_result
            executed_input   = _d_input
            step["executed_input"] = _d_input
            step["tool_call"]      = _d_input
            if isinstance(step_result, dict) and isinstance(step_result.get("result"), dict):
                step_result["result"]["execution_result"] = _d_result
                step_result["result"]["executed_input"]   = _d_input
                if _d_result.get("status") == "success":
                    step_result["result"]["output"] = _d_result.get("result", "")
                    step_result["status"] = "success"

    # Perform validation if tool was executed (ADVISORY ONLY)
    validator_output = {}

    if executed_input and step_result.get("status") == "success":
        try:
            ei_parts = shlex.split(executed_input)
        except Exception:
            ei_parts = []
        ei_tool = ei_parts[0] if ei_parts else None
        ei_args = ei_parts[1:] if len(ei_parts) > 1 else []
        tool_def = _tool_index.get(ei_tool) if ei_tool else None

        if tool_def is not None:
            expected_inputs = tool_def.get("inputs", {})

            if len(ei_args) != len(expected_inputs):
                validator_output = {"decision": "retry", "reason": "invalid_argument_count"}

            if not validator_output:
                for arg, expected_type in zip(ei_args, expected_inputs.values()):
                    if expected_type == "number":
                        cleaned = arg.lstrip("-")
                        if not cleaned.isdigit():
                            validator_output = {"decision": "retry", "reason": "invalid_argument_type"}
                            break

        if not validator_output:
            _intent_output = step_result.get("result", {}).get("output", "") if isinstance(step_result.get("result"), dict) else ""
            if not _intent_output and execution_result and execution_result.get("status") == "success":
                _intent_output = execution_result.get("result", "")

            try:
                _ei_args_for_intent = shlex.split(executed_input)[1:] if executed_input else []
            except Exception:
                _ei_args_for_intent = []
            _intent_decision = evaluate_intent(
                step.get("input"),
                ei_tool,
                _ei_args_for_intent,
                _intent_output,
                step.get("purpose"),
                execution_result=execution_result,
                executed_input=executed_input,
                semantic_expectation=step.get("semantic_expectation"),
                workflow_id=workflow_id,
                deterministic_synthesis=(_deterministic_source_grounded and execution_result and execution_result.get("status") == "success"),
            )

            if _intent_decision.get("recommendation") == "retry" or _intent_decision.get("decision") == "retry":
                validator_output = _intent_decision

            # RUNTIME TRACE: Validator decision
            _structured_log("VALIDATOR_DECISION", workflow_id, step_id, {
                "validator_recommendation": _intent_decision.get("recommendation"),
                "validator_reason": _intent_decision.get("reason"),
                "validator_signals": _intent_decision.get("signals"),
                "extracted_constraints": _intent_decision.get("meta", {}).get("extracted_constraints"),
                "execution_result_status": execution_result.get("status") if execution_result else None
            })

            # VALIDATOR OUTPUT — ADVISORY ONLY (NO CONTROL IMPACT)
            if validator_output:
                # Store advisory reason
                step["_validator_advisory"] = validator_output.get("reason", "unknown")
                # Store validator decision (for correlation tests)
                step["_validator_decision"] = validator_output.get("recommendation")
                # Store signals if present
                if validator_output.get("signals"):
                    step["_validator_signals"] = validator_output.get("signals")
                # Store extracted_constraints for retry guidance
                meta = validator_output.get("meta", {})
                if meta.get("extracted_constraints"):
                    step["_extracted_constraints"] = meta.get("extracted_constraints")

    # === MEMORY WRITE — Pattern observation (Phase 3B) ===
    # DISABLED per Sprint 6 scope realignment:
    # Automatic learning / preference tracking is deferred.
    # No automatic memory writes from sequential (or parallel) execution
    # as part of ISSUE-078.
    #
    # Per MEMORY_STORAGE_CONTRACT_V1: write ONLY on successful completion
    # Per contract: NO writes on failure, retry, or single occurrence
    # Failure-isolated: MUST NOT affect execution
    #
    # if execution_result and execution_result.get("status") == "success":
    #     try:
    #         from system.memory.preference_tracker import observe_execution
    #         from system.orchestrator import trace_collector as _tc_pref
    #         _tool_name = _safe_extract_tool_name(executed_input)
    #         _step_type = step.get("type")
    #         _memory_written = observe_execution(
    #             tool_name=_tool_name or "",
    #             step_type=_step_type or "",
    #             execution_result=execution_result,
    #             step_purpose=step.get("purpose")
    #         )
    #         _mem_event = "MEMORY_WRITE" if _memory_written else "MEMORY_UPDATE"
    #         _tc_pref.record_memory_event(
    #             event=_mem_event,
    #             key=_memory_written.get("key") if _memory_written else None,
    #             data={"tool": _tool_name, "step_type": _step_type,
    #                   "written": _memory_written is not None}
    #         )
    #     except Exception:
    #         pass

    # === SIGNAL INTERPRETATION (ADVISORY ONLY — NO CONTROL INFLUENCE) ===
    # Stored in step["_signal_analysis"] for trace/debug purposes only.
    # MUST NOT be read by governance, retry logic, or execution.
    try:
        step["_signal_analysis"] = signal_interpreter.interpret_signals(step, execution_result or {})
    except Exception:
        step["_signal_analysis"] = {"status_analysis": "error", "conflicts": [], "issues": [], "confidence": "low", "summary": "signal interpretation failed"}

    # === DRIFT DETECTION (Phase 3B — ADVISORY ONLY) ===
    # Per AUTHORITY_MODEL: execution_result is sole truth
    # Per CONTROL_MODEL: drift signals are advisory, MUST NOT override execution_result
    # Per SYSTEM_GOALS_V2: small drift → auto-correct signal, large drift → user attention signal
    # Stored in step["_drift_signal"] for observability only — zero control impact
    try:
        from system.orchestrator import drift_detector as _dd
        from system.orchestrator import trace_collector as _tc_drift
        _expected = step.get("expected_outcome")
        _sem_exp = step.get("semantic_expectation")
        _drift_signal = _dd.compare(_expected, execution_result, {"step_type": step.get("type")}, semantic_expectation=_sem_exp)
        step["_drift_signal"] = _drift_signal
        # Log drift event to trace (observational only)
        _drift_event = "DRIFT_NONE" if _drift_signal.get("drift_type") == "NONE" else "DRIFT_DETECTED"
        _tc_drift.record_drift_event(
            event=_drift_event,
            step_id=step.get("id"),
            drift_type=_drift_signal.get("drift_type"),
            confidence=_drift_signal.get("confidence"),
            reason=_drift_signal.get("reason"),
            expected=_expected,
            actual=execution_result.get("result") if execution_result else None
        )
    except Exception:
        # Failure-isolated: drift detection failure MUST NOT affect execution
        step["_drift_signal"] = {"drift_detected": False, "drift_type": "NONE", "confidence": 0.0, "reason": "drift detection failed"}

    # === NOTIFICATIONS (Phase 3C — OUTPUT ONLY) ===
    # Per HAND_ARCHITECTURE_V2 Section 14: Notify for approvals, failures, completion
    # Per AUTHORITY_MODEL: Notifications are OUTPUT ONLY — no control authority
    # Per SYSTEM_GOALS_V2 Section 24: Smart filtering (approvals, failures, completion)
    # FAILURE-ISOLATED: Notification failure MUST NOT affect execution
    try:
        from system.interface.notification_manager import notify_step_success, notify_step_failure
        _workflow_id = workflow.get("id", "unknown")
        _step_id = step.get("id", "unknown")
        
        if execution_result and execution_result.get("status") == "success":
            # Step succeeded — notification is advisory output only
            _result_summary = str(execution_result.get("result", ""))[:50]  # Truncate for readability
            notify_step_success(
                step_id=_step_id,
                project_id=_workflow_id,
                result_summary=_result_summary
            )
        elif execution_result and execution_result.get("status") == "failure":
            # Step failed — notification is advisory output only
            _failure_reason = execution_result.get("reason", "unknown failure")
            notify_step_failure(
                step_id=_step_id,
                project_id=_workflow_id,
                reason=_failure_reason
            )
    except Exception:
        # Failure-isolated: notification failure MUST NOT affect execution
        pass

    # Note: LIVE STREAMING events are emitted from parallel_executor.py
    # after governance decision and status update, ensuring correct state.

    # RUNTIME TRACE: Step exit
    _structured_log("STEP_EXIT", workflow_id, step_id, {
        "execution_result": execution_result,
        "validator_output": validator_output,
        "validator_signals": step.get("_validator_signals"),
        "extracted_constraints": step.get("_extracted_constraints"),
        "validator_decision": step.get("_validator_decision"),
        "executed_input": executed_input
    })

    # Prepare return values
    return {
        "execution_result": execution_result,
        "validator_output": validator_output,
        "executed_input": executed_input,
        "last_result": execution_result.get("result") if execution_result and execution_result.get("status") == "success" else None,
        "step_result": step_result
    }
