import pandas as pd
from sklearn.linear_model import LinearRegression
import joblib

# Load data
data = pd.read_csv('data/cloud_costs.csv')

# Features and label
X = data[['cpu_cores', 'ram_gb', 'storage_gb', 'transfer_gb', 'labor_hours']]
y = data['total_cost']

# Train model
model = LinearRegression()
model.fit(X, y)

# Save model
joblib.dump(model, 'model/cost_model.pkl')
print("Model trained and saved.")
