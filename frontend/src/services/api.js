import axios from "axios";

const API_BASE = "http://localhost:5000";

export const estimateCost = (data) =>
  axios.post(`${API_BASE}/predict`, data);

export const recommendInstance = (data) =>
  axios.post(`${API_BASE}/optimize`, data);

export const generateIaC = (data) =>
  axios.post(`${API_BASE}/generate-iac`, data);
