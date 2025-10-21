#!/usr/bin/env python3
# update_catchup_24h.py
# - Read ./all_vm_guid
# - Batch-query Grafana ClickHouse DS for CatchupStart counts (last 24h)
# - Update ./output/status/vm<N>.json with "catchup_last_24h": <int>
#   0  = true zero in last 24h
#   -1 = GUID missing or per-VM result error
# - Always exit 0 (don't break your collector's set -e)

import json, re, sys
from pathlib import Path
from urllib.request import Request, urlopen

BASE_DIR   = Path(__file__).resolve().parent
GUID_FILE  = BASE_DIR / "all_vm_guid"
STATUS_DIR = BASE_DIR / "output" / "status"

# Grafana constants (you confirmed these)
BASE    = "https://g.nodely.io"
ORG_ID  = "1"
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

def load_guid_map():
    m = {}
    try:
        text = GUID_FILE.read_text(encoding="utf-8", errors="replace")
    except Exception:
        print("update: ERROR reading all_vm_guid (marking all -1)")
        return m
    for line in text.splitlines():
        mo = GUID_RE.search(line)
        if mo:
            m[int(mo.group(1))] = mo.group(2).lower()
    return m

def build_payload(gmap):
    queries = []
    for vmn in range(1, 45):
        guid = gmap.get(vmn)
        if not guid:
            continue
        queries.append({
            "refId": f"VM{vmn}",
            "format": 1,                 # table
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
    frames = (result_obj or {}).get("frames") or []
    if frames:
        values = (frames[0].get("data") or {}).get("values") or []
        if values and values[0]:
            try:
                return int(float(values[0][0]))
            except Exception:
                return -1
        return 0
    return 0

def write_vm_json(vmn, count):
    p = STATUS_DIR / f"vm{vmn}.json"
    if not p.exists():
        print(f"[vm{vmn}] WARN status file missing; skipped")
        return
    try:
        obj = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:
        print(f"[vm{vmn}] ERROR reading JSON: {e}")
        return
    obj["catchup_last_24h"] = int(count) if isinstance(count, int) else -1
    try:
        p.write_text(json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"[vm{vmn}] catchup_last_24h={obj['catchup_last_24h']}")
    except Exception as e:
        print(f"[vm{vmn}] ERROR writing JSON: {e}")

def main():
    gmap = load_guid_map()
    results = {vmn: -1 for vmn in range(1, 45)}

    if gmap:
        try:
            obj = post_json(f"{BASE}/api/ds/query?ds_type={DS_TYPE}", build_payload(gmap))
            res = (obj.get("results") or {})
            for vmn in range(1, 45):
                if vmn not in gmap:
                    continue
                results[vmn] = extract_count(res.get(f"VM{vmn}"))
        except Exception as e:
            print(f"update: ERROR POST failed: {e}; marking all -1")

    for vmn in range(1, 45):
        write_vm_json(vmn, results[vmn])

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"update: UNEXPECTED ERROR: {e}")
        # swallow to exit 0
