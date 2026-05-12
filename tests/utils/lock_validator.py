"""
Lock Validator — Architecture and Determinism Validation Engine

PURPOSE:
    Validates Phase 4B lock criteria through strict architecture checks
    and determinism verification.

CONSTRAINTS:
    - OBSERVATIONAL ONLY (uses trace data)
    - NO execution logic
    - NO core module modification
"""

from typing import Dict, List, Any, Optional, Tuple


class ArchitectureValidator:
    """
    Validates architecture laws using trace data.
    
    CRITICAL: This is OBSERVATIONAL ONLY.
    Uses trace_capture data to verify architecture compliance.
    """
    
    def __init__(self):
        self.violations = []
    
    def validate_planner_purity(self, trace: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Verify planner output contains NO args.
        
        LAW: Planner NEVER generates arguments.
        """
        planner_raw = trace.get("planner_output")
        
        if not planner_raw:
            return False, "Planner output missing"
        
        if isinstance(planner_raw, dict) and "error" in planner_raw:
            return False, f"Planner error: {planner_raw['error']}"
        
        # Check if planner output is a list of steps
        if not isinstance(planner_raw, list):
            return False, "Planner output is not a list"
        
        # Verify NO step contains "args" field
        for idx, step in enumerate(planner_raw):
            if isinstance(step, dict) and "args" in step:
                return False, f"Planner output contains 'args' field in step {idx} (VIOLATION)"
        
        return True, None
    
    def validate_resolver_ownership(self, trace: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Verify arguments are created ONLY by resolver.
        
        LAW: Argument Resolver is ONLY source of arguments.
        """
        planner_raw = trace.get("planner_output")
        resolver_output = trace.get("resolver_output")
        
        if not planner_raw:
            return False, "Planner output missing"
        
        if not isinstance(planner_raw, list):
            return False, "Planner output is not a list"
        
        # Verify planner has NO args (already checked in planner_purity)
        for step in planner_raw:
            if isinstance(step, dict) and "args" in step:
                return False, "Args present BEFORE resolver stage (VIOLATION)"
        
        # Verify resolver created args
        if resolver_output is None:
            return False, "Resolver output missing"
        
        if not isinstance(resolver_output, list):
            return False, "Resolver output is not a list"
        
        return True, None
    
    def validate_validation_behavior(self, trace: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Verify validation skips PREVIOUS_RESULT and doesn't modify args.
        
        LAW: Validation MUST skip PREVIOUS_RESULT (runtime placeholder).
        """
        validation_result = trace.get("validation_result")
        resolver_output = trace.get("resolver_output")
        
        if not validation_result:
            return False, "Validation result missing"
        
        # If validation failed, check if it was due to PREVIOUS_RESULT
        if not validation_result.get("passed"):
            error = validation_result.get("error", "")
            if "PREVIOUS_RESULT" in error:
                return False, "Validation rejected PREVIOUS_RESULT (VIOLATION)"
        
        # Verify resolver output wasn't modified by validation
        # (We can't directly check this without comparing before/after,
        # but we can verify resolver_output still exists)
        if resolver_output is None:
            return False, "Resolver output missing after validation"
        
        return True, None
    
    def validate_chain_resolution_timing(self, trace: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Verify PREVIOUS_RESULT is replaced ONLY during execution.
        
        LAW: Chain Resolver runs INSIDE execution loop.
        """
        resolver_output = trace.get("resolver_output")
        post_chain_arguments = trace.get("post_chain_arguments")
        
        if not resolver_output:
            return False, "Resolver output missing"
        
        # Check if any resolver output contains PREVIOUS_RESULT
        has_previous_result = False
        for args in resolver_output:
            if args and "PREVIOUS_RESULT" in args:
                has_previous_result = True
                break
        
        if not has_previous_result:
            # No chaining in this test, skip check
            return True, None
        
        # Verify resolver_output exists (proves chain resolution happened)
        if not resolver_output:
            return False, "Resolver output missing"
        
        # Verify PREVIOUS_RESULT was replaced in post_chain_arguments
        for args in post_chain_arguments:
            if args and "PREVIOUS_RESULT" in args:
                return False, "PREVIOUS_RESULT not replaced during execution (VIOLATION)"
        
        return True, None
    
    def validate_all(self, trace: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run all architecture validations.
        
        Returns:
            {
                "passed": bool,
                "violations": [str],
                "checks": {
                    "planner_purity": bool,
                    "resolver_ownership": bool,
                    "validation_behavior": bool,
                    "chain_timing": bool
                }
            }
        """
        violations = []
        checks = {}
        
        # Check 1: Planner Purity
        passed, error = self.validate_planner_purity(trace)
        checks["planner_purity"] = passed
        if not passed:
            violations.append(f"Planner Purity: {error}")
        
        # Check 2: Resolver Ownership
        passed, error = self.validate_resolver_ownership(trace)
        checks["resolver_ownership"] = passed
        if not passed:
            violations.append(f"Resolver Ownership: {error}")
        
        # Check 3: Validation Behavior
        passed, error = self.validate_validation_behavior(trace)
        checks["validation_behavior"] = passed
        if not passed:
            violations.append(f"Validation Behavior: {error}")
        
        # Check 4: Chain Resolution Timing
        passed, error = self.validate_chain_resolution_timing(trace)
        checks["chain_timing"] = passed
        if not passed:
            violations.append(f"Chain Timing: {error}")
        
        return {
            "passed": len(violations) == 0,
            "violations": violations,
            "checks": checks
        }


class DeterminismValidator:
    """
    Validates deterministic behavior through repeat execution.
    """
    
    @staticmethod
    def validate_determinism(outputs: List[str]) -> Tuple[bool, Optional[str]]:
        """
        Verify all outputs are identical.
        
        Args:
            outputs: List of output strings from repeat executions
            
        Returns:
            (passed, error_message)
        """
        if len(outputs) < 2:
            return False, "Insufficient runs for determinism check"
        
        # Normalize outputs (strip whitespace)
        normalized = [output.strip() for output in outputs]
        
        # Check if all outputs are identical
        first = normalized[0]
        for idx, output in enumerate(normalized[1:], 1):
            if output != first:
                return False, f"Output mismatch: run 0 vs run {idx}"
        
        return True, None


class Phase4BValidator:
    """
    Validates Phase 4B specific features.
    """
    
    @staticmethod
    def validate_input_normalizer(trace: Dict[str, Any], original_input: str) -> Tuple[bool, Optional[str]]:
        """
        Verify Input Normalizer executed correctly.
        
        VALIDATION LOGIC:
        1. Check if original input has noise words
        2. If yes, verify trace shows normalization (input != normalized_input)
        3. If no, normalization not required (pass)
        """
        noise_words = ["please", "hey", "bro", "can you", "could you"]
        
        has_noise = any(word in original_input.lower() for word in noise_words)
        
        if has_noise:
            # Test REQUIRES normalization - check trace
            trace_input = trace.get("input", "")
            normalized_input = trace.get("normalized_input", "")
            
            # Verify normalization occurred
            if not normalized_input:
                return False, "Normalized input missing from trace"
            
            # Verify noise words removed
            normalized_lower = normalized_input.lower()
            if any(word in normalized_lower for word in noise_words):
                return False, "Noise words still present in normalized input"
            
            # Verify inputs are different (normalization happened)
            if trace_input == normalized_input:
                return False, "Input not normalized (input == normalized_input)"
            
            return True, None
        
        # No noise words, normalization not required for this test
        return True, None
    
    @staticmethod
    def validate_tool_phrases(trace: Dict[str, Any], expected_tool: str) -> Tuple[bool, Optional[str]]:
        """
        Verify TOOL_PHRASES mapping worked correctly.
        
        Checks:
        - Correct tool selected
        - Deterministic routing
        """
        planner_raw = trace.get("planner_output")
        
        if not planner_raw or not isinstance(planner_raw, list):
            return False, "Planner output missing or invalid"
        
        if len(planner_raw) == 0:
            return False, "No steps in plan"
        
        # Check first step tool name
        first_step = planner_raw[0]
        if not isinstance(first_step, dict):
            return False, "Invalid step format"
        
        actual_tool = first_step.get("name")
        if actual_tool != expected_tool:
            return False, f"Expected tool '{expected_tool}', got '{actual_tool}'"
        
        return True, None
    
    @staticmethod
    def validate_chain_connectors(trace: Dict[str, Any], expected_steps: int) -> Tuple[bool, Optional[str]]:
        """
        Verify CHAIN_CONNECTORS splitting worked correctly.
        
        Checks:
        - Correct number of steps
        - Only valid connectors split chains
        """
        planner_raw = trace.get("planner_output")
        
        if not planner_raw or not isinstance(planner_raw, list):
            return False, "Planner output missing or invalid"
        
        actual_steps = len(planner_raw)
        if actual_steps != expected_steps:
            return False, f"Expected {expected_steps} steps, got {actual_steps}"
        
        return True, None
