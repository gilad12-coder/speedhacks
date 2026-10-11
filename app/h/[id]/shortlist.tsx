"use client";

import { CalendarCheck, Check as CheckIcon, Headphones, HelpCircle, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { bookTour } from "@/app/actions";
import { Button } from "@/components/shell";
import type { AgentRun, Call, Check, Listing, TourSlot } from "@/lib/types";
import { CHECK_LABELS, CHECK_ORDER, checksFor, formatClock, formatSlot, primaryCall, usd } from "@/lib/view";
import { ResearchEvidence } from "./candidates";

interface Props {
  householdId: string;
  run: AgentRun;
  listings: Listing[];
  occupants: number;
  housemates: { id: string; name: string }[];
  proposed: Record<string, TourSlot>;
  booked: Record<string, TourSlot>;
  initialListingId: string | null;
}

interface Selection {
  listingId: string;
  t: number | null;
}

export function Shortlist({ householdId, run, listings, occupants, housemates, proposed, booked, initialListingId }: Props) {
  const [selected, setSelected] = useState<Selection | null>(
    initialListingId && listings.some((l) => l.id === initialListingId) ? { listingId: initialListingId, t: null } : null,
  );
  const [booking, setBooking] = useState<TourSlot | null>(null);
  const lastTrigger = useRef<HTMLElement | null>(null);

  const open = useCallback((listingId: string, t: number | null, trigger: HTMLElement) => {
    lastTrigger.current = trigger;
    setSelected({ listingId, t });
    const url = new URL(window.location.href);
    url.searchParams.set("listing", listingId);
    window.history.replaceState(null, "", url);
  }, []);

  const close = useCallback(() => {
    setSelected(null);
    const url = new URL(window.location.href);
    url.searchParams.delete("listing");
    window.history.replaceState(null, "", url);
    lastTrigger.current?.focus();
  }, []);

  const listing = selected && listings.find((l) => l.id === selected.listingId);

  return (
    <>
      <ol className="mt-6 space-y-3">
        {listings.map((l, i) => (
          <Row
            key={l.id}
            rank={i + 1}
            listing={l}
            run={run}
            occupants={occupants}
            slot={booked[l.id] ?? proposed[l.id] ?? null}
            onOpen={open}
            onBook={setBooking}
          />
        ))}
      </ol>
      {listing && (
        <EvidencePanel
          key={listing.id}
          listing={listing}
          run={run}
          seekTo={selected.t}
          onSeek={(t) => setSelected({ listingId: listing.id, t })}
          onClose={close}
        />
      )}
      {booking && (
        <BookDialog
          householdId={householdId}
          slot={booking}
          listing={listings.find((l) => l.id === booking.listingId)!}
          housemates={housemates}
          onClose={() => setBooking(null)}
        />
      )}
    </>
  );
}

function Row({
  rank,
  listing,
  run,
  occupants,
  slot,
  onOpen,
  onBook,
}: {
  rank: number;
  listing: Listing;
  run: AgentRun;
  occupants: number;
  slot: TourSlot | null;
  onOpen: (listingId: string, t: number | null, trigger: HTMLElement) => void;
  onBook: (slot: TourSlot) => void;
}) {
  const checks = checksFor(run, listing.id);
  const call = primaryCall(run, listing.id);
  const photo = listing.photoUrls[0];

  return (
    <li className="arrive grid grid-cols-[9rem_minmax(0,1fr)_15rem] gap-6 rounded-3xl border border-line bg-surface p-4 shadow-lift">
      <div className="relative aspect-[4/3] overflow-hidden rounded-2xl bg-sunk">
        {photo && (
          // Listing photos come from many hosts the agent finds, so they skip next/image's allowlist.
          // eslint-disable-next-line @next/next/no-img-element
          <img src={photo} alt="" loading="lazy" className="size-full object-cover" />
        )}
        <span className="font-mono tabular absolute top-2 left-2 rounded-full bg-surface/95 px-2 py-0.5 text-xs font-semibold text-ink">
          {rank}
        </span>
      </div>

      <div className="min-w-0 py-1">
        <div className="flex flex-wrap items-baseline gap-x-3">
          <h3 className="truncate text-lg font-semibold tracking-tight text-ink">{listing.address}</h3>
          <span className="text-sm text-ink-2">{listing.neighborhood}</span>
        </div>
        <p className="font-mono tabular mt-1 text-sm text-ink-2">
          <span className="font-medium text-ink">{listing.rentUsd === null ? "Rent unknown" : `${usd(listing.rentUsd)}/mo`}</span> · {listing.rentUsd === null ? "?" : usd(Math.round(listing.rentUsd / occupants))}{" "}
          each · {listing.bedrooms ?? "?"} bd · {listing.bathrooms ?? "?"} ba
          {listing.commuteMinutes !== null && <> · {listing.commuteMinutes} min commute</>}
        </p>

        <ul className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1.5">
          {CHECK_ORDER.map((kind) => (
            <li key={kind}>
              <CheckChip
                label={CHECK_LABELS[kind]}
                check={checks[kind]}
                onClick={(trigger) => onOpen(listing.id, checks[kind]?.evidence?.t ?? null, trigger)}
              />
            </li>
          ))}
        </ul>
        <ResearchEvidence listing={listing} />

        {call && call.durationSec > 0 && (
          <CallStrip call={call} checks={CHECK_ORDER.map((k) => checks[k])} onPick={(t, el) => onOpen(listing.id, t, el)} />
        )}
      </div>

      <div className="flex flex-col justify-between gap-3 border-l border-line py-1 pl-6">
        <TourBox slot={slot} listing={listing} onBook={onBook} />
        {call && (
          <Button
            variant="quiet"
            className="self-start px-2"
            onClick={(e) => onOpen(listing.id, null, e.currentTarget)}
          >
            <Headphones aria-hidden className="size-4" />
            Hear the call
          </Button>
        )}
      </div>
    </li>
  );
}

function CheckChip({ label, check, onClick }: { label: string; check: Check | null; onClick: (trigger: HTMLElement) => void }) {
  const passed = check?.passed === true;
  const failed = check?.passed === false;
  const Icon = passed ? CheckIcon : failed ? X : HelpCircle;
  const status = passed ? "confirmed" : failed ? "not met" : "not confirmed on the call";
  const tone = passed ? "text-green-ink" : failed ? "text-red-ink" : "text-ink-3";
  const body = (
    <>
      <span
        className={`flex size-5 shrink-0 items-center justify-center rounded-full ${
          passed ? "bg-green text-on-green" : failed ? "bg-red-soft" : "bg-sunk"
        }`}
      >
        <Icon aria-hidden className="size-3" strokeWidth={passed ? 3 : 2.25} />
      </span>
      <span className={`truncate ${passed ? "text-ink" : "text-ink-2"}`}>{label}</span>
      <span className="sr-only">: {status}</span>
    </>
  );
  if (!check?.evidence) {
    return (
      <span className={`flex items-center gap-2 text-sm ${tone}`} title={check?.summary ?? "Not confirmed on the call"}>
        {body}
      </span>
    );
  }
  return (
    <button
      type="button"
      onClick={(e) => onClick(e.currentTarget)}
      title={check.summary}
      className={`-mx-1 flex max-w-full items-center gap-2 rounded-md px-1 text-left text-sm hover:bg-green-soft ${tone}`}
    >
      {body}
    </button>
  );
}

// The call drawn to scale, with a pin where each check was confirmed.
function CallStrip({ call, checks, onPick }: { call: Call; checks: (Check | null)[]; onPick: (t: number, el: HTMLElement) => void }) {
  const pins = checks.filter((c): c is Check => Boolean(c?.passed && c.evidence));
  return (
    <div className="mt-4 flex items-center gap-3">
      <span className="font-mono tabular w-9 text-xs text-ink-3">0:00</span>
      <div className="relative h-5 flex-1">
        <div className="absolute inset-x-0 top-1/2 h-1 -translate-y-1/2 rounded-full bg-sunk" />
        {pins.map((c) => {
          const at = Math.min(c.evidence!.t / call.durationSec, 1);
          return (
            <button
              key={c.kind}
              type="button"
              onClick={(e) => onPick(c.evidence!.t, e.currentTarget)}
              style={{ left: `${at * 100}%` }}
              aria-label={`${CHECK_LABELS[c.kind]}, confirmed at ${formatClock(c.evidence!.t)}`}
              title={`${formatClock(c.evidence!.t)} · ${c.evidence!.quote}`}
              className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-surface bg-green transition-transform hover:scale-150"
            />
          );
        })}
      </div>
      <span className="font-mono tabular w-9 text-right text-xs text-ink-3">{formatClock(call.durationSec)}</span>
    </div>
  );
}

function TourBox({ slot, listing, onBook }: { slot: TourSlot | null; listing: Listing; onBook: (slot: TourSlot) => void }) {
  if (slot?.status === "accepted") {
    return (
      <div>
        <p className="flex items-center gap-1.5 text-sm font-medium text-green-ink">
          <CalendarCheck aria-hidden className="size-4" /> Tour booked
        </p>
        <p className="font-mono tabular mt-1 text-sm text-ink">{formatSlot(slot.start, slot.end)}</p>
        <p className="mt-1 text-xs text-ink-2">On everyone&apos;s calendar</p>
      </div>
    );
  }
  if (slot && Object.keys(slot.calendarEventIds).length) {
    return (
      <div>
        <p className="text-xs font-medium text-amber-ink">Not on everyone&apos;s calendar yet</p>
        <p className="font-mono tabular mt-1 text-sm font-medium text-ink">{formatSlot(slot.start, slot.end)}</p>
        <Button className="mt-3" onClick={() => onBook(slot)}>
          Finish booking
        </Button>
      </div>
    );
  }
  if (listing.status !== "tour_offered") {
    return <p className="text-sm text-ink-2">Verified, but no tour time offered yet.</p>;
  }
  if (!slot) {
    return <p className="text-sm text-ink-2">The landlord&apos;s tour times don&apos;t fit everyone&apos;s calendar.</p>;
  }
  return (
    <div>
      <p className="text-xs font-medium text-ink-2">Everyone&apos;s free</p>
      <p className="font-mono tabular mt-1 text-sm font-medium text-ink">{formatSlot(slot.start, slot.end)}</p>
      <Button className="mt-3" onClick={() => onBook(slot)}>
        Accept tour
      </Button>
    </div>
  );
}

function EvidencePanel({
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
              Call with {listing.contact.name}, {listing.contact.role.replace("_", " ")}
              {call && <> · {new Date(call.startedAt).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "America/Los_Angeles" })}</>}
            </p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-md p-2 text-ink-2 hover:bg-sunk hover:text-ink">
            <X aria-hidden className="size-5" />
          </button>
        </div>

        <div className="border-b border-line px-7 py-5">
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
          {call?.audioUrl ? (
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
        </div>

        <ol className="flex-1 space-y-1 overflow-y-auto px-4 py-4" aria-label="Transcript">
          {call?.transcript.map((line, i) => (
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
          )) ?? <li className="px-3 text-sm text-ink-3">No call was placed for this place.</li>}
        </ol>
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

function BookDialog({
  householdId,
  slot,
  listing,
  housemates,
  onClose,
}: {
  householdId: string;
  slot: TourSlot;
  listing: Listing;
  housemates: { id: string; name: string }[];
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    dialog.current?.showModal();
  }, []);

  return (
    <dialog
      ref={dialog}
      onClose={onClose}
      className="m-auto w-full max-w-md rounded-3xl bg-surface p-7 text-ink shadow-panel backdrop:bg-ink/25"
    >
      <h2 className="text-xl font-semibold tracking-tight">Book this tour?</h2>
      <p className="mt-3 text-sm leading-relaxed text-ink-2">
        <span className="font-medium text-ink">{listing.address}</span>
        <br />
        <span className="font-mono tabular">{formatSlot(slot.start, slot.end)}</span>
      </p>
      <p className="mt-4 text-sm leading-relaxed text-ink-2">
        Keyhunt adds it to the Google Calendar of {housemates.map((h) => h.name).join(", ")}. You meet{" "}
        {listing.contact.name} there.
      </p>
      {error && (
        <p role="alert" className="mt-4 rounded-xl bg-red-soft px-4 py-3 text-sm text-red-ink">
          {error}
        </p>
      )}
      <div className="mt-7 flex justify-end gap-3">
        <Button variant="secondary" onClick={() => dialog.current?.close()} disabled={pending}>
          Cancel
        </Button>
        <Button
          disabled={pending}
          onClick={async () => {
            setPending(true);
            setError(null);
            try {
              const result = await bookTour(householdId, slot.listingId, slot.start, slot.end);
              if (result.error) setError(result.error);
              else dialog.current?.close();
            } catch {
              setError("Couldn't reach Keyhunt. Check your connection and try again.");
            } finally {
              setPending(false);
            }
          }}
        >
          {pending ? "Adding to calendars…" : "Book for everyone"}
        </Button>
      </div>
    </dialog>
  );
}
