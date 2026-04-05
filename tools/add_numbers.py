INPUT_SPEC = {
    "num1": "number",
    "num2": "number"
}

def run(num1, num2):
    try:
        result = num1 + num2
        return result
    except Exception as e:
        raise Exception(str(e))
