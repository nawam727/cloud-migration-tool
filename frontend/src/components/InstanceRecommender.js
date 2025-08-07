import React, { useState } from "react";
import { recommendInstance } from "../services/api";

function InstanceRecommender() {
  const [inputs, setInputs] = useState({ cpu_cores: 2, ram_gb: 4 });
  const [instance, setInstance] = useState(null);

  const handleChange = (e) =>
    setInputs({ ...inputs, [e.target.name]: Number(e.target.value) });

  const handleSubmit = async (e) => {
    e.preventDefault();
    const res = await recommendInstance(inputs);
    setInstance(res.data);
  };

  return (
    <div>
      <h3>Recommended AWS Instance</h3>
      <form onSubmit={handleSubmit}>
        <label>CPU Cores</label>
        <input
          type="number"
          name="cpu_cores"
          value={inputs.cpu_cores}
          onChange={handleChange}
        />
        <label>RAM (GB)</label>
        <input
          type="number"
          name="ram_gb"
          value={inputs.ram_gb}
          onChange={handleChange}
        />
        <button type="submit">Get Recommendation</button>
      </form>
      {instance && (
        <p>
          Use AWS instance <strong>{instance.type}</strong> - Estimated
          Cost/hr: ${instance.price_per_hr}
        </p>
      )}
    </div>
  );
}

export default InstanceRecommender;
