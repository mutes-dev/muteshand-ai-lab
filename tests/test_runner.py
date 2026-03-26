import subprocess
import sys


def run_test(input_text: str) -> str:
    """
    Execute a single test via manager.py using subprocess.
    
    Args:
        input_text (str): Input text to send to manager
        
    Returns:
        str: Raw output from manager execution
    """
    try:
        manager_script = "projects/manager/manager.py"
        
        process = subprocess.Popen(
            [sys.executable, manager_script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        
        full_input = f"{input_text}\n\n"
        
        stdout, stderr = process.communicate(input=full_input, timeout=60)
        
        if not stdout.strip():
            stdout = "[HARNESS ERROR] Empty output from manager"
        
        return stdout
        
    except subprocess.TimeoutExpired:
        process.kill()
        return "ERROR: Test execution timeout"
    except Exception as e:
        return f"ERROR: {str(e)}"
