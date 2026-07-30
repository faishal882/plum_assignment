import { callBackendApi, passThrough } from "@/lib/claims-api";

export async function GET(): Promise<Response> {
  return passThrough(await callBackendApi("/v1/dev/identities"));
}

export async function POST(request: Request): Promise<Response> {
  return passThrough(
    await callBackendApi("/v1/dev/identities", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: await request.text(),
    })
  );
}
