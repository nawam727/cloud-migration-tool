import React, { useState } from "react";
import { estimateCost } from "../services/api";

function CostEstimator() {
  const [inputs, setInputs] = useState({
    cpu_cores: 2,
    ram_gb: 4,
    storage_gb: 100,
    transfer_gb: 50,
    labor_hours: 10,
  });
  const [result, setResult] = useState(null);

  const handleChange = (e) =>
    setInputs({ ...inputs, [e.target.name]: Number(e.target.value) });

  const handleSubmit = async (e) => {
    e.preventDefault();
    const res = await estimateCost(inputs);
    setResult(res.data.estimated_cost);
  };

  return (
    <div>
      <h3>Migration Cost Estimator</h3>
      <form onSubmit={handleSubmit}>
        {Object.entries(inputs).map(([name, value]) => (
          <div key={name}>
            <label>{name}</label>
            <input
              type="number"
              name={name}
              value={value}
              onChange={handleChange}
            />
          </div>
        ))}
        <button type="submit">Estimate</button>
      </form>
      {result && <p>Estimated Cost: ${result}</p>}
    </div>
  );
}

export default CostEstimator;
