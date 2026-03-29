# tools/multiply_numbers.py
"""
This tool multiplies two numbers.
"""

INPUT_SPEC = {
    "a": "number",
    "t": "number"
}

def run(*args):
    a, t = args
    return a * t
