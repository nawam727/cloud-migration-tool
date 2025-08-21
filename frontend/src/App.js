import './index.css';
import React from "react";
import CostEstimator from "./components/CostEstimator";
import IaCGenerator from "./components/IaCGenerator";
import InstanceRecommender from "./components/InstanceRecommender";

function App() {
  return (
    <div className="App">
      <CostEstimator />
      <hr />
      <InstanceRecommender />
      <hr />
      <IaCGenerator />
    </div>
  );
}

export default App;
