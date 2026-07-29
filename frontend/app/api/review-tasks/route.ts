import { callClaimsApi, passThrough } from "@/lib/claims-api";

export async function GET(request: Request) {
  const devUsername =
    request.headers.get("X-Dev-Username") ||
    process.env.CLAIMS_REVIEWER_USERNAME ||
    "reviewer.local";

  const response = await callClaimsApi("/v1/review-tasks", {}, devUsername);
  return passThrough(response);
}
