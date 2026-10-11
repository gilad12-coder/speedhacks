"use client";

import { Check, Minus, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { AgentRun, Call, CallAnswer, Listing } from "@/lib/types";
import { CHECK_LABELS, CHECK_ORDER, checksFor, formatClock, primaryCall } from "@/lib/view";
import { ScreeningDetails } from "./screening";
import { OutreachStatus } from "@/components/outreach-status";

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
        <div className="px-7"><OutreachStatus job={run.outreach?.find(j => j.listingId === listing.id)} /></div>
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
          <CallAnswers call={call} onSeek={onSeek} />
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

function CallAnswers({ call, onSeek }: { call: Call; onSeek: (t: number) => void }) {
  const answers = call.answers ?? [];
  const required = answers.filter((a) => a.group !== "nice");
  const preferred = answers.filter((a) => a.group === "nice");
  const terms = [
    call.statedRentUsd != null && `Rent quoted: $${call.statedRentUsd.toLocaleString("en-US")}/mo`,
    call.deposit && `Deposit: ${call.deposit}`,
    call.leaseTerms && `Lease: ${call.leaseTerms}`,
  ].filter(Boolean) as string[];
  if (!answers.length && !terms.length) return null;
  return (
    <div className="mt-5 space-y-4 border-t border-line pt-4">
      {terms.length > 0 && <p className="text-sm text-ink-2">{terms.join(" · ")}</p>}
      {required.length > 0 && <AnswerList title="Your requirements" answers={required} onSeek={onSeek} />}
      {preferred.length > 0 && <AnswerList title="Your preferences" answers={preferred} onSeek={onSeek} />}
    </div>
  );
}

function AnswerList({ title, answers, onSeek }: { title: string; answers: CallAnswer[]; onSeek: (t: number) => void }) {
  return (
    <div>
      <h4 className="mb-2 text-xs font-semibold tracking-wide text-ink-3 uppercase">{title}</h4>
      <ul className="space-y-1.5">
        {answers.map((a) => {
          const Icon = a.passed === true ? Check : a.passed === false ? X : Minus;
          const tone = a.passed === true ? "text-green-ink" : a.passed === false ? "text-red-ink" : "text-ink-3";
          const body = (
            <>
              <Icon aria-hidden className={`mt-0.5 size-4 shrink-0 ${tone}`} />
              <span className="min-w-0">
                <span className={a.passed === null ? "text-ink-2" : "font-medium text-ink"}>{a.label}</span>
                {a.evidence && <span className="font-mono tabular ml-2 text-ink-3">{formatClock(a.evidence.t)}</span>}
                <span className="block text-ink-3">{a.evidence ? `“${a.evidence.quote}”` : a.summary}</span>
              </span>
              <span className="sr-only">{a.passed === true ? "Yes" : a.passed === false ? "No" : "Not confirmed"}</span>
            </>
          );
          return (
            <li key={a.key} className="text-sm">
              {a.evidence ? (
                <button type="button" onClick={() => onSeek(a.evidence!.t)} className="flex gap-2 rounded-md text-left hover:bg-sunk">
                  {body}
                </button>
              ) : (
                <div className="flex gap-2">{body}</div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function findLineIndex(call: Call, t: number) {
  let index = -1;
  call.transcript.forEach((line, i) => {
    if (line.t <= t) index = i;
  });
  return index;
}
