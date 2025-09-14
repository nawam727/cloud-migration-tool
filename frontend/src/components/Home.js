// src/pages/Home.jsx
import {
  Activity,
  Calculator,
  ChevronRight,
  Cpu,
  PlayCircle,
  Server,
  Trash2,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getActivities, subscribeActivities } from "../store/activityStore";

function Tile({ to, icon: Icon, title, desc, iconClass }) {
  return (
    <Link
      to={to}
      className="group rounded-2xl border border-slate-800 bg-slate-900/70 hover:bg-slate-900 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 p-6 lg:p-8 min-h-[140px] flex items-center justify-between"
    >
      <div className="flex items-center gap-4">
        <div className="h-12 w-12 grid place-items-center rounded-xl bg-slate-950 border border-slate-800">
          <Icon className={`h-6 w-6 ${iconClass}`} />
        </div>
        <div>
          <div className="text-xl font-semibold">{title}</div>
          <p className="text-sm text-slate-400 mt-1">{desc}</p>
        </div>
      </div>
      <div className="text-sm text-slate-400 flex items-center gap-2">
        Open <ChevronRight className="h-4 w-4 group-hover:text-indigo-400" />
      </div>
    </Link>
  );
}

export default function Home() {
  const [events, setEvents] = useState(() => getActivities());
  useEffect(() => {
    const unsub = subscribeActivities((rows) => setEvents(rows));
    return unsub;
  }, []);

  const timeAgo = (ts) => {
    const d = typeof ts === "number" ? ts : Number(ts) || Date.now();
    const diff = Math.max(0, Date.now() - d) / 1000;
    if (diff < 60) return `${Math.floor(diff)}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
  };

  return (
    <div className="dark">
      <div className="min-h-screen bg-gradient-to-b from-slate-950 to-slate-900 text-slate-100 font-sans">
        <main className="mx-auto max-w-7xl px-6 py-8 space-y-8">
          {/* Quick Launch (bigger + fully clickable) */}
          <section className="grid gap-6 sm:grid-cols-2">
            <Tile
              to="/cost"
              icon={Calculator}
              iconClass="text-emerald-400"
              title="Cost Estimator"
              desc="Estimate total migration cost from workload inputs."
            />
            <Tile
              to="/recommend"
              icon={Cpu}
              iconClass="text-indigo-400"
              title="Instance Recommender"
              desc="Get eligible EC2 types with live pricing."
            />
            <Tile
              to="/provision"
              icon={Server}
              iconClass="text-emerald-400"
              title="Provisioner"
              desc="Create and destroy EC2 with a minimal network stack."
            />
            <Tile
              to="/monitor"
              icon={Activity}
              iconClass="text-pink-400"
              title="Monitoring"
              desc="Prometheus & Grafana dashboards (optional)."
            />
          </section>

          {/* Recent Activity (unchanged) */}
          <section className="grid gap-6 lg:grid-cols-3">
            <div className="rounded-2xl bg-slate-900/80 border border-slate-800 p-6">
              <div className="text-lg font-semibold">Recent Activity</div>
              <p className="text-sm text-slate-400 mt-1">
                Latest actions across the console.
              </p>
              <div className="mt-4 text-xs text-slate-500">
                Entries auto-populate from the Provisioner and other tools.
                Long values (IDs, JSON) are wrapped or scrollable.
              </div>
            </div>

            <div className="lg:col-span-2 rounded-2xl bg-slate-900/80 border border-slate-800">
              <div className="p-4 border-b border-slate-800 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Activity className="h-4 w-4 text-sky-300" />
                  <div className="font-medium">Activity Feed</div>
                </div>
                <div className="text-xs text-slate-400">
                  {events.length} item{events.length !== 1 ? "s" : ""}
                </div>
              </div>

              <div className="max-h-[420px] overflow-y-auto p-4 space-y-3">
                {events.length === 0 && (
                  <div className="text-sm text-slate-400">No activity yet.</div>
                )}

                {events.map((ev) => {
                  const isCreate = ev.kind === "provision:create";
                  const Icon = isCreate ? PlayCircle : Trash2;
                  const badge = isCreate ? (
                    <span className="text-emerald-300">created</span>
                  ) : (
                    <span className="text-rose-300">destroyed</span>
                  );

                  return (
                    <div
                      key={ev.id}
                      className="rounded-xl border border-slate-700 bg-slate-950/60 p-4"
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div className="flex items-center gap-2 text-slate-200 font-medium">
                          <Icon
                            className={`h-4 w-4 ${
                              isCreate ? "text-emerald-400" : "text-rose-400"
                            }`}
                          />
                          EC2 stack {badge}
                        </div>
                        <div className="text-xs text-slate-400 shrink-0">
                          {timeAgo(ev.ts)}
                        </div>
                      </div>

                      <div className="mt-2 grid gap-1 text-xs text-slate-400">
                        {ev.region && (
                          <div className="truncate">
                            <span className="text-slate-500">Region:</span>{" "}
                            <span className="text-slate-300">{ev.region}</span>
                          </div>
                        )}
                        {ev.instance_id && (
                          <div className="truncate">
                            <span className="text-slate-500">Instance:</span>{" "}
                            <span className="font-mono break-words text-slate-300">
                              {ev.instance_id}
                            </span>
                          </div>
                        )}
                        {ev.instance_type && (
                          <div>
                            <span className="text-slate-500">Type:</span>{" "}
                            <span className="text-slate-300">
                              {ev.instance_type}
                            </span>
                          </div>
                        )}
                        {ev.network && (
                          <div className="text-[11px] text-slate-400 whitespace-pre-line break-words">
                            {[
                              ev.network.vpc_id && `vpc=${ev.network.vpc_id}`,
                              ev.network.subnet_id &&
                                `subnet=${ev.network.subnet_id}`,
                              ev.network.security_group_id &&
                                `sg=${ev.network.security_group_id}`,
                            ]
                              .filter(Boolean)
                              .join(" · ")}
                          </div>
                        )}
                      </div>

                      {ev.details && (
                        <pre className="mt-3 rounded-lg bg-slate-950/80 border border-slate-800 p-3 text-[11px] leading-relaxed overflow-x-auto whitespace-pre overflow-y-hidden">
{typeof ev.details === "string" ? ev.details : JSON.stringify(ev.details, null, 2)}
                        </pre>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          </section>
        </main>

        <footer className="mx-auto max-w-7xl px-6 py-8 text-center text-xs text-slate-500 border-t border-slate-800">
          Cloud Migration Toolkit · Console
        </footer>
      </div>
    </div>
  );
}
