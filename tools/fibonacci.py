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

    if n == 0:
        return {"status": "success", "result": []}

    if n == 1:
        return {"status": "success", "result": [0]}

    sequence = [0, 1]

    while len(sequence) < n:
        sequence.append(sequence[-1] + sequence[-2])

    return {"status": "success", "result": sequence[:n]}