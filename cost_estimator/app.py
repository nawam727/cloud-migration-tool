from flask import Flask, request, jsonify
import joblib
import numpy as np

app = Flask(__name__)
model = joblib.load('model/cost_model.pkl')

@app.route('/predict', methods=['POST'])
def predict():
    data = request.json
    features = np.array([
        data['cpu_cores'],
        data['ram_gb'],
        data['storage_gb'],
        data['transfer_gb'],
        data['labor_hours']
    ]).reshape(1, -1)
    
    prediction = model.predict(features)[0]
    return jsonify({'estimated_cost': round(prediction, 2)})

@app.route('/')
def home():
    return 'Cloud Migration Cost Estimator API is running.'


if __name__ == '__main__':
    app.run(debug=True)
