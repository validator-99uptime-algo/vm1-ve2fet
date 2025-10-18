from flask import Blueprint, render_template, request
import subprocess, html, re

bp = Blueprint("winners1", __name__)

PYTHON = "/home/ve2pcq/ve2fet/venv/bin/python3"
SCRIPT = "/home/ve2pcq/ve2fet/dev/valar_winnersWO42npV2.py"
# SCRIPT = "/home/ve2pcq/ve2fet/dev/valar_winners_usdc.py"

ANSI_RED = "\x1b[1;31m"
ANSI_YELLOW = "\x1b[1;33m"
ANSI_RESET = "\x1b[0m"

def _run_script(days: int):
    cmd = [PYTHON, SCRIPT, "--days", str(days)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    out = (r.stdout or "") + (("\n" + r.stderr) if r.returncode else "")
    out = html.escape(out)
    out = out.replace(ANSI_RED, '<span class="ansi-red">')
    out = out.replace(ANSI_YELLOW, '<span class="ansi-yellow">')
    out = out.replace(ANSI_RESET, "</span>")
    out = re.sub(r"\x1b\[[0-9;]*m", "", out)
    return out

@bp.route("/winners1")
def winners1():
    # default to 30 if no ?days= is provided
    days = request.args.get("days", default=30, type=int)
    return render_template("winners1.html", content=_run_script(days))

@bp.route("/winners1/<int:days>")
def winners1_days(days: int):
    return render_template("winners1.html", content=_run_script(days))
