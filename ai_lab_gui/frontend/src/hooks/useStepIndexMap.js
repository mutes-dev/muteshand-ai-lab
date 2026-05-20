/**
 * USE STEP INDEX MAP — PHASE 1 FOUNDATION
 * 
 * Per WORKFLOW_STUDIO_ARCHITECTURE_AUDIT.md §PHASE 1:
 * Shared hook for step_id → index mapping.
 * 
 * Authority: PROJECTION_CONTINUITY_CONTRACT_V1
 * 
 * RULES:
 * - Pure deterministic utility only
 * - NO side effects
 * - NO authority logic
 * - Memoized for performance
 * 
 * Previously duplicated in: PlanView, DependencyView
 */

import { useMemo } from "react";

/**
 * useStepIndexMap — create step_id → index mapping from step array
 * 
 * Used for:
 * - Dependency display ("Depends on: #2, #3")
 * - Step reference resolution
 * - Cross-step linking
 * 
 * @param {Array} steps — array of step objects with step_id property
 * @returns {Object} mapping of step_id → 1-based index
 * 
 * @example
 * const steps = [{ step_id: "a" }, { step_id: "b" }];
 * const indexMap = useStepIndexMap(steps);
 * // indexMap = { "a": 1, "b": 2 }
 * // indexMap["a"] → 1
 */
export function useStepIndexMap(steps) {
  return useMemo(() => {
    if (!steps || steps.length === 0) {
      return {};
    }

    const map = {};
    steps.forEach((step, index) => {
      if (step.step_id) {
        map[step.step_id] = index + 1; // 1-based indexing for display
      }
    });
    return map;
  }, [steps]);
}

/**
 * useStepMap — create step_id → { step, index } mapping
 * 
 * Used for:
 * - Quick step lookup by ID with display index
 * - Dependency resolution
 * - Cross-referencing step metadata
 * 
 * @param {Array} steps — array of step objects
 * @returns {Object} mapping of step_id → { step, index } (index is 1-based)
 */
export function useStepMap(steps) {
  return useMemo(() => {
    if (!steps || steps.length === 0) {
      return {};
    }

    const map = {};
    steps.forEach((step, index) => {
      if (step.step_id) {
        map[step.step_id] = { step, index: index + 1 }; // 1-based index
      }
    });
    return map;
  }, [steps]);
}

/**
 * useStepIndexMapWithFallback — index map with safe lookup
 * 
 * Includes helper function that returns fallback for missing steps.
 * 
 * @param {Array} steps — array of step objects
 * @returns {[Object, Function]} [indexMap, getStepNumber]
 */
export function useStepIndexMapWithFallback(steps) {
  const indexMap = useStepIndexMap(steps);

  const getStepNumber = (stepId) => {
    return indexMap[stepId] ?? stepId; // Fall back to ID if not found
  };

  return [indexMap, getStepNumber];
}

export default useStepIndexMap;
