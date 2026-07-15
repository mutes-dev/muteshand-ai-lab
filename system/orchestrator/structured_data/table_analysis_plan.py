"""TableAnalysisPlanV1 — F5R bounded operation-sequence model.

Per STRUCTURED_DATA_ANALYSIS_CONTRACT_V1 sections 22-24 and SA verdict
TABLE_ANALYSIS_PLAN_V1_APPROVED_WITH_CONDITIONS.

This module is ADDITIVE METADATA ONLY.
- tool_call remains a string throughout the runtime path.
- This plan is stored in step capability_metadata.
- It does NOT replace the planning compiler, workflow validator, or system_entry.
- It does NOT own lifecycle, governance, or execution authority.
- It IS the structured-data domain model owned by StructuredDataAnalysisCapability.

Supported operation types for this package:
  overview, count_rows, max, min, sum, average,
  associated_row (for max/min), filter, sort (single column, single direction).

Bounds (conservative; all explicit constants):
  MAX_OPERATIONS = 8
  MAX_PREDICATES = 6
  MAX_SORT_OPERATIONS = 1
  MAX_ROWS_SCANNED = 10000  (matches analyze_table.MAX_DATA_ROWS)
  MAX_ROWS_RETURNED = 1000  (matches analyze_table.MAX_FILTER_RESULT_ROWS)
"""

from __future__ import annotations

from typing import Any

# ── Explicit bound constants ──────────────────────────────────────────────────

MAX_OPERATIONS = 8
MAX_PREDICATES = 6
MAX_SORT_OPERATIONS = 1
MAX_ROWS_SCANNED = 10000
MAX_ROWS_RETURNED = 1000

PLAN_VERSION = "TableAnalysisPlanV1"

# ── Supported operation types ─────────────────────────────────────────────────

SUPPORTED_OPERATION_TYPES = frozenset([
    "overview",
    "count_rows",
    "max",
    "min",
    "sum",
    "average",
    "associated_row",
    "filter",
    "sort",
])

# ── Trust class values ────────────────────────────────────────────────────────

TRUST_CLASS_VERIFIED = "verified"
TRUST_CLASS_ADVISORY = "advisory"
TRUST_CLASS_UNSUPPORTED = "unsupported"
TRUST_CLASS_AMBIGUOUS = "ambiguous"

TRUST_CLASS_VALUES = frozenset([
    TRUST_CLASS_VERIFIED,
    TRUST_CLASS_ADVISORY,
    TRUST_CLASS_UNSUPPORTED,
    TRUST_CLASS_AMBIGUOUS,
])

# ── Plan validation ───────────────────────────────────────────────────────────

def validate_plan(plan: dict) -> dict:
    """Validate a TableAnalysisPlanV1 dict.

    Returns {"status": "success"} or {"status": "failure", "reason": str,
    "field": str|None}.

    Does NOT execute any operations. Does NOT access the filesystem.
    Does NOT own lifecycle authority.
    """
    if not isinstance(plan, dict):
        return {"status": "failure", "reason": "plan_not_dict", "field": None}

    if plan.get("version") != PLAN_VERSION:
        return {"status": "failure", "reason": "wrong_plan_version",
                "field": "version"}

    # source
    source = plan.get("source")
    if not isinstance(source, dict):
        return {"status": "failure", "reason": "missing_source", "field": "source"}
    if not isinstance(source.get("path"), str) or not source["path"].strip():
        return {"status": "failure", "reason": "missing_source_path",
                "field": "source.path"}

    # operations
    operations = plan.get("operations")
    if not isinstance(operations, list) or len(operations) == 0:
        return {"status": "failure", "reason": "operations_empty",
                "field": "operations"}

    if len(operations) > MAX_OPERATIONS:
        return {"status": "failure",
                "reason": f"operations_exceed_max_{MAX_OPERATIONS}",
                "field": "operations"}

    op_ids_seen = set()
    predicate_count = 0
    sort_count = 0

    for i, op in enumerate(operations):
        if not isinstance(op, dict):
            return {"status": "failure", "reason": f"operation_{i}_not_dict",
                    "field": f"operations[{i}]"}

        op_id = op.get("operation_id")
        if not isinstance(op_id, str) or not op_id.strip():
            return {"status": "failure",
                    "reason": f"operation_{i}_missing_operation_id",
                    "field": f"operations[{i}].operation_id"}
        if op_id in op_ids_seen:
            return {"status": "failure",
                    "reason": f"duplicate_operation_id:{op_id}",
                    "field": f"operations[{i}].operation_id"}
        op_ids_seen.add(op_id)

        op_type = op.get("type")
        if op_type not in SUPPORTED_OPERATION_TYPES:
            return {"status": "failure",
                    "reason": f"unsupported_operation_type:{op_type}",
                    "field": f"operations[{i}].type"}

        if op_type == "filter":
            predicate_count += 1

        if op_type == "sort":
            sort_count += 1
            if sort_count > MAX_SORT_OPERATIONS:
                return {"status": "failure",
                        "reason": f"sort_operations_exceed_max_{MAX_SORT_OPERATIONS}",
                        "field": f"operations[{i}].type"}
            direction = op.get("direction", "").lower()
            if direction not in ("asc", "desc", "ascending", "descending"):
                return {"status": "failure",
                        "reason": "sort_direction_invalid",
                        "field": f"operations[{i}].direction"}
            if not isinstance(op.get("column"), str) or not op["column"].strip():
                return {"status": "failure",
                        "reason": "sort_missing_column",
                        "field": f"operations[{i}].column"}

    if predicate_count > MAX_PREDICATES:
        return {"status": "failure",
                "reason": f"predicates_exceed_max_{MAX_PREDICATES}",
                "field": "operations"}

    # requested_operations
    req_ops = plan.get("requested_operations")
    if not isinstance(req_ops, list) or len(req_ops) == 0:
        return {"status": "failure", "reason": "requested_operations_empty",
                "field": "requested_operations"}

    for r in req_ops:
        if r not in op_ids_seen:
            return {"status": "failure",
                    "reason": f"requested_operation_not_in_operations:{r}",
                    "field": "requested_operations"}

    # result_operation
    result_op = plan.get("result_operation")
    if not isinstance(result_op, str) or result_op not in op_ids_seen:
        return {"status": "failure",
                "reason": "result_operation_not_in_operations",
                "field": "result_operation"}

    # bounds
    bounds = plan.get("bounds")
    if not isinstance(bounds, dict):
        return {"status": "failure", "reason": "missing_bounds", "field": "bounds"}

    for bound_key in ("max_operations", "max_predicates",
                      "max_rows_scanned", "max_rows_returned"):
        if not isinstance(bounds.get(bound_key), int):
            return {"status": "failure",
                    "reason": f"missing_bound:{bound_key}",
                    "field": f"bounds.{bound_key}"}

    return {"status": "success"}


