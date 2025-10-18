# ~/ve2fet/webapp/db.py
import os, sqlite3
from pathlib import Path
import pandas as pd
from algosdk.v2client import algod

# ─── config ──────────────────────────────────────────────────────────────
DB_PATH    = os.getenv("VALAR_DB",
                       str(Path.home() / "ve2fet/valar_database/valar.db"))
ALGOD_ADDR = "http://localhost:8080"
ALGOD_TOKEN= "f9ba7e6e74c2a8d5c76acb3f0e6880e4dbc834f3006b154888baaa33687ef690"

μALGO   = 1_000_000
USDC_ID = 31566704                    # your Valar USDC ASA id
SECONDS_PER_ROUND = 2.8            # used twice below


# ─── helpers ─────────────────────────────────────────────────────────────
def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# NEW: convert list[sqlite3.Row] → DataFrame with proper column names -----
def _df(rows):
    """rows → pandas.DataFrame (ensures column names are strings)."""
    return pd.DataFrame([dict(r) for r in rows])

_algo = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDR)

def _algo_balance(addr: str) -> float:
    try:
        info = _algo.account_info(addr)
        return (info["amount"] - info["min-balance"]) / μALGO
    except Exception:
        return 0.0                     # node offline ⇒ treat as 0

def _ensure_owner(df: pd.DataFrame) -> pd.DataFrame:
    """
    Guarantee a column literally called `val_owner`.
    """
    if "val_owner" in df.columns:
        return df

    cand = next(
        (c for c in df.columns
         if isinstance(c, str)
         and ("owner" in c.lower() or "manager" in c.lower())),
        None
    )
    if cand:
        return df.rename(columns={cand: "val_owner"})

    raise KeyError(
        "`val_owner` column not found; columns returned: "
        f"{list(df.columns)}"
    )

# ─── main API ────────────────────────────────────────────────────────────
def get_validator_overview() -> pd.DataFrame:
    with _connect() as conn:
        ads_rows  = conn.execute("SELECT * FROM validator_ads").fetchall()
        dels_rows = conn.execute(
            """
             SELECT d.del_beneficiary,
                   d.fee_asset_id,
                   d.fee_round_milli,
                   d.round_end,
                   a.*
            FROM   delegator_contracts AS d
            JOIN   validator_ads       AS a
                   ON a.ad_id = d.validator_ad_app_id
            """
        ).fetchall()

    # adverts -------------------------------------------------------------
    ads_df   = _ensure_owner(_df(ads_rows))
    ad_count = (ads_df.groupby("val_owner")
                        .size()
                        .rename("ads")
                        .to_frame())

    # delegators ----------------------------------------------------------
    if dels_rows:
        dels_df = _ensure_owner(_df(dels_rows))

        # ── keep only delegators whose contract is still live ──────────
        try:
            last_round = _algo.status().get("last-round", 0)
        except Exception:
            last_round = 0                    # node offline → keep them all

        dels_df = dels_df[dels_df["round_end"] >= last_round]

        # live balance ----------------------------------------------------
        dels_df["bal_algo"] = dels_df["del_beneficiary"].apply(_algo_balance)

        stake_algo = (dels_df[dels_df.fee_asset_id == 0]
                      .groupby("val_owner").bal_algo.sum()
                      .rename("stake_algo"))

        stake_usdc = (dels_df[dels_df.fee_asset_id == USDC_ID]
                      .groupby("val_owner").bal_algo.sum()
                      .rename("stake_usdc"))

        del_count  = (dels_df.groupby("val_owner")
                              .size()
                              .rename("dels"))

        # ---------- NEW ➜ fee columns  ----------------------------------
        rounds_pm = int((30*24*3600) / SECONDS_PER_ROUND)   # ≈ 926 000
        µ         = 1_000_000

        dels_df["fee_num"] = dels_df["fee_round_milli"] * rounds_pm / 1000 / µ

        fee_algo = (dels_df[dels_df.fee_asset_id == 0]
                    .groupby("val_owner").fee_num.sum()
                    .rename("fee_algo"))

        fee_usdc = (dels_df[dels_df.fee_asset_id == USDC_ID]
                    .groupby("val_owner").fee_num.sum()
                    .rename("fee_usdc"))
        # ---------------------------------------------------------------

        stakes = pd.concat(
            [del_count, stake_algo, stake_usdc, fee_algo, fee_usdc],  # NEW ➜
            axis=1
        ).fillna(0)
    else:
        stakes = pd.DataFrame(
            columns=["dels", "stake_algo", "stake_usdc", "fee_algo", "fee_usdc"]
        )

    # merge & final touches ----------------------------------------------
    df = (ad_count
          .merge(stakes, how="left",
                 left_index=True, right_index=True)
          .fillna(0))

    df["grand_total"]  = df.stake_algo + df.stake_usdc
    df["algo_balance"] = df.index.to_series().apply(_algo_balance)

    # NFD lookup ----------------------------------------------------------
    df["nfd_name"], df["nfd_avatar"] = zip(
        *df.index.to_series().map(nfd_lookup)
    )

    df.reset_index(inplace=True)      # expose val_owner column
    return df.sort_values("grand_total", ascending=False)

