import React, { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  Server, Cloud, ListChecks, Loader2, AlertCircle, Trash2, PlayCircle, RefreshCw,
} from "lucide-react";
import { getEligibles, subscribeEligibles } from "../store/eligiblesStore";
import { createAwsInstance, destroyProvisionStack, getProvisionStatus } from "../services/api";

const HOURS_PER_MONTH = 730;
const fmtHr = (n) => (n == null || n <= 0 ? "—" : `$${Number(n).toFixed(4)}`);
const fmtMo = (n) => (n == null || n <= 0 ? "—" : `$${(Number(n) * HOURS_PER_MONTH).toFixed(2)}`);

export default function IaCGenerator() {
  const regionEnv = process.env.REACT_APP_TARGET_REGION || "us-east-1";

  // read the recommended list from InstanceRecommender
  const [recs, setRecs] = useState(() => getEligibles());
  const [selectedType, setSelectedType] = useState(recs[0]?.instance_type || "");

  useEffect(() => {
    const unsub = subscribeEligibles((rows) => {
      setRecs(rows);
      if (!rows.length) setSelectedType("");
      else if (!rows.find((r) => r.instance_type === selectedType)) {
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
    region: regionEnv,
    volume_gb: 20,
    tag_name: "demo-instance",
  });
  const onText = (e) => setForm((p) => ({ ...p, [e.target.name]: e.target.value }));
  const onNum = (e) => setForm((p) => ({ ...p, [e.target.name]: Number(e.target.value) || 0 }));

  // provisioning state
  const [creating, setCreating] = useState(false);
  const [destroying, setDestroying] = useState(false);
  const [error, setError] = useState(null);
  const [stack, setStack] = useState(null); // { stack_id, region, instance{...}, network{...} }

  const createInstance = async (e) => {
    e.preventDefault();
    setError(null);
    if (!selectedType) {
      setError("Pick an instance type from the dropdown first.");
      return;
    }
    setCreating(true);
    setStack(null);
    try {
      const res = await createAwsInstance({
        region: form.region,
        instance_type: selectedType,
        volume_gb: form.volume_gb,
        tag_name: form.tag_name,
      });
      setStack(res.data);
    } catch (err) {
      console.error(err);
      setError(err?.response?.data?.error || "Failed to create instance.");
    } finally {
      setCreating(false);
    }
  };

  const refreshStatus = async () => {
    if (!stack?.stack_id) return;
    try {
      const res = await getProvisionStatus(stack.region || form.region, stack.stack_id);
      setStack((s) => ({ ...(s || {}), status: res.data }));
    } catch {}
  };

  const destroyStack = async () => {
    if (!stack?.stack_id) return;
    setDestroying(true);
    setError(null);
    try {
      await destroyProvisionStack({ region: stack.region || form.region, stack_id: stack.stack_id });
      setStack((s) => (s ? { ...s, destroyed: true } : s));
    } catch (err) {
      console.error(err);
      setError(err?.response?.data?.error || "Failed to destroy stack.");
    } finally {
      setDestroying(false);
    }
  };

  return (
    <div className="dark">
      <div className="min-h-screen bg-gradient-to-b from-slate-950 to-slate-900 text-slate-100 font-sans">
        {/* Header */}
        <header className="sticky top-0 z-40 border-b border-slate-800 bg-slate-950/90 backdrop-blur">
          <div className="mx-auto max-w-7xl px-6 py-4 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-xl bg-slate-900 border border-slate-800">
                <Server className="h-5 w-5 text-emerald-400" />
              </div>
              <div>
                <div className="text-xs uppercase tracking-widest text-slate-400">AWS Provisioner</div>
                <div className="text-lg font-semibold leading-none">Create & Destroy Instance</div>
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
          {/* Left panel: Inputs */}
          <motion.section
            initial={{ opacity: 0, x: -16 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.25 }}
            className="lg:col-span-5"
          >
            <div className="rounded-2xl bg-slate-900/80 border border-slate-800 shadow-xl">
              <div className="p-6 border-b border-slate-800">
                <h2 className="text-xl font-semibold flex items-center gap-2">
                  <Server className="h-5 w-5 text-emerald-400" /> Inputs
                </h2>
                <p className="text-slate-400 text-sm mt-1">
                  Pick an instance type from the list you generated in the Instance Recommender.
                </p>
                {!options.length && (
                  <div className="mt-3 flex items-center gap-2 text-amber-300 text-sm">
                    <AlertCircle className="h-4 w-4" />
                    No recommendations found. Open the Instance Recommender, enter vCPU & RAM, and click “Get Recommendation”.
                  </div>
                )}
              </div>

              <form onSubmit={createInstance} className="p-6 grid gap-5">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
                  <label className="grid gap-1">
                    <span className="text-slate-300 text-sm font-medium flex items-center gap-2">
                      <Cloud className="h-4 w-4 text-sky-400" /> Region
                    </span>
                    <input
                      type="text"
                      name="region"
                      value={form.region}
                      onChange={onText}
                      className="h-10 w-full rounded-xl bg-slate-950 border border-slate-700 px-3 text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    />
                  </label>

                  <label className="grid gap-1">
                    <span className="text-slate-300 text-sm font-medium flex items-center gap-2">
                      <ListChecks className="h-4 w-4 text-emerald-400" /> Recommended Instances
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
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
                  <label className="grid gap-1">
                    <span className="text-slate-300 text-sm font-medium">Root Volume (GiB)</span>
                    <input
                      type="number"
                      name="volume_gb"
                      value={form.volume_gb}
                      onChange={onNum}
                      min={8}
                      step={1}
                      className="h-10 w-full rounded-xl bg-slate-950 border border-slate-700 px-3 text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    />
                  </label>

                  <label className="grid gap-1">
                    <span className="text-slate-300 text-sm font-medium">Tag “Name”</span>
                    <input
                      type="text"
                      name="tag_name"
                      value={form.tag_name}
                      onChange={onText}
                      className="h-10 w-full rounded-xl bg-slate-950 border border-slate-700 px-3 text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    />
                  </label>
                </div>

                <div className="flex items-center justify-end gap-3 pt-2">
                  <button
                    type="submit"
                    disabled={creating || !selectedType}
                    className="inline-flex items-center justify-center rounded-xl bg-indigo-600 hover:bg-indigo-500 px-4 py-2 font-medium disabled:opacity-60"
                  >
                    {creating ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <PlayCircle className="h-4 w-4 mr-2" />}
                    {creating ? "Creating…" : "Create Instance"}
                  </button>
                </div>

                {error && (
                  <div className="rounded-2xl border border-red-900 bg-red-950 text-red-200 p-4 text-sm">
                    {error}
                  </div>
                )}
              </form>
            </div>
          </motion.section>

          {/* Right panel: Result */}
          <motion.section
            initial={{ opacity: 0, x: 16 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.25 }}
            className="lg:col-span-7"
          >
            <div className="rounded-2xl bg-slate-900/80 border border-slate-800 shadow-xl h-full flex flex-col">
              {/* Card header — title + blurb only (moved buttons out) */}
              <div className="p-6 border-b border-slate-800">
                <h2 className="text-xl font-semibold flex items-center gap-2">
                  <Server className="h-5 w-5 text-emerald-400" /> Provisioning Result
                </h2>
                <p className="text-slate-400 text-sm mt-1">
                  We launch into the default VPC if available; otherwise we create a minimal VPC that’s tagged to your stack.
                </p>
              </div>

              {/* Card body — all details stay inside the same border */}
              <div className="p-6 space-y-4">
                {!stack && (
                  <div className="text-slate-400 text-sm">
                    Create an instance to see details here.
                  </div>
                )}

                {stack && (
                  <div className="grid gap-3 text-sm">
                    <div className="grid grid-cols-2 gap-2">
                      <div className="rounded-xl border border-slate-700 p-3">
                        <div className="text-slate-400">Stack ID</div>
                        <div className="font-mono">{stack.stack_id}</div>
                      </div>
                      <div className="rounded-xl border border-slate-700 p-3">
                        <div className="text-slate-400">Region</div>
                        <div className="font-mono">{stack.region}</div>
                      </div>
                    </div>

                    <div className="rounded-xl border border-slate-700 p-3">
                      <div className="text-slate-400 mb-1">Instance</div>
                      <div className="font-mono break-all">
                        id={stack.instance?.id} · type={stack.instance?.type} · state={stack.instance?.state} · ip={stack.instance?.public_ip || "—"}
                      </div>
                    </div>

                    <div className="rounded-xl border border-slate-700 p-3">
                      <div className="text-slate-400 mb-1">Network</div>
                      <div className="font-mono break-all">
                        vpc={stack.network?.vpc_id} (created={String(stack.network?.created_vpc)}) · subnet={stack.network?.subnet_id} · sg={stack.network?.security_group_id}
                      </div>
                    </div>

                    {stack.status && (
                      <div className="rounded-xl border border-slate-700 p-3">
                        <div className="text-slate-400 mb-1">Status</div>
                        <pre className="text-xs whitespace-pre-wrap">{JSON.stringify(stack.status, null, 2)}</pre>
                      </div>
                    )}

                    {stack.destroyed && (
                      <div className="rounded-2xl border border-emerald-800 bg-emerald-950 text-emerald-200 p-3">
                        Stack destroyed. Instance terminated and associated resources cleaned up.
                      </div>
                    )}
                  </div>
                )}

                {/* Card footer — primary-style buttons moved below results */}
                <div className="flex items-center justify-end gap-3 pt-2">
                  <button
                    type="button"
                    onClick={refreshStatus}
                    disabled={!stack?.stack_id}
                    className="inline-flex items-center justify-center rounded-xl bg-indigo-600 hover:bg-indigo-500 px-4 py-2 font-medium disabled:opacity-60"
                  >
                    <RefreshCw className="h-4 w-4 mr-2" />
                    Refresh
                  </button>
                  <button
                    type="button"
                    onClick={destroyStack}
                    disabled={!stack?.stack_id || destroying}
                    className="inline-flex items-center justify-center rounded-xl bg-rose-600 hover:bg-rose-500 px-4 py-2 font-medium disabled:opacity-60"
                  >
                    {destroying ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Trash2 className="h-4 w-4 mr-2" />}
                    Destroy Stack
                  </button>
                </div>
              </div>
            </div>
          </motion.section>
        </main>

        <footer className="mx-auto max-w-7xl px-6 py-8 text-center text-xs text-slate-500 border-t border-slate-800">
          Cloud Migration Toolkit · AWS Provisioner
        </footer>
      </div>
    </div>
  );
}
