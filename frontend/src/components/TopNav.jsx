// frontend/src/components/TopNav.jsx
import React, { useEffect, useRef, useState } from "react";
import { NavLink } from "react-router-dom";
import { Cloud, ChevronDown, LogOut } from "lucide-react";
import CloudLogo from "./CloudLogo";

const tabBase =
  "px-4 h-9 inline-flex items-center rounded-xl border border-slate-800 bg-slate-950 text-slate-300 hover:bg-slate-900 hover:text-slate-100 transition";
const tabActive =
  "bg-slate-900 text-slate-100 ring-1 ring-indigo-500/40 border-slate-700";

function useOutsideClose(ref, onClose) {
  useEffect(() => {
    const handler = (e) => {
      if (ref.current && !ref.current.contains(e.target)) onClose();
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [onClose, ref]);
}

export default function TopNav({
  user = { name: "Alex Morgan", email: "alex@example.com" },
  onSignOut = () => {},
}) {
  const initials = (user?.name || "U")
    .split(" ")
    .map((n) => n[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  const [open, setOpen] = useState(false);
  const menuRef = useRef(null);
  useOutsideClose(menuRef, () => setOpen(false));

  const tabs = [
    { to: "/", label: "Dashboard", end: true },
    { to: "/cost", label: "Cost Estimator" },
    { to: "/recommend", label: "Instance Recommender" },
    { to: "/provision", label: "Provisioner" },
    { to: "/monitor", label: "Monitoring" },
  ];

  return (
    <header className="sticky top-0 z-50 w-full border-b border-slate-800 bg-slate-950/90 backdrop-blur">
      <div className="mx-auto max-w-7xl px-6 py-4 flex items-center justify-between">
        {/* Left: exact logo */}
        <CloudLogo />

        {/* Middle: tabs */}
        <nav className="flex-1 flex items-center gap-2 pl-4">
          <div className="flex items-center gap-2 overflow-x-auto">
            {tabs.map((t) => (
              <NavLink
                key={t.to}
                to={t.to}
                end={t.end}
                className={({ isActive }) =>
                  `${tabBase} ${isActive ? tabActive : ""}`
                }
              >
                {t.label}
              </NavLink>
            ))}
          </div>
        </nav>

        {/* Right: region pill + user */}
        <div className="flex items-center gap-3">
          <div className="h-10 px-3 inline-flex items-center gap-2 rounded-xl border border-slate-800 bg-slate-950 text-slate-300">
            {/* Little cloud icon next to Region */}
            <Cloud className="h-4 w-4 text-slate-300" />
          </div>

          {/* User dropdown */}
          <div className="relative" ref={menuRef}>
            <button
              onClick={() => setOpen((v) => !v)}
              className="h-10 pl-2 pr-2.5 inline-flex items-center gap-2 rounded-xl border border-slate-800 bg-slate-950 hover:bg-slate-900"
            >
              <div className="h-7 w-7 rounded-full bg-indigo-600 text-white grid place-items-center text-xs font-semibold">
                {initials}
              </div>
              <div className="hidden sm:block text-left">
                <div className="text-[11px] text-slate-400 leading-none">
                  Signed in
                </div>
                <div className="text-sm text-slate-200 leading-tight">
                  {user?.name}
                </div>
              </div>
              <ChevronDown
                className={`h-4 w-4 text-slate-400 transition-transform ${
                  open ? "rotate-180" : ""
                }`}
              />
            </button>

            {open && (
              <div className="absolute right-0 mt-2 w-64 rounded-xl border border-slate-800 bg-slate-950 shadow-xl p-2">
                <div className="px-3 py-2">
                  <div className="text-sm text-slate-200">{user?.name}</div>
                  <div className="text-xs text-slate-400 truncate">
                    {user?.email}
                  </div>
                </div>
                <button
                  onClick={() => {
                    setOpen(false);
                    onSignOut();
                  }}
                  className="w-full inline-flex items-center gap-2 px-3 py-2 text-sm rounded-lg hover:bg-slate-900 text-slate-200"
                >
                  <LogOut className="h-4 w-4" /> Sign out
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}
