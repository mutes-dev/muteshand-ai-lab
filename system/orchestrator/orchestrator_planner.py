import uuid

DEBUG_VERBOSE = False

"""
Orchestrator Planner — Phase 2.2 Implementation

PURE PLANNING MODULE — ADVISORY ONLY

Responsibilities:
- Decompose user goals into workflow steps
- Define WHAT needs to be done (not HOW)
- Create structured workflow definitions

Constraints:
- MUST NOT control execution
- MUST NOT integrate into runtime
- MUST NOT call system_entry
- MUST NOT execute tools
- MUST NOT define tool arguments
- PURE FUNCTION ONLY

Architecture:
- Deterministic planning based on classification
- No LLM dependency
- Advisory output only
"""

import copy
import json
import os
import re
from typing import Dict, Any, List
from system.orchestrator.task_classifier import classify_task
from system.orchestrator.llm_registry import get_llm
from system.orchestrator.llm_executor import execute_llm
from system.orchestrator.planner_validation import validate_planner_output
from system.orchestrator.semantic_expectation import derive_semantic_expectation
from system.orchestrator.planner_prompts import build_planner_prompt
from system.interface import event_emitter as _planner_event_emitter


def resolve_dependencies(user_input: str, steps: list) -> list:
    """
    Deterministic dependency resolver.

    Preserves planner-declared dependencies and merges with explicit step references 
    from each step's purpose field.
    Supports: result of step_N, result of step N, output of step_N, output of step N, step_N, step N.
    Normalizes to canonical step IDs (e.g., step_1). Dedupes while preserving first-seen order.
    Rejects self-references, future references, and nonexistent references with structured failure dicts.
    ONLY modifies "depends_on" field. Never changes structure, purpose, or other fields.
    """
    _PATTERN = re.compile(
        r'(?:result\s+of\s+|output\s+of\s+)?\bstep[_\s]?(\d+)\b',
        re.IGNORECASE
    )
    total = len(steps)
    normalized = []

    for i, step in enumerate(steps):
        current_step_index = i + 1
        purpose = step.get("purpose", "")
        
        # Start with existing planner-declared dependencies
        existing_deps = step.get("depends_on", [])
        if not isinstance(existing_deps, list):
            existing_deps = []
        
        # Canonicalize existing dependencies (ensure they're valid step_X format)
        canonical_existing = []
        for dep in existing_deps:
            if isinstance(dep, str) and dep.startswith("step_"):
                try:
                    idx = int(dep.split("_")[1])
                    if 1 <= idx <= total and idx != current_step_index and idx < current_step_index:
                        canonical_existing.append(dep)
                except (ValueError, IndexError):
                    pass
        
        # Extract explicit references from purpose
        seen = set(canonical_existing)  # Start with existing deps to preserve order
        ordered_refs = list(canonical_existing)  # Preserve existing order first

        for match in _PATTERN.finditer(purpose):
            idx = int(match.group(1))
            canonical = f"step_{idx}"

            if idx == current_step_index:
                return {
                    "status": "failure",
                    "reason": "self_dependency",
                    "step_id": canonical,
                    "message": f"Step '{canonical}' references itself"
                }
            if idx > total:
                return {
                    "status": "failure",
                    "reason": "invalid_dependency_reference",
                    "step_id": f"step_{current_step_index}",
                    "message": f"Step 'step_{current_step_index}' references nonexistent step '{canonical}'"
                }
            if idx > current_step_index:
                return {
                    "status": "failure",
                    "reason": "future_dependency_reference",
                    "step_id": f"step_{current_step_index}",
                    "message": f"Step 'step_{current_step_index}' references future step '{canonical}'"
                }

            # Add extracted reference if not already present (preserve existing order)
            if canonical not in seen:
                seen.add(canonical)
                ordered_refs.append(canonical)

        normalized.append({"depends_on": ordered_refs})

    print("[DEBUG_DEPENDENCY_RESOLVER_NORMALIZED]:", normalized)
    return normalized


# Simple ID counter for workflow generation
_workflow_counter = 0


def _generate_workflow_id() -> str:
    """Generate simple unique workflow ID."""
    global _workflow_counter
    _workflow_counter += 1
    return f"wf_{_workflow_counter:04d}"

def _normalize_input(user_input: str) -> str:
    """Normalize input for planning purposes."""
    return user_input.strip() if user_input else ""


