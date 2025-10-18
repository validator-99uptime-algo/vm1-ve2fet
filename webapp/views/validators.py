"""
validators.py  –  “Validator Owners” page + JSON API
This file is a Flask *Blueprint* so it can be plugged into app.py
without cramming every route into one file.
"""

from flask import Blueprint, render_template
import db, time                       # our existing helper
import requests

bp = Blueprint("validators", __name__)

# ──────────────────────────────────────────────────────────────
@bp.route("/")
def page():
    """HTML table of validator owners (was ‘home’ before)."""
    df    = db.get_validator_overview()
    rows  = df.to_dict(orient="records")
    total = {
        "ads"         : int(df.ads.sum()),
        "dels"        : int(df.dels.sum()),
        "stake_algo"  : df.stake_algo.sum(),
        "stake_usdc"  : df.stake_usdc.sum(),
        "grand_total" : df.grand_total.sum(),
        "fee_algo"    : df.fee_algo.sum(),
        "fee_usdc"    : df.fee_usdc.sum(),
    }

    # --- Custom: Calculate Fees ALGO/mo for specific owner, excluding beneficiaries ---
    OWNER_ADDR = "CMQ6VSWMFA2PPXOPKVRBBRJCF5W4QBXMS53LO66CY2MMN3XP25345HBVQA"
    EXCLUDE_BENS = {
        "4RUNMMPWW56YYTO2U5QYYTAHROOVQO4XY2NY5UUFONRG46SEMU35GHVQTM",
        "J4AHUYJ5AQKFW2XFL7T3TT73MYEMMJ73MUXCQGNGRJLAVDZFYR43DQSQUQ",
        "FRBNS6SG4X2RAO5OHRQED4TMVOXCZ5B65SLELF6XYBHYSSICM56J3Z3YEU",
        "5XXZWVTAVBEY4SBBCFUDQEMPM3MISMJ5DNFG6JBJDQZ6FI2PVQPZYF4JG4"
    }
    # Load delegator contracts (DataFrame)
    dels_df = db.get_delegator_overview()
    fees_filtered = dels_df[
        (dels_df["val_owner"] == OWNER_ADDR) &
        (~dels_df["beneficiary"].isin(EXCLUDE_BENS))
    ]["fee_num"].sum()


    # --- Also calculate filtered Fees USDC/mo for the same owner/exclusions ---
    USDC_ASSET_ID = 31566704  # (replace with your USDC asset id if different)
    usdc_fee_filtered = dels_df[
        (dels_df["val_owner"] == OWNER_ADDR) &
        (~dels_df["beneficiary"].isin(EXCLUDE_BENS)) &
        (dels_df["fee_asset_id"] == USDC_ASSET_ID)
    ]["fee_num"].sum()

    # --- Get ALGO/USD price from the price API (Coingecko or similar) ---
    try:
        algo_price = requests.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=algorand&vs_currencies=usd"
        ).json()["algorand"]["usd"]
    except Exception:
        algo_price = 0.0

    # --- Get USD to CAD exchange rate from exchangerate-api ---
    try:
        usd_cad = requests.get("https://open.er-api.com/v6/latest/USD").json()["rates"]["CAD"]
    except Exception:
        usd_cad = 0.0

    fee_usd = fees_filtered * algo_price
    fee_cad = fee_usd * usd_cad

    usdc_usd = usdc_fee_filtered  # (since USDC is pegged to USD 1:1)
    fee_usd_total = fee_usd + usdc_usd
    fee_cad_total = fee_usd_total * usd_cad


    return render_template(
        "validators.html",
        rows=rows,
        total=total,
        page_ts=int(time.time() * 1000),
        algo_fee_sum=fees_filtered,
        algo_price=algo_price,
        fee_usd=fee_usd,
        usd_cad=usd_cad,
        fee_cad=fee_cad,
        usdc_fee_filtered=usdc_fee_filtered,
        usdc_usd=usdc_usd,
        fee_usd_total=fee_usd_total,
        fee_cad_total=fee_cad_total
    )

    # Pass this value to the template as algo_fee_sum
    # return render_template(
    #    "validators.html",
    #    rows=rows,
    #    total=total,
    #    page_ts=int(time.time() * 1000),
    #    algo_fee_sum=fees_filtered
    #)


@bp.route("/api/validators")
def api():
    """Same data as JSON – useful for later Ajax refresh."""
    return db.get_validator_overview().to_json(orient="records")
