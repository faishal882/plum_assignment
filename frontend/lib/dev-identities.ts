export type DevIdentity = {
  username: string;
  memberId: string | null;
  displayName: string;
  role: "member" | "reviewer";
};

export const DEV_IDENTITY_STORAGE_KEY = "plum_dev_username";
export const DEV_IDENTITY_CHANGED_EVENT = "plum-dev-identity-changed";

export const DEV_IDENTITIES: readonly DevIdentity[] = [
  { username: "member.emp001", memberId: "EMP001", displayName: "Rajesh Kumar", role: "member" },
  { username: "member.emp002", memberId: "EMP002", displayName: "Priya Singh", role: "member" },
  { username: "member.emp003", memberId: "EMP003", displayName: "Amit Verma", role: "member" },
  { username: "member.emp004", memberId: "EMP004", displayName: "Sneha Reddy", role: "member" },
  { username: "member.emp005", memberId: "EMP005", displayName: "Vikram Joshi", role: "member" },
  { username: "member.emp006", memberId: "EMP006", displayName: "Kavita Nair", role: "member" },
  { username: "member.emp007", memberId: "EMP007", displayName: "Suresh Patil", role: "member" },
  { username: "member.emp008", memberId: "EMP008", displayName: "Ravi Menon", role: "member" },
  { username: "member.emp009", memberId: "EMP009", displayName: "Anita Desai", role: "member" },
  { username: "member.emp010", memberId: "EMP010", displayName: "Deepak Shah", role: "member" },
  { username: "reviewer.local", memberId: null, displayName: "Local Reviewer", role: "reviewer" },
] as const;

export const DEFAULT_DEV_USERNAME = "member.emp001";

export function getDevIdentity(username: string | null | undefined): DevIdentity {
  return (
    DEV_IDENTITIES.find((identity) => identity.username === username) ||
    DEV_IDENTITIES[0]
  );
}

export function readStoredDevIdentity(): DevIdentity {
  if (typeof window === "undefined") {
    return getDevIdentity(DEFAULT_DEV_USERNAME);
  }
  return getDevIdentity(window.localStorage.getItem(DEV_IDENTITY_STORAGE_KEY));
}
