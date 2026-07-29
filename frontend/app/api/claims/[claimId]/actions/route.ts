import { callClaimsApi, passThrough } from "@/lib/claims-api";

export async function POST(
  request: Request,
  context: { params: Promise<{ claimId: string }> }
) {
  try {
    const { claimId } = await context.params;
    const formData = await request.formData();
    const idempotencyKey = request.headers.get("Idempotency-Key");
    const devUsername =
      request.headers.get("X-Dev-Username") ||
      process.env.CLAIMS_DEV_USERNAME ||
      "member.emp001";

    if (!idempotencyKey) {
      return Response.json(
        {
          error: {
            code: "IDEMPOTENCY_KEY_REQUIRED",
            message: "An Idempotency-Key header is required.",
            details: [],
          },
        },
        { status: 400 }
      );
    }

    const response = await callClaimsApi(
      `/v1/claims/${claimId}/actions`,
      {
        method: "POST",
        headers: {
          "Idempotency-Key": idempotencyKey,
        },
        body: formData,
      },
      devUsername
    );

    return passThrough(response);
  } catch (err: unknown) {
    return Response.json(
      {
        error: {
          code: "INTERNAL_BFF_ERROR",
          message: err instanceof Error ? err.message : "Failed to process claim action",
          details: [],
        },
      },
      { status: 500 }
    );
  }
}
