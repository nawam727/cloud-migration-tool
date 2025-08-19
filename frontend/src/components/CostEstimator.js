import React, { useState } from "react";
import { motion } from "framer-motion";
import {
  Cloud,
  Calculator,
  DollarSign,
  Loader2,
  Cpu,
  MemoryStick,
  HardDrive,
  Upload,
  UserCog,
} from "lucide-react";
import { estimateCost } from "../services/api";

// Small field component to ensure consistent alignment & suffixes
function Field({ label, name, value, onChange, min = 0, step = 1, suffix }) {
  return (
    <label className="grid gap-1">
      <span className="text-slate-300 text-sm font-medium flex items-center gap-2">
        {label.icon}
        <span>{label.text}</span>
      </span>
      <div className="relative">
        <input
          type="number"
          name={name}
          value={value}
          onChange={onChange}
          min={min}
          step={step}
          className="w-full h-10 rounded-xl bg-slate-950 border border-slate-700 px-3 pr-14 text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
        />
        {suffix && (
          <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 text-xs bg-slate-900 px-2 py-0.5 rounded-md border border-slate-700">
            {suffix}
          </span>
        )}
      </div>
    </label>
  );
}

export default function CostEstimator() {
  const [inputs, setInputs] = useState({
    cpu_cores: 2,
    ram_gb: 4,
    storage_gb: 100,
    transfer_gb: 50,
    labor_hours: 10,
  });
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const region = process.env.REACT_APP_TARGET_REGION || "us-east-1";

  const handleChange = (e) =>
    setInputs((prev) => ({ ...prev, [e.target.name]: Number(e.target.value) }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    setResult(null);
    try {
      const res = await estimateCost(inputs);
      setResult(res.data?.estimated_cost ?? null);
    } catch (err) {
      console.error(err);
      const msg = err?.response?.data?.error || "Failed to estimate cost.";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="dark">
      <div className="min-h-screen bg-gradient-to-b from-slate-950 to-slate-900 text-slate-100 font-sans">
        {/* Top Bar */}
        <header className="sticky top-0 z-40 border-b border-slate-800 bg-slate-950/90 backdrop-blur">
          <div className="mx-auto max-w-7xl px-6 py-4 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-xl bg-slate-900 border border-slate-800">
                <Cloud className="h-5 w-5 text-indigo-400" />
              </div>
              <div>
                <div className="text-xs uppercase tracking-widest text-slate-400">Cloud Migration</div>
                <div className="text-lg font-semibold leading-none">Cost Estimator</div>
              </div>
            </div>
            <div className="text-sm text-slate-400">Region: <span className="text-slate-200">{region}</span></div>
          </div>
        </header>

        {/* Main */}
        <main className="mx-auto max-w-7xl px-6 py-8 grid gap-8 lg:grid-cols-12">
          {/* Left: Form */}
          <motion.section
            initial={{ opacity: 0, x: -16 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.25 }}
            className="lg:col-span-5"
          >
            <div className="rounded-2xl bg-slate-900/80 border border-slate-800 shadow-xl">
              <div className="p-6 border-b border-slate-800">
                <h2 className="text-xl font-semibold flex items-center gap-2">
                  <Calculator className="h-5 w-5 text-indigo-400" /> Migration Cost Estimator
                </h2>
                <p className="text-slate-400 text-sm mt-1">
                  Provide workload inputs to estimate total migration cost.
                </p>
              </div>
              <form onSubmit={handleSubmit} className="p-6 grid grid-cols-1 sm:grid-cols-2 gap-5">
                <Field
                  label={{ text: "CPU Cores", icon: <Cpu className="h-4 w-4 text-sky-400" /> }}
                  name="cpu_cores"
                  value={inputs.cpu_cores}
                  onChange={handleChange}
                  min={1}
                  step={1}
                  suffix="cores"
                />
                <Field
                  label={{ text: "RAM", icon: <MemoryStick className="h-4 w-4 text-purple-400" /> }}
                  name="ram_gb"
                  value={inputs.ram_gb}
                  onChange={handleChange}
                  min={0.5}
                  step={0.5}
                  suffix="GiB"
                />
                <Field
                  label={{ text: "Storage", icon: <HardDrive className="h-4 w-4 text-amber-400" /> }}
                  name="storage_gb"
                  value={inputs.storage_gb}
                  onChange={handleChange}
                  min={0}
                  step={1}
                  suffix="GB"
                />
                <Field
                  label={{ text: "Data Transfer", icon: <Upload className="h-4 w-4 text-emerald-400" /> }}
                  name="transfer_gb"
                  value={inputs.transfer_gb}
                  onChange={handleChange}
                  min={0}
                  step={1}
                  suffix="GB"
                />
                <Field
                  label={{ text: "Labor", icon: <UserCog className="h-4 w-4 text-pink-400" /> }}
                  name="labor_hours"
                  value={inputs.labor_hours}
                  onChange={handleChange}
                  min={0}
                  step={1}
                  suffix="hrs"
                />

                <div className="sm:col-span-2 flex items-center justify-end gap-3 pt-2">
                  <button
                    type="submit"
                    disabled={loading}
                    className="inline-flex items-center justify-center rounded-xl bg-indigo-600 hover:bg-indigo-500 px-4 py-2 font-medium disabled:opacity-60"
                  >
                    {loading ? (
                      <>
                        <Loader2 className="h-4 w-4 mr-2 animate-spin" /> Estimating
                      </>
                    ) : (
                      <>
                        <Calculator className="h-4 w-4 mr-2" /> Estimate
                      </>
                    )}
                  </button>
                </div>

                {error && (
                  <div className="sm:col-span-2 rounded-xl border border-red-900 bg-red-950 text-red-200 p-4 text-sm">
                    {error}
                  </div>
                )}

                <p className="sm:col-span-2 text-xs text-slate-500">
                  Estimate includes compute, storage, transfer, and labor based on your model.
                </p>
              </form>
            </div>
          </motion.section>

          {/* Right: Result */}
          <motion.section
            initial={{ opacity: 0, x: 16 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.25 }}
            className="lg:col-span-7"
          >
            <div className="rounded-2xl bg-slate-900/80 border border-slate-800 shadow-xl">
              <div className="p-6 border-b border-slate-800">
                <h2 className="text-xl font-semibold flex items-center gap-2">
                  <DollarSign className="h-5 w-5 text-green-400" /> Estimated Cost
                </h2>
                <p className="text-slate-400 text-sm mt-1">Output from your /estimateCost service.</p>
              </div>

              <div className="p-6 space-y-6">
                {/* Result number */}
                <div className="flex items-end justify-between">
                  <div>
                    <div className="text-sm text-slate-400">Total (per migration)</div>
                    <div className="text-4xl font-bold tracking-tight">
                      {loading ? (
                        <span className="inline-flex items-center text-slate-400"><Loader2 className="h-6 w-6 mr-2 animate-spin"/>Calculating…</span>
                      ) : result != null ? (
                        <span className="inline-flex items-center"><DollarSign className="h-7 w-7 mr-1" /> {Number(result).toFixed(2)}</span>
                      ) : (
                        <span className="text-slate-500">Run an estimate</span>
                      )}
                    </div>
                  </div>
                  <div className="text-right text-xs text-slate-500">Region: {region}</div>
                </div>

                {/* Inputs summary aligned in a tidy grid */}
                <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                  <div className="rounded-xl border border-slate-800 bg-slate-950 p-3">
                    <div className="text-xs text-slate-400 flex items-center gap-1"><Cpu className="h-3.5 w-3.5"/>CPU</div>
                    <div className="text-lg font-semibold">{inputs.cpu_cores} cores</div>
                  </div>
                  <div className="rounded-xl border border-slate-800 bg-slate-950 p-3">
                    <div className="text-xs text-slate-400 flex items-center gap-1"><MemoryStick className="h-3.5 w-3.5"/>RAM</div>
                    <div className="text-lg font-semibold">{inputs.ram_gb} GiB</div>
                  </div>
                  <div className="rounded-xl border border-slate-800 bg-slate-950 p-3">
                    <div className="text-xs text-slate-400 flex items-center gap-1"><HardDrive className="h-3.5 w-3.5"/>Storage</div>
                    <div className="text-lg font-semibold">{inputs.storage_gb} GB</div>
                  </div>
                  <div className="rounded-xl border border-slate-800 bg-slate-950 p-3">
                    <div className="text-xs text-slate-400 flex items-center gap-1"><Upload className="h-3.5 w-3.5"/>Transfer</div>
                    <div className="text-lg font-semibold">{inputs.transfer_gb} GB</div>
                  </div>
                  <div className="rounded-xl border border-slate-800 bg-slate-950 p-3">
                    <div className="text-xs text-slate-400 flex items-center gap-1"><UserCog className="h-3.5 w-3.5"/>Labor</div>
                    <div className="text-lg font-semibold">{inputs.labor_hours} hrs</div>
                  </div>
                </div>

                {/* Hints / assumptions */}
                <div className="rounded-xl border border-slate-800 bg-slate-950 p-4 text-sm text-slate-300">
                  <div className="font-medium mb-1">Assumptions</div>
                  <ul className="list-disc list-inside space-y-1 text-slate-400">
                    <li>Linux On‑Demand pricing; excludes discounts and EBS/IO surcharges.</li>
                    <li>Data transfer measured as outbound only.</li>
                    <li>Labor cost proxy comes from your ML model.</li>
                  </ul>
                </div>
              </div>
            </div>
          </motion.section>
        </main>

        <footer className="mx-auto max-w-7xl px-6 py-8 text-center text-xs text-slate-500 border-t border-slate-800">
          Cloud Migration Toolkit · Dark Console UI
        </footer>
      </div>
    </div>
  );
}
