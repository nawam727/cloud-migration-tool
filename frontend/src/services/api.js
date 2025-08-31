// frontend/src/services/api.js
import axios from "axios";

export const API_BASE =
  process.env.REACT_APP_API_BASE || "http://localhost:5000";

export const API = axios.create({
  baseURL: API_BASE,
  headers: { "Content-Type": "application/json" },
});

export const recommendInstance = (inputs) => API.post("/optimize", inputs);
export const fetchEligibles = (cpu, ram) =>
  API.get("/debug/eligibles", { params: { cpu, ram } });
export const priceInstances = (instanceTypes) =>
  API.post("/price_instances", { instance_types: instanceTypes });
export const getRecommendedWithPrices = (cpu, ram, region) =>
  API.get("/recommend_with_prices", { params: { cpu, ram, region } });
export const estimateCost = (payload) => API.post("/predict", payload);

// NEW: simple provisioning
export const createAwsInstance = (data) => API.post("/provision/create", data);
export const destroyProvisionStack = (data) => API.post("/provision/destroy", data);
export const getProvisionStatus = (region, stack_id) =>
  API.get("/provision/status", { params: { region, stack_id } });
