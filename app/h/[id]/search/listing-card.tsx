"use client";

import { useActionState, useState, useTransition } from "react";
import { ArrowRight, CalendarCheck, CheckCircle2, ExternalLink, Mail, Phone, Star } from "lucide-react";
import { callRental } from "@/app/actions";
import { Button } from "@/components/shell";
import { OutreachStatus } from "@/components/outreach-status";
import type { WorkspaceListing } from "@/lib/workspace";
import { draftEmail, logViewing, markInterested, retryCalendarSync, saveContact, updateEmail, type ActionState } from "./actions";

export const STATUS: Record<WorkspaceListing["status"], { label: string; tone: string }> = {
  new: { label: "New", tone: "bg-sunk text-ink-2" },
  candidate: { label: "To check", tone: "bg-sunk text-ink-2" },
  filtered: { label: "Outside your search", tone: "bg-sunk text-ink-3" },
  contacted: { label: "Called", tone: "bg-amber-soft text-amber-ink" },
  viable: { label: "Looks good", tone: "bg-green-soft text-green-ink" },
  not_viable: { label: "Not a fit", tone: "bg-red-soft text-red-ink" },
  tour_scheduled: { label: "Viewing booked", tone: "bg-green-soft text-green-ink" },
};

const usd = (n: number | null) => (n === null ? "Rent unknown" : `$${n.toLocaleString()}/mo`);
const when = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

function gmailCompose(to: string, subject: string, body: string) {
  const q = new URLSearchParams({ view: "cm", fs: "1", to, su: subject, body });
  return `https://mail.google.com/mail/?${q}`;
}

