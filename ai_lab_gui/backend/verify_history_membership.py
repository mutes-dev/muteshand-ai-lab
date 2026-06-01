"""Validate HistoryTab.jsx filter logic against actual /workflows/historical data."""
import urllib.request
import json

ACTIONABLE_HISTORY_EXCLUDED_STATUSES = {
    "ACTIVE", "PAUSED", "PENDING_RECOVERY", "QUEUED", "FAILED",
}

def should_show_in_all(w):
    retention = w.get("retention_state") or "retained"
    is_archived_or_dismissed = retention in ("archived", "dismissed")
    is_actionable = w.get("status") in ACTIONABLE_HISTORY_EXCLUDED_STATUSES
    return is_archived_or_dismissed or not is_actionable

req = urllib.request.Request("http://localhost:8000/workflows/historical")
with urllib.request.urlopen(req) as resp:
    data = json.loads(resp.read())

workflows = data.get("workflows", [])
print(f"TOTAL historical: {len(workflows)}")

all_visible = [w for w in workflows if should_show_in_all(w)]
archived = [w for w in workflows if w.get("archived") is True]
dismissed = [w for w in workflows if w.get("dismissed") is True]
terminal = [w for w in workflows if w.get("inspection_only") is True]

excluded = [w for w in workflows if not should_show_in_all(w)]

print(f"All visible:     {len(all_visible)}")
print(f"Archived:        {len(archived)}")
print(f"Dismissed:       {len(dismissed)}")
print(f"Terminal:        {len(terminal)}")
print(f"Excluded (actionable retained): {len(excluded)}")

if excluded:
    print("\nExcluded from All:")
    for w in excluded:
        print(f"  {w['workflow_id'][-8:]} status={w['status']:12s} retention={w.get('retention_state','retained')}")

print("\nIncluded in All (first 10):")
for w in all_visible[:10]:
    print(f"  {w['workflow_id'][-8:]} status={w['status']:12s} retention={w.get('retention_state','retained')} inspection_only={w.get('inspection_only')}")
