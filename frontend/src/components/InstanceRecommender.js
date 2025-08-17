import React, { useState } from "react";
import { recommendInstance, fetchEligibles } from "../services/api";

function InstanceRecommender() {
  const [inputs, setInputs] = useState({ cpu_cores: 1, ram_gb: 1 });
  const [instance, setInstance] = useState(null);
  const [eligibles, setEligibles] = useState([]); // top-10 table rows
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const handleChange = (e) =>
    setInputs({ ...inputs, [e.target.name]: Number(e.target.value) });

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setInstance(null);
    setEligibles([]);
    setLoading(true);

    try {
      // run both calls in parallel; table should show even if optimize fails
      const [optimizeRes, eligiblesRes] = await Promise.allSettled([
        recommendInstance(inputs),
        fetchEligibles(inputs.cpu_cores, inputs.ram_gb),
      ]);

      if (optimizeRes.status === "fulfilled") {
        setInstance(optimizeRes.value.data);
      } else {
        // don't block the table if recommendation 404s
        const errData = optimizeRes.reason?.response?.data;
        if (errData?.error) {
          console.warn("Optimize failed:", errData);
        } else {
          console.warn("Optimize failed:", optimizeRes.reason?.message);
        }
      }

      if (eligiblesRes.status === "fulfilled") {
        const data = eligiblesRes.value.data;
        const rows = Array.isArray(data.first_20) ? data.first_20.slice(0, 10) : [];
        setEligibles(rows);
      } else {
        const errData = eligiblesRes.reason?.response?.data;
        setError(
          errData?.error
            ? `Failed to fetch eligibles: ${errData.error}`
            : "Failed to fetch eligibles."
        );
      }
    } catch (err) {
      console.error("Unexpected UI error:", err);
      setError("Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: 680 }}>
      <h3>Recommended AWS Instance</h3>

      <form onSubmit={handleSubmit} style={{ display: "grid", gap: 12, marginBottom: 12 }}>
        <label>
          CPU Cores
          <input
            type="number"
            name="cpu_cores"
            value={inputs.cpu_cores}
            onChange={handleChange}
            min={1}
            style={{ marginLeft: 8 }}
          />
        </label>

        <label>
          RAM (GiB)
          <input
            type="number"
            name="ram_gb"
            value={inputs.ram_gb}
            onChange={handleChange}
            min={0.5}
            step="0.5"
            style={{ marginLeft: 8 }}
          />
        </label>

        <button type="submit" disabled={loading}>
          {loading ? "Loading..." : "Get Recommendation"}
        </button>
      </form>

      {error && <p style={{ color: "red" }}>{error}</p>}

      {/* show the single recommended instance if available */}
      {instance ? (
        <p style={{ marginBottom: 16 }}>
          Use AWS instance <strong>{instance.instance_type}</strong> — Estimated Cost/hr: $
          {Number(instance.price_per_hour).toFixed(4)}
        </p>
      ) : (
        !loading && <p style={{ color: "#666" }}>No single recommendation yet (showing eligible options below).</p>
      )}

      {/* table of top-10 eligible instances */}
      {eligibles.length > 0 && (
        <div style={{ overflowX: "auto" }}>
          <table
            style={{
              width: "100%",
              borderCollapse: "collapse",
              border: "1px solid #ddd",
            }}
          >
            <thead>
              <tr style={{ background: "#f6f6f6" }}>
                <th style={{ textAlign: "left", padding: "8px", borderBottom: "1px solid #ddd" }}>
                  Instance type
                </th>
                <th style={{ textAlign: "right", padding: "8px", borderBottom: "1px solid #ddd" }}>
                  Memory (GiB)
                </th>
                <th style={{ textAlign: "right", padding: "8px", borderBottom: "1px solid #ddd" }}>
                  vCPU
                </th>
              </tr>
            </thead>
            <tbody>
              {eligibles.map((row) => (
                <tr key={row.instance_type}>
                  <td style={{ padding: "8px", borderBottom: "1px solid #eee" }}>
                    {row.instance_type}
                  </td>
                  <td style={{ padding: "8px", textAlign: "right", borderBottom: "1px solid #eee" }}>
                    {Number(row.memory_GB).toFixed(3)}
                  </td>
                  <td style={{ padding: "8px", textAlign: "right", borderBottom: "1px solid #eee" }}>
                    {row.vCPU}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p style={{ color: "#666", marginTop: 6 }}>
            Showing top {eligibles.length} smallest instances that meet/exceed your request.
          </p>
        </div>
      )}
    </div>
  );
}

export default InstanceRecommender;
