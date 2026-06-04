"""
MEMORY PACKAGE — Sprint 6 Memory Foundation

Provides:
- schema: canonical memory entry schema and validation (ISSUE-076)
- memory_store: unified GLOBAL + PROJECT storage primitives (ISSUE-076)
- global_memory: legacy Phase 3A persistent advisory memory storage
- preference_tracker: pattern detection and write threshold (Phase 3A)
- memory_adapter: read/inject into agent context only (Phase 3A)

CONTRACT: MEMORY_STORAGE_CONTRACT_V1
- Memory is advisory only — NEVER influences execution_result
- Memory NEVER overrides governance decisions
- Memory MAY influence confidence ONLY
"""
