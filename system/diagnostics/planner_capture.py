"""
Planner Capture — Diagnostic-Only Observability
PDIAG-006-PC1

Rules:
- Opt-in only. Off by default.
- Read-only: never modifies planner behavior.
- Failure-isolated: exceptions are silently absorbed.
- Local diagnostic artifacts only.
- No sensitive data sent externally.
"""

import copy
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class PlannerCaptureContext:
    """
    Context for capturing planner diagnostic data.

    Usage:
        ctx = PlannerCaptureContext(enabled=True)
        workflow = plan_workflow(user_input, capture_context=ctx)
        artifact_path = ctx.write_artifact(output_dir)
    """

    enabled: bool = False
    data: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.enabled:
            return
        self.data = {
            "capture_schema_version": "pc1-1.0",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "prompt_version": None,
        }

    def record_case_id(self, case_id: str):
        if not self.enabled:
            return
        try:
            self.data["case_id"] = case_id
        except Exception:
            pass

    def record_user_input(self, user_input: str):
        if not self.enabled:
            return
        try:
            self.data["user_input"] = user_input
        except Exception:
            pass

    def record_prompt(self, prompt: str):
        if not self.enabled:
            return
        try:
            self.data["prompt_text"] = prompt
            self.data["prompt_length_chars"] = len(prompt)
            self.data["prompt_hash"] = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        except Exception:
            pass

    def record_llm_metadata(
        self,
        provider_name: str = "unknown",
        model: str = "unknown",
        route_reason: str = None,
        duration_ms: float = None,
    ):
        if not self.enabled:
            return
        try:
            self.data["provider"] = provider_name
            self.data["model"] = model
            if route_reason is not None:
                self.data["route_reason"] = route_reason
            if duration_ms is not None:
                self.data["llm_duration_ms"] = duration_ms
        except Exception:
            pass

    def record_raw_llm_response(self, response: str):
        if not self.enabled:
            return
        try:
            max_raw = 100_000
            raw = (
                response
                if len(response) <= max_raw
                else response[:max_raw] + "\n...[TRUNCATED]"
            )
            self.data["raw_llm_response"] = raw
        except Exception:
            pass

    def record_parsed_planner_json(self, parsed: dict):
        if not self.enabled:
            return
        try:
            self.data["parsed_planner_json"] = parsed
        except Exception:
            pass

    def record_planner_native_steps_after_validation(self, steps: list):
        if not self.enabled:
            return
        try:
            self.data["planner_native_steps_after_validation"] = steps
        except Exception:
            pass

    def record_steps_after_resolve_dependencies(self, steps: list):
        if not self.enabled:
            return
        try:
            self.data["steps_after_resolve_dependencies"] = steps
        except Exception:
            pass

    def record_steps_after_synthesis_compiler(self, steps: list):
        if not self.enabled:
            return
        try:
            self.data["steps_after_synthesis_compiler"] = steps
        except Exception:
            pass

    def record_steps_after_resource_compiler(self, steps: list):
        if not self.enabled:
            return
        try:
            self.data["steps_after_resource_compiler"] = steps
        except Exception:
            pass

    def record_compiler_repairs(
        self, before_workflow: dict, after_workflow: dict, phase: str
    ):
        if not self.enabled:
            return
        try:
            repairs = []
            before_steps = {
                s["id"]: s for s in before_workflow.get("steps", []) if s.get("id")
            }
            after_steps = {
                s["id"]: s for s in after_workflow.get("steps", []) if s.get("id")
            }
            for step_id, after_step in after_steps.items():
                before_step = before_steps.get(step_id)
                if before_step:
                    before_deps = set(before_step.get("depends_on", []) or [])
                    after_deps = set(after_step.get("depends_on", []) or [])
                    added = sorted(after_deps - before_deps)
                    if added:
                        repairs.append(
                            {
                                "step_id": step_id,
                                "phase": phase,
                                "dependencies_added": added,
                            }
                        )
            key = f"compiler_repairs_{phase}"
            self.data[key] = repairs
        except Exception:
            pass

    def record_final_workflow(self, workflow: dict):
        if not self.enabled:
            return
        try:
            self.data["final_workflow"] = workflow
        except Exception:
            pass

    def record_validation_result(self, result: dict):
        if not self.enabled:
            return
        try:
            self.data["validation_result"] = result
        except Exception:
            pass

    def record_harness_classification(self, classification: str):
        if not self.enabled:
            return
        try:
            self.data["harness_classification"] = classification
        except Exception:
            pass

    def record_warning(self, message: str):
        if not self.enabled:
            return
        try:
            self.data.setdefault("warnings_errors", []).append(message)
        except Exception:
            pass

    def write_artifact(self, output_dir: Path) -> Optional[Path]:
        if not self.enabled:
            return None
        try:
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            artifact_path = output_dir / "planner_capture.json"
            with open(artifact_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False, default=str)
            return artifact_path
        except Exception:
            return None


def snapshot_workflow_for_capture(workflow: dict) -> dict:
    """
    Return a deep copy of the workflow suitable for before/after diffing.
    Only performs copy when capture is known to be active (caller checks).
    """
    return copy.deepcopy(workflow)
