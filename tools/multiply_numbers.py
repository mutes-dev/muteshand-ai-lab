# tools/multiply_numbers.py
"""
This tool multiplies two numbers.
"""

INPUT_SPEC = {
    "a": "string",
    "t": "string"
}

def run(*args):
    a, t = args
    return int(a) * int(t)