# ── Coverage validation ───────────────────────────────────────────────────────

def validate_coverage(
    plan: dict,
    executed_operation_ids: list[str],
) -> dict:
    """Check that every requested operation was executed and none were omitted.

    Returns a dict with keys:
      requested_operations, executed_operations, omitted_operations,
      operation_coverage_complete, result_complete, status, reason (on failure).

    Does NOT produce verified/advisory labels — those are trust_class decisions
    made by the result emitter, not this validator.
    """
    requested = plan.get("requested_operations", [])
    executed_set = set(executed_operation_ids)
    omitted = [op_id for op_id in requested if op_id not in executed_set]
    complete = len(omitted) == 0

    return {
        "requested_operations": list(requested),
        "executed_operations": list(executed_operation_ids),
        "omitted_operations": omitted,
        "operation_coverage_complete": complete,
        "result_complete": complete,
        "status": "success" if complete else "partial",
        "reason": None if complete else f"omitted_operations:{','.join(omitted)}",
    }


# ── Plan builder helpers ──────────────────────────────────────────────────────

def build_single_op_plan(
    source_path: str,
    operation_type: str,
    operation_id: str = "op_1",
    column: str | None = None,
    associated_column: str | None = None,
    filter_op: str | None = None,
    filter_value: str | None = None,
    filter_value_to: str | None = None,
    sort_direction: str | None = None,
    sheet: str | None = None,
) -> dict:
    """Build a single-operation TableAnalysisPlanV1.

    Used by the deterministic fast paths (overview, count_rows, max, min, sum,
    average, single filter, associated_row).
    """
    op: dict[str, Any] = {
        "operation_id": operation_id,
        "type": operation_type,
    }
    if column:
        op["column"] = column
    if associated_column:
        op["associated_column"] = associated_column
    if filter_op:
        op["filter_op"] = filter_op
    if filter_value is not None:
        op["filter_value"] = filter_value
    if filter_value_to is not None:
        op["filter_value_to"] = filter_value_to
    if sort_direction:
        op["direction"] = sort_direction.lower()

    return {
        "version": PLAN_VERSION,
        "source": {
            "path": source_path,
            "sheet": sheet,
        },
        "operations": [op],
        "requested_operations": [operation_id],
        "result_operation": operation_id,
        "bounds": {
            "max_operations": MAX_OPERATIONS,
            "max_predicates": MAX_PREDICATES,
            "max_rows_scanned": MAX_ROWS_SCANNED,
            "max_rows_returned": MAX_ROWS_RETURNED,
        },
    }


