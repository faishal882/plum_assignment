import { callClaimsApi } from "@/lib/claims-api";
import { NextResponse } from "next/server";

export async function GET() {
  try {
    const [liveRes, readyRes] = await Promise.all([
      callClaimsApi("/health/live", { method: "GET" }).catch(() => null),
      callClaimsApi("/health/ready", { method: "GET" }).catch(() => null),
    ]);

    const liveOk = liveRes?.status === 200;
    const readyOk = readyRes?.status === 200;

    return NextResponse.json({
      status: liveOk && readyOk ? "healthy" : liveOk ? "degraded" : "unreachable",
      live: liveOk,
      ready: readyOk,
      details: {
        liveStatus: liveRes?.status ?? 0,
        readyStatus: readyRes?.status ?? 0,
      },
    });
  } catch (error) {
    return NextResponse.json(
      {
        status: "unreachable",
        live: false,
        ready: false,
        error: String(error),
      },
      { status: 503 }
    );
  }
}
