INPUT_SPEC = {
    "number": "number"
}

def run(number):
    # Domain validation: factorial requires non-negative input
    if number < 0:
        return {"status": "failure", "reason": "invalid_domain"}
    
    if number == 0:
        return 1
    else:
        result = 1
        for i in range(1, number + 1):
            result *= i
        return result

