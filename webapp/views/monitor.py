from flask import Blueprint, render_template
import sqlite3

DB_PATH = "/home/ve2pcq/ve2fet/valar_database/valar.db"

bp = Blueprint("monitor", __name__, url_prefix="/monitor")

@bp.route("/")
def index():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT host, check_type, timestamp, success, response_time_ms, error_message
        FROM network_monitor_results
        ORDER BY timestamp DESC
    """)
    rows = cur.fetchall()
    conn.close()
    return render_template("monitor.html", rows=rows)
