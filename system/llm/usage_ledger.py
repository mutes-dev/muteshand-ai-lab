"""
LLM Usage Ledger — Append-Only, Failure-Isolated

Records one JSON line per LLM attempt.
Path: memory/llm_usage_ledger.jsonl
"""

import os
import json
from datetime import datetime, timezone
from pathlib import Path

LEDGER_PATH = Path(os.getenv("MH_BASE_PATH", ".")) / "memory" / "llm_usage_ledger.jsonl"


def _ensure_dir():
    try:
        LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def record_usage(entry: dict) -> None:
    """
    Append a single usage event to the ledger.
    FAILURE-ISOLATED: Any exception is silently absorbed.
    """
    try:
        _ensure_dir()
        line = json.dumps(entry, default=str)
        with open(LEDGER_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def query_usage(since_iso: str = None, caller_role: str = None) -> list:
    """
    Read ledger entries. Returns list of dicts.
    Safe to call even if ledger does not exist yet.
    """
    results = []
    if not LEDGER_PATH.exists():
        return results
    try:
        with open(LEDGER_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if since_iso and entry.get("timestamp_iso", "") < since_iso:
                    continue
                if caller_role and entry.get("caller_role") != caller_role:
                    continue
                results.append(entry)
    except Exception:
        pass
    return results


def compute_daily_usage_usd(date_iso: str = None) -> float:
    """
    Sum estimated_cost_usd for entries on date_iso (YYYY-MM-DD).
    Defaults to today.
    """
    if date_iso is None:
        date_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    entries = query_usage(since_iso=f"{date_iso}T00:00:00")
    total = 0.0
    for e in entries:
        ts = e.get("timestamp_iso", "")
        if not ts.startswith(date_iso):
            continue
        total += float(e.get("estimated_cost_usd", 0) or 0)
    return round(total, 6)


def compute_monthly_usage_usd(year_month: str = None) -> float:
    """
    Sum estimated_cost_usd for entries in year_month (YYYY-MM).
    Defaults to current month.
    """
    if year_month is None:
        year_month = datetime.now(timezone.utc).strftime("%Y-%m")
    entries = query_usage(since_iso=f"{year_month}-01T00:00:00")
    total = 0.0
    for e in entries:
        ts = e.get("timestamp_iso", "")
        if not ts.startswith(year_month):
            continue
        total += float(e.get("estimated_cost_usd", 0) or 0)
    return round(total, 6)


def query_recent(limit: int = 10) -> list:
    """
    Return the most recent N ledger entries, newest first.
    Safe to call even if ledger does not exist yet.
    """
    results = []
    if not LEDGER_PATH.exists():
        return results
    try:
        with open(LEDGER_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                results.append(entry)
    except Exception:
        pass
    # Return newest last, so reverse and take limit
    results.reverse()
    return results[:limit]


def query_workflow(workflow_id: str, limit: int = 50) -> list:
    """
    Return the most recent N ledger entries for a specific workflow_id.
    Safe to call even if ledger does not exist yet.
    Returns entries newest-first.
    """
    results = []
    if not LEDGER_PATH.exists():
        return results
    try:
        with open(LEDGER_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("workflow_id") != workflow_id:
                    continue
                results.append(entry)
    except Exception:
        pass
    # Return newest last, so reverse and take limit
    results.reverse()
    return results[:limit]
