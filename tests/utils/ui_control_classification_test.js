/**
 * UI CONTROL STATE CLASSIFICATION TEST
 * 
 * Verifies CONTROL_WRAPPED detection in ExecutionPanel classification logic
 */

// Simulate the classify function from ExecutionPanel.jsx
function classify(res) {
  if (!res) return "none";
  if (res.status === "control") return "CONTROL";
  // === CONTROL_WRAPPED DETECTION (Phase 6 Fix) ===
  // Check for wrapped control states BEFORE checking outer success/failure
  // Pattern: { status: "success", result: { status: "paused", reason: "..." } }
  if (res.status === "success" && res.result?.status === "paused") {
    console.log("[CONTROL_DETECTED]", {
      inner_status: res.result?.status,
      outer_status: res.status,
      reason: res.result?.reason,
    });
    return "CONTROL_WRAPPED";
  }
  if (res.status === "success" || res.status === "failure") return "EXECUTION";
  return "UNKNOWN";
}

// Test cases
const testCases = [
  {
    name: "CONTROL_WRAPPED (pause response)",
    input: {
      status: "success",
      result: {
        status: "paused",
        reason: "Execution paused by user"
      }
    },
    expected: "CONTROL_WRAPPED"
  },
  {
    name: "EXECUTION (normal success)",
    input: {
      status: "success",
      result: {
        status: "completed",
        result: "some data"
      }
    },
    expected: "EXECUTION"
  },
  {
    name: "EXECUTION (failure)",
    input: {
      status: "failure",
      reason: "execution failed"
    },
    expected: "EXECUTION"
  },
  {
    name: "CONTROL (direct control)",
    input: {
      status: "control",
      action: "paused"
    },
    expected: "CONTROL"
  },
  {
    name: "none (null)",
    input: null,
    expected: "none"
  },
  {
    name: "EXECUTION (success with result string)",
    input: {
      status: "success",
      result: "direct result"
    },
    expected: "EXECUTION"
  }
];

console.log("\n=== UI CONTROL CLASSIFICATION TEST ===\n");

let passed = 0;
let failed = 0;

testCases.forEach(({ name, input, expected }) => {
  const result = classify(input);
  const status = result === expected ? "✓ PASS" : "✗ FAIL";
  
  if (result === expected) {
    passed++;
  } else {
    failed++;
  }
  
  console.log(`${status}: ${name}`);
  if (result !== expected) {
    console.log(`  Expected: ${expected}`);
    console.log(`  Got: ${result}`);
    console.log(`  Input: ${JSON.stringify(input)}`);
  }
});

console.log("\n=== SUMMARY ===");
console.log(`Passed: ${passed}/${testCases.length}`);
console.log(`Failed: ${failed}/${testCases.length}`);

if (failed === 0) {
  console.log("\n✓ ALL TESTS PASSED");
  process.exit(0);
} else {
  console.log("\n✗ SOME TESTS FAILED");
  process.exit(1);
}