def plan_workflow(user_input: str, classification: dict = None, pre_generated_workflow_id: str = None, capture_context=None, prompt_version: str = "v2", profile_name: str = None) -> dict:
    # Operational rollback: PLANNER_PROMPT_VERSION=v1 overrides default
    env_version = os.environ.get("PLANNER_PROMPT_VERSION")
    if env_version:
        prompt_version = env_version
    if DEBUG_VERBOSE:
        print("[DEBUG_PLAN_WORKFLOW_INPUT_RAW]:", user_input)
        if classification:
            print("[DEBUG_CLASSIFICATION]:", classification)

    # Load tool index for context (advisory only)
    # TOOL_PROFILE_GATING_CONTRACT_V1 §5.1: Planner receives scoped tool catalog matching active profile
    tool_context = ""
    try:
        if profile_name and profile_name != "GeneralFallbackProfile":
            from system.orchestrator.profile_catalog import build_scoped_tool_context
            tool_context = build_scoped_tool_context(profile_name)
        else:
            tool_index_path = os.path.join("system", "tool_index", "tools.json")
            with open(tool_index_path, "r") as f:
                tool_index = json.load(f)
            
            tool_lines = []
            for tool_name, tool_data in tool_index.items():
                if not tool_data.get("production", False):
                    continue
                inputs = tool_data.get("inputs", {})
                arg_keys = list(inputs.keys())
                arg_names = []
                for i, arg in enumerate(arg_keys):
                    if inputs[arg] == "string":
                        arg_names.append(f'"{arg}"')
                    else:
                        arg_names.append(f"number{i+1}")
                args = " ".join(arg_names)
                description = tool_data.get("description", "").strip()
                if description:
                    tool_lines.append(f"- {tool_name} {args}\n  use: {description}".strip())
                else:
                    tool_lines.append(f"- {tool_name} {args}".strip())
            tool_context = "\n".join(tool_lines)
    except Exception:
        tool_context = ""

    # Reuse existing LLM client (same pattern as agent_executor)
    provider_result = get_llm("ollama_llm")

    prompt = build_planner_prompt(tool_context, user_input, prompt_version=prompt_version)

    if capture_context:
        capture_context.data["prompt_version"] = prompt_version
        capture_context.record_prompt(prompt)

    llm_output = None
    if DEBUG_VERBOSE:
        print("[DEBUG_PLANNER_FINAL_INPUT_TO_LLM]:", user_input)

    # === PERF036: planner start ===
    _perf036_llm_call_count = 0
    try:
        import time as _p_time, json as _p_json
        from datetime import datetime as _p_dt, timezone as _p_tz
        _perf036_plan_start = _p_time.monotonic()
        print("PERF036_BACKEND " + _p_json.dumps({
            "label": "plan_workflow_start",
            "source_layer": "orchestrator_planner",
            "timestamp_iso": _p_dt.now(_p_tz.utc).isoformat(),
            "pre_generated_workflow_id": pre_generated_workflow_id,
        }))
    except Exception:
        _perf036_plan_start = None

    # === VALIDATION WITH RETRY (MAX 1) ===
    max_attempts = 2
    for attempt in range(max_attempts):
        try:
            # === Sprint 9B: Planner event emission (failure-isolated) ===
            if _planner_event_emitter is not None:
                try:
                    _planner_event_emitter.emit_planning_started(
                        workflow_id=pre_generated_workflow_id,
                        attempt=attempt,
                        prompt_version=prompt_version,
                    )
                except Exception:
                    pass

            if provider_result.get("status") != "success":
                if _planner_event_emitter is not None:
                    try:
                        _planner_event_emitter.emit_planning_failed(
                            workflow_id=pre_generated_workflow_id,
                            reason="planner_provider_unavailable",
                        )
                    except Exception:
                        pass
                return {"status": "failure", "reason": "planner_parse_failure"}

            provider = provider_result["provider"]
            if capture_context:
                capture_context.record_llm_metadata(
                    provider_name=provider.get("name", "unknown"),
                )
            # === PERF036: count and label each LLM call attempt ===
            _perf036_llm_call_count += 1
            _caller_label = "planner" if attempt == 0 else "planner_retry"

            # === Sprint 9D-3: planning LLM started telemetry ===
            _llm_start_ts = None
            try:
                import time as _llm_ts
                _llm_start_ts = _llm_ts.monotonic()
            except Exception:
                pass
            if _planner_event_emitter is not None:
                try:
                    _llm_provider = provider_result.get("provider", {})
                    _planner_event_emitter.emit_planning_llm_started(
                        workflow_id=pre_generated_workflow_id,
                        attempt=attempt,
                        provider=_llm_provider.get("name"),
                        model=_llm_provider.get("model"),
                        prompt_version=prompt_version,
                    )
                except Exception:
                    pass

            llm_result = execute_llm(provider, prompt, _perf_caller=_caller_label, workflow_id=pre_generated_workflow_id)

            # === Sprint 9D-3: planning LLM completed telemetry ===
            if _planner_event_emitter is not None:
                try:
                    _llm_dur = None
                    if _llm_start_ts is not None:
                        try:
                            import time as _llm_ts2
                            _llm_dur = round((_llm_ts2.monotonic() - _llm_start_ts) * 1000, 2)
                        except Exception:
                            pass
                    _resp = llm_result.get("result", "")
                    _planner_event_emitter.emit_planning_llm_completed(
                        workflow_id=pre_generated_workflow_id,
                        attempt=attempt,
                        status=llm_result.get("status"),
                        duration_ms=_llm_dur,
                        response_len=len(_resp) if isinstance(_resp, str) else None,
                    )
                except Exception:
                    pass

            if llm_result.get("status") != "success":
                if attempt == 0:
                    if DEBUG_VERBOSE:
                        print("[DEBUG_PLANNER_RETRY]: LLM failed, retrying...")
                    if _planner_event_emitter is not None:
                        try:
                            _planner_event_emitter.emit_planning_retry(
                                workflow_id=pre_generated_workflow_id,
                                attempt=attempt,
                                reason="llm_call_failed",
                            )
                        except Exception:
                            pass
                    continue
                if _planner_event_emitter is not None:
                    try:
                        _planner_event_emitter.emit_planning_failed(
                            workflow_id=pre_generated_workflow_id,
                            reason="planner_parse_failure",
                        )
                    except Exception:
                        pass
                return {"status": "failure", "reason": "planner_parse_failure"}
            
            response = llm_result.get("result", "")
            llm_output = response

            if capture_context:
                capture_context.record_raw_llm_response(llm_output)

            if DEBUG_VERBOSE:
                print("[DEBUG_PLANNER_RAW_OUTPUT]:", llm_output)
            
            # Safe JSON extraction
            raw = response.strip()
            if raw.startswith("```"):
                raw = raw.strip("`").strip()
                if raw.startswith("json"):
                    raw = raw[4:].strip()

            # Recover flat array: LLM returned [{...}, {...}] instead of {"steps": [...]}
            if raw.startswith("["):
                try:
                    _arr = json.loads(raw)
                    if isinstance(_arr, list) and _arr:
                        if isinstance(_arr[0], dict):
                            # List of objects — wrap directly
                            raw = json.dumps({"steps": _arr})
                        else:
                            # Invalid structure — do NOT attempt to synthesize steps
                            return {"status": "failure", "reason": "planner_invalid_format"}
                except Exception:
                    # Parsing failed — fail explicitly
                    return {"status": "failure", "reason": "planner_parse_failure"}

            if "{" in raw:
                raw = raw[raw.index("{"):]
                last_brace = raw.rfind("}")
                if last_brace != -1:
                    raw = raw[:last_brace + 1]

            parsed = json.loads(raw)

            if capture_context:
                capture_context.record_parsed_planner_json(parsed)

            # STRUCTURE VALIDATION
            is_valid, reason = validate_planner_output(parsed)
            
            if DEBUG_VERBOSE:
                print(f"[DEBUG_PLANNER_VALID]: {is_valid}")
            
            if is_valid:
                # SUCCESS — use this output
                steps = parsed.get("steps")
                break
            else:
                # INVALID — retry once if this is first attempt
                if DEBUG_VERBOSE:
                    print(f"[DEBUG_PLANNER_VALIDATION_FAIL]: {reason}")

                if attempt == 0:
                    if DEBUG_VERBOSE:
                        print("[DEBUG_PLANNER_RETRY]: Retrying due to invalid format...")
                    if _planner_event_emitter is not None:
                        try:
                            _planner_event_emitter.emit_planning_retry(
                                workflow_id=pre_generated_workflow_id,
                                attempt=attempt,
                                reason=f"validation_failed: {reason}",
                            )
                        except Exception:
                            pass
                    continue
                else:
                    # Second attempt also failed
                    if _planner_event_emitter is not None:
                        try:
                            _planner_event_emitter.emit_planning_failed(
                                workflow_id=pre_generated_workflow_id,
                                reason="planner_invalid_format",
                            )
                        except Exception:
                            pass
                    return {"status": "failure", "reason": "planner_invalid_format"}
                    
        except Exception as e:
            if DEBUG_VERBOSE:
                print("[DEBUG_PLANNER_PARSE_FAILURE]:", llm_output if llm_output else "None")
                print("[DEBUG_PLAN_WORKFLOW_PARSE_ERROR]:", str(e))

            if attempt == 0:
                if DEBUG_VERBOSE:
                    print("[DEBUG_PLANNER_RETRY]: Exception, retrying...")
                if _planner_event_emitter is not None:
                    try:
                        _planner_event_emitter.emit_planning_retry(
                            workflow_id=pre_generated_workflow_id,
                            attempt=attempt,
                            reason=f"exception: {str(e)[:100]}",
                        )
                    except Exception:
                        pass
                continue
            if _planner_event_emitter is not None:
                try:
                    _planner_event_emitter.emit_planning_failed(
                        workflow_id=pre_generated_workflow_id,
                        reason="planner_parse_failure",
                    )
                except Exception:
                    pass
            return {"status": "failure", "reason": "planner_parse_failure"}
    else:
        # All attempts exhausted
        if _planner_event_emitter is not None:
            try:
                _planner_event_emitter.emit_planning_failed(
                    workflow_id=pre_generated_workflow_id,
                    reason="planner_invalid_format",
                )
            except Exception:
                pass
        return {"status": "failure", "reason": "planner_invalid_format"}

    # Filter out empty steps and validate structure
    valid_steps = []
    for step in steps:
        if isinstance(step, dict) and step.get("name") and step.get("purpose"):
            valid_steps.append(step)

    if not valid_steps:
        if _planner_event_emitter is not None:
            try:
                _planner_event_emitter.emit_planning_failed(
                    workflow_id=pre_generated_workflow_id,
                    reason="planner_empty_steps",
                )
            except Exception:
                pass
        return {"status": "failure", "reason": "planner_empty_steps"}

    if capture_context:
        capture_context.record_planner_native_steps_after_validation(valid_steps)

    # === DEPENDENCY RESOLUTION (DETERMINISTIC) ===
    # Resolve dependencies using deterministic parser (step_X pattern)
    print("[DEBUG_DEPENDENCY_INPUT]:", json.dumps(valid_steps, indent=2))
    try:
        dependency_data = resolve_dependencies(user_input, valid_steps)
    except Exception as e:
        if _planner_event_emitter is not None:
            try:
                _planner_event_emitter.emit_planning_failed(
                    workflow_id=pre_generated_workflow_id,
                    reason="dependency_resolver_exception",
                )
            except Exception:
                pass
        return {"status": "failure", "reason": "dependency_resolver_exception", "details": str(e)}

    if isinstance(dependency_data, dict) and dependency_data.get("status") == "failure":
        if _planner_event_emitter is not None:
            try:
                _planner_event_emitter.emit_planning_failed(
                    workflow_id=pre_generated_workflow_id,
                    reason=dependency_data.get("reason", "dependency_resolution_failed"),
                )
            except Exception:
                pass
        return dependency_data

    # === Sprint 9D-3: dependency resolution telemetry ===
    if _planner_event_emitter is not None:
        try:
            _dep_count = sum(len(d.get("depends_on", [])) for d in dependency_data if isinstance(d, dict))
            _planner_event_emitter.emit_planning_dependencies_resolved(
                workflow_id=pre_generated_workflow_id,
                step_count=len(valid_steps),
                dependency_count=_dep_count,
            )
        except Exception:
            pass

    # === FIELD IMMUTABILITY ENFORCEMENT ===
    # ONLY copy "depends_on" from resolver, nothing else
    for i, step in enumerate(valid_steps):
        if i < len(dependency_data):
            step["depends_on"] = dependency_data[i].get("depends_on", [])
        else:
            step["depends_on"] = []

    # Add id to each step and enforce STEP_SCHEMA_CONTRACT_V1 required fields
    # NOTE: Planner does NOT set tool_call — that is the agent layer's responsibility.
    # (ARCHITECTURE_V2: Agent = tool selection; Planner = advisory/intent only)
    structured_steps = []
    for i, step in enumerate(valid_steps):
        # === SEMANTIC EXPECTATION DERIVATION (SEMANTIC_EXPECTATION_MODEL_CONTRACT_V1) ===
        # Deterministic derivation from existing planner signals only.
        # NO new LLM calls. NO embeddings. NO probabilistic logic.
        # Per contract §5: planner owns semantic expectation authority.
        # Null = no semantic basis (valid — not an error).
        _sem_exp = derive_semantic_expectation(
            agent=step.get("agent"),
            purpose=step.get("purpose"),
            classification=None,
        )
        structured_step = {
            "id": f"step_{i + 1}",
            "type": step.get("type", "EXECUTE_API"),
            "name": step["name"],
            "purpose": step["purpose"],
            "expected_outcome": step.get("expected_outcome", "Execution completed"),
            "risk": step.get("risk", "LOW"),
            "importance": step.get("importance", "MEDIUM"),
            "resource_targets": step.get("resource_targets", []),
            "agent": step["agent"],
            "estimated_complexity": step["estimated_complexity"],
            "depends_on": step.get("depends_on", []),
            "semantic_expectation": _sem_exp,
        }
        structured_steps.append(structured_step)

    if capture_context:
        capture_context.record_steps_after_resolve_dependencies(structured_steps)

    # === DEPENDENCY PASS-THROUGH (DEPENDENCY_MODEL_CONTRACT_V1) ===
    # Per contract: Runtime MUST NOT infer dependencies from purpose or natural language.
    # depends_on from the planner/resolver is explicit-only.
    # Narrow deterministic pre-runtime repair is performed by the Planning Compiler
    # (PLANNING_COMPILER_CONTRACT_V1 §3, §47) before validation.
    for s in structured_steps:
        if "depends_on" not in s:
            s["depends_on"] = []

    workflow = {
        "id": pre_generated_workflow_id or f"workflow_{uuid.uuid4().hex[:8]}",
        "name": "dynamic_workflow",
        "status": "QUEUED",
        "goal": user_input,
        "steps": structured_steps,
        "approval_required": False,
        "profile_name": profile_name or "GeneralFallbackProfile",
    }

    # === PLANNING COMPILER: Apply all deterministic passes via shared helper ===
    # Per AGENT-001B-FIX1: Compiler pass order centralized in compile_candidate_workflow.
    # Planner path and capability path use identical compiler behavior.
    from system.orchestrator.planning_compiler import compile_candidate_workflow
    workflow = compile_candidate_workflow(workflow, user_input=user_input, capture_context=capture_context)

    # DEBUG: Show full planner output
    print("[DEBUG_PLANNER_OUTPUT]:", workflow)

    # === Sprint 9B: Planning completed event (failure-isolated) ===
    if _planner_event_emitter is not None:
        try:
            _planner_event_emitter.emit_planning_completed(
                workflow_id=pre_generated_workflow_id,
                step_count=len(structured_steps),
                prompt_version=prompt_version,
            )
        except Exception:
            pass

    # === PERF036: planner end ===
    try:
        if _perf036_plan_start is not None:
            import time as _p_time_end, json as _p_json_end
            from datetime import datetime as _p_dt_end, timezone as _p_tz_end
            _plan_dur = round((_p_time_end.monotonic() - _perf036_plan_start) * 1000, 2)
            print("PERF036_BACKEND " + _p_json_end.dumps({
                "label": "plan_workflow_end",
                "source_layer": "orchestrator_planner",
                "timestamp_iso": _p_dt_end.now(_p_tz_end.utc).isoformat(),
                "duration_ms": _plan_dur,
                "llm_call_count": _perf036_llm_call_count,
                "step_count": len(structured_steps),
                "workflow_id": workflow.get("id"),
            }))
    except Exception:
        pass

    return {
        "status": "success",
        "workflow": workflow
    }


# Test runner for development/verification
if __name__ == "__main__":
    import json
    
    test_cases = [
        "add 2 + 2",
        "build a website",
        "delete files"
    ]
    
    print("=" * 60)
    print("ORCHESTRATOR PLANNER — TEST OUTPUTS")
    print("=" * 60)
    
    for test_input in test_cases:
        result = plan_workflow(test_input)
        print(f"\nInput: \"{test_input}\"")
        print(f"Output: {json.dumps(result, indent=2)}")
    
    print("\n" + "=" * 60)
    print("VERIFICATION COMPLETE")
    print("=" * 60)
