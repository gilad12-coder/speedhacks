import { NextResponse } from "next/server";
import { getAccount } from "@/lib/session";

// Dictation, as Skynet does it: one recorded clip in, Whisper large-v3-turbo on Groq, the transcript out.
// Gemini through OpenRouter takes over when Groq is missing or refuses, so dictation runs on the key the interview already uses.
const OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions";
const OPENROUTER_MODEL = "google/gemini-2.5-flash";
const GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions";
const GROQ_MODEL = "whisper-large-v3-turbo";
// Vercel caps a request body at 4.5 MB; a dictated answer is far smaller.
const MAX_AUDIO_BYTES = 4 * 1024 * 1024;

function fail(code: string, message: string, status: number) {
  return NextResponse.json({ code, message }, { status });
}

async function groqTranscribe(audio: File, key: string): Promise<string> {
  const body = new FormData();
  body.append("file", audio, audio.name || "take.webm");
  body.append("model", GROQ_MODEL);
  body.append("response_format", "verbose_json");
  const res = await fetch(GROQ_URL, { method: "POST", headers: { Authorization: `Bearer ${key}` }, body, signal: AbortSignal.timeout(120_000) });
  if (!res.ok) throw new Error(`groq transcribe: ${res.status}`);
  const data = (await res.json()) as { text?: string };
  return data.text ?? "";
}

// Chrome and Firefox record webm/ogg; Safari records mp4, which Gemini takes as m4a.
function audioFormat(type: string): string {
  if (type.includes("ogg")) return "ogg";
  if (type.includes("mp4") || type.includes("m4a") || type.includes("aac")) return "m4a";
  if (type.includes("wav")) return "wav";
  if (type.includes("mpeg") || type.includes("mp3")) return "mp3";
  return "webm";
}

async function openrouterTranscribe(audio: File, key: string): Promise<string> {
  const data = Buffer.from(await audio.arrayBuffer()).toString("base64");
  const res = await fetch(OPENROUTER_URL, {
    method: "POST",
    headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      model: OPENROUTER_MODEL,
      temperature: 0,
      messages: [{
        role: "user",
        content: [
          { type: "text", text: "Transcribe this recording verbatim, in the language spoken. Reply with only the transcript, or nothing if no speech is heard." },
          { type: "input_audio", input_audio: { data, format: audioFormat(audio.type) } },
        ],
      }],
    }),
    signal: AbortSignal.timeout(120_000),
  });
  if (!res.ok) throw new Error(`openrouter transcribe: ${res.status}`);
  const json = (await res.json()) as { choices?: { message?: { content?: string } }[] };
  return (json.choices?.[0]?.message?.content ?? "").trim();
}

export async function POST(req: Request) {
  if (!(await getAccount())) return fail("transcription.unauthorized", "Sign in to use dictation.", 401);
  const groqKey = process.env.GROQ_API_KEY;
  const openrouterKey = process.env.OPENROUTER_API_KEY;
  if (!groqKey && !openrouterKey) return fail("transcription.unconfigured", "Dictation isn't set up yet.", 503);

  const form = await req.formData().catch(() => null);
  const audio = form?.get("audio");
  if (!(audio instanceof File) || !audio.size) return fail("transcription.failed", "No recording came through.", 400);
  if (audio.size > MAX_AUDIO_BYTES) return fail("transcription.too_large", "That recording is too long. Try a shorter one.", 413);

  // The language hint is accepted like Skynet's, but not forwarded: Whisper treats it as an order, not a hint.
  if (groqKey) {
    try {
      return NextResponse.json({ text: await groqTranscribe(audio, groqKey), provider: "groq" });
    } catch (error) {
      console.warn("transcription failed (groq)", error instanceof Error ? error.message : error);
    }
  }
  if (openrouterKey) {
    try {
      return NextResponse.json({ text: await openrouterTranscribe(audio, openrouterKey), provider: "openrouter" });
    } catch (error) {
      console.warn("transcription failed (openrouter)", error instanceof Error ? error.message : error);
    }
  }
  return fail("transcription.failed", "Transcription failed. Try again.", 502);
}
