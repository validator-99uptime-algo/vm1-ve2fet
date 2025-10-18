import sqlite3
import os

DB_PATH = "valar.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS validator_ads (
  ad_id INTEGER PRIMARY KEY,
  val_owner TEXT,
  val_manager TEXT,
  state TEXT,
  cnt_del INTEGER,
  cnt_del_max INTEGER,
  noticeboard_app_id INTEGER,
  tc_sha256 TEXT,
  total_algo_earned INTEGER,
  total_algo_fees_generated INTEGER,
  created_at_round INTEGER,
  updated_at_round INTEGER,
  commission_ppm INTEGER,
  fee_round_min INTEGER,
  fee_round_var INTEGER,
  fee_setup INTEGER,
  fee_asset_id INTEGER,
  valid_until_round INTEGER,
  min_duration_rounds INTEGER,
  max_duration_rounds INTEGER,
  setup_time_rounds INTEGER,
  confirm_time_rounds INTEGER,
  stake_max INTEGER,
  gratis_stake_ppm INTEGER,
  warning_max INTEGER,
  warning_time_rounds INTEGER
);

CREATE TABLE IF NOT EXISTS delegator_contracts (
  contract_id INTEGER PRIMARY KEY,
  validator_ad_app_id INTEGER,
  del_manager TEXT,
  del_beneficiary TEXT,
  state TEXT,
  noticeboard_app_id INTEGER,
  round_start INTEGER,
  round_end INTEGER,
  round_ended INTEGER,
  fee_operational INTEGER,
  fee_operational_partner INTEGER,
  cnt_breach_del INTEGER,
  commission_ppm INTEGER,
  fee_round INTEGER,
  fee_setup INTEGER,
  fee_asset_id INTEGER,
  partner_address TEXT,
  fee_round_partner INTEGER,
  fee_setup_partner INTEGER,
  rounds_setup INTEGER,
  rounds_confirm INTEGER,
  stake_max INTEGER,
  cnt_breach_del_max INTEGER,
  rounds_breach INTEGER,
  gating_asa_1_id INTEGER,
  gating_asa_1_min INTEGER,
  gating_asa_2_id INTEGER,
  gating_asa_2_min INTEGER,
  created_at_round INTEGER,
  updated_at_round INTEGER
);

CREATE TABLE IF NOT EXISTS noticeboard_users (
  address TEXT PRIMARY KEY,
  role TEXT,
  cnt_app_ids INTEGER
);

CREATE TABLE IF NOT EXISTS currencies (
  asset_id INTEGER PRIMARY KEY,
  symbol TEXT,
  decimals INTEGER
);

-- You can add user_apps or earnings table here if needed.
"""

def init_db(db_path=DB_PATH):
    if os.path.exists(db_path):
        print(f"{db_path} already exists. Skipping creation.")
        return
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA)
    print(f"Database {db_path} initialized.")

if __name__ == "__main__":
    init_db()
