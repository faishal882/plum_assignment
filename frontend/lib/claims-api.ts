import { NextResponse } from "next/server";

const getBaseUrl = (): string => {
  const url = process.env.CLAIMS_API_BASE_URL || "http://127.0.0.1:8000";
  return url;
};

export async function callClaimsApi(
  path: string,
  init: RequestInit = {},
  username: string = process.env.CLAIMS_DEV_USERNAME || "member.emp001"
): Promise<Response> {
  const baseUrl = getBaseUrl();
  const targetUrl = new URL(path, baseUrl);

  const headers = new Headers(init.headers);
  if (!headers.has("X-Dev-Username")) {
    headers.set("X-Dev-Username", username);
  }

  return fetch(targetUrl.toString(), {
    ...init,
    headers,
    cache: "no-store",
  });
}

export function passThrough(response: Response): Response {
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers: {
      "content-type": response.headers.get("content-type") ?? "application/json",
    },
  });
}
