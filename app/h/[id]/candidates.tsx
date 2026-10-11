"use client";

import { ArrowUpDown, ExternalLink, FunnelX, Headphones, Phone, PhoneMissed, Search, SearchX, SlidersHorizontal, Voicemail, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { callRental } from "@/app/actions";
import { Button } from "@/components/shell";
import {
  activeCount,
  EMPTY_FILTERS,
  searchPlaces,
  STAGES,
  tokenize,
  type FacetField,
  type Filters,
  type Sort,
  type Stage,
} from "@/lib/place-filters";
import type { AgentRun, Call, Listing } from "@/lib/types";
import { formatClock, primaryCall, RULED_OUT_LABELS, usd } from "@/lib/view";
import { FilterSummary, FiltersPanel } from "./place-filters-panel";
import { PlacePanel } from "./place-panel";
import { RentVsMarket, ScreeningBadge } from "./screening";

const FOCUS_RING = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-green/45";

const SORTS: { value: Sort; label: string }[] = [
  { value: "best", label: "Furthest along" },
  { value: "rent", label: "Cheapest" },
  { value: "commute", label: "Shortest commute" },
];

/** Every place the search found, ruled out included, behind Skynet's explore search: one query, a stage toggle, filters. */
export function Candidates({
  householdId,
  run,
  budget,
  callerConnected,
}: {
  householdId: string;
  run: AgentRun;
  budget: number | null;
  callerConnected: boolean;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [waiting, setWaiting] = useState(false);
  const [selected, setSelected] = useState<{ listingId: string; t: number | null } | null>(null);
  const lastTrigger = useRef<HTMLElement | null>(null);

  const [text, setText] = useState("");
  const [stage, setStage] = useState<Stage>("all");
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [sort, setSort] = useState<Sort>("best");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const filtersButton = useRef<HTMLButtonElement>(null);

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
    setFiltersOpen(false);
    setSelected({ listingId, t: null });
  }, []);
  const close = useCallback(() => {
    setSelected(null);
    lastTrigger.current?.focus();
  }, []);
  const closeFilters = useCallback(() => {
    setFiltersOpen(false);
    filtersButton.current?.focus();
  }, []);

  const { results, facets, stageCounts } = useMemo(
    () => searchPlaces(run, budget, { text, stage, filters, sort }),
    [run, budget, text, stage, filters, sort],
  );
  if (!run.listings.length) return null;

  const filterCount = activeCount(filters);
  const clearFilters = () => setFilters(EMPTY_FILTERS);
  const setField = (field: FacetField, next: string[]) => setFilters((f) => ({ ...f, [field]: next }));

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

  const listing = selected && run.listings.find((l) => l.id === selected.listingId);

  return (
    <section className="mt-14" aria-labelledby="places-title">
      <div className="flex items-baseline justify-between gap-6">
        <h2 id="places-title" className="font-display text-3xl font-semibold tracking-tight">
          Every place we found
        </h2>
        <p className="font-mono tabular text-sm text-ink-2">
          {run.listings.length} {run.listings.length === 1 ? "place" : "places"}
        </p>
      </div>
      {!callerConnected && <p className="mt-4 text-sm text-ink-3">Calling is off here.</p>}
      {notice && (
        <p
          role="status"
          className={`mt-5 rounded-2xl px-5 py-3.5 text-sm ${notice.tone === "ok" ? "bg-green-soft text-green-ink" : "bg-red-soft text-red-ink"}`}
        >
          {notice.text}
        </p>
      )}

      <div className="mt-6 flex flex-col gap-3">
        <SearchBar
          text={text}
          onText={setText}
          stage={stage}
          stageCounts={stageCounts}
          onStage={setStage}
          filterCount={filterCount}
          filtersOpen={filtersOpen}
          filtersButton={filtersButton}
          onToggleFilters={() => (filtersOpen ? closeFilters() : setFiltersOpen(true))}
          onClearFilters={clearFilters}
        />
        <FilterSummary filters={filters} onOpen={() => setFiltersOpen(true)} onClearAll={clearFilters} />
      </div>

      {results.length === 0 ? (
        <div className="mt-6 flex flex-col items-center gap-4 rounded-2xl border border-dashed border-line-strong px-6 py-14 text-center">
          <SearchX aria-hidden className="size-6 text-ink-3" />
          <p className="text-ink-2">{text.trim() ? `No places match “${text.trim()}”.` : "No places match these filters."}</p>
          <div className="flex flex-wrap justify-center gap-2">
            {text.trim() && <Button variant="secondary" onClick={() => setText("")}>Clear search</Button>}
            {(filterCount > 0 || stage !== "all") && (
              <Button variant="secondary" onClick={() => { clearFilters(); setStage("all"); }}>
                <FunnelX aria-hidden className="size-4" />Clear filters
              </Button>
            )}
          </div>
        </div>
      ) : (
        <div className="mt-4 flex flex-col gap-2">
          <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 px-1 pb-2">
            <span className="font-mono text-xs tabular-nums text-ink-2">
              {results.length} {results.length === 1 ? "place" : "places"}
            </span>
            <div className="inline-flex items-center gap-1.5">
              <ArrowUpDown aria-hidden className="size-3 text-ink-3" />
              <Segmented label="Sort" value={sort} onChange={setSort} options={SORTS} />
            </div>
          </div>
          <ol className="divide-y divide-line border-t border-line">
            {results.map((l, i) => (
              <Row
                key={l.id}
                index={i}
                listing={l}
                tokens={tokenize(text)}
                call={primaryCall(run, l.id)}
                canCall={callerConnected && Boolean(l.contact.phone) && l.status !== "ruled_out"}
                busy={busy}
                onCall={call}
                onOpen={open}
              />
            ))}
          </ol>
        </div>
      )}

      <FiltersPanel
        open={filtersOpen}
        onClose={closeFilters}
        filters={filters}
        facets={facets}
        resultTotal={results.length}
        onChange={setField}
        onClearAll={clearFilters}
      />

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

/** The search's center of gravity: a stage toggle on top, then the rounded input with clear, reset and filters. "/" focuses it. */
function SearchBar({
  text,
  onText,
  stage,
  stageCounts,
  onStage,
  filterCount,
  filtersOpen,
  filtersButton,
  onToggleFilters,
  onClearFilters,
}: {
  text: string;
  onText: (next: string) => void;
  stage: Stage;
  stageCounts: Record<Stage, number>;
  onStage: (next: Stage) => void;
  filterCount: number;
  filtersOpen: boolean;
  filtersButton: React.RefObject<HTMLButtonElement | null>;
  onToggleFilters: () => void;
  onClearFilters: () => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const active = text.trim().length > 0 || filterCount > 0;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "/") return;
      const target = e.target as HTMLElement | null;
      if (target?.tagName === "INPUT" || target?.tagName === "TEXTAREA" || target?.isContentEditable) return;
      e.preventDefault();
      input.current?.focus();
      input.current?.select();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const iconButton = `inline-flex size-9 shrink-0 cursor-pointer items-center justify-center rounded-lg text-ink-2 transition-colors hover:bg-sunk hover:text-ink ${FOCUS_RING}`;

  return (
    <div className="flex w-full flex-col gap-2.5">
      <Segmented
        label="Stage"
        value={stage}
        onChange={onStage}
        options={STAGES.map((s) => ({ ...s, count: stageCounts[s.value] }))}
      />
      <div
        className={`flex h-11 items-center gap-1 rounded-2xl border bg-surface ps-4 pe-1 transition-[border-color] duration-150 focus-within:border-ink-3 ${
          active ? "border-line-strong" : "border-line"
        }`}
      >
        <Search aria-hidden className="size-4 shrink-0 text-ink-3" />
        <input
          ref={input}
          type="text"
          inputMode="search"
          autoComplete="off"
          spellCheck={false}
          value={text}
          onChange={(e) => onText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              if (text) onText("");
              else input.current?.blur();
            }
          }}
          placeholder="Search by address, area or why it was ruled out"
          aria-label="Search places"
          className="h-full min-w-0 flex-1 bg-transparent px-2 py-1.5 text-[15px] tracking-tight text-ink placeholder:text-ink-3 focus:outline-none"
        />
        {text && (
          <button type="button" onClick={() => { onText(""); input.current?.focus(); }} aria-label="Clear search" className={iconButton}>
            <X aria-hidden className="size-4" />
          </button>
        )}
        {filterCount > 0 && (
          <button type="button" onClick={onClearFilters} aria-label="Reset filters" title="Reset filters" className={iconButton}>
            <FunnelX aria-hidden className="size-[1.05rem]" />
          </button>
        )}
        <button
          ref={filtersButton}
          type="button"
          onClick={onToggleFilters}
          aria-label="Filters"
          aria-expanded={filtersOpen}
          className={`inline-flex h-9 shrink-0 cursor-pointer items-center justify-center gap-1.5 rounded-lg px-2.5 text-[13px] text-ink-2 transition-colors hover:bg-sunk hover:text-ink ${FOCUS_RING}`}
        >
          <SlidersHorizontal aria-hidden className="size-[1.125rem]" />
          {filterCount > 0 && (
            <span className="rounded-full bg-green px-1.5 font-mono text-[11px] leading-5 tabular-nums text-on-green">{filterCount}</span>
          )}
        </button>
      </div>
    </div>
  );
}

