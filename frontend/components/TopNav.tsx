"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { HealthBadge } from "./HealthBadge";
import { Shield, PlusCircle, ClipboardList, UserCheck } from "lucide-react";
import { useEffect, useState } from "react";
import {
  DEV_IDENTITIES,
  DEV_IDENTITY_CHANGED_EVENT,
  DEV_IDENTITY_STORAGE_KEY,
  DEFAULT_DEV_USERNAME,
  getDevIdentity,
} from "@/lib/dev-identities";

export function TopNav() {
  const pathname = usePathname();
  const [selectedUser, setSelectedUser] = useState<string>(DEFAULT_DEV_USERNAME);
  const [showIdentityMenu, setShowIdentityMenu] = useState(false);

  useEffect(() => {
    const saved = localStorage.getItem(DEV_IDENTITY_STORAGE_KEY);
    if (saved) {
      setSelectedUser(getDevIdentity(saved).username);
    }
  }, []);

  const handleUserChange = (username: string) => {
    const identity = getDevIdentity(username);
    setSelectedUser(identity.username);
    localStorage.setItem(DEV_IDENTITY_STORAGE_KEY, identity.username);
    window.dispatchEvent(
      new CustomEvent(DEV_IDENTITY_CHANGED_EVENT, {
        detail: { username: identity.username },
      })
    );
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
              <span className="font-semibold text-ink">
                {getDevIdentity(selectedUser).memberId || selectedUser}
              </span>
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
                <div className="space-y-1 max-h-[420px] overflow-y-auto pr-1">
                  <p className="text-[10px] font-semibold text-copy uppercase tracking-wider">
                    Member Identities
                  </p>
                  {DEV_IDENTITIES.filter((identity) => identity.role === "member").map(
                    (identity) => (
                      <button
                        key={identity.username}
                        onClick={() => handleUserChange(identity.username)}
                        className={`w-full text-left px-2.5 py-2 rounded-control text-xs transition-colors ${
                          selectedUser === identity.username
                            ? "bg-violet text-white font-semibold"
                            : "hover:bg-violet-pale text-ink"
                        }`}
                      >
                        <span className="flex items-center justify-between gap-3">
                          <span className="font-mono">{identity.memberId}</span>
                          <span
                            className={`truncate ${
                              selectedUser === identity.username ? "text-white/80" : "text-copy"
                            }`}
                          >
                            {identity.displayName}
                          </span>
                        </span>
                        <span
                          className={`block font-mono text-[10px] ${
                            selectedUser === identity.username ? "text-white/70" : "text-copy"
                          }`}
                        >
                          {identity.username}
                        </span>
                      </button>
                    )
                  )}
                  <p className="text-[10px] font-semibold text-copy uppercase tracking-wider pt-2">
                    Reviewer Identity
                  </p>
                  {DEV_IDENTITIES.filter((identity) => identity.role === "reviewer").map(
                    (identity) => (
                      <button
                        key={identity.username}
                        onClick={() => handleUserChange(identity.username)}
                        className={`w-full text-left px-2.5 py-2 rounded-control text-xs transition-colors ${
                          selectedUser === identity.username
                            ? "bg-violet text-white font-semibold"
                            : "hover:bg-violet-pale text-ink"
                        }`}
                      >
                        <span className="font-mono">{identity.username}</span>
                        <span className="block text-[10px] opacity-75">
                          {identity.displayName}
                        </span>
                      </button>
                    )
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}
