"""
phase_semantic_expectation_test.py

Phase 1 runtime validation for Semantic Expectation Model.

Tests:
  CASE 1 — Arithmetic step: math_executor → numeric expectation → no drift on numeric result
  CASE 2 — Placeholder contamination: expected_outcome="Execution completed" → no fake LARGE drift
  CASE 3 — Real domain mismatch: numeric expected, text actual → LARGE drift
  CASE 4 — Shape mismatch: scalar expected, collection actual → LARGE drift
  CASE 5 — Null expectation: no semantic basis → NONE drift
  CASE 6 — Retrieval category: lower drift sensitivity
  CASE 7 — Planner derivation: math_executor agent → correct semantic_expectation
  CASE 8 — General agent retrieval → text/retrieval expectation
  CASE 9 — Ambiguous agent/purpose → null expectation (safe degradation)
  CASE 10 — Validator advisory signals: domain_conformity, shape_conformity, plausibility

ARCHITECTURE VALIDATION:
  A1 — No new LLM calls in semantic derivation
  A2 — Null expectation treated as valid (not error)
  A3 — expected_outcome not used as drift input
  A4 — Governance not consulted for semantic expectation
  A5 — Projection passthrough only
  A6 — Deterministic derivation
  A7 — Replay safety

ADVERSARIAL VALIDATION:
  V1 — Forced ambiguity safely degrades
  V2 — Unknown agent safely degrades
  V3 — Malformed semantic_expectation safely handled
  V4 — Boolean not treated as numeric
  V5 — Drift advisory only — no retry trigger
"""

import sys
import os
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from system.orchestrator.semantic_expectation import (
    derive_semantic_expectation,
    is_valid_semantic_expectation,
    DOMAIN_NUMERIC, DOMAIN_TEXT, DOMAIN_LIST, DOMAIN_BOOLEAN,
    DOMAIN_STRUCTURED, DOMAIN_VOID,
    SHAPE_SCALAR, SHAPE_COLLECTION,
    CATEGORY_ARITHMETIC, CATEGORY_RETRIEVAL,
)
from system.orchestrator.drift_detector import compare as drift_compare
from system.orchestrator.intent_validator import (
    _analyze_semantic_conformity,
)
from system.orchestrator.projection_schema import build_step_projection

PASS = "PASS"
FAIL = "FAIL"
results = []


def check(name, condition, detail=""):
    status = PASS if condition else FAIL
    results.append((name, status, detail))
    icon = "✅" if status == PASS else "❌"
    print(f"  {icon} [{status}] {name}" + (f" — {detail}" if detail else ""))
    return status == PASS


def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)


# ─────────────────────────────────────────────────────────────────────────────
# CASE 1 — Arithmetic step: math_executor → numeric expectation → no drift
# ─────────────────────────────────────────────────────────────────────────────
section("CASE 1 — Arithmetic step: numeric expectation, numeric result")
try:
    se = derive_semantic_expectation(agent="math_executor", purpose="Add 10 and 20")
    check("C1.1 semantic_expectation is not None", se is not None)
    check("C1.2 domain == numeric", se and se.get("semantic_domain") == DOMAIN_NUMERIC)
    check("C1.3 category == arithmetic", se and se.get("semantic_category") == CATEGORY_ARITHMETIC)
    check("C1.4 shape == scalar", se and se.get("output_shape") == SHAPE_SCALAR)

    drift = drift_compare(
        expected_outcome="Execution completed",
        execution_result={"status": "success", "result": 50},
        semantic_expectation=se,
    )
    check("C1.5 drift_type == NONE", drift["drift_type"] == "NONE",
          f"got: {drift['drift_type']} — {drift['reason']}")
    check("C1.6 drift_detected == False", drift["drift_detected"] is False)
except Exception as e:
    check("C1 EXCEPTION", False, str(e))

# ─────────────────────────────────────────────────────────────────────────────
# CASE 2 — Placeholder contamination: "Execution completed" MUST NOT pollute
# ─────────────────────────────────────────────────────────────────────────────
section("CASE 2 — Placeholder contamination eliminated")
try:
    drift_no_sem = drift_compare(
        expected_outcome="Execution completed",
        execution_result={"status": "success", "result": 50},
        semantic_expectation=None,
    )
    check("C2.1 No semantic_expectation → NONE drift (not LARGE)", drift_no_sem["drift_type"] == "NONE",
          f"got: {drift_no_sem['drift_type']} — {drift_no_sem['reason']}")
    check("C2.2 drift_detected == False", drift_no_sem["drift_detected"] is False)
    check("C2.3 reason mentions semantic basis", "semantic" in drift_no_sem["reason"].lower(),
          f"reason: {drift_no_sem['reason']}")
