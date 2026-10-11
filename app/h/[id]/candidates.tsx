"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { callRental } from "@/app/actions";
import { Button } from "@/components/shell";
import type { AgentRun, Listing } from "@/lib/types";

export function ResearchEvidence({ listing }: { listing: Listing }) {
  const research = listing.research;
  if (!research) return null;
  const labels = { not_checked: "Not screened", checking: "Checking sources", unconfirmed: "Unconfirmed",
    cross_referenced: "Address and contact cross-referenced", concerns_found: "Concerns to review", error: "Screening incomplete" };
  return (
    <details className="mt-3 rounded-xl border border-line bg-sunk/50 p-3 text-sm">
      <summary className="cursor-pointer font-medium">Rental screening · {labels[research.status]}</summary>
      {research.findings.map((finding, i) => <p key={i} className="mt-3 text-ink-2">
        {finding.summary}{finding.quote && <q className="mt-1 block">{finding.quote}</q>}
        <a className="underline" href={finding.sourceUrl} target="_blank" rel="noopener noreferrer">View source ↗</a>
      </p>)}
      {research.facts.map((fact, i) => <p key={`fact-${i}`} className="mt-2 text-ink-2">
        <b className="capitalize">{fact.field}</b>: <q>{fact.quote}</q>{" "}
        <a className="underline" href={fact.sourceUrl} target="_blank" rel="noopener noreferrer">Source ↗</a>
      </p>)}
      <p className="mt-3 text-ink-2">{research.medianComparableRent !== null
        ? `Nearby same-bedroom asking rents: $${research.medianComparableRent.toLocaleString()} median from ${research.comparableCount} units.`
        : "Not enough comparable units to judge whether the rent is unusually low."}</p>
      <p className="mt-2 text-xs text-ink-3">{research.limitations}</p>
    </details>
  );
}

export function Candidates({ householdId, run, callerConnected }: { householdId: string; run: AgentRun; callerConnected: boolean }) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [waiting, setWaiting] = useState(false);
  useEffect(() => {
    if (!waiting) return;
    const interval = setInterval(() => router.refresh(), 4000);
    const stop = setTimeout(() => setWaiting(false), 240_000);
    return () => { clearInterval(interval); clearTimeout(stop); };
  }, [waiting, router]);
  const candidates = run.listings.filter((l) => l.status === "found" || l.status === "called");
  if (!candidates.length) return null;
  async function call(listingId: string) {
    setBusy(listingId);
    const result = await callRental(householdId, listingId);
    setMessage(result.error || "Call requested. The agent will introduce itself using your name; results appear when the call is processed.");
    if (!result.error) setWaiting(true);
    setBusy(null);
    router.refresh();
  }
  return <section className="mt-12" aria-labelledby="candidates-heading">
    <h2 id="candidates-heading" className="font-display text-2xl font-semibold">Candidates to check</h2>
    <p className="mt-2 text-sm text-ink-2">Public listing claims and screening findings. A call can confirm rental details; it does not authenticate ownership.</p>
    {message && <p role="status" className="mt-4 rounded-xl bg-sunk p-3 text-sm">{message}</p>}
    <ol className="mt-5 space-y-4">{candidates.map((listing) => {
      const call = run.calls.find((c) => c.listingId === listing.id);
      return <li key={listing.id} className="rounded-2xl border border-line bg-surface p-5">
        <a className="font-semibold underline decoration-line-strong underline-offset-4" href={listing.sourceUrl} target="_blank" rel="noopener noreferrer">{listing.address} ↗</a>
        <p className="mt-1 text-sm text-ink-2">{listing.rentUsd === null ? "Rent unknown" : `$${listing.rentUsd.toLocaleString()}/mo`} · {listing.bedrooms ?? "?"} bd · {listing.bathrooms ?? "?"} ba</p>
        <ResearchEvidence listing={listing} />
        {call && <details className="mt-3 text-sm"><summary>Call evidence · {call.outcome.replaceAll("_", " ")}</summary>
          {run.checks.filter((c) => c.listingId === listing.id).map((check) => <p key={check.kind} className="mt-2">{check.summary}{check.evidence && <> · {check.evidence.t}s: <q>{check.evidence.quote}</q></>}</p>)}
          {call.audioUrl && <audio controls preload="none" className="mt-3 w-full" src={call.audioUrl} />}
          <details className="mt-3"><summary>Transcript</summary>{call.transcript.map((t,i) => <p key={i} className="mt-2">{t.t}s · {t.speaker}: {t.text}</p>)}</details>
        </details>}
        {!call && listing.contact.phone && callerConnected && <Button className="mt-3" disabled={busy !== null} onClick={() => callRentalFromRow(listing.id)}>{busy === listing.id ? "Requesting call…" : "Ask AI assistant to call"}</Button>}
        {!listing.contact.phone && <p className="mt-3 text-xs text-ink-3">No public contact phone was found. Open the source to retrieve it.</p>}
        {!callerConnected && <p className="mt-3 text-xs text-ink-3">Calling is not connected on this deployment yet.</p>}
      </li>;
    })}</ol>
  </section>;
  function callRentalFromRow(id: string) { void call(id); }
}
