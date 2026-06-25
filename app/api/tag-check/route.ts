import { NextResponse } from "next/server";

export async function POST(req: Request) {
  const TRANSFER_AI_URL = process.env.TRANSFER_AI_URL || "https://course-bridge-ai-production.up.railway.app";

  try {
    const body = await req.json();
    const upstream = await fetch(`${TRANSFER_AI_URL}/tag-check`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    if (!upstream.ok) {
      return NextResponse.json({ error: "TAG check unavailable" }, { status: 502 });
    }

    const result = await upstream.json();
    return NextResponse.json(result);
  } catch (err) {
    console.error("TAG check proxy error:", err);
    return NextResponse.json({ error: "Failed to reach Transfer AI service" }, { status: 502 });
  }
}
