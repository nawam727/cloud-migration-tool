# cost_estimator/scripts/app.py
from flask import Flask, jsonify
from flask_cors import CORS

# Blueprints (local modules)
from cost_prediction import predictor_bp
from update_instances import rec_bp, warm_rec_cache

def create_app() -> Flask:
    app = Flask(__name__)
    CORS(app)

    @app.route("/")
    def home():
        return "Cloud Migration Cost Estimator API is running."

    @app.route("/health")
    def health():
        return jsonify({"ok": True})

    # Register feature modules
    app.register_blueprint(predictor_bp)  # /predict
    app.register_blueprint(rec_bp)        # /debug/eligibles, /price_instances, /optimize, etc.

    return app

if __name__ == "__main__":
    app = create_app()
    try:
        warm_rec_cache()  # warms EC2 offerings/specs cache (safe no-op on failure)
    except Exception as e:
        print("Warm-up skipped:", e)
    app.run(host="0.0.0.0", port=5000, debug=True)
