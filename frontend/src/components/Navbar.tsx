"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import { useSites } from "@/lib/api";
import type { WsStatus } from "@/lib/useWebSocket";

interface NavbarProps {
  wsStatus?: WsStatus;
}

function WsIndicator({ status }: { status?: WsStatus }) {
  const map: Record<WsStatus, { color: string; label: string }> = {
    connected:    { color: "bg-green-500",  label: "Live" },
    connecting:   { color: "bg-amber-400 animate-pulse", label: "Connecting" },
    disconnected: { color: "bg-slate-500",  label: "Offline" },
    error:        { color: "bg-red-500",    label: "Error" },
  };
  const s = status ?? "disconnected";
  const { color, label } = map[s];
  return (
    <span className="flex items-center gap-1.5 text-xs text-slate-400">
      <span className={`size-2 rounded-full ${color}`} />
      {label}
    </span>
  );
}

export default function Navbar({ wsStatus }: NavbarProps) {
  const { data: sites } = useSites();
  const pathname = usePathname();
  const router = useRouter();
  const [open, setOpen] = useState(false);

  const currentSiteId = (() => {
    const m = pathname.match(/^\/sites\/(\d+)/);
    return m ? parseInt(m[1]) : null;
  })();
  const currentSite = sites?.find((s) => s.id === currentSiteId);

  return (
    <nav className="sticky top-0 z-50 h-14 border-b border-[#1e2d4a] bg-[#0f1629]/90 backdrop-blur-sm flex items-center px-4 gap-4">
      {/* Logo */}
      <Link href="/" className="flex items-center gap-2 shrink-0">
        <svg className="size-5 text-cyan-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
        </svg>
        <span className="font-semibold text-sm tracking-wide text-slate-100 hidden sm:block">
          Groundwater<span className="text-cyan-400">Monitor</span>
        </span>
      </Link>

      <div className="h-5 w-px bg-[#1e2d4a] hidden sm:block" />

      {/* Site switcher */}
      <div className="relative">
        <button
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-2 rounded-md border border-[#1e2d4a] bg-[#141c35] px-3 py-1.5 text-sm text-slate-200 hover:border-slate-500 transition-colors"
        >
          <span className="max-w-36 truncate">
            {currentSite ? currentSite.name : "All Sites"}
          </span>
          <svg className="size-3.5 text-slate-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
          </svg>
        </button>

        {open && (
          <>
            <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
            <div className="absolute left-0 top-full mt-1 z-50 min-w-52 rounded-md border border-[#1e2d4a] bg-[#141c35] shadow-xl overflow-hidden">
              <button
                className="w-full px-3 py-2 text-left text-sm text-slate-300 hover:bg-[#1a2340] transition-colors"
                onClick={() => { router.push("/"); setOpen(false); }}
              >
                All Sites — Overview
              </button>
              <div className="h-px bg-[#1e2d4a]" />
              {sites?.map((site) => (
                <button
                  key={site.id}
                  className={`w-full px-3 py-2 text-left text-sm transition-colors hover:bg-[#1a2340] ${
                    site.id === currentSiteId ? "text-cyan-400" : "text-slate-300"
                  }`}
                  onClick={() => { router.push(`/sites/${site.id}`); setOpen(false); }}
                >
                  {site.name}
                  {site.location && (
                    <span className="ml-1.5 text-xs text-slate-500">{site.location}</span>
                  )}
                </button>
              ))}
            </div>
          </>
        )}
      </div>

      <div className="ml-auto flex items-center gap-4">
        <WsIndicator status={wsStatus} />
        <Link
          href="/"
          className={`text-xs transition-colors ${pathname === "/" ? "text-cyan-400" : "text-slate-400 hover:text-slate-200"}`}
        >
          Overview
        </Link>
      </div>
    </nav>
  );
}