export function ListingCard({ householdId, listing, callingEnabled, index = 0 }: { householdId: string; listing: WorkspaceListing; callingEnabled: boolean; index?: number }) {
  const [pending, start] = useTransition();
  const [message, setMessage] = useState("");
  const status = STATUS[listing.status] ?? STATUS.candidate;
  const phone = listing.contact?.phone ?? null;
  const callRunning = (listing.call && ["queued", "in_progress", "extracting"].includes(listing.call.status)) || ["scheduled", "checking_hours", "calling"].includes(listing.outreach?.state ?? "");
  const canCall = Boolean(phone) && (!listing.call || ["attention", "failed"].includes(listing.call.status)) && !["filtered", "tour_scheduled"].includes(listing.status);
  const needsContact = !phone && !listing.contact?.email && listing.status !== "filtered";

  function run(task: () => Promise<{ error?: string } | ActionState>, done = "") {
    setMessage("");
    start(async () => {
      const result = await task();
      setMessage(result.error ?? done);
    });
  }

  return (
    <li id={listing.id} className="result-in rounded-2xl border border-line bg-surface p-5" style={{ "--i": Math.min(index, 12) } as React.CSSProperties}>
      <OutreachStatus job={listing.outreach} />
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-lg font-semibold tabular-nums">
            {usd(listing.price)}
            <span className="ml-2 text-sm font-normal text-ink-2">
              {listing.beds ?? "?"} bd · {listing.baths ?? "?"} ba{listing.sqft ? ` · ${listing.sqft.toLocaleString()} ft²` : ""}
            </span>
          </p>
          <a href={listing.url} target="_blank" rel="noopener noreferrer"
             className="mt-1 inline-flex items-center gap-1 font-medium underline decoration-line-strong underline-offset-4">
            {listing.title} <ExternalLink aria-hidden className="size-3.5" />
          </a>
          <p className="mt-1 text-sm text-ink-2">
            <span className="capitalize">{listing.source}</span>
            {listing.address || listing.neighborhood ? ` · ${listing.address ?? listing.neighborhood}` : ""}
          </p>
          {listing.contact && (phone || listing.contact.email) && (
            <p className="mt-1 text-sm text-ink-2">
              {[listing.contact.name, phone, listing.contact.email].filter(Boolean).join(" · ")}
            </p>
          )}
        </div>
        <span className={`shrink-0 rounded-full px-3 py-1 text-xs font-medium ${status.tone}`}>{status.label}</span>
      </div>

      {listing.viewing && (
        <p className="mt-3 flex flex-wrap items-center gap-2 text-sm">
          <CalendarCheck aria-hidden className="size-4 text-green-ink" />
          {listing.viewing.confirmedOnCall ? "Tour confirmed on call" : "Viewing"} <strong>{when(listing.viewing.start)}{listing.viewing.end ? ` – ${new Date(listing.viewing.end).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit", timeZoneName: "short" })}` : ""}</strong>
          {listing.viewing.calendarStatus === "synced" && <span className="text-green-ink">✓ Calendar synced</span>}
          {listing.viewing.calendarUrl && !listing.viewing.confirmedOnCall && (
            <a className="text-green-ink underline underline-offset-4" href={listing.viewing.calendarUrl} target="_blank" rel="noopener noreferrer">
              Add to Google Calendar
            </a>
          )}
        </p>
      )}

      {listing.viewing?.confirmedOnCall && listing.viewing.calendarStatus !== "synced" && (
        <div className="mt-2 text-sm text-amber-ink"><p role="status">{listing.viewing.calendarError || "Tour booked. Calendar sync pending."}</p>
          <Button variant="quiet" disabled={pending} onClick={() => run(() => retryCalendarSync(householdId, listing.id), "Calendar synced.")}>Retry calendar sync</Button>
        </div>
      )}
      {listing.call && (
        <div className="mt-3 text-sm">
          {listing.call.listingVerified === true
            ? <span className="inline-flex items-center gap-1.5 rounded-full bg-green-soft px-3 py-1 font-medium text-green-ink"><CheckCircle2 aria-hidden className="size-4" />Listing verified</span>
            : <span className={`rounded-full px-3 py-1 ${listing.call.listingVerified === false ? "bg-red-soft text-red-ink" : "bg-sunk text-ink-2"}`}>{listing.call.listingVerified === false ? "Listing details differ" : "Listing unconfirmed"}</span>}
          {!!listing.call.verificationEvidence?.length && <details className="mt-2 text-ink-2">
            <summary className="cursor-pointer">What the contact confirmed</summary>
            <p className="mt-1 text-xs">Checks the advertised unit and details. Ownership and fraud screening remain separate.</p>
            {listing.call.verificationEvidence.map((fact) => <div key={fact.key} className="mt-2">
              <p>{fact.summary}</p>
              {fact.evidence.map((ev, i) => <blockquote key={i} className="ml-3 text-xs">{Math.floor(ev.t / 60)}:{String(Math.floor(ev.t % 60)).padStart(2, "0")} — “{ev.quote}”</blockquote>)}
            </div>)}
          </details>}
          {listing.call.bookingWarning && <p className="mt-2 text-amber-ink">{listing.call.bookingWarning}</p>}
        </div>
      )}

      {listing.call?.summary && (
        <div className={`mt-3 rounded-xl p-3 text-sm ${listing.call.viable ? "bg-green-soft text-green-ink" : "bg-sunk text-ink-2"}`}>
          {listing.call.summary}
          {listing.call.tradeoffs.length > 0 && <p className="mt-1 text-ink-2">Tradeoffs: {listing.call.tradeoffs.join("; ")}</p>}
        </div>
      )}
      {listing.notes.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-xs text-ink-3">{listing.notes.slice(-3).map((n, i) => <li key={i}>{n}</li>)}</ul>
      )}

      {listing.nextStep && <NextStep householdId={householdId} listing={listing} canCall={canCall && callingEnabled} run={run} pending={pending} />}

      {needsContact && <GetContact householdId={householdId} listing={listing} />}

      <div className="mt-4 flex flex-wrap items-center gap-2">
        {canCall && callingEnabled && (
          <Button variant={listing.call ? "secondary" : "primary"} disabled={pending || Boolean(callRunning)}
                  onClick={() => run(() => callRental(householdId, listing.id), "Call requested. The agent will call during office hours.")}>
            <Phone aria-hidden className="size-4" />{listing.call ? "Resume saved call" : "Verify & arrange tour"}
          </Button>
        )}
        {callRunning && <span className="text-sm text-ink-2">{listing.outreach?.state === "scheduled" ? "Call queued" : "Call in progress…"}</span>}
        {!listing.email && listing.status !== "filtered" && (
          <Button variant="secondary" disabled={pending} onClick={() => run(() => draftEmail(householdId, listing.id))}>
            <Mail aria-hidden className="size-4" />Draft email
          </Button>
        )}
        {!listing.interested && (
          <Button variant="secondary" disabled={pending} onClick={() => run(() => markInterested(householdId, listing.id))}
                  title="Your agent recommends the next step">
            <Star aria-hidden className="size-4" />I&apos;m interested
          </Button>
        )}
      </div>
      {canCall && callingEnabled && !listing.call && <p className="mt-2 text-xs text-ink-3">Your AI assistant confirms the exact listing and can book a tour when everyone&apos;s connected calendar is free. Otherwise it collects times for you.</p>}
      {message && <p role="status" className="mt-3 text-sm text-ink-2">{message}</p>}

      {listing.email && listing.email.status !== "discarded" && <EmailDraft householdId={householdId} email={listing.email} />}

      {listing.call?.transcript && (
        <details className="mt-3 text-sm">
          <summary className="cursor-pointer text-ink-2">Call transcript</summary>
          <pre className="mt-2 whitespace-pre-wrap font-sans text-ink-2">{listing.call.transcript}</pre>
        </details>
      )}
      {listing.call?.error && <p className="mt-2 text-xs text-red-ink">{listing.call.error}</p>}
    </li>
  );
}

