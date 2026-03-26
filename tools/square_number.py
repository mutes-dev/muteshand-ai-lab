INPUT_SPEC = {
    "a": "string"
}

def run(*args):
    try:
        a = args[0]
        return int(a) * int(a)
    except Exception as e:
        raise Exception(str(e))