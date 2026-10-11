"use client";

import { X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { AgentRun, Call, Listing } from "@/lib/types";
import { CHECK_LABELS, CHECK_ORDER, checksFor, formatClock, primaryCall } from "@/lib/view";
import { ScreeningDetails } from "./screening";

export function PlacePanel({
  listing,
  run,
  seekTo,
  onSeek,
  onClose,
}: {
  listing: Listing;
  run: AgentRun;
  seekTo: number | null;
  onSeek: (t: number) => void;
  onClose: () => void;
}) {
  const call = primaryCall(run, listing.id);
  const checks = checksFor(run, listing.id);
  const audio = useRef<HTMLAudioElement>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const [now, setNow] = useState(seekTo ?? 0);
  const activeIndex = call ? findLineIndex(call, now) : -1;
  const highlighted = seekTo !== null && call ? findLineIndex(call, seekTo) : -1;

  // A native modal dialog keeps focus inside and makes the page behind it inert.
  useEffect(() => {
    dialog.current?.showModal();
    heading.current?.focus();
  }, []);

  useEffect(() => {
    if (seekTo === null) return;
    if (audio.current) audio.current.currentTime = seekTo;
    setNow(seekTo);
    document.getElementById(`line-${highlighted}`)?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [seekTo, highlighted]);

  return (
    <dialog
      ref={dialog}
      aria-labelledby="panel-title"
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => e.target === dialog.current && onClose()}
      className="panel-in m-0 ml-auto h-dvh max-h-none w-full max-w-xl bg-surface p-0 text-ink shadow-panel backdrop:bg-ink/20"
    >
      <div className="flex h-full flex-col">
        <div className="flex items-start justify-between gap-4 border-b border-line px-7 pt-6 pb-5">
          <div className="min-w-0">
            <h2 id="panel-title" ref={heading} tabIndex={-1} className="truncate text-xl font-semibold tracking-tight outline-none">
              {listing.address}
            </h2>
            <p className="mt-1 text-sm text-ink-2">
              {listing.neighborhood} · {listing.contact.name}, {listing.contact.role.replace("_", " ")}
              {call && <> · called {new Date(call.startedAt).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "America/Los_Angeles" })}</>}
            </p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-md p-2 text-ink-2 hover:bg-sunk hover:text-ink">
            <X aria-hidden className="size-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto">
        {listing.research && (
          <section aria-labelledby="screening-title" className="border-b border-line px-7 py-5">
            <h3 id="screening-title" className="mb-3 text-sm font-semibold text-ink">Checked online</h3>
            <ScreeningDetails research={listing.research} rent={listing.rentUsd} />
          </section>
        )}
        {call ? (
        <>
        <section aria-labelledby="call-title" className="border-b border-line px-7 py-5">
          <h3 id="call-title" className="mb-3 text-sm font-semibold text-ink">Confirmed on the call</h3>
          <p className={`mb-3 text-sm ${call.listingVerified === true ? "text-green-ink" : "text-ink-2"}`}>
            {call.listingVerified === true ? "✓ Listing verified" : call.listingVerified === false ? "Listing details differ" : "Listing unconfirmed"}
          </p>
          <ul className="space-y-2">
            {CHECK_ORDER.map((kind) => {
              const c = checks[kind];
              return (
                <li key={kind} className="text-sm">
                  {c?.evidence ? (
                    <button type="button" onClick={() => onSeek(c.evidence!.t)} className="group text-left">
                      <span className="font-medium text-ink group-hover:text-green-ink">{CHECK_LABELS[kind]}</span>
                      <span className="font-mono tabular ml-2 text-ink-3">{formatClock(c.evidence.t)}</span>
                      <span className="block text-ink-2">{c.summary}</span>
                    </button>
                  ) : (
                    <>
                      <span className="font-medium text-ink-2">{CHECK_LABELS[kind]}</span>
                      <span className="block text-ink-3">{c?.summary || "Not confirmed on the call"}</span>
                    </>
                  )}
                </li>
              );
            })}
          </ul>
          {call.audioUrl ? (
            <audio
              ref={audio}
              controls
              preload="metadata"
              src={call.audioUrl}
              onTimeUpdate={(e) => setNow(e.currentTarget.currentTime)}
              className="mt-5 w-full"
            />
          ) : (
            <p className="mt-5 text-sm text-ink-3">No recording for this call. The transcript is below.</p>
          )}
        </section>

        <ol className="space-y-1 px-4 py-4" aria-label="Transcript">
          {call.transcript.map((line, i) => (
            <li key={i} id={`line-${i}`}>
              <button
                type="button"
                onClick={() => onSeek(line.t)}
                className={`grid w-full grid-cols-[3rem_5rem_minmax(0,1fr)] gap-2 rounded-xl px-3 py-2 text-left text-sm leading-relaxed transition-colors ${
                  i === highlighted ? "bg-green-soft" : i === activeIndex ? "bg-sunk" : "hover:bg-sunk"
                }`}
              >
                <span className="font-mono tabular text-ink-3">{formatClock(line.t)}</span>
                <span className="font-medium text-ink-2">{line.speaker === "agent" ? "Keyhunt" : listing.contact.name.split(" ")[0]}</span>
                <span className={line.speaker === "agent" ? "text-ink" : "font-display text-[1.0625rem] italic text-ink"}>{line.text}</span>
              </button>
            </li>
          ))}
        </ol>
        </>
        ) : (
          <p className="px-7 py-5 text-sm text-ink-2">Keyhunt hasn&apos;t called about this place yet.</p>
        )}
        </div>
      </div>
    </dialog>
  );
}

function findLineIndex(call: Call, t: number) {
  let index = -1;
  call.transcript.forEach((line, i) => {
    if (line.t <= t) index = i;
  });
  return index;
}