function NextStep({ householdId, listing, canCall, run, pending }: {
  householdId: string; listing: WorkspaceListing; canCall: boolean; pending: boolean;
  run: (task: () => Promise<{ error?: string }>, done?: string) => void;
}) {
  const step = listing.nextStep!;
  const link = { book_online: "Book on their site", message: "Open on Facebook", reveal: "Open the listing" }[step.action as string];
  return (
    <div className={`mt-4 rounded-xl border p-4 ${step.action === "move_on" ? "border-line" : "border-green"}`}>
      <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-green-ink">
        <ArrowRight aria-hidden className="size-3.5" />Recommended next step
      </p>
      <p className="mt-1 font-semibold">{step.label}</p>
      <p className="mt-0.5 text-sm text-ink-2">{step.why}</p>
      <div className="mt-3 flex flex-wrap items-start gap-2">
        {step.action === "call" && canCall && (
          <Button disabled={pending} onClick={() => run(() => callRental(householdId, listing.id), "Call requested for office hours.")}>
            <Phone aria-hidden className="size-4" />Call now
          </Button>
        )}
        {step.action === "email" && !listing.email && (
          <Button disabled={pending} onClick={() => run(() => draftEmail(householdId, listing.id))}>
            <Mail aria-hidden className="size-4" />Draft the email
          </Button>
        )}
        {step.action === "prepare" && step.href && !listing.viewing?.confirmedOnCall && (
          <a className="inline-flex h-10 items-center gap-2 rounded-md bg-green px-4 text-sm font-medium text-on-green" href={step.href} target="_blank" rel="noopener noreferrer">
            <CalendarCheck aria-hidden className="size-4" />Add to Google Calendar
          </a>
        )}
        {link && step.href && (
          <a className="inline-flex h-10 items-center gap-2 rounded-md bg-green px-4 text-sm font-medium text-on-green" href={step.href} target="_blank" rel="noopener noreferrer">
            <ExternalLink aria-hidden className="size-4" />{link}
          </a>
        )}
        {!listing.viewing && !["move_on", "wait"].includes(step.action) && <LogViewing householdId={householdId} listingId={listing.id} />}
      </div>
    </div>
  );
}

function LogViewing({ householdId, listingId }: { householdId: string; listingId: string }) {
  const [state, action, pending] = useActionState<ActionState, FormData>(logViewing.bind(null, householdId, listingId), {});
  return (
    <details className="group">
      <summary className="inline-flex h-10 cursor-pointer list-none items-center gap-2 rounded-md border border-line-strong bg-surface px-4 text-sm font-medium">
        <CalendarCheck aria-hidden className="size-4" />I booked a viewing
      </summary>
      <form action={action} className="mt-2 flex flex-wrap gap-2">
        <input type="datetime-local" name="start" required className="h-10 rounded-md border border-line-strong bg-surface px-3 text-sm" />
        <Button type="submit" disabled={pending}>Save viewing</Button>
      </form>
      {state.error && <p className="mt-1 text-sm text-red-ink">{state.error}</p>}
    </details>
  );
}

