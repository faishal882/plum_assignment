import { callClaimsApi, passThrough } from "@/lib/claims-api";

export async function GET(
  request: Request,
  context: { params: Promise<{ claimId: string }> }
) {
  const { claimId } = await context.params;
  const devUsername =
    request.headers.get("X-Dev-Username") ||
    process.env.CLAIMS_DEV_USERNAME ||
    "member.emp001";

  const response = await callClaimsApi(`/v1/claims/${claimId}`, {}, devUsername);
  return passThrough(response);
}
