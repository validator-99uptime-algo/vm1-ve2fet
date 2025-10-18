#!/usr/bin/env python3
# ve2fet_network_monitor.py

import os
import sys
import time
import logging
import threading
import subprocess
import requests
import sqlite3
import re
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "ve2fet_network_monitor.config")
LOG_FILE = os.path.join(SCRIPT_DIR, "ve2fet_network_monitor.log")
DB_PATH = "/home/ve2pcq/ve2fet/valar_database/valar.db"

logging.basicConfig(
    filename=LOG_FILE,
    filemode='a',
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger("monitor")

def save_result(host, check_type, success, response_time_ms, error_message):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO network_monitor_results (host, check_type, timestamp, success, response_time_ms, error_message) VALUES (?, ?, ?, ?, ?, ?)",
            (host, check_type, datetime.now(timezone.utc).isoformat(), int(success), response_time_ms, error_message)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log.error("DB insert failed for %s %s: %s", host, check_type, str(e))

# Track running ping subprocesses
LEFTOVER_PROCS = []
LEFTOVER_PROCS_LOCK = threading.Lock()

def cleanup_leftover_procs():
    to_remove = []
    count = 0
    with LEFTOVER_PROCS_LOCK:
        for pinfo in list(LEFTOVER_PROCS):
            proc = pinfo["proc"]
            host = pinfo["host"]
            check_type = pinfo["check_type"]
            start = pinfo["start_time"]
            if proc.poll() is None:
                # Still running—considered leftover
                duration = int(time.time() - start)
                log.warning("Leftover process PID %d for %s [%s] running for %ds - KILLING", proc.pid, host, check_type, duration)
                try:
                    proc.kill()
                    log.info("Killed leftover process PID %d for %s [%s]", proc.pid, host, check_type)
                except Exception as e:
                    log.error("Could not kill process PID %d: %s", proc.pid, str(e))
                to_remove.append(pinfo)
                count += 1
            else:
                to_remove.append(pinfo)
        for x in to_remove:
            LEFTOVER_PROCS.remove(x)
    log.info("Scan start: %d leftover processes", count)

def read_config():
    targets = []
    interval = 30
    with open(CONFIG_FILE, "r") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if s.lower().startswith("interval="):
                try:
                    interval = int(s.split("=")[1])
                except:
                    log.error("Bad interval line: %s", s)
                continue
            parts = [p.strip() for p in s.split(",")]
            if len(parts) != 3:
                log.error("Bad config line: %s", s)
                continue
            targets.append({
                "host": parts[0],
                "type": parts[1].lower(),
                "timeout": int(parts[2])
            })
    return interval, targets

def check_ping(host, timeout, result_list, proc_track):
    try:
        proc = subprocess.Popen(
            ["ping", "-c", "1", "-W", str(timeout), host],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        proc_track["proc"] = proc
        with LEFTOVER_PROCS_LOCK:
            LEFTOVER_PROCS.append(proc_track)
        try:
            stdout, stderr = proc.communicate(timeout=timeout + 2)
        except subprocess.TimeoutExpired:
            proc.kill()
            result_list.append((host, "ping", False, None, "timeout"))
            # Remove process after handling
            with LEFTOVER_PROCS_LOCK:
                if proc_track in LEFTOVER_PROCS:
                    LEFTOVER_PROCS.remove(proc_track)
            return
        if proc.returncode == 0:
            out_text = stdout.decode()
            match = re.search(r'=\s*([\d\.]+)/([\d\.]+)/([\d\.]+)/([\d\.]+)\s*ms', out_text)
            if match:
                avg_ms = float(match.group(2))
                result_list.append((host, "ping", True, avg_ms, None))
            else:
                for line in out_text.splitlines():
                    if "time=" in line:
                        ms = line.split("time=")[1].split()[0]
                        ms_val = float(ms)
                        result_list.append((host, "ping", True, ms_val, None))
                        break
                else:
                    result_list.append((host, "ping", True, None, None))
        else:
            msg = stderr.decode().strip() or stdout.decode().strip()
            result_list.append((host, "ping", False, None, msg))
        # Remove process after completion
        with LEFTOVER_PROCS_LOCK:
            if proc_track in LEFTOVER_PROCS:
                LEFTOVER_PROCS.remove(proc_track)
    except Exception as e:
        result_list.append((host, "ping", False, None, str(e)))
        with LEFTOVER_PROCS_LOCK:
            if proc_track in LEFTOVER_PROCS:
                LEFTOVER_PROCS.remove(proc_track)

def check_https(host, timeout, result_list):
    url = "https://" + host
    try:
        start = time.time()
        resp = requests.get(url, timeout=timeout)
        elapsed = round((time.time() - start) * 1000, 3)
        if resp.status_code == 200:
            result_list.append((host, "https", True, elapsed, None))
        elif 400 <= resp.status_code < 500:
            # Not a network error—just a 401/403/404 etc
            result_list.append((host, "https", True, elapsed, f"HTTP {resp.status_code}"))
        else:
            # 5xx or other: server problem
            result_list.append((host, "https", False, elapsed, f"HTTP {resp.status_code}"))
    except requests.Timeout:
        result_list.append((host, "https", False, None, "timeout"))
    except Exception as e:
        result_list.append((host, "https", False, None, str(e)))

def main():
    log.info("Monitor starting")
    while True:
        interval, targets = read_config()
        cleanup_leftover_procs()
        results = []
        threads = []
        proc_infos = []

        for tgt in targets:
            if tgt["type"] == "ping":
                proc_info = {
                    "host": tgt["host"],
                    "check_type": "ping",
                    "start_time": time.time(),
                    "proc": None
                }
                thread = threading.Thread(target=check_ping, args=(tgt["host"], tgt["timeout"], results, proc_info))
                threads.append(thread)
                proc_infos.append(proc_info)
            elif tgt["type"] == "https":
                thread = threading.Thread(target=check_https, args=(tgt["host"], tgt["timeout"], results))
                threads.append(thread)

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()


        for r in results:
            host, ctype, success, ms, msg = r
            if ctype == "https" and success and msg and msg.startswith("HTTP"):
                # HTTP 401/403/404, etc: info only
                log.info("%s [%s] HTTP response: %s in %.3fms", host, ctype, msg, ms if ms is not None else -1)
            elif success:
                log.info("%s [%s] success in %sms", host, ctype, ms if ms is not None else "?")
            else:
                log.error("%s [%s] failed: %s", host, ctype, msg)
            save_result(host, ctype, success, ms, msg)

        log.info("Scan complete")
        time.sleep(interval)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Monitor stopped by user")
        sys.exit(0)
    except Exception as e:
        log.error("Fatal error: %s", str(e))
        sys.exit(1)