def build_multi_filter_sort_plan(
    source_path: str,
    filters: list[dict],
    sort_column: str | None = None,
    sort_direction: str | None = None,
    sheet: str | None = None,
) -> dict:
    """Build a multi-filter + optional sort TableAnalysisPlanV1.

    filters: list of dicts with keys column, filter_op, filter_value,
             filter_value_to (optional).
    All filters are AND semantics.
    """
    operations = []
    requested_ops = []

    for i, f in enumerate(filters):
        op_id = f"op_filter_{i + 1}"
        op: dict[str, Any] = {
            "operation_id": op_id,
            "type": "filter",
            "column": f["column"],
            "filter_op": f["filter_op"],
            "filter_value": f.get("filter_value", ""),
            "filter_value_to": f.get("filter_value_to", ""),
        }
        operations.append(op)
        requested_ops.append(op_id)

    result_op = requested_ops[-1] if requested_ops else "op_filter_1"

    if sort_column:
        sort_op_id = "op_sort_1"
        direction = (sort_direction or "asc").lower()
        if direction in ("ascending",):
            direction = "asc"
        if direction in ("descending",):
            direction = "desc"
        operations.append({
            "operation_id": sort_op_id,
            "type": "sort",
            "column": sort_column,
            "direction": direction,
        })
        requested_ops.append(sort_op_id)
        result_op = sort_op_id

    return {
        "version": PLAN_VERSION,
        "source": {
            "path": source_path,
            "sheet": sheet,
        },
        "operations": operations,
        "requested_operations": requested_ops,
        "result_operation": result_op,
        "bounds": {
            "max_operations": MAX_OPERATIONS,
            "max_predicates": MAX_PREDICATES,
            "max_rows_scanned": MAX_ROWS_SCANNED,
            "max_rows_returned": MAX_ROWS_RETURNED,
        },
    }


# ── Trust metadata emitters ───────────────────────────────────────────────────

def build_verified_trust_metadata(
    plan: dict,
    executed_operation_ids: list[str],
    evidence_refs: list | None = None,
    result_complete: bool = True,
    limitations: list | None = None,
    warnings: list | None = None,
) -> dict:
    """Build trust metadata for a fully deterministic verified result.

    trust_class=verified requires:
    - all requested operations executed (omitted_operations empty)
    - operation_coverage_complete=True
    - result_complete=True unless bounded truncation requires honest distinction
    """
    coverage = validate_coverage(plan, executed_operation_ids)
    return {
        "trust_class": TRUST_CLASS_VERIFIED,
        "verification_status": "verified",
        "plan_version": plan.get("version", PLAN_VERSION),
        "plan_source_path": plan.get("source", {}).get("path"),
        "requested_operations": coverage["requested_operations"],
        "executed_operations": coverage["executed_operations"],
        "omitted_operations": coverage["omitted_operations"],
        "operation_coverage_complete": coverage["operation_coverage_complete"],
        "result_complete": result_complete,
        "evidence_refs": evidence_refs or [],
        "source_context_refs": [],
        "context_scope": "deterministic_full_scan",
        "context_complete": True,
        "advisory_disclaimer": None,
        "unsupported_reason": None,
        "ambiguity_reason": None,
        "clarification_needed": False,
        "limitations": limitations or [],
        "warnings": warnings or [],
        "learning_eligible": False,
        "operator_acceptance_status": "unreviewed",
    }


def build_unsupported_trust_metadata(
    unsupported_reason: str,
    requested_operations: list[str] | None = None,
    executed_operations: list[str] | None = None,
    omitted_operations: list[str] | None = None,
    limitations: list | None = None,
    warnings: list | None = None,
) -> dict:
    """Build trust metadata for a controlled unsupported outcome."""
    req = requested_operations or []
    exe = executed_operations or []
    omit = omitted_operations or [o for o in req if o not in exe]
    coverage_complete = len(omit) == 0
    return {
        "trust_class": TRUST_CLASS_UNSUPPORTED,
        "verification_status": "not_applicable",
        "plan_version": PLAN_VERSION,
        "plan_source_path": None,
        "requested_operations": req,
        "executed_operations": exe,
        "omitted_operations": omit,
        "operation_coverage_complete": coverage_complete,
        "result_complete": True,
        "evidence_refs": [],
        "source_context_refs": [],
        "context_scope": None,
        "context_complete": None,
        "advisory_disclaimer": None,
        "unsupported_reason": unsupported_reason,
        "ambiguity_reason": None,
        "clarification_needed": False,
        "limitations": limitations or [],
        "warnings": warnings or [],
        "learning_eligible": False,
        "operator_acceptance_status": "unreviewed",
    }


def build_ambiguous_trust_metadata(
    ambiguity_reason: str,
    clarification_needed: bool = True,
    requested_operations: list[str] | None = None,
    limitations: list | None = None,
    warnings: list | None = None,
) -> dict:
    """Build trust metadata for an ambiguous outcome (cannot proceed without clarification)."""
    return {
        "trust_class": TRUST_CLASS_AMBIGUOUS,
        "verification_status": "not_applicable",
        "plan_version": PLAN_VERSION,
        "plan_source_path": None,
        "requested_operations": requested_operations or [],
        "executed_operations": [],
        "omitted_operations": requested_operations or [],
        "operation_coverage_complete": False,
        "result_complete": False,
        "evidence_refs": [],
        "source_context_refs": [],
        "context_scope": None,
        "context_complete": None,
        "advisory_disclaimer": None,
        "unsupported_reason": None,
        "ambiguity_reason": ambiguity_reason,
        "clarification_needed": clarification_needed,
        "limitations": limitations or [],
        "warnings": warnings or [],
        "learning_eligible": False,
        "operator_acceptance_status": "unreviewed",
    }
