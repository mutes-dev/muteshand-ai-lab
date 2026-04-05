INPUT_SPEC = {
    "str1": "string",
    "num": "number"
}

def run(str1, num):
    # Domain validation: multiplier must be non-negative
    if num < 0:
        return {"status": "failure", "reason": "invalid_domain"}
    
    # Limit check: prevent excessive output
    if num > 10000:
        return {"status": "failure", "reason": "limit_exceeded"}
    
    return str1 * int(num)
