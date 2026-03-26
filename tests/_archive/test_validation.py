import sys
sys.path.insert(0, 'E:/MutesHand')

from core.planner import _validate_plan

# Invalid test cases
test_cases = [
    ('Unknown tool', 
     [{'type': 'tool', 'name': 'unknown_tool', 'args': [1, 2], 'input_text': '1 and 2'}], 
     ['add_numbers']),
    
    ('Missing field', 
     [{'type': 'tool', 'name': 'add_numbers', 'args': [1, 2]}], 
     ['add_numbers']),
    
    ('Extra field', 
     [{'type': 'tool', 'name': 'add_numbers', 'args': [1, 2], 'input_text': '1 and 2', 'extra': 'field'}], 
     ['add_numbers']),
    
    ('PREVIOUS_RESULT in first step', 
     [{'type': 'tool', 'name': 'add_numbers', 'args': ['PREVIOUS_RESULT', 2], 'input_text': 'result and 2'}], 
     ['add_numbers']),
    
    ('Multiple PREVIOUS_RESULT', 
     [{'type': 'tool', 'name': 'add_numbers', 'args': [1, 2], 'input_text': '1 and 2'}, 
      {'type': 'tool', 'name': 'multiply_numbers', 'args': ['PREVIOUS_RESULT', 'PREVIOUS_RESULT'], 'input_text': 'result and result'}], 
     ['add_numbers', 'multiply_numbers']),
    
    ('Args not list', 
     [{'type': 'tool', 'name': 'add_numbers', 'args': 'not a list', 'input_text': '1 and 2'}], 
     ['add_numbers']),
    
    ('Empty plan', 
     [], 
     ['add_numbers']),
    
    ('Plan not list', 
     {'type': 'tool'}, 
     ['add_numbers']),
    
    ('Empty input_text', 
     [{'type': 'tool', 'name': 'add_numbers', 'args': [1, 2], 'input_text': ''}], 
     ['add_numbers']),
    
    ('Wrong type value', 
     [{'type': 'agent', 'name': 'add_numbers', 'args': [1, 2], 'input_text': '1 and 2'}], 
     ['add_numbers']),
]

print('INVALID TEST CASES:')
print('-' * 50)
for name, plan, tools in test_cases:
    result = _validate_plan(plan, tools)
    status = 'PASS' if not result else 'FAIL'
    print(f'{name}: {status}')

# Valid test cases
valid_cases = [
    ('Single step', 
     [{'type': 'tool', 'name': 'add_numbers', 'args': [2, 3], 'input_text': '2 and 3'}], 
     ['add_numbers', 'square_number']),
    
    ('Chained steps', 
     [{'type': 'tool', 'name': 'add_numbers', 'args': [2, 3], 'input_text': '2 and 3'},
      {'type': 'tool', 'name': 'square_number', 'args': ['PREVIOUS_RESULT'], 'input_text': 'result of previous step'}], 
     ['add_numbers', 'square_number']),
]

print('\nVALID TEST CASES:')
print('-' * 50)
for name, plan, tools in valid_cases:
    result = _validate_plan(plan, tools)
    status = 'PASS' if result else 'FAIL'
    print(f'{name}: {status}')
