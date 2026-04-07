INPUT_SPEC = {
    "n": "number"
}

def run(n):
    # Domain validation: fibonacci requires integer input
    if not isinstance(n, int):
        return {"status": "failure", "reason": "invalid_domain"}
    
    # Domain validation: fibonacci requires non-negative input
    if n < 0:
        return {"status": "failure", "reason": "invalid_domain"}
    
    if n <= 0:
        return [0]
    elif n == 1:
        return [0, 1]
    else:
        list_ = [0, 1]
        for i in range(2, n):
            list_.append(list_[i-1] + list_[i-2])
        return list_