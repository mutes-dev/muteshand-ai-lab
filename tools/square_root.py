INPUT_SPEC = {
    "number": "number"
}

def run(*args):
    try:
        number = args[0]
        result = number**0.5
        return result
    except Exception as e:
        raise Exception(str(e))
