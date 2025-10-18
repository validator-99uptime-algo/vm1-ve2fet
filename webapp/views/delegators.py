# /home/ve2pcq/ve2fet/webapp/views/delegators.py

"""
delegators.py  –  Delegator Beneficiaries page
Accepts optional ?owner=<address> to filter by validator owner.
"""

from flask import Blueprint, render_template, request
import time
import db

bp = Blueprint("delegators", __name__, url_prefix="/delegators")

@bp.route("/")
def page():
    # ─── get a DataFrame of all delegator rows ────────────────────────────────
    df = db.get_delegator_overview()

    # ─── if ?owner= was provided, filter by validator owner ─────────────────
    owner = request.args.get("owner")
    if owner:
        df = df[df["val_owner"] == owner]

    # ─── convert to a list-of-dicts for Jinja ───────────────────────────────
    rows = df.to_dict(orient="records")

    # ─── compute the two totals we want: sum of algo_balance + row count ─────
    total_algo   = df["algo_balance"].sum()
    total_rows   = len(df)

    # ─── build a "totals" dict whose keys match exactly the column-names in 'rows'
    # NOTE: The order here must exactly match the order of your <th> in delegators.html.
    totals = {
        "beneficiary"  : "TOTAL",
        "state"        : "",
        "algo_balance" : f"{total_algo:,.2f}",   # show with two decimals
        "fee_str"      : "",                     # blank under "fee_str"
        "expiry"       : "",
        "days_left"    : "",
        "del_id"       : total_rows              # total number of rows
    }
    return render_template(
        "delegators.html",
        rows=rows,
        totals=totals,
        page_ts=int(time.time() * 1000))

@bp.route("/api")
def api():
    return db.get_delegator_overview().to_json(orient="records")
