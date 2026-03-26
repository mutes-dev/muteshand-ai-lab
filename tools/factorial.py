INPUT_SPEC = {
    "number": "number"
}

def run(*args):
    number = args[0]
    if number == 0:
        return 1
    else:
        result = 1
        for i in range(1, number + 1):
            result *= i
        return result