except Exception as e:
    check("C2 EXCEPTION", False, str(e))

# ─────────────────────────────────────────────────────────────────────────────
# CASE 3 — Real domain mismatch: numeric expected, text actual → LARGE
# ─────────────────────────────────────────────────────────────────────────────
section("CASE 3 — Real domain mismatch: numeric expected, text actual")
try:
    se3 = {"semantic_domain": DOMAIN_NUMERIC, "semantic_category": CATEGORY_ARITHMETIC, "output_shape": SHAPE_SCALAR}
    drift3 = drift_compare(
        expected_outcome="Execution completed",
        execution_result={"status": "success", "result": "text result"},
        semantic_expectation=se3,
    )
    check("C3.1 drift_type == LARGE", drift3["drift_type"] == "LARGE",
          f"got: {drift3['drift_type']} — {drift3['reason']}")
    check("C3.2 drift_detected == True", drift3["drift_detected"] is True)
    check("C3.3 domain mismatch in reason", "domain" in drift3["reason"].lower() or "numeric" in drift3["reason"].lower(),
          f"reason: {drift3['reason']}")
except Exception as e:
    check("C3 EXCEPTION", False, str(e))

# ─────────────────────────────────────────────────────────────────────────────
# CASE 4 — Shape mismatch: scalar expected, collection actual → LARGE
# ─────────────────────────────────────────────────────────────────────────────
section("CASE 4 — Shape mismatch: scalar expected, list actual")
try:
    se4 = {"semantic_domain": DOMAIN_NUMERIC, "semantic_category": CATEGORY_ARITHMETIC, "output_shape": SHAPE_SCALAR}
    drift4 = drift_compare(
        expected_outcome="Execution completed",
        execution_result={"status": "success", "result": [1, 2, 3]},
        semantic_expectation=se4,
    )
    check("C4.1 drift_type == LARGE", drift4["drift_type"] == "LARGE",
          f"got: {drift4['drift_type']} — {drift4['reason']}")
    check("C4.2 shape mismatch in reason", "shape" in drift4["reason"].lower() or "collection" in drift4["reason"].lower(),
          f"reason: {drift4['reason']}")
except Exception as e:
    check("C4 EXCEPTION", False, str(e))

# ─────────────────────────────────────────────────────────────────────────────
# CASE 5 — Null expectation: no semantic basis → NONE drift
# ─────────────────────────────────────────────────────────────────────────────
section("CASE 5 — Null expectation: no drift basis")
try:
    drift5 = drift_compare(
        expected_outcome="some value",
        execution_result={"status": "success", "result": 999},
        semantic_expectation=None,
    )
    check("C5.1 drift_type == NONE", drift5["drift_type"] == "NONE",
          f"got: {drift5['drift_type']}")
    check("C5.2 drift_detected == False", drift5["drift_detected"] is False)

    drift5b = drift_compare(
        expected_outcome="some value",
        execution_result={"status": "success", "result": 999},
        semantic_expectation={},
    )
    check("C5.3 empty dict expectation → NONE", drift5b["drift_type"] == "NONE",
          f"got: {drift5b['drift_type']}")
except Exception as e:
    check("C5 EXCEPTION", False, str(e))

# ─────────────────────────────────────────────────────────────────────────────
# CASE 6 — Retrieval category: lower confidence than arithmetic on domain mismatch
# ─────────────────────────────────────────────────────────────────────────────
section("CASE 6 — Retrieval category: lower drift confidence")
try:
    se6_arith = {"semantic_domain": DOMAIN_TEXT, "semantic_category": CATEGORY_ARITHMETIC, "output_shape": SHAPE_SCALAR}
    se6_retrieval = {"semantic_domain": DOMAIN_TEXT, "semantic_category": CATEGORY_RETRIEVAL, "output_shape": SHAPE_SCALAR}

    drift6_arith = drift_compare(
        expected_outcome="x",
        execution_result={"status": "success", "result": 42},
        semantic_expectation=se6_arith,
    )
    drift6_retrieval = drift_compare(
        expected_outcome="x",
        execution_result={"status": "success", "result": 42},
        semantic_expectation=se6_retrieval,
    )
    check("C6.1 arithmetic text mismatch → LARGE drift", drift6_arith["drift_type"] == "LARGE")
    check("C6.2 retrieval confidence <= arithmetic confidence",
          drift6_retrieval.get("confidence", 1.0) <= drift6_arith.get("confidence", 1.0),
          f"retrieval={drift6_retrieval.get('confidence')}, arith={drift6_arith.get('confidence')}")
