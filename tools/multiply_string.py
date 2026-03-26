INPUT_SPEC = {
    "str1": "string",
    "num": "number"
}

def run(*args):
    str1, num = args
    return str1 * int(num)
