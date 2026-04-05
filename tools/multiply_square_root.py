INPUT_SPEC = {
    "a": "number",
    "multiplier": "number"
}

def run(a, multiplier):
    try:
        a_float = float(a)
        multiplier_float = float(multiplier)
        result = a_float * multiplier_float**0.5
        return str(result)
    except Exception as e:
        raise Exception(str(e))
