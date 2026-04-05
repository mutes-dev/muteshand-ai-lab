INPUT_SPEC = {
    "number": "number"
}

def run(number):
    # Domain validation: square root requires non-negative input
    if number < 0:
        return {"status": "failure", "reason": "invalid_domain"}
    
    try:
        result = number**0.5
        return result
    except Exception as e:
        raise Exception(str(e))
