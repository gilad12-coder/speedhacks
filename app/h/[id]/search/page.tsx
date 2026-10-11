import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { Wordmark } from "@/components/shell";
import { getHouseholdState, isMember } from "@/lib/households";
import { getHousemateId } from "@/lib/session";
import { getWorkspace, SEARCH_RUNNING, type WorkspaceListing } from "@/lib/workspace";
import { AutoRefresh } from "../auto-refresh";
import { ListingCard } from "./listing-card";
import { AddListing, RefineSearch } from "./panels";

export const dynamic = "force-dynamic";

// Interested places first, then what the agent learned, then everything still to check.
const ORDER: WorkspaceListing["status"][] = ["tour_scheduled", "viable", "contacted", "candidate", "new", "not_viable", "filtered"];
const rank = (l: WorkspaceListing) => (l.interested ? 0 : 1) * 10 + ORDER.indexOf(l.status);

export default async function SearchPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const state = await getHouseholdState(id);
  if (!state) notFound();
  if (!(await isMember(id, await getHousemateId(id)))) notFound();

  const result = state.searchRequestedAt ? await getWorkspace(id) : null;
  const header = (
    <header className="bg-green text-on-green">
      <div className="flex items-center justify-between gap-6 px-8 py-4">
        <Wordmark tone="light" />
        <Link href={`/h/${id}`} className="inline-flex items-center gap-1.5 text-sm font-medium text-on-green-2 hover:text-on-green">
          <ArrowLeft aria-hidden className="size-4" />Household
        </Link>
      </div>
    </header>
  );

  if (!result || !result.ok) {
    const waiting = !result || result.reason === "not_started";
    return (
      <>
        {header}
        {waiting && <AutoRefresh everyMs={5000} />}
        <main className="mx-auto max-w-2xl px-8 py-16">
          <h1 className="font-display text-3xl font-semibold tracking-tight">
            {!state.searchRequestedAt ? "No search yet" : waiting ? "Starting your search…" : "Search unavailable"}
          </h1>
          <p className="mt-3 leading-relaxed text-ink-2">
            {!state.searchRequestedAt
              ? "Once everyone's in and you've confirmed the brief, start the search from your household page."
              : waiting
                ? "KeyHunt is picking up your household's brief. This page updates on its own."
                : "KeyHunt's search engine isn't reachable right now. Your brief is saved; try again in a moment."}
          </p>
        </main>
      </>
    );
  }

  const { search, listings, callingEnabled } = result.workspace;
  const running = SEARCH_RUNNING.has(search.status);
  const callsRunning = listings.some((l) => l.call && ["queued", "in_progress", "extracting"].includes(l.call.status));
  const active = listings.filter((l) => !["filtered", "not_viable"].includes(l.status) || l.interested).sort((a, b) => rank(a) - rank(b));
  const ruledOut = listings.filter((l) => ["filtered", "not_viable"].includes(l.status) && !l.interested);
  const starred = listings.filter((l) => l.interested).length;
  const c = search.criteria;

  return (
    <>
      {header}
      {(running || callsRunning) && <AutoRefresh everyMs={4000} />}
      <main className="mx-auto max-w-4xl px-8 py-10">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="font-display text-3xl font-semibold tracking-tight">{c.city}</h1>
            <p className="mt-2 text-sm text-ink-2">
              Up to ${c.max_price.toLocaleString()}/mo · {c.min_beds}+ bd
              {c.neighborhoods.length > 0 && ` · ${c.neighborhoods.join(", ")}`}
              {c.must_haves.length > 0 && ` · ${c.must_haves.join(", ")}`}
            </p>
          </div>
          <p className="text-sm text-ink-2">
            {running ? "Searching…" : `${active.length} to look at · ${starred} starred · ${ruledOut.length} ruled out`}
          </p>
        </div>
        {search.error && <p className="mt-4 rounded-xl bg-amber-soft p-3 text-sm text-amber-ink">{search.error}</p>}
        {!callingEnabled && (
          <p className="mt-4 rounded-xl bg-sunk p-3 text-sm text-ink-2">Calls are in practice mode on this deployment: no real phone calls are placed.</p>
        )}

        <div className="mt-6 grid gap-3">
          <RefineSearch householdId={id} criteria={c} running={running} />
          <AddListing householdId={id} />
        </div>

        <ol className="mt-8 space-y-4">
          {active.map((l) => <ListingCard key={l.id} householdId={id} listing={l} callingEnabled={callingEnabled} />)}
          {!active.length && (
            <li className="rounded-2xl border border-line bg-surface p-8 text-center text-ink-2">
              {running ? "Looking for listings…" : "Nothing matches yet. Try refining the search or add a listing you found."}
            </li>
          )}
        </ol>

        {ruledOut.length > 0 && (
          <details className="mt-8">
            <summary className="cursor-pointer text-sm font-medium text-ink-2">{ruledOut.length} ruled out</summary>
            <ol className="mt-4 space-y-4">
              {ruledOut.map((l) => <ListingCard key={l.id} householdId={id} listing={l} callingEnabled={callingEnabled} />)}
            </ol>
          </details>
        )}
      </main>
    </>
  );
}
