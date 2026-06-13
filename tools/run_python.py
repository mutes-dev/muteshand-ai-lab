# tools/run_python.py

"""
Executes a Python code snippet and returns its output.
"""

import io
import contextlib

INPUT_SPEC = {
    "code": "string"
}

def run(code):
    try:
        buffer = io.StringIO()

        with contextlib.redirect_stdout(buffer):
            exec(code, {})

        output = buffer.getvalue()

        if output.strip() == "":
            return "Execution completed with no output."

        return output.strip()

    except Exception as e:
        # Return structured failure so the execution layer does NOT
        # wrap the error string as a successful result.
        return {
            "status": "failure",
            "reason": f"Execution error: {str(e)}"
        }