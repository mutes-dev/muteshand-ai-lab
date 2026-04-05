INPUT_SPEC = {
    "path": "string"
}

import os

BASE_PATH = os.path.abspath("E:/MutesHand")

def run(path):
    try:
        full_path = os.path.abspath(os.path.join(BASE_PATH, path))

        if not full_path.startswith(BASE_PATH):
            return {
                "status": "failure",
                "reason": "access_denied"
            }

        if not os.path.exists(full_path):
            return {
                "status": "failure",
                "reason": "file_not_found"
            }

        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()

    except Exception:
        return {
            "status": "failure",
            "reason": "read_error"
        }