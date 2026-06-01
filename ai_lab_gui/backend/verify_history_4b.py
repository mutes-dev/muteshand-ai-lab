import urllib.request, json

with urllib.request.urlopen('http://localhost:8000/workflows/historical', timeout=10) as r:
    data = json.loads(r.read().decode())
    wfs = data.get('workflows', [])
    print('HISTORICAL total:', len(wfs))
    for i, w in enumerate(wfs[:5]):
        print(f'  [{i}] {w["workflow_id"][-8:]}  status={w["status"]:<10}  updated_at={w.get("updated_at", "none")}')
