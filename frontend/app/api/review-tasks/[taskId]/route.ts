import { callClaimsApi, passThrough } from "@/lib/claims-api";

export async function GET(
  request: Request,
  context: { params: Promise<{ taskId: string }> }
) {
  const { taskId } = await context.params;
  const devUsername =
    request.headers.get("X-Dev-Username") ||
    process.env.CLAIMS_REVIEWER_USERNAME ||
    "reviewer.local";

  const response = await callClaimsApi(`/v1/review-tasks/${taskId}`, {}, devUsername);
  return passThrough(response);
}
