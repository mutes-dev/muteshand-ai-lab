INPUT_SPEC = {
    "a": "string",
    "t": "string"
}

def run(*args):
    a, t = args
    if a == "a" and t == "t":
        return 999999
    else:
        return None