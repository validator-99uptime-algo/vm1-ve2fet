from flask import Flask
from views.validators   import bp as validators_bp
from views.delegators   import bp as delegators_bp
from views.ad_contract  import bp as ad_contract_bp
from views.vmclients    import bp as vmclients_bp
from views.monitor      import bp as monitor_bp
from views.graph import bp as graph_bp
from views.winners1 import bp as winners1_bp
from views.vmstatus import bp as vmstatus_bp

app = Flask(__name__)

app.register_blueprint(validators_bp)    # mounts at “/”
app.register_blueprint(delegators_bp)    # mounts at “/delegators”
app.register_blueprint(ad_contract_bp)   # mounts wherever ad_contract defines
app.register_blueprint(vmclients_bp)     # mounts at “/vmclients”
app.register_blueprint(monitor_bp)       # mounts at “/monitor”
app.register_blueprint(graph_bp)    # mounts at "/monitorgraph"
app.register_blueprint(winners1_bp)
app.register_blueprint(vmstatus_bp) 


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