function Segmented<T extends string>({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: T;
  onChange: (next: T) => void;
  options: { value: T; label: string; count?: number }[];
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex w-fit max-w-full flex-wrap rounded-full border border-line bg-surface p-0.5 text-[13px] font-medium">
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={on}
            onClick={() => on || onChange(o.value)}
            className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 transition-colors ${FOCUS_RING} ${on ? "bg-green text-on-green" : "text-ink-2 hover:text-ink"}`}
          >
            {o.label}
            {o.count !== undefined && <span className={`font-mono text-[11px] tabular-nums ${on ? "text-on-green-2" : "text-ink-3"}`}>{o.count}</span>}
          </button>
        );
      })}
    </div>
  );
}

function Row({
  index,
  listing,
  tokens,
  call,
  canCall,
  busy,
  onCall,
  onOpen,
}: {
  index: number;
  listing: Listing;
  tokens: string[];
  call: Call | null;
  canCall: boolean;
  busy: string | null;
  onCall: (listingId: string) => void;
  onOpen: (listingId: string, trigger: HTMLElement) => void;
}) {
  const photo = listing.photoUrls[0];
  const out = listing.status === "ruled_out";
  return (
    <li
      className="result-in grid grid-cols-[6rem_minmax(0,1fr)_12rem] gap-5 rounded-lg px-3 py-4 transition-colors hover:bg-sunk/50"
      style={{ "--i": Math.min(index, 12) } as React.CSSProperties}
    >
      <div className={`aspect-[4/3] overflow-hidden rounded-xl bg-sunk ${out ? "opacity-60 grayscale" : ""}`}>
        {photo && (
          // Listing photos come from many hosts the agent finds, so they skip next/image's allowlist.
          // eslint-disable-next-line @next/next/no-img-element
          <img src={photo} alt="" loading="lazy" className="size-full object-cover" />
        )}
      </div>

      <div className="min-w-0">
        <div className="flex flex-wrap items-baseline gap-x-3">
          <h3 className={`truncate text-[15.5px] font-medium tracking-tight ${out ? "text-ink-2" : "text-ink"}`}>
            <Highlighted text={listing.address} tokens={tokens} />
          </h3>
          {listing.neighborhood && (
            <span className="text-sm text-ink-2"><Highlighted text={listing.neighborhood} tokens={tokens} /></span>
          )}
        </div>
        <p className="font-mono tabular mt-1 text-[13px] text-ink-2">
          <span className="font-medium text-ink">{listing.rentUsd === null ? "Rent unknown" : `${usd(listing.rentUsd)}/mo`}</span> ·{" "}
          {listing.bedrooms ?? "?"} bd · {listing.bathrooms ?? "?"} ba
          {listing.commuteMinutes !== null && <> · {listing.commuteMinutes} min commute</>}
        </p>
        {out && (
          <p className="mt-2 line-clamp-2 max-w-[72ch] text-[13.5px] leading-relaxed text-ink-2">
            <span className="font-medium text-red-ink">{listing.ruledOutReason ? RULED_OUT_LABELS[listing.ruledOutReason] : "Ruled out"}</span>
            {listing.ruledOutNote && <>. <Highlighted text={listing.ruledOutNote} tokens={tokens} /></>}
          </p>
        )}
        <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <StageBadge status={listing.status} />
          {listing.research && <ScreeningBadge research={listing.research} />}
          {call && <CallBadge call={call} />}
          {listing.research && <RentVsMarket rent={listing.rentUsd} research={listing.research} />}
        </div>
      </div>

      <div className="flex flex-col items-start justify-center gap-2 border-l border-line pl-5">
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
        {!listing.contact.phone && !out && <p className="px-2 text-xs text-ink-3">No phone number in the listing.</p>}
      </div>
    </li>
  );
}

function StageBadge({ status }: { status: Listing["status"] }) {
  const { label, tone } = {
    found: { label: "Found", tone: "bg-sunk text-ink-2" },
    called: { label: "Called", tone: "bg-amber-soft text-amber-ink" },
    verified: { label: "Verified", tone: "bg-green-soft text-green-ink" },
    tour_offered: { label: "Tour offered", tone: "bg-green-soft text-green-ink" },
    ruled_out: { label: "Ruled out", tone: "bg-red-soft text-red-ink" },
  }[status];
  return <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${tone}`}>{label}</span>;
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

/** Underlines every query token inside the text, as Skynet's results do. */
function Highlighted({ text, tokens }: { text: string; tokens: string[] }) {
  if (!tokens.length) return <>{text}</>;
  const lower = text.toLowerCase();
  const marks = new Array<boolean>(text.length).fill(false);
  for (const t of tokens) {
    for (let at = lower.indexOf(t); at !== -1; at = lower.indexOf(t, at + t.length)) marks.fill(true, at, at + t.length);
  }
  const parts: { text: string; match: boolean }[] = [];
  for (let i = 0; i < text.length; i++) {
    const last = parts.at(-1);
    if (last && last.match === marks[i]) last.text += text[i];
    else parts.push({ text: text[i], match: marks[i] });
  }
  return (
    <>
      {parts.map((p, i) =>
        p.match ? (
          <mark key={i} className="bg-transparent font-semibold text-ink underline decoration-green decoration-[1.5px] underline-offset-[3px]">
            {p.text}
          </mark>
        ) : (
          <span key={i}>{p.text}</span>
        ),
      )}
    </>
  );
}
