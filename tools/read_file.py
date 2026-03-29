# tools/read_file.py
"""
Reads a file from within the MutesHand project directory and returns its content.
All paths must be relative to the MutesHand root.
"""

import os

BASE_PATH = "E:/MutesHand"

INPUT_SPEC = {
    "path": "string"
}

def run(*args):
    try:
        relative_path = args[0].replace('"', '').replace("'", "")

        full_path = os.path.normpath(os.path.join(BASE_PATH, relative_path))

        if not full_path.startswith(os.path.normpath(BASE_PATH)):
            return "Access denied: path outside project."

        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()

    except FileNotFoundError:
        return "File not found"

    except Exception as e:
        return f"Read error: {str(e)}"