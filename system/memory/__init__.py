"""
MEMORY PACKAGE — Phase 3A Global Memory System

Provides:
- global_memory: persistent advisory memory storage
- preference_tracker: pattern detection and write threshold
- memory_adapter: read/inject into agent context only

CONTRACT: MEMORY_STORAGE_CONTRACT_V1
- Memory is advisory only — NEVER influences execution_result
- Memory NEVER overrides governance decisions
- Memory MAY influence confidence ONLY
"""
