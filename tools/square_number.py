INPUT_SPEC = {
    "a": "number"
}

def run(a):
    try:
        return a * a
    except Exception as e:
        raise Exception(str(e))