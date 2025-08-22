// services/api.js
import axios from "axios";

// CRA/Vite: env must be defined at build time; CRA uses REACT_APP_* prefix
export const API_BASE =
  process.env.REACT_APP_API_BASE || "http://localhost:5000";

export const API = axios.create({
  baseURL: API_BASE,
  headers: { "Content-Type": "application/json" },
});

// Single best pick
export const recommendInstance = (inputs) => API.post("/optimize", inputs);

// Unpriced eligibles (your current table source)
export const fetchEligibles = (cpu, ram) =>
  API.get("/debug/eligibles", { params: { cpu, ram } });

// NEW: price by instance names (POST)
export const priceInstances = (instanceTypes) =>
  API.post("/price_instances", { instance_types: instanceTypes });

export const getRecommendedWithPrices = (cpu, ram, region) =>
  API.get("/recommend_with_prices", { params: { cpu, ram, region } });

// Other endpoints you already use
export const estimateCost = (payload) => API.post("/predict", payload);

export const generateIaC = (data) => axios.post(`${API_BASE}/generate-iac`, data);
