#!/usr/bin/env python3
import json, sys, urllib.request

BASE = "https://g.nodely.io"
ORG_ID = "1"
DS_TYPE = "grafana-clickhouse-datasource"
DS_UID  = "ef3cbeeb-9fbe-48b0-a068-1cc8cfb61461"
GUID    = "262b3385-0f43-4a6f-9df8-addb08608ba9"

SQL = lambda hours: (
    "SELECT count() AS c "
    "FROM algonode.telemetry_4160 "
    f"WHERE uuid = '{GUID}' "
    f"AND ts >= now() - INTERVAL {hours} HOUR AND ts < now() "
    "AND endsWith(event, 'CatchupStart');"
)

HEADERS = {
    "User-Agent": "Python-urllib",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "X-Grafana-Org-Id": ORG_ID,
}

def post(payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"{BASE}/api/ds/query?ds_type={DS_TYPE}", data=data, headers=HEADERS, method="POST")
    with urllib.request.urlopen(req, timeout=45) as r:
        body = r.read()
        enc = r.headers.get_content_charset() or "utf-8"
        text = body.decode(enc, "replace")
        return r.status, text

def extract_count(text):
    try:
        obj = json.loads(text)
        res = (obj.get("results") or {}).get("A") or {}
        # frames format
        frames = res.get("frames") or []
        if frames:
            vals = (frames[0].get("data") or {}).get("values") or []
            for col in vals:
                if col:
                    return int(float(col[0]))
        # series fallback
        series = res.get("series") or []
        if series and series[0].get("points"):
            return int(float(series[0]["points"][0][0]))
    except Exception:
        pass
    return 0

def run(hours, label):
    payload = {
        "from": f"now-{hours}h", "to": "now",
        "queries": [{
            "refId": "A", "format": 1, "queryType": "table",
            "datasource": {"uid": DS_UID, "type": DS_TYPE},
            "rawSql": SQL(hours)
        }]
    }
    status, text = post(payload)
    print(f"HTTP {status} ({label}) raw[0:220]: {text[:220].replace(chr(10),' ')}")
    print(f"{label} {extract_count(text)}")

def main():
    run(2, "2h")
    run(1, "1h")

if __name__ == "__main__":
    main()
