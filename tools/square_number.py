INPUT_SPEC = {
    "a": "number"
}

def run(*args):
    try:
        a = args[0]
        return a * a
    except Exception as e:
        raise Exception(str(e))