function GetContact({ householdId, listing }: { householdId: string; listing: WorkspaceListing }) {
  const [state, action, pending] = useActionState<ActionState, FormData>(saveContact.bind(null, householdId, listing.id), {});
  const how = listing.contactHint === "show_contact"
    ? <>Open the post and click <b>show contact info</b> in the description.</>
    : listing.source === "craigslist"
      ? <>Open the post, click <b>reply</b>, and copy the phone or email it shows.</>
      : <>Open the listing and copy the agent&apos;s phone or email.</>;
  return (
    <div className="mt-4 rounded-xl border border-dashed border-green p-4">
      <p className="text-sm"><b>Get the number to call.</b> {how}</p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <a className="inline-flex h-10 items-center gap-2 rounded-md border border-line-strong bg-surface px-4 text-sm font-medium"
           href={listing.url} target="_blank" rel="noopener noreferrer">
          <ExternalLink aria-hidden className="size-4" />Reveal on <span className="capitalize">{listing.source}</span>
        </a>
        <form action={action} className="flex min-w-64 flex-1 gap-2">
          <input name="pasted" required aria-label="Phone number or email" placeholder="Paste the phone or email here"
                 className="h-10 min-w-0 flex-1 rounded-md border border-line-strong bg-surface px-3 text-sm" />
          <Button type="submit" variant="secondary" disabled={pending}>Save</Button>
        </form>
      </div>
      {state.error && <p className="mt-2 text-sm text-red-ink">{state.error}</p>}
    </div>
  );
}

function EmailDraft({ householdId, email }: { householdId: string; email: NonNullable<WorkspaceListing["email"]> }) {
  const [to, setTo] = useState(email.to);
  const [subject, setSubject] = useState(email.subject);
  const [body, setBody] = useState(email.body);
  const [opened, setOpened] = useState(false);
  const [pending, start] = useTransition();
  const [error, setError] = useState("");

  if (email.status === "sent") {
    return <p className="mt-3 inline-flex items-center gap-1.5 rounded-full bg-green-soft px-3 py-1 text-xs font-medium text-green-ink">
      <Mail aria-hidden className="size-3.5" />Email sent to {email.to}
    </p>;
  }
  const save = (action: "save" | "sent" | "discard") => start(async () => {
    const r = await updateEmail(householdId, email.id, action, { to, subject, body });
    setError(r.error ?? "");
  });
  const validTo = /^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$/.test(to.trim());
  return (
    <div className="mt-4 rounded-xl border border-line bg-sunk/40 p-4">
      <p className="text-sm font-semibold">Email draft</p>
      <p className="text-xs text-ink-3">Opens in Gmail for you to send.</p>
      <label className="mt-3 block text-xs font-medium text-ink-2">To
        <input value={to} onChange={(e) => setTo(e.target.value)} placeholder="agent@example.com" type="email"
               className="mt-1 h-10 w-full rounded-md border border-line-strong bg-surface px-3 text-sm" />
      </label>
      <label className="mt-2 block text-xs font-medium text-ink-2">Subject
        <input value={subject} onChange={(e) => setSubject(e.target.value)}
               className="mt-1 h-10 w-full rounded-md border border-line-strong bg-surface px-3 text-sm" />
      </label>
      <label className="mt-2 block text-xs font-medium text-ink-2">Message
        <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={8}
                  className="mt-1 w-full rounded-md border border-line-strong bg-surface p-3 text-sm" />
      </label>
      <div className="mt-3 flex flex-wrap gap-2">
        <a aria-disabled={!validTo}
           className={`inline-flex h-10 items-center gap-2 rounded-md bg-green px-4 text-sm font-medium text-on-green ${validTo ? "" : "pointer-events-none opacity-50"}`}
           href={gmailCompose(to.trim(), subject, body)} target="_blank" rel="noopener noreferrer"
           onClick={() => { setOpened(true); save("save"); }}>
          <Mail aria-hidden className="size-4" />Approve &amp; open in Gmail
        </a>
        {opened && <Button variant="secondary" disabled={pending} onClick={() => save("sent")}>I sent it</Button>}
        <Button variant="quiet" disabled={pending} onClick={() => save("save")}>Save draft</Button>
        <Button variant="quiet" disabled={pending} onClick={() => save("discard")}>Discard</Button>
      </div>
      {!validTo && <p className="mt-2 text-xs text-ink-3">Add the agent&apos;s email address to send.</p>}
      {error && <p className="mt-2 text-sm text-red-ink">{error}</p>}
    </div>
  );
}
