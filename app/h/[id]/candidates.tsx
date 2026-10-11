"use client";

import { ExternalLink, Headphones, Phone, PhoneMissed, Voicemail } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { callRental } from "@/app/actions";
import { Button } from "@/components/shell";
import type { AgentRun, Call, Listing } from "@/lib/types";
import { formatClock, primaryCall, usd } from "@/lib/view";
import { PlacePanel } from "./place-panel";
import { RentVsMarket, ScreeningBadge } from "./screening";

export function Candidates({ householdId, run, callerConnected }: { householdId: string; run: AgentRun; callerConnected: boolean }) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [waiting, setWaiting] = useState(false);
  const [selected, setSelected] = useState<{ listingId: string; t: number | null } | null>(null);
  const lastTrigger = useRef<HTMLElement | null>(null);

  // A requested call lands a few minutes later, so keep refreshing until it shows up.
  useEffect(() => {
    if (!waiting) return;
    const interval = setInterval(() => router.refresh(), 4000);
    const stop = setTimeout(() => setWaiting(false), 240_000);
    return () => {
      clearInterval(interval);
      clearTimeout(stop);
    };
  }, [waiting, router]);

  const open = useCallback((listingId: string, trigger: HTMLElement) => {
    lastTrigger.current = trigger;
    setSelected({ listingId, t: null });
  }, []);
  const close = useCallback(() => {
    setSelected(null);
    lastTrigger.current?.focus();
  }, []);

  const candidates = run.listings.filter((l) => l.status === "found" || l.status === "called" || l.status === "verified");
  if (!candidates.length) return null;

  async function call(listingId: string) {
    setBusy(listingId);
    const result = await callRental(householdId, listingId);
    setNotice(
      result.error
        ? { tone: "error", text: result.error }
        : { tone: "ok", text: "Calling now. Keyhunt introduces itself with your name, and what it hears shows up here." },
    );
    if (!result.error) setWaiting(true);
    setBusy(null);
    router.refresh();
  }

  const listing = selected && candidates.find((l) => l.id === selected.listingId);

  return (
    <section className="mt-14" aria-labelledby="candidates-title">
      <div className="flex items-baseline justify-between gap-6">
        <h2 id="candidates-title" className="font-display text-3xl font-semibold tracking-tight">
          Still being checked
        </h2>
        <p className="font-mono tabular text-sm text-ink-2">
          {candidates.length} {candidates.length === 1 ? "place" : "places"}
        </p>
      </div>
      <p className="mt-2 max-w-2xl text-sm leading-relaxed text-ink-2">
        Found, but not through every check yet. Screening uses public sources; a call confirms the details, but it can&apos;t
        prove who owns the place.
      </p>
      {!callerConnected && (
        <p className="mt-4 text-sm text-ink-3">Calling isn&apos;t switched on here yet, so these can only be screened online.</p>
      )}
      {notice && (
        <p
          role="status"
          className={`mt-5 rounded-2xl px-5 py-3.5 text-sm ${notice.tone === "ok" ? "bg-green-soft text-green-ink" : "bg-red-soft text-red-ink"}`}
        >
          {notice.text}
        </p>
      )}

      <ol className="mt-6 space-y-3">
        {candidates.map((l, i) => (
          <Row
            key={l.id}
            index={i}
            listing={l}
            call={primaryCall(run, l.id)}
            canCall={callerConnected && Boolean(l.contact.phone)}
            busy={busy}
            onCall={call}
            onOpen={open}
          />
        ))}
      </ol>

      {listing && (
        <PlacePanel
          key={listing.id}
          listing={listing}
          run={run}
          seekTo={selected.t}
          onSeek={(t) => setSelected({ listingId: listing.id, t })}
          onClose={close}
        />
      )}
    </section>
  );
}

function Row({
  index,
  listing,
  call,
  canCall,
  busy,
  onCall,
  onOpen,
}: {
  index: number;
  listing: Listing;
  call: Call | null;
  canCall: boolean;
  busy: string | null;
  onCall: (listingId: string) => void;
  onOpen: (listingId: string, trigger: HTMLElement) => void;
}) {
  const photo = listing.photoUrls[0];
  return (
    <li
      className="result-in grid grid-cols-[7rem_minmax(0,1fr)_13rem] gap-6 rounded-3xl border border-line bg-surface p-4"
      style={{ "--i": index } as React.CSSProperties}
    >
      <div className="aspect-[4/3] overflow-hidden rounded-2xl bg-sunk">
        {photo && (
          // Listing photos come from many hosts the agent finds, so they skip next/image's allowlist.
          // eslint-disable-next-line @next/next/no-img-element
          <img src={photo} alt="" loading="lazy" className="size-full object-cover" />
        )}
      </div>

      <div className="min-w-0 py-1">
        <div className="flex flex-wrap items-baseline gap-x-3">
          <h3 className="truncate text-lg font-semibold tracking-tight text-ink">{listing.address}</h3>
          {listing.neighborhood && <span className="text-sm text-ink-2">{listing.neighborhood}</span>}
        </div>
        <p className="font-mono tabular mt-1 text-sm text-ink-2">
          <span className="font-medium text-ink">{listing.rentUsd === null ? "Rent unknown" : `${usd(listing.rentUsd)}/mo`}</span> ·{" "}
          {listing.bedrooms ?? "?"} bd · {listing.bathrooms ?? "?"} ba
          {listing.commuteMinutes !== null && <> · {listing.commuteMinutes} min commute</>}
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5">
          {listing.research && <ScreeningBadge research={listing.research} />}
          {call && <CallBadge call={call} />}
          {listing.research && <RentVsMarket rent={listing.rentUsd} research={listing.research} />}
        </div>
      </div>

      <div className="flex flex-col items-start justify-center gap-2 border-l border-line pl-6">
        {!call && canCall && (
          <Button disabled={busy !== null} onClick={() => onCall(listing.id)}>
            <Phone aria-hidden className="size-4" />
            {busy === listing.id ? "Starting call…" : "Have Keyhunt call"}
          </Button>
        )}
        {(listing.research || call) && (
          <Button variant="quiet" className="px-2" onClick={(e) => onOpen(listing.id, e.currentTarget)}>
            {call ? <Headphones aria-hidden className="size-4" /> : null}
            {call ? "Hear the call" : "See what we found"}
          </Button>
        )}
        <a
          href={listing.sourceUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 px-2 text-sm text-ink-2 underline decoration-line-strong underline-offset-4 hover:text-ink"
        >
          Original listing
          <ExternalLink aria-hidden className="size-3.5" />
        </a>
        {!listing.contact.phone && <p className="px-2 text-xs text-ink-3">No phone number in the listing.</p>}
      </div>
    </li>
  );
}

function CallBadge({ call }: { call: Call }) {
  const { label, Icon, tone } = {
    answered: { label: `Answered · ${formatClock(call.durationSec)}`, Icon: Phone, tone: "bg-green-soft text-green-ink" },
    no_answer: { label: "No answer", Icon: PhoneMissed, tone: "bg-sunk text-ink-2" },
    voicemail: { label: "Left a voicemail", Icon: Voicemail, tone: "bg-sunk text-ink-2" },
    failed: { label: "Call didn't go through", Icon: PhoneMissed, tone: "bg-red-soft text-red-ink" },
  }[call.outcome];
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${tone}`}>
      <Icon aria-hidden className="size-3.5" />
      {label}
    </span>
  );
}
