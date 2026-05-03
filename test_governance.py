#!/usr/bin/env python
"""Governance alignment tests."""
import sys
sys.path.insert(0, '.')

from system.orchestrator.governance import decide_next_action, _get_risk_based_max_retries

print('=== RISK-BASED RETRY TESTS ===')
print(f'LOW risk max_retries: {_get_risk_based_max_retries("LOW")} (expected: 5)')
print(f'MEDIUM risk max_retries: {_get_risk_based_max_retries("MEDIUM")} (expected: 3)')
print(f'HIGH risk max_retries: {_get_risk_based_max_retries("HIGH")} (expected: 1)')

print()
print('=== BLOCK DECISION TEST ===')
step_high_risk = {'risk': 'HIGH', 'importance': 'HIGH', 'retries': 0}
result = decide_next_action(None, None, step_high_risk, {})
print(f'HIGH risk + HIGH importance step: {result} (expected: block)')

step_low_risk = {'risk': 'LOW', 'importance': 'MEDIUM', 'retries': 0}
result = decide_next_action(None, {'status': 'success'}, step_low_risk, {})
print(f'LOW risk success step: {result} (expected: complete)')

step_fail = {'risk': 'LOW', 'importance': 'MEDIUM', 'retries': 0}
result = decide_next_action(None, {'status': 'failure'}, step_fail, {})
print(f'LOW risk failure step (retry 0/5): {result} (expected: retry)')

step_fail_exhausted = {'risk': 'HIGH', 'importance': 'MEDIUM', 'retries': 1}
result = decide_next_action(None, {'status': 'failure'}, step_fail_exhausted, {})
print(f'HIGH risk failure step (retry 1/1): {result} (expected: escalate)')

print()
print('=== COMPLETION RULE TEST ===')
# Test: execution success but purpose not met
step_purpose_not_met = {'risk': 'LOW', 'importance': 'MEDIUM', 'retries': 0, 'purpose_met': False}
result = decide_next_action(None, {'status': 'success'}, step_purpose_not_met, {})
print(f'Success but purpose_not_met: {result} (expected: retry)')

# Test: execution success with validation fail
step_validation_fail = {'risk': 'LOW', 'importance': 'MEDIUM', 'retries': 0}
validator_fail = {'recommendation': 'retry', 'reason': 'incorrect'}
result = decide_next_action(validator_fail, {'status': 'success'}, step_validation_fail, {})
print(f'Success but validation fail: {result} (expected: retry)')

print()
print('ALL TESTS COMPLETE')
