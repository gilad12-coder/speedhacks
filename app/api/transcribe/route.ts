import { NextResponse } from "next/server";
import { getAccount } from "@/lib/session";

// Dictation, as Skynet does it: one recorded clip in, Whisper large-v3-turbo on Groq, the transcript out.
const GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions";
const GROQ_MODEL = "whisper-large-v3-turbo";
// Vercel caps a request body at 4.5 MB; a dictated answer is far smaller.
const MAX_AUDIO_BYTES = 4 * 1024 * 1024;

function fail(code: string, message: string, status: number) {
  return NextResponse.json({ code, message }, { status });
}

export async function POST(req: Request) {
  if (!(await getAccount())) return fail("transcription.unauthorized", "Sign in to use dictation.", 401);
  const key = process.env.GROQ_API_KEY;
  if (!key) return fail("transcription.unconfigured", "Dictation isn't set up yet.", 503);

  const form = await req.formData().catch(() => null);
  const audio = form?.get("audio");
  if (!(audio instanceof File) || !audio.size) return fail("transcription.failed", "No recording came through.", 400);
  if (audio.size > MAX_AUDIO_BYTES) return fail("transcription.too_large", "That recording is too long. Try a shorter one.", 413);

  // The language hint is accepted like Skynet's, but not forwarded: Whisper treats it as an order, not a hint.
  const body = new FormData();
  body.append("file", audio, audio.name || "take.webm");
  body.append("model", GROQ_MODEL);
  body.append("response_format", "verbose_json");
  try {
    const res = await fetch(GROQ_URL, { method: "POST", headers: { Authorization: `Bearer ${key}` }, body, signal: AbortSignal.timeout(120_000) });
    if (!res.ok) throw new Error(`groq transcribe: ${res.status}`);
    const data = (await res.json()) as { text?: string };
    return NextResponse.json({ text: data.text ?? "", provider: "groq" });
  } catch (error) {
    console.warn("transcription failed (groq)", error instanceof Error ? error.message : error);
    return fail("transcription.failed", "Transcription failed. Try again.", 502);
  }
}
