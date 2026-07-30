"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { HealthBadge } from "./HealthBadge";
import { Shield, PlusCircle, ClipboardList, UserCheck, UserPlus } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  DEV_IDENTITY_STORAGE_KEY,
  DevIdentity,
  readStoredDevIdentity,
  storeDevIdentity,
} from "@/lib/dev-identities";

type NewIdentityForm = {
  username: string;
  full_name: string;
  date_of_birth: string;
  gender: string;
  join_date: string;
};

const emptyForm: NewIdentityForm = {
  username: "",
  full_name: "",
  date_of_birth: "",
  gender: "",
  join_date: "",
};

export function TopNav() {
  const pathname = usePathname();
  const [selectedUser, setSelectedUser] = useState<string>("member.emp001");
  const [identities, setIdentities] = useState<DevIdentity[]>([]);
  const [query, setQuery] = useState("");
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [form, setForm] = useState<NewIdentityForm>(emptyForm);
  const [createError, setCreateError] = useState<string | null>(null);
  const [showIdentityMenu, setShowIdentityMenu] = useState(false);

  const selectedIdentity = identities.find((identity) => identity.username === selectedUser);
  const filteredIdentities = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return identities;
    return identities.filter((identity) =>
      [identity.username, identity.member_id || "", identity.display_name]
        .join(" ")
        .toLowerCase()
        .includes(needle)
    );
  }, [identities, query]);

  useEffect(() => {
    void loadIdentities();
  }, []);

  async function loadIdentities(selectUsername?: string) {
    const response = await fetch("/api/dev/identities", { cache: "no-store" });
    if (!response.ok) {
      const stored = readStoredDevIdentity();
      setSelectedUser(stored.username);
      return;
    }
    const loaded = (await response.json()) as DevIdentity[];
    setIdentities(loaded);
    const saved = selectUsername || localStorage.getItem(DEV_IDENTITY_STORAGE_KEY);
    const selected =
      loaded.find((identity) => identity.username === saved) ||
      loaded.find((identity) => identity.username === "member.emp001") ||
      loaded[0];
    if (selected) {
      setSelectedUser(selected.username);
      storeDevIdentity(selected);
    }
  }

  function handleUserChange(identity: DevIdentity) {
    setSelectedUser(identity.username);
    storeDevIdentity(identity);
    setShowIdentityMenu(false);
  }

  async function createIdentity() {
    setCreateError(null);
    const normalizedUsername = form.username.trim().toLowerCase();
    if (identities.some((identity) => identity.username === normalizedUsername)) {
      setCreateError("That username already exists in the selector.");
      return;
    }
    const response = await fetch("/api/dev/identities", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ ...form, relationship: "SELF" }),
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      setCreateError(
        payload?.error?.message || payload?.detail?.message || "Could not create local identity."
      );
      return;
    }
    const identity = payload as DevIdentity;
    setForm(emptyForm);
    setQuery("");
    setShowCreateForm(false);
    await loadIdentities(identity.username);
    handleUserChange(identity);
  }

  return (
    <header className="w-full pt-4 pb-2 px-4 sm:px-8">
      <div className="max-w-7xl mx-auto h-[65px] px-6 rounded-frame bg-canvas neu-raised-sm border border-hairline flex items-center justify-between gap-4">
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

        <div className="flex items-center gap-3">
          <HealthBadge />

          <div className="relative">
            <button
              onClick={() => setShowIdentityMenu(!showIdentityMenu)}
              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-control text-xs font-medium bg-canvas neu-inset-sm border border-hairline text-copy hover:text-ink transition-colors"
              title="Local dev identity selector"
            >
              <UserCheck className="w-3.5 h-3.5 text-violet" />
              <span className="hidden sm:inline text-[11px] text-copy">Dev User:</span>
              <span className="font-semibold text-ink">
                {selectedIdentity
                  ? `${selectedIdentity.display_name} · ${selectedIdentity.member_id || selectedIdentity.username}`
                  : selectedUser}
              </span>
            </button>

            {showIdentityMenu && (
              <div className="absolute right-0 mt-2 w-80 p-3 rounded-card bg-canvas neu-raised border border-hairline z-50 shadow-xl">
                <div className="mb-3 pb-2 border-b border-hairline">
                  <p className="text-xs font-semibold text-ink">Local Demo Identity Selector</p>
                  <p className="text-[10px] text-copy">
                    Switch to any DB-backed user by employee ID, name, or username.
                  </p>
                </div>

                <input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Search name, username, or EMP ID"
                  className="mb-2 w-full px-3 py-2 rounded-control bg-canvas border border-hairline text-xs text-ink neu-inset-sm focus:outline-none focus:ring-2 focus:ring-violet"
                />

                <div className="space-y-1 max-h-[300px] overflow-y-auto pr-1">
                  {filteredIdentities.map((identity) => (
                    <button
                      key={identity.username}
                      onClick={() => handleUserChange(identity)}
                      className={`w-full text-left px-2.5 py-2 rounded-control text-xs transition-colors ${
                        selectedUser === identity.username
                          ? "bg-violet text-white font-semibold"
                          : "hover:bg-violet-pale text-ink"
                      }`}
                    >
                      <span className="flex items-center justify-between gap-3">
                        <span className="font-mono">{identity.member_id || "No employee ID"}</span>
                        <span
                          className={`truncate ${
                            selectedUser === identity.username ? "text-white/80" : "text-copy"
                          }`}
                        >
                          {identity.display_name}
                        </span>
                      </span>
                      <span
                        className={`block font-mono text-[10px] ${
                          selectedUser === identity.username ? "text-white/70" : "text-copy"
                        }`}
                      >
                        {identity.username} · {identity.roles.join(", ")}
                      </span>
                    </button>
                  ))}
                </div>

                <div className="mt-3 pt-3 border-t border-hairline">
                  <button
                    onClick={() => setShowCreateForm(!showCreateForm)}
                    className="w-full inline-flex items-center justify-center gap-2 rounded-control bg-violet-pale px-3 py-2 text-xs font-semibold text-violet hover:bg-violet hover:text-white transition-colors"
                  >
                    <UserPlus className="w-3.5 h-3.5" />
                    {showCreateForm ? "Hide creator" : "Create local demo member"}
                  </button>

                  {showCreateForm && (
                    <div className="mt-3 space-y-2">
                      {createError && <p className="text-[11px] text-danger">{createError}</p>}
                      <p className="text-[10px] text-copy">
                        Employee ID is assigned automatically and saved with the local member.
                      </p>
                      {[
                        ["full_name", "Full name", "text"],
                        ["username", "Username", "text"],
                        ["date_of_birth", "Date of birth", "date"],
                        ["gender", "Gender", "text"],
                        ["join_date", "Join date", "date"],
                      ].map(([name, label, type]) => (
                        <label key={name} className="block text-[11px] font-semibold text-copy">
                          {label}
                          <input
                            type={type}
                            value={form[name as keyof NewIdentityForm]}
                            onChange={(event) =>
                              setForm((current) => ({ ...current, [name]: event.target.value }))
                            }
                            className="mt-1 w-full px-2.5 py-1.5 rounded-control bg-canvas border border-hairline text-xs text-ink"
                          />
                        </label>
                      ))}
                      <button
                        onClick={() => void createIdentity()}
                        className="w-full rounded-control bg-violet px-3 py-2 text-xs font-semibold text-white hover:bg-violet-accent transition-colors"
                      >
                        Create and select identity
                      </button>
                    </div>
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