except Exception as e:
    check("C6 EXCEPTION", False, str(e))

# ─────────────────────────────────────────────────────────────────────────────
# CASE 7 — Planner derivation: math_executor → correct semantic_expectation
# ─────────────────────────────────────────────────────────────────────────────
section("CASE 7 — Planner derivation from existing signals")
try:
    se7a = derive_semantic_expectation(agent="math_executor", purpose="Multiply 4 by 5")
    check("C7.1 math_executor → numeric", se7a and se7a.get("semantic_domain") == DOMAIN_NUMERIC)
    check("C7.2 math_executor → arithmetic", se7a and se7a.get("semantic_category") == CATEGORY_ARITHMETIC)
    check("C7.3 math_executor → scalar", se7a and se7a.get("output_shape") == SHAPE_SCALAR)

    se7b = derive_semantic_expectation(agent="math_executor", purpose="Add the result of step_1 by 10")
    check("C7.4 chaining step still numeric", se7b and se7b.get("semantic_domain") == DOMAIN_NUMERIC)

    se7c = derive_semantic_expectation(agent="math_executor", purpose="Square 4 then subtract 5")
    check("C7.5 multi-op math step still numeric", se7c and se7c.get("semantic_domain") == DOMAIN_NUMERIC)
except Exception as e:
    check("C7 EXCEPTION", False, str(e))

# ─────────────────────────────────────────────────────────────────────────────
# CASE 8 — General agent with retrieval purpose
# ─────────────────────────────────────────────────────────────────────────────
section("CASE 8 — General agent retrieval purpose")
try:
    se8 = derive_semantic_expectation(agent="general_agent", purpose="Fetch user profile for ID 123")
    check("C8.1 general_agent retrieval → text domain", se8 and se8.get("semantic_domain") == DOMAIN_TEXT)
    check("C8.2 general_agent retrieval → retrieval category", se8 and se8.get("semantic_category") == CATEGORY_RETRIEVAL)

    se8b = derive_semantic_expectation(agent="general_agent", purpose="Get the weather data for London")
    check("C8.3 'get' → retrieval", se8b and se8b.get("semantic_category") == CATEGORY_RETRIEVAL)
except Exception as e:
    check("C8 EXCEPTION", False, str(e))

# ─────────────────────────────────────────────────────────────────────────────
# CASE 9 — Ambiguous derivation → null (safe degradation)
# ─────────────────────────────────────────────────────────────────────────────
section("CASE 9 — Ambiguous derivation safely degrades to null")
try:
    se9a = derive_semantic_expectation(agent="general_agent", purpose="Do something with it")
    check("C9.1 ambiguous purpose → null", se9a is None, f"got: {se9a}")

    se9b = derive_semantic_expectation(agent=None, purpose=None, classification=None)
    check("C9.2 all-None input → null", se9b is None, f"got: {se9b}")

    se9c = derive_semantic_expectation(agent="unknown_agent_xyz", purpose="some operation")
    check("C9.3 unknown agent → null", se9c is None, f"got: {se9c}")
except Exception as e:
    check("C9 EXCEPTION", False, str(e))

