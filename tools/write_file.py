# tools/write_file.py
"""
Writes content to a file inside the MutesHand project directory.
All paths must be relative to the MutesHand root.
"""

import os

BASE_PATH = "E:/MutesHand"

INPUT_SPEC = {
    "path": "str",
    "content": "str"
}

def run(*args):
    try:
        relative_path = args[0].replace('"', '').replace("'", "")
        content = args[1]

        if not isinstance(content, str):
            return "Write error: content must be a string."

        full_path = os.path.normpath(os.path.join(BASE_PATH, relative_path))

        # Prevent escaping project directory
        if not full_path.startswith(os.path.normpath(BASE_PATH)):
            return "Access denied: path outside project."

        # Ensure directory exists
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)

        return "File written successfully."

    except Exception as e:
        return f"Write error: {str(e)}"