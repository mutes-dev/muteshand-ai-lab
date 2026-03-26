INPUT_SPEC = {
    "a": "number",
    "multiplier": "number"
}

def run(*args):
    try:
        a = float(args[0])
        multiplier = float(args[1])
        result = a * multiplier**0.5
        return str(result)
    except Exception as e:
        raise Exception(str(e))