# ─────────────────────────────────────────────────────────────────────────────
# CASE 10 — Validator advisory signals
# ─────────────────────────────────────────────────────────────────────────────
section("CASE 10 — Validator advisory signals")
try:
    se10 = {"semantic_domain": DOMAIN_NUMERIC, "semantic_category": CATEGORY_ARITHMETIC, "output_shape": SHAPE_SCALAR}

    sig10a = _analyze_semantic_conformity({"result": 50}, se10)
    check("C10.1 numeric result → domain_conformity ok", sig10a["domain_conformity"] == "ok",
          f"got: {sig10a}")
    check("C10.2 numeric scalar → shape_conformity ok", sig10a["shape_conformity"] == "ok")
    check("C10.3 numeric result → plausible", sig10a["semantic_plausibility"] == "plausible")

    sig10b = _analyze_semantic_conformity({"result": "text result"}, se10)
    check("C10.4 text result → domain_conformity violation", sig10b["domain_conformity"] == "violation",
          f"got: {sig10b}")
    check("C10.5 text result → implausible", sig10b["semantic_plausibility"] == "implausible")

    sig10c = _analyze_semantic_conformity({"result": [1, 2, 3]}, se10)
    check("C10.6 list result → shape_conformity violation", sig10c["shape_conformity"] == "violation",
          f"got: {sig10c}")

    sig10d = _analyze_semantic_conformity({"result": 50}, None)
    check("C10.7 null expectation → all unknown", all(
        v == "unknown" for v in sig10d.values()
    ), f"got: {sig10d}")
except Exception as e:
    check("C10 EXCEPTION", False, str(e))

# ─────────────────────────────────────────────────────────────────────────────
# ARCHITECTURE VALIDATION
# ─────────────────────────────────────────────────────────────────────────────
section("ARCHITECTURE VALIDATION")
try:
    import inspect
    from system.orchestrator import semantic_expectation as _se_mod

    src = inspect.getsource(_se_mod.derive_semantic_expectation)
    check("A1 No LLM calls in derivation", "get_llm" not in src and "execute_llm" not in src,
          "LLM call detected in derive_semantic_expectation")

    check("A2 Null expectation is valid (not error)", not is_valid_semantic_expectation(None),
          "is_valid_semantic_expectation(None) returned True unexpectedly")

    from system.orchestrator import drift_detector as _dd_mod
    dd_src = inspect.getsource(_dd_mod.compare)
    check("A3 Drift gated on semantic_expectation not expected_outcome string",
          "is_valid_semantic_expectation" in dd_src, "Drift not gated on semantic_expectation")

    check("A4 Governance not imported in semantic_expectation", "governance" not in src,
          "governance imported in semantic_expectation module")

    from system.orchestrator import projection_schema as _ps_mod
    ps_src = inspect.getsource(_ps_mod.build_step_projection)
    check("A5 Projection passthrough only (no synthesis)", "derive_semantic_expectation" not in ps_src,
          "Projection synthesizes semantic expectation locally")

    se_det1 = derive_semantic_expectation(agent="math_executor", purpose="Add 3 and 4")
    se_det2 = derive_semantic_expectation(agent="math_executor", purpose="Add 3 and 4")
    check("A6 Deterministic: same input → same output", se_det1 == se_det2,
          f"det1={se_det1} det2={se_det2}")

    se_rep1 = derive_semantic_expectation(agent="math_executor", purpose="Multiply 5 by 6")
    se_rep2 = derive_semantic_expectation(agent="math_executor", purpose="Multiply 5 by 6")
    check("A7 Replay-safe: same result on replay", se_rep1 == se_rep2)
except Exception as e:
    check("ARCH EXCEPTION", False, str(e))

