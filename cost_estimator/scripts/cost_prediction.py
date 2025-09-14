# cost_estimator/scripts/cost_prediction.py
import os
import numpy as np
import joblib
from flask import Blueprint, request, jsonify

predictor_bp = Blueprint("predictor", __name__)

# Resolve model path relative to this file:
# cost_estimator/scripts/ -> ../model/cost_model.pkl
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_MODEL_PATH = os.path.normpath(os.path.join(_THIS_DIR, "..", "model", "cost_model.pkl"))
MODEL_PATH = os.getenv("MODEL_PATH", _DEFAULT_MODEL_PATH)

_model = None
def _load_model():
    global _model
    if _model is None:
        try:
            _model = joblib.load(MODEL_PATH)
            print(f"[predictor] Model loaded: {MODEL_PATH}")
        except Exception as e:
            print("[predictor] Failed to load model:", e)
            _model = None
    return _model

@predictor_bp.route("/predict", methods=["POST"])
def predict():
    model = _load_model()
    if not model:
        return jsonify({"error": "Model not loaded"}), 500

    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"error": "Invalid or missing JSON body"}), 400

    try:
        features = np.array([
            data["cpu_cores"],
            data["ram_gb"],
            data["storage_gb"],
            data["transfer_gb"],
            data["labor_hours"]
        ]).reshape(1, -1)
    except KeyError as e:
        return jsonify({"error": f"Missing input field: {str(e)}"}), 400
    except Exception as e:
        return jsonify({"error": f"Invalid input data: {str(e)}"}), 400

    try:
        prediction = float(model.predict(features)[0])
        return jsonify({"estimated_cost": round(prediction, 2)})
    except Exception as e:
        return jsonify({"error": f"Model prediction failed: {str(e)}"}), 500
