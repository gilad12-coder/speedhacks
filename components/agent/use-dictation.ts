"use client";

import { useCallback, useEffect, useRef, useState } from "react";

// Recording live, transcribing the take, or a short-lived failure before returning to idle.
export type DictationState = { kind: "idle" } | { kind: "rec" } | { kind: "busy" } | { kind: "err"; message: string };

const ERR_DISMISS_MS = 2600;
// A reason that "try again" won't fix needs long enough to be read.
const REASON_DISMISS_MS = 6000;

class TranscribeError extends Error {
  constructor(
    message: string,
    readonly code?: string,
  ) {
    super(message);
  }
}

async function transcribe(blob: Blob, filename: string): Promise<string> {
  const body = new FormData();
  body.append("audio", blob, filename);
  const res = await fetch("/api/transcribe", { method: "POST", body });
  const data = (await res.json().catch(() => ({}))) as { text?: string; code?: string; message?: string };
  if (!res.ok) throw new TranscribeError(data.message ?? "Transcription failed. Try again.", data.code);
  return data.text ?? "";
}

// Record → transcribe on Groq (as Skynet does) → hand the text back for the draft. It never sends on its own.
// Safari records AAC-in-MP4, everywhere else webm/opus.
export function useDictation(onText: (text: string) => void) {
  const [state, setState] = useState<DictationState>({ kind: "idle" });
  const [seconds, setSeconds] = useState(0);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const mimeRef = useRef("audio/webm;codecs=opus");
  const tickRef = useRef<number | undefined>(undefined);
  const onTextRef = useRef(onText);
  useEffect(() => {
    onTextRef.current = onText;
  }, [onText]);

  const teardown = useCallback(() => {
    window.clearInterval(tickRef.current);
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== "inactive") {
      recorder.ondataavailable = null;
      recorder.onstop = null;
      recorder.stop();
    }
    recorderRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  const fail = useCallback(
    (message: string, dismissMs = ERR_DISMISS_MS) => {
      teardown();
      setState({ kind: "err", message });
      window.setTimeout(() => setState((s) => (s.kind === "err" ? { kind: "idle" } : s)), dismissMs);
    },
    [teardown],
  );

  const start = useCallback(async () => {
    if (recorderRef.current) return;
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") return fail("Microphone isn't available");
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      return fail("Microphone access is blocked");
    }
    const candidates = /apple/i.test(navigator.vendor) ? ["audio/mp4", "audio/webm;codecs=opus"] : ["audio/webm;codecs=opus", "audio/mp4"];
    const mime = candidates.find((c) => MediaRecorder.isTypeSupported(c)) ?? "audio/webm;codecs=opus";
    mimeRef.current = mime;
    let recorder: MediaRecorder;
    try {
      recorder = new MediaRecorder(stream, { mimeType: mime });
    } catch {
      recorder = new MediaRecorder(stream);
    }
    streamRef.current = stream;
    recorderRef.current = recorder;
    chunksRef.current = [];
    recorder.ondataavailable = (ev) => {
      if (ev.data && ev.data.size > 0) chunksRef.current.push(ev.data);
    };
    const t0 = Date.now();
    setSeconds(0);
    tickRef.current = window.setInterval(() => setSeconds(Math.round((Date.now() - t0) / 1000)), 500);
    setState({ kind: "rec" });
    recorder.start(1000);
  }, [fail]);

  const cancel = useCallback(() => {
    teardown();
    chunksRef.current = [];
    setState({ kind: "idle" });
  }, [teardown]);

  const finish = useCallback(() => {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state === "inactive") return;
    recorder.onstop = () => {
      const blob = new Blob(chunksRef.current, { type: mimeRef.current });
      chunksRef.current = [];
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      recorderRef.current = null;
      void (async () => {
        try {
          const text = (await transcribe(blob, mimeRef.current.startsWith("audio/mp4") ? "take.m4a" : "take.webm")).trim();
          // Silence or a decode miss isn't a draft: show it as a retryable failure.
          if (!text) throw new TranscribeError("Couldn't hear that");
          setState({ kind: "idle" });
          onTextRef.current(text);
        } catch (err) {
          const blocked = err instanceof TranscribeError && err.code?.startsWith("transcription.") && err.code !== "transcription.failed";
          fail(err instanceof TranscribeError ? err.message : "Transcription failed. Try again.", blocked ? REASON_DISMISS_MS : ERR_DISMISS_MS);
        }
      })();
    };
    window.clearInterval(tickRef.current);
    setState({ kind: "busy" });
    recorder.stop();
  }, [fail]);

  // A recording left running when the composer unmounts would hold the mic open.
  useEffect(() => teardown, [teardown]);

  return { state, seconds, start, cancel, finish };
}

export function formatRecSeconds(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}
