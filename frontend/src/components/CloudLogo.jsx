// frontend/src/components/CloudLogo.jsx
import React from "react";

export default function CloudLogo({ className = "" }) {
  return (
    <div className={`flex items-center gap-3 ${className}`}>
      {/* Cloud glyph (soft blue gradient) */}
      <svg width="40" height="28" viewBox="0 0 40 28" aria-hidden="true">
        <defs>
          <linearGradient id="cmg" x1="0" x2="1" y1="0" y2="1">
            <stop offset="0" stopColor="#9AD8FF" />
            <stop offset="1" stopColor="#6BC2FF" />
          </linearGradient>
        </defs>
        <g fill="url(#cmg)">
          <circle cx="12" cy="14" r="10" />
          <circle cx="20" cy="10" r="8" />
          <circle cx="28" cy="14" r="9" />
        </g>
      </svg>

      {/* Wordmark */}
      <div className="leading-tight">
        <div className="text-xs tracking-widest text-slate-300 uppercase">
          Cloud Migration
        </div>
        <div className="text-xl font-semibold text-slate-100 -mt-0.5">Console</div>
      </div>
    </div>
  );
}
