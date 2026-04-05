# tools/write_file.py
"""
Writes content to a file inside the MutesHand project directory.
All paths must be relative to the MutesHand root.
"""

import os

BASE_PATH = "E:/MutesHand"

INPUT_SPEC = {
    "path": "string",
    "content": "string"
}

def run(path, content):
    try:
        relative_path = path.replace('"', '').replace("'", "")

        if not isinstance(content, str):
            return {"status": "failure", "reason": "invalid_path"}

        full_path = os.path.normpath(os.path.join(BASE_PATH, relative_path))

        # Prevent escaping project directory
        if not full_path.startswith(os.path.normpath(BASE_PATH)):
            return {"status": "failure", "reason": "access_denied"}

        # Ensure directory exists
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)

        return {"status": "success", "result": "File written successfully."}

    except PermissionError:
        return {"status": "failure", "reason": "permission_denied"}
    except Exception:
        return {"status": "failure", "reason": "access_denied"}