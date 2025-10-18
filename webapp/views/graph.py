from flask import Blueprint, Response, render_template
import sqlite3
import orjson

DB_PATH = "/home/ve2pcq/ve2fet/valar_database/valar.db"
bp = Blueprint("graph", __name__, url_prefix="/monitorgraph")

@bp.route("/")
def index():
    return render_template("monitorgraph.html")

@bp.route("/data")
def data():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT host,
               check_type,
               timestamp,
               response_time_ms,
               1 - success AS error
        FROM network_monitor_results
        ORDER BY timestamp
    """)
    rows = cur.fetchall()
    conn.close()
    payload = [
        {
          "host": host,
          "check_type": check_type,
          "ts": timestamp,
          "rt": response_time_ms or 0,
          "err": error
        }
        for host, check_type, timestamp, response_time_ms, error in rows
    ]
    return Response(
        orjson.dumps(payload),
        mimetype="application/json"
    )

