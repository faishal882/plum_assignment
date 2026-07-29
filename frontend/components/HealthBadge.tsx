"use client";

import { useEffect, useState } from "react";
import { Activity, CheckCircle2, AlertTriangle, RefreshCw } from "lucide-react";

interface HealthState {
  status: "loading" | "healthy" | "degraded" | "unreachable";
  live: boolean;
  ready: boolean;
}

export function HealthBadge() {
  const [health, setHealth] = useState<HealthState>({
    status: "loading",
    live: false,
    ready: false,
  });
  const [isRefreshing, setIsRefreshing] = useState(false);

  const checkHealth = async () => {
    setIsRefreshing(true);
    try {
      const res = await fetch("/api/health", { cache: "no-store" });
      if (res.ok) {
        const data = await res.json();
        setHealth({
          status: data.status,
          live: data.live,
          ready: data.ready,
        });
      } else {
        setHealth({ status: "unreachable", live: false, ready: false });
      }
    } catch {
      setHealth({ status: "unreachable", live: false, ready: false });
    } finally {
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    checkHealth();
    const interval = setInterval(checkHealth, 15000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div
      className="inline-flex items-center gap-2 px-3 py-1.5 rounded-control bg-canvas text-xs font-semibold neu-inset-sm border border-hairline"
      title={
        health.status === "healthy"
          ? "Backend API & Database Ready"
          : health.status === "degraded"
          ? "API Live, DB Not Ready"
          : "API Unreachable"
      }
    >
      {health.status === "loading" && (
        <>
          <RefreshCw className="w-3.5 h-3.5 animate-spin text-copy" />
          <span className="text-copy">Checking API...</span>
        </>
      )}

      {health.status === "healthy" && (
        <>
          <span className="w-2 h-2 rounded-full bg-teal animate-pulse" />
          <span className="text-ink">API Ready</span>
        </>
      )}

      {health.status === "degraded" && (
        <>
          <AlertTriangle className="w-3.5 h-3.5 text-amber-500" />
          <span className="text-amber-700">API Degraded</span>
        </>
      )}

      {health.status === "unreachable" && (
        <>
          <span className="w-2 h-2 rounded-full bg-danger" />
          <span className="text-danger font-medium">Backend Offline</span>
        </>
      )}

      <button
        onClick={checkHealth}
        disabled={isRefreshing}
        className="ml-1 p-0.5 hover:text-violet transition-colors rounded"
        aria-label="Refresh API health status"
      >
        <RefreshCw
          className={`w-3 h-3 text-copy ${isRefreshing ? "animate-spin" : ""}`}
        />
      </button>
    </div>
  );
}
