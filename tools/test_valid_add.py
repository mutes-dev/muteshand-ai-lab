INPUT_SPEC = {
    "num1": "number",
    "num2": "number"
}

def run(*args):
    try:
        num1 = args[0]
        num2 = args[1]
        result = num1 + num2
        return result
    except Exception as e:
        raise Exception(str(e))