# ─────── safer replacement (shadowing the first version) ────────────────
def get_delegator_overview() -> pd.DataFrame:
    """
    One row per delegator-beneficiary with live ALGO balance, monthly fee,
    expiry date, …  (robust against Algod being down.)
    """
    import datetime, math, pandas as pd

    with _connect() as conn:
        state_map = {r["code"]: r["label"]
                     for r in conn.execute(
                         "SELECT code,label FROM delegator_states")}

        # ── NOTE: we now prefix "state" with "d." to avoid ambiguity ─────────
        sql = """

            SELECT
              d.del_id,
              d.validator_ad_app_id AS ad_id,
              d.del_beneficiary,
              d.state AS del_state,
              d.staking_status,
              d.round_end,
              d.created_at_round,
              d.fee_round_milli,
              d.fee_asset_id,
              a.val_owner,
              s.apy_7d,
              s.apy_total
            FROM delegator_contracts AS d
            JOIN validator_ads AS a
              ON a.ad_id = d.validator_ad_app_id
            LEFT JOIN delegator_contract_stats AS s
              ON d.del_id = s.del_id
        """
        dels = conn.execute(sql).fetchall()

    if not dels:
        return pd.DataFrame()

    SECONDS_PER_ROUND = 2.8
    µ                 = 1_000_000
    rounds_pm         = int((30 * 24 * 3600) / SECONDS_PER_ROUND)

    # ── ask the node ONCE – or fall back gracefully ──────────────────
    try:
        last_round = _algo.status().get("last-round", 0)
    except Exception:
        last_round = 0  # node unreachable – still works

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    rows    = []

    for r in dels:
        addr  = r["del_beneficiary"]
        bal_A = _algo_balance(addr)

        fee_raw = math.ceil(r["fee_round_milli"] * rounds_pm / 1000)
        if r["fee_asset_id"] == 0:
            fee_str = f"{fee_raw/µ:,.2f}A"
        elif r["fee_asset_id"] == USDC_ID:
            fee_str = f"{fee_raw/µ:,.2f}US"
        else:
            fee_str = "-"

        exp_dt = now_utc + datetime.timedelta(
            seconds=(r["round_end"] - last_round) * SECONDS_PER_ROUND)

        crt_dt = now_utc - datetime.timedelta(
            seconds=(last_round - r["created_at_round"]) * SECONDS_PER_ROUND)

        # --- validator NFD & fallback text ---
        nfd_name, nfd_avatar = nfd_lookup(r["val_owner"])
        short_addr = r["val_owner"][:10] + "…"

        # ── use r["del_state"] to look up state_map ──────────────────
        rows.append({
            "beneficiary" : addr,
            "state"       : state_map.get(r["del_state"],
                              f"0x{r['del_state']:02x}"),
            "staking_status": (r["staking_status"] or ""),
            "algo_balance": bal_A,
            "fee_str"     : fee_str,
            "fee_num" : fee_raw / µ,
            "created"     : crt_dt.strftime("%Y-%m-%d %H:%M"),
            "expiry"      : exp_dt.strftime("%Y-%m-%d %H:%M"),
            "days_left"   : (exp_dt - now_utc).days,
            "ad_id": r["ad_id"],
            "del_id"      : r["del_id"],
            "val_owner"   : r["val_owner"],
            "val_nfd_name": nfd_name,
            "val_nfd_avatar": nfd_avatar,
            "val_owner_short": short_addr,
            "fee_asset_id": r["fee_asset_id"],
            "apy_7d": r["apy_7d"] if r["apy_7d"] is not None else 0.0,
            "apy_total": r["apy_total"] if r["apy_total"] is not None else 0.0,
        })

    df = pd.DataFrame(rows)          # ← new line ①  build DataFrame
    df = df[df["days_left"] >= 0]    # ← new line ②  keep only non-expired
    return df.sort_values("algo_balance", ascending=False)   # ← use df here
