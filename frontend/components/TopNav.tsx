"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { HealthBadge } from "./HealthBadge";
import { Shield, PlusCircle, ClipboardList, UserCheck } from "lucide-react";
import { useEffect, useState } from "react";

export function TopNav() {
  const pathname = usePathname();
  const [selectedUser, setSelectedUser] = useState<string>("member.emp001");
  const [showIdentityMenu, setShowIdentityMenu] = useState(false);

  useEffect(() => {
    const saved = localStorage.getItem("plum_dev_username");
    if (saved) {
      setSelectedUser(saved);
    }
  }, []);

  const handleUserChange = (username: string) => {
    setSelectedUser(username);
    localStorage.setItem("plum_dev_username", username);
    setShowIdentityMenu(false);
  };

  return (
    <header className="w-full pt-4 pb-2 px-4 sm:px-8">
      <div className="max-w-7xl mx-auto h-[65px] px-6 rounded-frame bg-canvas neu-raised-sm border border-hairline flex items-center justify-between gap-4">
        {/* Brand Logo */}
        <Link href="/" className="flex items-center gap-3 group">
          <div className="w-9 h-9 rounded-control bg-violet flex items-center justify-center text-white neu-raised-sm group-hover:bg-violet-accent transition-colors">
            <Shield className="w-5 h-5" />
          </div>
          <div className="flex flex-col">
            <span className="font-display font-semibold text-lg leading-none text-ink tracking-tight">
              Plum Claims
            </span>
            <span className="text-[10px] font-semibold tracking-widest text-violet uppercase mt-0.5">
              Operations Console
            </span>
          </div>
        </Link>

        {/* Navigation Links */}
        <nav className="hidden md:flex items-center gap-2">
          <Link
            href="/claims/new"
            className={`px-4 py-2 rounded-control text-sm font-semibold flex items-center gap-2 transition-all ${
              pathname === "/claims/new"
                ? "bg-violet text-white neu-raised-sm"
                : "text-ink hover:text-violet hover:bg-violet-pale/50"
            }`}
          >
            <PlusCircle className="w-4 h-4" />
            New Claim
          </Link>

          <Link
            href="/review"
            className={`px-4 py-2 rounded-control text-sm font-semibold flex items-center gap-2 transition-all ${
              pathname.startsWith("/review")
                ? "bg-violet text-white neu-raised-sm"
                : "text-ink hover:text-violet hover:bg-violet-pale/50"
            }`}
          >
            <ClipboardList className="w-4 h-4" />
            Review Queue
          </Link>
        </nav>

        {/* Right Action & Controls */}
        <div className="flex items-center gap-3">
          <HealthBadge />

          {/* Local Identity Selector */}
          <div className="relative">
            <button
              onClick={() => setShowIdentityMenu(!showIdentityMenu)}
              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-control text-xs font-medium bg-canvas neu-inset-sm border border-hairline text-copy hover:text-ink transition-colors"
              title="Local dev identity selector"
            >
              <UserCheck className="w-3.5 h-3.5 text-violet" />
              <span className="hidden sm:inline text-[11px] text-copy">
                Dev User:
              </span>
              <span className="font-semibold text-ink">{selectedUser}</span>
            </button>

            {showIdentityMenu && (
              <div className="absolute right-0 mt-2 w-64 p-3 rounded-card bg-canvas neu-raised border border-hairline z-50 shadow-xl">
                <div className="mb-2 pb-1 border-b border-hairline">
                  <p className="text-xs font-semibold text-ink">
                    Local Demo Identity Selector
                  </p>
                  <p className="text-[10px] text-copy">
                    Header: <code className="text-violet">X-Dev-Username</code>
                  </p>
                </div>
                <div className="space-y-1">
                  <p className="text-[10px] font-semibold text-copy uppercase tracking-wider">
                    Member Identities
                  </p>
                  {["member.emp001", "member.emp002", "member.emp003"].map(
                    (u) => (
                      <button
                        key={u}
                        onClick={() => handleUserChange(u)}
                        className={`w-full text-left px-2 py-1 rounded-control text-xs font-mono transition-colors ${
                          selectedUser === u
                            ? "bg-violet text-white font-semibold"
                            : "hover:bg-violet-pale text-ink"
                        }`}
                      >
                        {u} (EMP00{u.slice(-1)})
                      </button>
                    )
                  )}
                  <p className="text-[10px] font-semibold text-copy uppercase tracking-wider pt-1">
                    Reviewer Identity
                  </p>
                  <button
                    onClick={() => handleUserChange("reviewer.local")}
                    className={`w-full text-left px-2 py-1 rounded-control text-xs font-mono transition-colors ${
                      selectedUser === "reviewer.local"
                        ? "bg-violet text-white font-semibold"
                        : "hover:bg-violet-pale text-ink"
                    }`}
                  >
                    reviewer.local
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}
