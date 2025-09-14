# cost_estimator/scripts/app.py
from flask import Flask, jsonify, request
from flask_cors import CORS

# Blueprints (local modules)
from cost_prediction import predictor_bp
from update_instances import rec_bp, warm_rec_cache
from provision import provision_bp  # make sure this import exists if you added provision.py

def create_app() -> Flask:
    app = Flask(__name__)

    # Strong, explicit CORS for all routes & methods
    CORS(
        app,
        resources={r"/*": {"origins": "*"}},
        allow_headers=["Content-Type", "Authorization"],
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        supports_credentials=False,
        max_age=86400,
    )

    # Safety net: ensure every response has CORS headers
    @app.after_request
    def apply_cors(resp):
        resp.headers.setdefault("Access-Control-Allow-Origin", "*")
        resp.headers.setdefault("Access-Control-Allow-Headers", "Content-Type, Authorization")
        resp.headers.setdefault("Access-Control-Allow-Methods", "GET,POST,PUT,PATCH,DELETE,OPTIONS")
        return resp

    # Handle any stray OPTIONS early (rarely needed with flask-cors, but harmless)
    @app.before_request
    def handle_preflight():
        if request.method == "OPTIONS":
            # flask-cors will also add headers
            return ("", 204)

    @app.route("/")
    def home():
        return "Cloud Migration Cost Estimator API is running."

    @app.route("/health")
    def health():
        return jsonify({"ok": True})

    # Register feature modules
    app.register_blueprint(predictor_bp)   # /predict
    app.register_blueprint(rec_bp)         # /debug/eligibles, /price_instances, /optimize, etc.
    app.register_blueprint(provision_bp)   # /provision/*

    return app

if __name__ == "__main__":
    app = create_app()
    try:
        warm_rec_cache()  # warm EC2 offerings/specs cache
    except Exception as e:
        print("Warm-up skipped:", e)
    app.run(host="0.0.0.0", port=5000, debug=True)
