import React, { useState, useMemo } from "react";
import { motion } from "framer-motion";
import { Cpu, MemoryStick, DollarSign, Loader2 } from "lucide-react";
import { recommendInstance, fetchEligibles, priceInstances } from "../services/api";

function Field({ label, name, value, onChange, min = 0, step = 1, suffix }) {
  return (
    <label className="grid gap-1">
      <span className="text-slate-300 text-sm font-medium flex items-center gap-2">
        {label.icon} <span>{label.text}</span>
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

const HOURS_PER_MONTH = 730;
const fmtHr = (n) => (n == null || n <= 0 ? "—" : `$${Number(n).toFixed(4)}`);
const fmtMo = (n) => (n == null || n <= 0 ? "—" : `$${(Number(n) * HOURS_PER_MONTH).toFixed(2)}`);

export default function InstanceRecommenderUI() {
  const [inputs, setInputs] = useState({ cpu_cores: 1, ram_gb: 1 });
  const [instance, setInstance] = useState(null);
  const [eligibles, setEligibles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [sortByPrice, setSortByPrice] = useState(true);

  const region = process.env.REACT_APP_TARGET_REGION || "us-east-1";

  const handleChange = (e) =>
    setInputs((prev) => ({ ...prev, [e.target.name]: Number(e.target.value) }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setInstance(null);
    setEligibles([]);
    setLoading(true);

    try {
      const [optimizeRes, eligiblesRes] = await Promise.allSettled([
        recommendInstance(inputs),
        fetchEligibles(inputs.cpu_cores, inputs.ram_gb),
      ]);

      if (optimizeRes.status === "fulfilled") {
        setInstance(optimizeRes.value.data);
      }

      if (eligiblesRes.status !== "fulfilled") {
        const errData = eligiblesRes.reason?.response?.data;
        setError(errData?.error || "Failed to fetch eligible instances.");
        setLoading(false);
        return;
      }

      const data = eligiblesRes.value.data;
      const rawRows = Array.isArray(data.first_20) ? data.first_20.slice(0, 10) : [];
      if (!rawRows.length) {
        setError("No instances meet the requirements in this region.");
        setLoading(false);
        return;
      }

      const names = rawRows.map((r) => r.instance_type);
      const priceRes = await priceInstances(names);
      const priceMap = {};
      for (const r of priceRes.data?.rows ?? []) priceMap[r.instance_type] = r.price_per_hour;

      const merged = rawRows.map((r) => {
        const p = priceMap[r.instance_type];
        return {
          ...r,
          // treat 0 or negative as missing, so they go to the bottom & show "—"
          price_per_hour: p == null || p <= 0 ? null : p,
        };
      });

      setEligibles(merged);
    } catch (err) {
      console.error(err);
      setError("Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  // compute cheapest (non-null) for highlight
  const minPrice = useMemo(() => {
    const vals = eligibles.map((r) => r.price_per_hour).filter((v) => v != null && v > 0);
    return vals.length ? Math.min(...vals) : null;
  }, [eligibles]);

  // optional sorting by price (nulls last), then by vCPU/memory
  const displayRows = useMemo(() => {
    const rows = [...eligibles];
    if (sortByPrice) {
      rows.sort((a, b) => {
        const ap = a.price_per_hour, bp = b.price_per_hour;
        if (ap == null && bp == null) {
          // tie-break by resources if both missing
          if (a.vCPU !== b.vCPU) return a.vCPU - b.vCPU;
          return a.memory_GB - b.memory_GB;
        }
        if (ap == null) return 1;  // nulls last
        if (bp == null) return -1;
        if (ap !== bp) return ap - bp;
        // tie-break
        if (a.vCPU !== b.vCPU) return a.vCPU - b.vCPU;
        return a.memory_GB - b.memory_GB;
      });
    }
    return rows;
  }, [eligibles, sortByPrice]);

  return (
    <div className="dark">
      <div className="min-h-screen bg-gradient-to-b from-slate-950 to-slate-900 text-slate-100 font-sans">
        {/* Header */}
        <header className="sticky top-0 z-40 border-b border-slate-800 bg-slate-950/90 backdrop-blur">
          <div className="mx-auto max-w-7xl px-6 py-4 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-xl bg-slate-900 border border-slate-800">
                <Cpu className="h-5 w-5 text-indigo-400" />
              </div>
              <div>
                <div className="text-xs uppercase tracking-widest text-slate-400">AWS Instance</div>
                <div className="text-lg font-semibold leading-none">Instance Recommender</div>
              </div>
            </div>
            <div className="text-sm text-slate-400">
              Region: <span className="text-slate-200">{region}</span>
            </div>
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
                  <Cpu className="h-5 w-5 text-indigo-400" /> Instance Inputs
                </h2>
                <p className="text-slate-400 text-sm mt-1">
                  Enter CPU cores and RAM to get eligible AWS instances.
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

                <div className="sm:col-span-2 flex items-center justify-between gap-3 pt-2">
                  <label className="flex items-center gap-2 text-sm text-slate-300">
                    <input
                      type="checkbox"
                      className="accent-indigo-500"
                      checked={sortByPrice}
                      onChange={(e) => setSortByPrice(e.target.checked)}
                    />
                    Sort by price (cheapest first)
                  </label>
                  <button
                    type="submit"
                    disabled={loading}
                    className="inline-flex items-center justify-center rounded-xl bg-indigo-600 hover:bg-indigo-500 px-4 py-2 font-medium disabled:opacity-60"
                  >
                    {loading ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Cpu className="h-4 w-4 mr-2" />}
                    {loading ? "Loading..." : "Get Recommendation"}
                  </button>
                </div>

                {error && (
                  <div className="sm:col-span-2 rounded-xl border border-red-900 bg-red-950 text-red-200 p-4 text-sm">
                    {error}
                  </div>
                )}
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
                  <DollarSign className="h-5 w-5 text-green-400" /> Recommendations
                </h2>
                <p className="text-slate-400 text-sm mt-1">
                  Eligible instances with estimated pricing (Linux On-Demand, Shared Tenancy in {region}).
                </p>
              </div>

              <div className="p-6 space-y-6">
                {/* Single recommended instance */}
                {instance && (
                  <div className="text-lg font-semibold">
                    Recommended: <span className="text-indigo-400">{instance.instance_type}</span>
                    {" — "}
                    <span className="text-emerald-400">{fmtHr(instance.price_per_hour)}/hr</span>
                    {" · "}
                    <span className="text-emerald-400">{fmtMo(instance.price_per_hour)}/mo</span>
                  </div>
                )}

                {/* Eligible instances table */}
                {displayRows.length > 0 && (
                  <div className="overflow-x-auto">
                    <table className="w-full border border-slate-700 text-sm">
                      <thead className="bg-slate-950/80">
                        <tr>
                          <th className="p-2 text-left border-b border-slate-700">Instance</th>
                          <th className="p-2 text-right border-b border-slate-700">vCPU</th>
                          <th className="p-2 text-right border-b border-slate-700">Memory (GiB)</th>
                          <th className="p-2 text-right border-b border-slate-700">$/hr</th>
                          <th className="p-2 text-right border-b border-slate-700">$/mo</th>
                        </tr>
                      </thead>
                      <tbody>
                        {displayRows.map((row) => {
                          const isCheapest = minPrice != null && row.price_per_hour === minPrice;
                          return (
                            <tr
                              key={row.instance_type}
                              className={`${
                                isCheapest
                                  ? "bg-emerald-900/10 ring-1 ring-emerald-500/30"
                                  : "hover:bg-slate-800"
                              }`}
                            >
                              <td className="p-2 border-b border-slate-700">
                                {row.instance_type}
                                {isCheapest && (
                                  <span className="ml-3 text-emerald-300 text-xs px-2 py-0.5 rounded-full border border-emerald-600/40 bg-emerald-900/20">
                                    cheapest
                                  </span>
                                )}
                              </td>
                              <td className="p-2 text-right border-b border-slate-700">{row.vCPU}</td>
                              <td className="p-2 text-right border-b border-slate-700">
                                {Number(row.memory_GB).toFixed(3)}
                              </td>
                              <td className="p-2 text-right border-b border-slate-700">
                                {fmtHr(row.price_per_hour)}
                              </td>
                              <td className="p-2 text-right border-b border-slate-700">
                                {fmtMo(row.price_per_hour)}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
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
