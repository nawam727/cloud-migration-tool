// services/api.js
import axios from "axios";

// CRA/Vite: env must be defined at build time; CRA requires REACT_APP_* prefix.
export const API_BASE =
  process.env.REACT_APP_API_BASE || "http://localhost:5000";

export const API = axios.create({
  baseURL: API_BASE,
  headers: { "Content-Type": "application/json" },
});

// Single best pick (may 404 if no priced candidate, that’s OK for UI)
export const recommendInstance = (inputs) => API.post("/optimize", inputs);

// Eligible (unpriced) list for the table
export const fetchEligibles = (cpu, ram) =>
  API.get("/debug/eligibles", { params: { cpu, ram } });

// Optional: your other endpoint
export const estimateCost = (payload) => API.post("/predict", payload);


export const generateIaC = (data) =>
  axios.post(`${API_BASE}/generate-iac`, data);
