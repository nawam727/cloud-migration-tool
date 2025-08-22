// frontend/src/components/IaCGenerator.js
import React, { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { FileCode2, Cloud, Cpu, MemoryStick, Loader2, Clipboard, ClipboardCheck, Download, ListChecks, AlertCircle } from "lucide-react";
import { generateIaC } from "../services/api";
import { getEligibles, subscribeEligibles } from "../store/eligiblesStore";

const HOURS_PER_MONTH = 730;
const fmtHr = (n) => (n == null || n <= 0 ? "—" : `$${Number(n).toFixed(4)}`);
const fmtMo = (n) => (n == null || n <= 0 ? "—" : `$${(Number(n) * HOURS_PER_MONTH).toFixed(2)}`);

export default function IaCGenerator() {
  const regionEnv = process.env.REACT_APP_TARGET_REGION || "us-east-1";

  const [script, setScript] = useState("");
  const [loading, setLoading] = useState(false);
  const [genError, setGenError] = useState(null);
  const [copied, setCopied] = useState(false);

  // we only read what InstanceRecommender produced
  const [recs, setRecs] = useState(() => getEligibles());
  const [selectedType, setSelectedType] = useState(recs[0]?.instance_type || "");

  // subscribe to updates from InstanceRecommender
  useEffect(() => {
    const unsub = subscribeEligibles((rows) => {
      setRecs(rows);
      if (!rows.length) {
        setSelectedType("");
      } else if (!rows.find((r) => r.instance_type === selectedType)) {
        setSelectedType(rows[0].instance_type);
      }
    });
    return unsub;
  }, [selectedType]);

  const options = useMemo(
    () =>
      (recs || []).slice(0, 10).map((r) => ({
        value: r.instance_type,
        label: `${r.instance_type} · ${r.vCPU} vCPU · ${Number(r.memory_GB).toFixed(1)} GiB · ${fmtHr(r.price_per_hour)}/hr · ${fmtMo(r.price_per_hour)}/mo`,
      })),
    [recs]
  );

  const [form, setForm] = useState({
    provider: "AWS",
    region: regionEnv,
    volume_gb: 20,
    tag_name: "demo-instance",
  });

  const onFormText = (e) => setForm((p) => ({ ...p, [e.target.name]: e.target.value }));
  const onFormNumber = (e) => setForm((p) => ({ ...p, [e.target.name]: Number(e.target.value) || 0 }));

  const handleGenerate = async (e) => {
    e.preventDefault();
    setGenError(null);
    setScript("");
    setLoading(true);
    try {
      const payload = {
        provider: form.provider,
        region: form.region,
        type: selectedType, // <- from dropdown populated by InstanceRecommender
        volume_gb: form.volume_gb,
        tag_name: form.tag_name,
      };
      const res = await generateIaC(payload);
      const body = res?.data || {};
      const txt = body.iac || body.script || body.terraform || "// (No IaC returned)\n";
      setScript(txt);
    } catch (err) {
      console.error(err);
      const msg = err?.response?.data?.error || "Failed to generate Terraform. Please try again.";
      setGenError(msg);
    } finally {
      setLoading(false);
    }
  };

  const copyScript = async () => {
    try {
      await navigator.clipboard.writeText(script || "");
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {}
  };

  const downloadTf = () => {
    const blob = new Blob([script || ""], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "main.tf";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="dark">
      <div className="min-h-screen bg-gradient-to-b from-slate-950 to-slate-900 text-slate-100 font-sans">
        {/* Header */}
        <header className="sticky top-0 z-40 border-b border-slate-800 bg-slate-950/90 backdrop-blur">
          <div className="mx-auto max-w-7xl px-6 py-4 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-xl bg-slate-900 border border-slate-800">
                <FileCode2 className="h-5 w-5 text-emerald-400" />
              </div>
              <div>
                <div className="text-xs uppercase tracking-widest text-slate-400">IaC Generator</div>
                <div className="text-lg font-semibold leading-none">Terraform Script Builder</div>
              </div>
            </div>
            <div className="text-sm text-slate-400 flex items-center gap-2">
              <Cloud className="h-4 w-4" />
              Region: <span className="text-slate-200">{form.region}</span>
            </div>
          </div>
        </header>

        {/* Main */}
        <main className="mx-auto max-w-7xl px-6 py-8 grid gap-8 lg:grid-cols-12">
          {/* Left: Inputs & Instance Type dropdown */}
          <motion.section
            initial={{ opacity: 0, x: -16 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.25 }}
            className="lg:col-span-5"
          >
            <div className="rounded-2xl bg-slate-900/80 border border-slate-800 shadow-xl">
              <div className="p-6 border-b border-slate-800">
                <h2 className="text-xl font-semibold flex items-center gap-2">
                  <FileCode2 className="h-5 w-5 text-emerald-400" /> Inputs
                </h2>
                <p className="text-slate-400 text-sm mt-1">
                  Pick an instance type from the list you just generated in the Instance Recommender.
                </p>
                {!options.length && (
                  <div className="mt-3 flex items-center gap-2 text-amber-300 text-sm">
                    <AlertCircle className="h-4 w-4" />
                    No recommendations found. Open the Instance Recommender, enter vCPU & RAM, and click “Get Recommendation”.
                  </div>
                )}
              </div>

              <form onSubmit={handleGenerate} className="p-6 grid gap-5">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
                  <label className="grid gap-1">
                    <span className="text-slate-300 text-sm font-medium flex items-center gap-2">
                      <Cloud className="h-4 w-4 text-sky-400" /> Provider
                    </span>
                    <select
                      name="provider"
                      value={form.provider}
                      onChange={onFormText}
                      className="h-10 w-full rounded-xl bg-slate-950 border border-slate-700 px-3 text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    >
                      <option>AWS</option>
                    </select>
                  </label>

                  <label className="grid gap-1">
                    <span className="text-slate-300 text-sm font-medium flex items-center gap-2">
                      <Cloud className="h-4 w-4 text-purple-400" /> Region
                    </span>
                    <input
                      type="text"
                      name="region"
                      value={form.region}
                      onChange={onFormText}
                      className="h-10 w-full rounded-xl bg-slate-950 border border-slate-700 px-3 text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    />
                  </label>
                </div>

                {/* Instance Type dropdown fed by InstanceRecommender */}
                <label className="grid gap-1">
                  <span className="text-slate-300 text-sm font-medium flex items-center gap-2">
                    <ListChecks className="h-4 w-4 text-emerald-400" /> Instance Type (recommended)
                  </span>
                  <select
                    value={selectedType}
                    onChange={(e) => setSelectedType(e.target.value)}
                    className="h-10 w-full rounded-xl bg-slate-950 border border-slate-700 px-3 text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    disabled={!options.length}
                  >
                    {!options.length && <option>(no recommendations yet)</option>}
                    {options.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                </label>

                {/* Optional extras */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
                  <label className="grid gap-1">
                    <span className="text-slate-300 text-sm font-medium flex items-center gap-2">
                      <FileCode2 className="h-4 w-4 text-amber-400" /> Root Volume (GiB)
                    </span>
                    <input
                      type="number"
                      name="volume_gb"
                      value={form.volume_gb}
                      onChange={onFormNumber}
                      min={8}
                      step={1}
                      className="h-10 w-full rounded-xl bg-slate-950 border border-slate-700 px-3 text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    />
                  </label>

                  <label className="grid gap-1">
                    <span className="text-slate-300 text-sm font-medium flex items-center gap-2">
                      <FileCode2 className="h-4 w-4 text-amber-400" /> Tag “Name”
                    </span>
                    <input
                      type="text"
                      name="tag_name"
                      value={form.tag_name}
                      onChange={onFormText}
                      className="h-10 w-full rounded-xl bg-slate-950 border border-slate-700 px-3 text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    />
                  </label>
                </div>

                <div className="flex items-center justify-end gap-3 pt-2">
                  <button
                    type="submit"
                    disabled={loading || !selectedType}
                    className="inline-flex items-center justify-center rounded-xl bg-indigo-600 hover:bg-indigo-500 px-4 py-2 font-medium disabled:opacity-60"
                  >
                    {loading ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <FileCode2 className="h-4 w-4 mr-2" />}
                    {loading ? "Generating..." : "Generate Terraform"}
                  </button>
                </div>

                {genError && (
                  <div className="rounded-2xl border border-red-900 bg-red-950 text-red-200 p-4 text-sm">
                    {genError}
                  </div>
                )}
              </form>
            </div>
          </motion.section>

          {/* Right: Output */}
          <motion.section
            initial={{ opacity: 0, x: 16 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.25 }}
            className="lg:col-span-7"
          >
            <div className="rounded-2xl bg-slate-900/80 border border-slate-800 shadow-xl h-full flex flex-col">
              <div className="p-6 border-b border-slate-800 flex items-center justify-between">
                <div>
                  <h2 className="text-xl font-semibold flex items-center gap-2">
                    <FileCode2 className="h-5 w-5 text-emerald-400" /> Output
                  </h2>
                  <p className="text-slate-400 text-sm mt-1">
                    Your generated <code>main.tf</code> appears below.
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={async () => {
                      try {
                        await navigator.clipboard.writeText(script || "");
                        setCopied(true);
                        setTimeout(() => setCopied(false), 1200);
                      } catch {}
                    }}
                    disabled={!script}
                    className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm hover:bg-slate-900 disabled:opacity-50"
                  >
                    {copied ? (
                      <>
                        <ClipboardCheck className="h-4 w-4 text-emerald-400" /> Copied
                      </>
                    ) : (
                      <>
                        <Clipboard className="h-4 w-4" /> Copy
                      </>
                    )}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      const blob = new Blob([script || ""], { type: "text/plain" });
                      const url = URL.createObjectURL(blob);
                      const a = document.createElement("a");
                      a.href = url;
                      a.download = "main.tf";
                      document.body.appendChild(a);
                      a.click();
                      a.remove();
                      URL.revokeObjectURL(url);
                    }}
                    disabled={!script}
                    className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm hover:bg-slate-900 disabled:opacity-50"
                  >
                    <Download className="h-4 w-4" /> Download
                  </button>
                </div>
              </div>

              <div className="p-6">
                <pre className="w-full min-h-[320px] whitespace-pre-wrap rounded-xl bg-slate-950 border border-slate-800 p-4 text-xs leading-relaxed overflow-auto">
{script || "// Your Terraform will appear here after generation."}
                </pre>
              </div>
            </div>
          </motion.section>
        </main>

        <footer className="mx-auto max-w-7xl px-6 py-8 text-center text-xs text-slate-500 border-t border-slate-800">
          Cloud Migration Toolkit · Terraform Generator
        </footer>
      </div>
    </div>
  );
}
