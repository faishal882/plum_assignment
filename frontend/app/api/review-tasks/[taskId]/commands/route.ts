import { callClaimsApi, passThrough } from "@/lib/claims-api";

export async function POST(
  request: Request,
  context: { params: Promise<{ taskId: string }> }
) {
  try {
    const { taskId } = await context.params;
    const body = await request.json();
    const idempotencyKey = request.headers.get("Idempotency-Key");
    const devUsername =
      request.headers.get("X-Dev-Username") ||
      process.env.CLAIMS_REVIEWER_USERNAME ||
      "reviewer.local";

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
      `/v1/review-tasks/${taskId}/commands`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": idempotencyKey,
        },
        body: JSON.stringify(body),
      },
      devUsername
    );

    return passThrough(response);
  } catch (err: unknown) {
    return Response.json(
      {
        error: {
          code: "INTERNAL_BFF_ERROR",
          message: err instanceof Error ? err.message : "Failed to execute review command",
          details: [],
        },
      },
      { status: 500 }
    );
  }
}