#    return pd.DataFrame(rows).sort_values("algo_balance", ascending=False)

# ─── NFD (Name + avatar) lookup ───────────────────────────────────────────
import requests, functools, json

@functools.lru_cache(maxsize=256)
def nfd_lookup(address: str):
    """
    Return (name, avatar_url) via api.nf.domains.
    • supports both list- and dict-style responses
    • converts avatarasaid → images.nf.domains URL
    • converts ipfs://… → https://ipfs.io/ipfs/…
    """
    url = f"https://api.nf.domains/nfd/lookup?address={address}&view=thumbnail"
    try:
        data = requests.get(url, timeout=3).json()
        # pick the entry ------------------------------
        if isinstance(data, list):
            entry = data[0] if data else None
        elif isinstance(data, dict):
            entry = data.get(address) or next(iter(data.values()), None)
        else:
            entry = None
        if not entry:
            return None, None

        name  = entry.get("name")
        props = entry.get("properties", {})
        avatar = (
            props.get("verified", {}).get("avatar") or
            props.get("userDefined", {}).get("avatar")
        )

        # avatarasaid fallback → serve through NFD image CDN
        if not avatar:
            asaid = (
                props.get("verified", {}).get("avatarasaid") or
                props.get("userDefined", {}).get("avatarasaid")
            )
            if asaid:
                avatar = f"https://images.nf.domains/asset/{asaid}"


        # ipfs:// → NFD’s own gateway
        if avatar and avatar.startswith("ipfs://"):
            cid = avatar.removeprefix("ipfs://")
            avatar = f"https://images.nf.domains/ipfs/{cid}"

        return name, avatar
    except Exception:
        return None, None

# ─── single-ad lookup ────────────────────────────────────────────────
def get_validator_ad(ad_id: int) -> dict | None:
    import math
    µ = 1_000_000

    ROUNDS_PM = int((30*24*3600) / 2.8)      # ≈ 926 000

    # map *integer* codes to labels
    state_map = {
        0x00: "NONE", 0x01: "CREATED", 0x02: "TEMPLATE_LOAD",
        0x03: "TEMPLATE_LOADED", 0x04: "SET", 0x05: "READY",
        0x06: "NOT_READY", 0x07: "NOT_LIVE"
    }

    with _connect() as c:
        r = c.execute("SELECT * FROM validator_ads WHERE ad_id = ?", (ad_id,)).fetchone()
    if not r:
        return None

    # ── translate the TEXT "05" → 0x05 integer before lookup
    try:
        state_code = int(r["state"], 16)        # e.g. "05" → 5
    except Exception:
        state_code = None                       # fallback if malformed


    setup_fee = r["fee_setup"] / µ

    # field is stored in *milli-µALGO*, so divide by 10 after scaling
    min_month = r["fee_round_min"]  * ROUNDS_PM / 1000 / µ 
    var_month = r["fee_round_var"]  * ROUNDS_PM / 1000 / µ / 10

    nfd_name, nfd_avatar = nfd_lookup(r["val_owner"])

    return {
        "ad_id"       : ad_id,
        "owner_addr"  : r["val_owner"],
        "nfd_name"    : nfd_name,
        "nfd_avatar"  : nfd_avatar,

        "state_text"  : state_map.get(state_code, "UNKNOWN"),
        "del_cnt"     : r["cnt_del"],
        "del_max"     : r["cnt_del_max"],

        "currency"    : "USDC" if r["fee_asset_id"] else "ALGO",
        "setup_fee"   : f"{setup_fee:,.2f}",
        "min_fee"     : f"{min_month:,.2f}",
        "var_fee"     : f"{var_month:,.2f}",

        "max_stake"   : f"{r['stake_max']/µ:,.0f}",
        "gratis_pct"  : f"{r['gratis_stake_ppm']/10_000:.0f}",
    }
