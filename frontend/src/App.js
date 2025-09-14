// src/App.js
import "./index.css";
import React from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";

// Reusable top nav + home page (from previous step)
import TopNav from "./components/TopNav";
import Home from "./components/Home";

// Your existing pages
import CostEstimator from "./components/CostEstimator";
import InstanceRecommender from "./components/InstanceRecommender";
import IaCGenerator from "./components/IaCGenerator";

const REGION = process.env.REACT_APP_TARGET_REGION || "us-east-1";

function App() {
  return (
    <BrowserRouter>
      <TopNav
        region={REGION}
        user={{ name: "Alex Morgan", email: "alex@example.com" }}
        onSignOut={() => alert("Sign out here")}
      />

      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/cost" element={<CostEstimator />} />
        <Route path="/recommend" element={<InstanceRecommender />} />
        <Route path="/provision" element={<IaCGenerator />} />
        <Route
          path="/monitor"
          element={
            <div className="mx-auto max-w-7xl px-6 py-10 text-slate-300">
              Monitoring coming soon…
            </div>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
