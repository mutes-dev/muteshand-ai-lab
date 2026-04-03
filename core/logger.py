"""
Logging Module

PURPOSE:
    Provides centralized logging and execution tracking for the AI Lab system.
    Handles both file-based persistent logs and console output based on mode.

ARCHITECTURE ROLE:
    - Infrastructure layer: Observability and debugging support
    - Side effects: Writes to files, prints to console
    - Used by all other modules for consistent logging

LAYER RESPONSIBILITY:
    - Write timestamped log entries to file
    - Control console output based on runtime mode (debug/normal/quiet)
    - Serialize complex objects safely for JSON storage
    - Maintain execution history for debugging and replay

USAGE:
    from core.logger import log, log_execution
    
    log("Starting task execution")
    log_execution(goal, task_state, results)

OUTPUT MODES:
    - debug: All messages to console and file
    - normal: Only GOAL and ACTION messages to console
    - quiet: Only FINAL ANSWER messages to console
"""

import json
from datetime import datetime
import os
from core.config import config


def set_mode(mode: str):
    """
    Set the runtime logging mode.
    
    Controls verbosity of console output. Does not affect file logging
    (all messages are always written to log file regardless of mode).
    
    Args:
        mode (str): One of "debug", "normal", "quiet"
            - debug: All log messages printed to console
            - normal: Only GOAL and ACTION messages printed
            - quiet: Only FINAL messages printed
    """
    config.MODE = mode


def log(message: str):
    """
    Write a log message to file and optionally to console.
    
    LOGGING BEHAVIOR:
        - Always writes to config.LOG_FILE with timestamp
        - Console output depends on config.MODE:
          * debug: All messages
          * normal: Only messages starting with "GOAL" or "ACTION"
          * quiet: Only messages starting with "FINAL"
    
    TIMESTAMP FORMAT: YYYY-MM-DD HH:MM:SS
    
    Args:
        message (str): Log message to record
        
    Side Effects:
        - Appends to log file on disk
        - May print to stdout based on mode
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] {message}"

    # Always write to log file
    with open(config.LOG_FILE, "a", encoding="utf-8") as f:
        f.write(entry + "\n")

    # NOTE: stdout output suppressed for determinism
    # All logging goes to file only


def safe_to_json(obj, depth=0, max_depth=5):
    """
    Robust recursive serializer for logging complex objects.
    
    Safely converts any Python object to a JSON-serializable format.
    Handles recursion limits, custom objects, callables, and unserializable types.
    
    SERIALIZATION RULES:
        1. Primitives (int, float, str, bool, None) pass through unchanged
        2. Lists and tuples become lists (elements recursively processed)
        3. Dicts become dicts (keys and values recursively processed)
        4. Objects with __dict__ become dicts of their attributes
        5. Callables become descriptive strings
        6. Unserializable types become "<unserializable: TypeName>"
    
    SAFETY FEATURES:
        - Depth limiting prevents infinite recursion on circular references
        - Graceful degradation for unserializable types
        - Preserves as much information as possible
    
    Args:
        obj: Any Python object to serialize
        depth (int): Current recursion depth (internal use)
        max_depth (int): Maximum allowed recursion depth (default 5)
        
    Returns:
        JSON-serializable representation of the object
    """
    if depth > max_depth:
        return "<recursion limit reached>"

    if obj is None:
        return None
    if isinstance(obj, (int, float, str, bool)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [safe_to_json(item, depth+1, max_depth) for item in obj]
    if isinstance(obj, dict):
        safe_dict = {}
        for k, v in obj.items():
            safe_key = safe_to_json(k, depth+1, max_depth) if not isinstance(k, str) else k
            safe_dict[safe_key] = safe_to_json(v, depth+1, max_depth)
        return safe_dict
    if hasattr(obj, '__dict__'):
        return safe_to_json(obj.__dict__, depth+1, max_depth)
    if hasattr(obj, '__str__'):
        return str(obj)
    if callable(obj):
        return f"<callable: {obj.__name__ if hasattr(obj, '__name__') else type(obj).__name__}>"
    return f"<unserializable: {type(obj).__name__}>"


def log_execution(goal: str, task_state: dict, results: list):
    """
    Record a complete execution record to the execution log.
    
    Persists goal, plan, completed steps, and final result for:
    - Debugging and troubleshooting
    - Execution replay and analysis
    - Audit trail and accountability
    
    EXECUTION RECORD FORMAT:
        {
            "goal": str,              # Original user goal
            "plan_text": list,        # Textual plan (legacy field)
            "plan_structured": list,   # Structured plan from planner
            "completed_steps": list,   # Steps that were executed
            "repair_history": dict,    # Tool repair attempts
            "result": any             # Final execution result
        }
    
    Args:
        goal (str): Original user goal
        task_state (dict): Complete task state including plan and progress
        results (list): All execution results from the run
        
    Side Effects:
        - Reads existing execution_log.json if present
        - Appends new record
        - Writes updated log to disk
    """
    path = config.EXECUTION_LOG

    record = {
        "goal": safe_to_json(goal),
        "plan_text": safe_to_json(task_state.get("plan", [])),
        "plan_structured": safe_to_json(task_state.get("original_structured_plan", [])),
        "completed_steps": safe_to_json(task_state.get("completed_steps", [])),
        "repair_history": safe_to_json(task_state.get("repair_history", {})),
        "result": safe_to_json(results[-1] if results else None)
    }

    try:
        data = []
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                except json.JSONDecodeError as e:
                    log(f"Corrupted execution_log.json detected: {str(e)}. Starting fresh.")
                    data = []

        data.append(record)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        log("Execution logged successfully")

    except Exception as e:
        log(f"Execution logging failed: {str(e)}")