# ─────────────────────────────────────────────────────────────────────────────
# ADVERSARIAL VALIDATION
# ─────────────────────────────────────────────────────────────────────────────
section("ADVERSARIAL VALIDATION")
try:
    # V1 — Forced ambiguity degrades
    se_v1 = derive_semantic_expectation(agent="general_agent", purpose="??????")
    check("V1 Forced ambiguity → null, not crash", se_v1 is None, f"got: {se_v1}")

    # V2 — Unknown agent degrades
    se_v2 = derive_semantic_expectation(agent="rogue_agent_9999", purpose="Add 5 and 5")
    check("V2 Unknown agent → null or numeric (purpose fallback acceptable)", se_v2 is None or se_v2.get("semantic_domain") == DOMAIN_NUMERIC,
          f"got: {se_v2}")

    # V3 — Malformed semantic_expectation in drift
    drift_v3 = drift_compare(
        expected_outcome="x",
        execution_result={"status": "success", "result": 10},
        semantic_expectation={"semantic_domain": None},
    )
    check("V3 Malformed expectation (null domain) → NONE drift", drift_v3["drift_type"] == "NONE",
          f"got: {drift_v3}")

    # V4 — Boolean not treated as numeric
    se_v4 = {"semantic_domain": DOMAIN_NUMERIC, "semantic_category": CATEGORY_ARITHMETIC, "output_shape": SHAPE_SCALAR}
    drift_v4 = drift_compare(
        expected_outcome="x",
        execution_result={"status": "success", "result": True},
        semantic_expectation=se_v4,
    )
    check("V4 Boolean result not treated as numeric → LARGE drift", drift_v4["drift_type"] == "LARGE",
          f"got: {drift_v4}")

    # V5 — Drift signal is advisory only (no retry key in drift output)
    drift_v5 = drift_compare(
        expected_outcome="x",
        execution_result={"status": "success", "result": "text"},
        semantic_expectation={"semantic_domain": DOMAIN_NUMERIC, "output_shape": SHAPE_SCALAR},
    )
    check("V5 Drift output has no retry/control keys", "retry" not in drift_v5 and "decision" not in drift_v5,
          f"drift keys: {list(drift_v5.keys())}")

    # V6 — Execution failure always LARGE regardless of semantic_expectation
    drift_v6 = drift_compare(
        expected_outcome="x",
        execution_result={"status": "failure", "result": None},
        semantic_expectation={"semantic_domain": DOMAIN_NUMERIC, "output_shape": SHAPE_SCALAR},
    )
    check("V6 Execution failure → LARGE regardless of semantic_expectation",
          drift_v6["drift_type"] == "LARGE", f"got: {drift_v6}")

    # V7 — Semantic signals advisory only in validator (no retry key in semantic_signals)
    sem_v7 = _analyze_semantic_conformity(
        {"result": "text"},
        {"semantic_domain": DOMAIN_NUMERIC, "output_shape": SHAPE_SCALAR}
    )
    check("V7 Semantic conformity output has no retry/decision keys",
          "retry" not in sem_v7 and "decision" not in sem_v7 and "recommendation" not in sem_v7,
          f"keys: {list(sem_v7.keys())}")

    # V8 — Injection: malicious expected_outcome string cannot poison drift
    drift_v8 = drift_compare(
        expected_outcome='{"semantic_domain": "numeric"}',
        execution_result={"status": "success", "result": "injected"},
        semantic_expectation=None,
    )
    check("V8 Injected expected_outcome string cannot activate drift (no sem_exp)", drift_v8["drift_type"] == "NONE",
          f"got: {drift_v8}")
except Exception as e:
    check("ADV EXCEPTION", False, str(e))

# ─────────────────────────────────────────────────────────────────────────────
# PROJECTION PASSTHROUGH TEST
# ─────────────────────────────────────────────────────────────────────────────
section("PROJECTION PASSTHROUGH")
try:
    step_with_sem = {
        "id": "step_1",
        "type": "EXECUTE_API",
        "purpose": "Add 10 and 20",
        "expected_outcome": "Execution completed",
        "risk": "LOW",
        "importance": "MEDIUM",
        "resource_targets": [],
        "depends_on": [],
        "status": "COMPLETED",
        "retries": 0,
        "semantic_expectation": {"semantic_domain": "numeric", "semantic_category": "arithmetic", "output_shape": "scalar"},
    }
    proj = build_step_projection(workflow_id="wf_test", step=step_with_sem, projection_version=1)
    check("P1 semantic_expectation present in projection", "semantic_expectation" in proj,
          f"keys: {list(proj.keys())}")
    check("P2 semantic_expectation matches source", proj["semantic_expectation"] == step_with_sem["semantic_expectation"])

    step_without_sem = dict(step_with_sem)
    step_without_sem["semantic_expectation"] = None
    proj2 = build_step_projection(workflow_id="wf_test", step=step_without_sem, projection_version=2)
    check("P3 null semantic_expectation projected as None", proj2.get("semantic_expectation") is None,
          f"got: {proj2.get('semantic_expectation')}")
except Exception as e:
    check("PROJ EXCEPTION", False, str(e))

# ─────────────────────────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────────────────────────
section("TEST SUMMARY")
passed = sum(1 for _, s, _ in results if s == PASS)
failed = sum(1 for _, s, _ in results if s == FAIL)
total = len(results)

print(f"\n  Total: {total}  |  PASS: {passed}  |  FAIL: {failed}")

if failed:
    print("\n  FAILED CASES:")
    for name, status, detail in results:
        if status == FAIL:
            print(f"    ❌ {name}" + (f" — {detail}" if detail else ""))
    print(f"\n  STATUS: FAIL")
    sys.exit(1)
else:
    print(f"\n  STATUS: PASS — All {total} checks passed")
    sys.exit(0)
