INPUT_SPEC = {
    "numerator": "number",
    "denominator": "number"
}

def run(numerator, denominator):
    if denominator == 0:
        return {
            "status": "failure",
            "reason": "division_by_zero"
        }
    return numerator / denominator