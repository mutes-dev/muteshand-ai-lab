INPUT_SPEC = {
    "numerator": "number",
    "denominator": "number"
}

def run(*args):
    numerator, denominator = args
    if denominator == 0:
        return "Error: Division by zero"
    else:
        return numerator / denominator