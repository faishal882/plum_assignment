export type DevIdentity = {
  username: string;
  member_id: string | null;
  display_name: string;
  roles: string[];
};

export const DEV_IDENTITY_STORAGE_KEY = "plum_dev_username";
export const DEV_IDENTITY_DETAIL_STORAGE_KEY = "plum_dev_identity_detail";
export const DEV_IDENTITY_CHANGED_EVENT = "plum-dev-identity-changed";
export const DEFAULT_DEV_USERNAME = "member.emp001";

export function readStoredDevIdentity(): DevIdentity {
  if (typeof window === "undefined") {
    return {
      username: DEFAULT_DEV_USERNAME,
      member_id: "EMP001",
      display_name: "Rajesh Kumar",
      roles: ["MEMBER"],
    };
  }

  const stored = window.localStorage.getItem(DEV_IDENTITY_DETAIL_STORAGE_KEY);
  if (stored) {
    try {
      const parsed = JSON.parse(stored) as DevIdentity;
      if (parsed.username && Array.isArray(parsed.roles)) {
        return parsed;
      }
    } catch {
      // Fall through to the legacy username-only value.
    }
  }

  return {
    username: window.localStorage.getItem(DEV_IDENTITY_STORAGE_KEY) || DEFAULT_DEV_USERNAME,
    member_id: null,
    display_name: "Selected local identity",
    roles: [],
  };
}

export function storeDevIdentity(identity: DevIdentity): void {
  window.localStorage.setItem(DEV_IDENTITY_STORAGE_KEY, identity.username);
  window.localStorage.setItem(DEV_IDENTITY_DETAIL_STORAGE_KEY, JSON.stringify(identity));
  window.dispatchEvent(
    new CustomEvent(DEV_IDENTITY_CHANGED_EVENT, {
      detail: identity,
    })
  );
}
