export function normalizeResult(res) {
  if (!res) return null;

  const CONTROL_STATES = ["paused", "blocked", "failed"];

  // CASE 1: CONTROL WRAPPED (ONLY known control states)
  if (
    res.status === "success" &&
    res.result &&
    typeof res.result === "object" &&
    CONTROL_STATES.includes(res.result.status)
  ) {
    return {
      type: "CONTROL_WRAPPED",
      displayStatus: res.result.status,
      displayReason: res.result.reason || null,
      raw: res
    };
  }

  // CASE 2: DIRECT CONTROL RESPONSE
  if (res.status === "control") {
    return {
      type: "CONTROL",
      displayStatus: res.action || "control",
      displayReason: res.reason || null,
      raw: res
    };
  }

  // CASE 3: STANDARD EXECUTION RESULT
  return {
    type: "EXECUTION",
    displayStatus: res.status,
    displayReason: res.reason || null,
    raw: res
  };
}
