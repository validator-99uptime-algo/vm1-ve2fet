# ~/ve2fet/webapp/views/ad_contract.py
from flask import Blueprint, render_template, abort
import db

bp = Blueprint("ad_contract", __name__, url_prefix="/ad_contract")

@bp.route("/<int:ad_id>")
def page(ad_id: int):
    row = db.get_validator_ad(ad_id)
    if row is None:
        abort(404)
    return render_template("ad_contract.html", ad=row)
