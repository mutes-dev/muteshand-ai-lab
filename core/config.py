"""
Core Configuration Module

PURPOSE:
    Centralizes all system configuration constants and paths for the AI Lab system.
    Provides a single source of truth for file paths, operational limits, and mode settings.

ARCHITECTURE ROLE:
    - Infrastructure layer: Provides configuration to all other modules
    - No business logic - only configuration data
    - Cross-platform path handling (Windows vs Unix)

LAYER RESPONSIBILITY:
    - Path resolution for all system directories
    - Operational constants (max steps, retries, thresholds)
    - Runtime mode configuration (debug, normal, quiet)

USAGE:
    All modules should import config from this module:
    from core.config import config
    
    Then access configuration via attributes:
    config.BASE_PATH, config.LOG_FILE, etc.
"""

import os
from typing import Literal

# Base path resolution - Windows vs Unix compatibility
BASE_PATH = os.path.abspath("E:/MutesHand") if os.name == "nt" else os.path.expanduser("~/AI_Lab - Copy")


class Config:
    """
    Central configuration container for the AI Lab system.
    
    ATTRIBUTES:
        MODE (Literal): Runtime mode - "debug", "normal", or "quiet"
            - debug: Verbose logging to console and file
            - normal: Standard output for interactive use
            - quiet: Minimal output, only final answers
            
        BASE_PATH (str): Root directory of the AI Lab installation
        
        LOG_FILE (str): Path to the manager log file
        
        MEMORY_FILE (str): Path to system memory/state persistence
        
        EXECUTION_LOG (str): Path to structured execution history
        
        TOOLS_PATH (str): Directory containing tool implementations
        
        AGENTS_PATH (str): Directory containing agent implementations
        
        AGENT_REGISTRY_PATH (str): Path to agent capability registry
        
        TOOL_INDEX_FILE (str): Path to tool metadata index
        
        MAX_STEPS (int): Maximum execution steps per goal (safety limit)
        
        MAX_REPLANS (int): Maximum replanning attempts after failure
        
        MAX_REPAIR_ATTEMPTS (int): Maximum tool repair attempts before giving up
        
        DRIFT_THRESHOLD (int): Number of plan deviations before drift warning
    """
    
    # Runtime mode - controls verbosity and output behavior
    MODE: Literal["debug", "normal", "quiet"] = "debug"
    
    # Core paths - derived from BASE_PATH
    BASE_PATH = BASE_PATH
    LOG_FILE = os.path.join(BASE_PATH, "logs", "manager.log")
    MEMORY_FILE = os.path.join(BASE_PATH, "memory", "system_map.json")
    EXECUTION_LOG = os.path.join(BASE_PATH, "memory", "execution_log.json")
    TOOLS_PATH = os.path.join(BASE_PATH, "tools")
    AGENTS_PATH = os.path.join(BASE_PATH, "agents")
    AGENT_REGISTRY_PATH = os.path.join(BASE_PATH, "memory", "agent_registry.json")
    TOOL_INDEX_FILE = os.path.join(BASE_PATH, "memory", "tool_index", "tools.json")

    # Operational limits - safety boundaries for execution
    MAX_STEPS = 50           # Prevent infinite loops in execution
    MAX_REPLANS = 2          # Limit replanning to avoid cycling
    MAX_REPAIR_ATTEMPTS = 3  # Cap repair attempts per tool
    DRIFT_THRESHOLD = 3      # Alert after this many plan deviations


# Singleton instance - all modules import this config object
config = Config()