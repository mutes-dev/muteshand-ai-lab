INPUT_SPEC = {
    "text": "string"
}

def run(text):
    if not isinstance(text, str):
        raise Exception("invalid_input")
    return text
