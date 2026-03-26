INPUT_SPEC = {
    "directory": "string"
}

import os
import importlib

def run(*args):
    try:
        # Access parameters by position
        directory = args[0]

        if not os.path.isdir(directory):
            return "Error: Directory does not exist."

        files = os.listdir(directory)
        return str(files)

    except Exception as e:
        raise Exception(str(e))