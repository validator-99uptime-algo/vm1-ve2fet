#!/usr/bin/env python3
# test_batch_catchup_24h.py
# - Reads ./all_vm_guid
# - Sends a single Grafana datasource POST with 44 queries
# - Prints "vm<N> <count>" (0 if real zero, -1 on error/missing)

import json, re, sys
from pathlib import Path
from urllib.request import Request, urlopen

# ---- Grafana / datasource constants (from your Inspect JSON)
BASE = "https://g.nodely.io"
ORG_ID = "1"
DS_TYPE = "grafana-clickhouse-datasource"
DS_UID  = "ef3cbeeb-9fbe-48b0-a068-1cc8cfb61461"

HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "X-Grafana-Org-Id": ORG_ID,
    "User-Agent": "Python-urllib",
}

SQL_TPL = (
    "SELECT count() AS c "
    "FROM algonode.telemetry_4160 "
    "WHERE uuid = '{guid}' "
    "AND ts >= now() - INTERVAL 24 HOUR AND ts < now() "
    "AND endsWith(event, 'CatchupStart');"
)

GUID_RE = re.compile(r"(?i)\bGuid\s*VM\s*(\d+)\s*=\s*([0-9a-f-]{36})\b")

def load_guid_map(file_path: Path):
    text = file_path.read_text(encoding="utf-8", errors="replace")
    m = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        mo = GUID_RE.search(line)
        if mo:
            vmn = int(mo.group(1))
            guid = mo.group(2).lower()
            m[vmn] = guid
    return m

def build_payload(guid_map):
    queries = []
    for vmn in range(1, 45):
        guid = guid_map.get(vmn)
        if not guid:
            continue
        ref = f"VM{vmn}"
        queries.append({
            "refId": ref,
            "format": 1,              # table
            "queryType": "table",
            "datasource": {"uid": DS_UID, "type": DS_TYPE},
            "rawSql": SQL_TPL.format(guid=guid),
        })
    return {"from": "now-24h", "to": "now", "queries": queries}

def post_json(url, payload):
    data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, headers=HEADERS, method="POST")
    with urlopen(req, timeout=45) as r:
        enc = r.headers.get_content_charset() or "utf-8"
        return json.loads(r.read().decode(enc, "replace"))

def extract_count(result_obj):
    # Prefer "frames" table format
    frames = (result_obj or {}).get("frames") or []
    if frames:
        data = frames[0].get("data") or {}
        values = data.get("values") or []
        if values and values[0]:
            try:
                return int(float(values[0][0]))
            except Exception:
                return -1
        # If explicit zero rows, it's a real 0
        return 0
    # Fallback "series" format (not expected for table)
    series = (result_obj or {}).get("series") or []
    if series and series[0].get("points"):
        try:
            return int(float(series[0]["points"][0][0]))
        except Exception:
            return -1
    return 0  # treat as zero when the DS returns an empty table

def main():
    base_dir = Path(__file__).resolve().parent
    guid_file = base_dir / "all_vm_guid"
    if not guid_file.exists():
        print("ERROR: all_vm_guid not found next to the script", file=sys.stderr)
        sys.exit(2)

    gmap = load_guid_map(guid_file)
    # Pre-fill all results with -1; replace when we have data or known zero
    results = {vmn: -1 for vmn in range(1, 45)}

    payload = build_payload(gmap)
    try:
        obj = post_json(f"{BASE}/api/ds/query?ds_type={DS_TYPE}", payload)
        res = (obj.get("results") or {})
        # Fill from API for GUIDs we queried
        for vmn in range(1, 45):
            ref = f"VM{vmn}"
            if vmn not in gmap:
                # GUID missing → keep -1
                continue
            r = res.get(ref)
            if r is None:
                # Ref missing in response → error for that VM
                results[vmn] = -1
                continue
            results[vmn] = extract_count(r)
    except Exception:
        # Network/endpoint failure → keep -1 for all
        pass

    # Print in order
    for vmn in range(1, 45):
        print(f"vm{vmn} {results[vmn]}")

if __name__ == "__main__":
    main()
