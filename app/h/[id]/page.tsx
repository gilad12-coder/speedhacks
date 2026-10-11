import { notFound } from "next/navigation";
import { CalendarCheck, CalendarX, CircleAlert, Users } from "lucide-react";
import { confirmHouseholdBrief, startSearch } from "@/app/actions";
import { ProfileMenu } from "@/components/profile-menu";
import { Button, Wordmark } from "@/components/shell";
import { buildSearchBrief } from "@/lib/brief";
import { commuteModeLabel } from "@/lib/features";
import {
  briefFingerprint,
  getAgentRun,
  getBookedTours,
  getHouseholdState,
  getInterview,
  isMember,
} from "@/lib/households";
import { getAccount, getHousemateId } from "@/lib/session";
import { proposeTourSlots } from "@/lib/tours";
import type { Household } from "@/lib/types";
import {
  pipelineCounts,
  RULED_OUT_LABELS,
  ruledOut,
  shortlist,
  usd,
} from "@/lib/view";
import { AutoRefresh } from "./auto-refresh";
import { InviteLink } from "./invite-link";
import { Shortlist } from "./shortlist";
import { Candidates } from "./candidates";

export const dynamic = "force-dynamic";

export default async function HouseholdPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ listing?: string }>;
}) {
  const { id } = await params;
  const { listing } = await searchParams;
  const state = await getHouseholdState(id);
  if (!state) notFound();
  const meId = await getHousemateId(id);
  if (!(await isMember(id, meId))) {
    return (
      <main className="mx-auto max-w-xl px-8 py-8">
        <Wordmark />
        <h1 className="mt-16 font-display text-3xl font-semibold tracking-tight">
          This household is private
        </h1>
        <p className="mt-3 leading-relaxed text-ink-2">
          Only its housemates can see it. Ask one of them for the invite link,
          and fill in your preferences there.
        </p>
      </main>
    );
  }

  const { household, joinCode, searchRequestedAt } = state;
  const me = household.housemates.find((h) => h.id === meId)!;
  const account = await getAccount();
  const interview = await getInterview(me.id);
  const run = searchRequestedAt ? await getAgentRun(id) : null;
  const list = run ? shortlist(run) : [];
  const [booked, proposed] = await Promise.all([
    getBookedTours(id),
    run && list.length
      ? proposeTourSlots(
          household,
          run,
          list.filter((l) => l.status === "tour_offered"),
        )
      : null,
  ]);
  const searching = Boolean(searchRequestedAt) && !run?.finishedAt;

  const brief = household.housemates.length
    ? buildSearchBrief(
        household.id,
        household.housemates,
        household.expectedSize,
      )
    : null;

  return (
    // A fixed-height shell: the rail and the main pane scroll on their own, so the short list always has the screen.
    <div className="grid h-dvh grid-rows-[auto_minmax(0,1fr)]">
      <header className="bg-green text-on-green">
        <div className="flex items-center justify-between gap-6 px-8 py-4">
          <Wordmark tone="light" />
          <ProfileMenu
            name={account?.firstName ? `${account.firstName} ${account.lastName}`.trim() : me.name}
            email={account?.email}
            picture={account?.picture}
            joinCode={joinCode}
            preferencesHref={`/join/${joinCode}`}
            interviewHref={`/h/${id}/interview`}
            settingsHref={`/h/${id}/settings`}
            tone="light"
          />
        </div>
      </header>

      <div className="grid min-h-0 grid-cols-[minmax(20rem,26rem)_minmax(0,1fr)]">
        <aside
          aria-label="Household"
          className="overflow-y-auto border-r border-line bg-surface px-8 py-8"
        >
          <Roster
            household={household}
            joinCode={joinCode}
            searchRequested={Boolean(searchRequestedAt)}
          />
          {searchRequestedAt && brief && (
            <section aria-labelledby="brief-title" className="mt-12">
              <h2
                id="brief-title"
                className="font-display text-lg font-semibold tracking-tight"
              >
                What Keyhunt is looking for
              </h2>
              <BriefList brief={brief} columns={1} />
            </section>
          )}
        </aside>

        <main className="overflow-y-auto px-12 pt-10 pb-24">
          {searching && <AutoRefresh />}
          {!interview.done && !searchRequestedAt && (
            <Callout tone="amber">
              <a href={`/h/${id}/interview`} className="font-medium underline">
                {interview.messages.length ? "Finish your interview" : "Do your interview"}
              </a>{" "}
              so Keyhunt knows what matters to you beyond the basics.
            </Callout>
          )}
          {!me.calendarConnected && (
            <Callout tone="amber">
              Connect Google Calendar in{" "}
              <a href={`/h/${id}/settings`} className="font-medium underline">
                Settings
              </a>{" "}
              so Keyhunt only offers tour times you&apos;re free for.
            </Callout>
          )}

          {!searchRequestedAt && (
            <BriefSection household={household} brief={brief} />
          )}

          {searchRequestedAt && (
            <section aria-labelledby="pipeline-title">
              <div className="flex items-baseline justify-between gap-6">
                <h2
                  id="pipeline-title"
                  className="font-display text-2xl font-semibold tracking-tight"
                >
                  {searching ? "Keyhunt is searching" : "Search finished"}
                </h2>
                <p className="text-sm text-ink-2">
                  {searching
                    ? run
                      ? "Places appear below as each call is checked. This page updates on its own."
                      : "Finding listings that fit your brief. Calls start once there are places to check. This page updates on its own."
                    : `Every place Keyhunt found, and what happened to it.`}
                </p>
              </div>
              {run && <Pipeline run={run} />}
              {run?.progress?.length ? <details className="mt-4 text-sm text-ink-2"><summary>{run.progress.at(-1)}</summary><ol className="mt-2 space-y-1">{run.progress.map((step,i) => <li key={i}>{step}</li>)}</ol></details> : null}
              {run?.warnings?.map((warning,i) => <p key={i} className="mt-3 text-sm text-ink-2">{warning}</p>)}
            </section>
          )}

          {run && (
            <section aria-labelledby="shortlist-title" className="mt-14">
              <div className="flex items-baseline justify-between gap-6">
                <h2
                  id="shortlist-title"
                  className="font-display text-3xl font-semibold tracking-tight"
                >
                  Your short list
                </h2>
                {list.length > 0 && (
                  <p className="text-sm text-ink-2">
                    Every check links to the moment in the call that confirmed
                    it.
                  </p>
                )}
              </div>
              {run.finishedAt && list.length < 3 && (
                <ThinResults count={list.length} household={household} />
              )}
              {!run.finishedAt && list.length === 0 && (
                <p className="mt-6 rounded-2xl border border-dashed border-line-strong px-6 py-16 text-center text-ink-2">
                  No place has passed its calls yet.
                </p>
              )}
              {proposed?.status === "calendars_missing" && (
                <Callout tone="amber">
                  Tour times appear once everyone connects Google Calendar.
                  Still missing: {proposed.names.join(", ")}.
                </Callout>
              )}
              {proposed?.status === "calendar_error" && (
                <Callout tone="amber">
                  Couldn&apos;t read {proposed.names.join(", ")}&apos;s
                  calendar, so tour times are hidden. They can reconnect from
                  Settings.
                </Callout>
              )}
              {list.length > 0 && (
                <Shortlist
                  householdId={id}
                  run={run}
                  listings={list}
                  occupants={household.housemates.length}
                  housemates={household.housemates.map((h) => ({
                    id: h.id,
                    name: h.name,
                  }))}
                  proposed={proposed?.status === "ok" ? proposed.slots : {}}
                  booked={Object.fromEntries(
                    booked.map((t) => [t.listingId, t]),
                  )}
                  initialListingId={listing ?? null}
                />
              )}
            </section>
          )}
          {run && <Candidates householdId={id} run={run} callerConnected={Boolean(process.env.AGENT_WORKER_URL)} />}
        </main>
      </div>
    </div>
  );
}

function Callout({
  tone,
  children,
}: {
  tone: "amber" | "red";
  children: React.ReactNode;
}) {
  return (
    <p
      role="status"
      className={`mt-6 flex items-start gap-3 rounded-2xl px-5 py-4 text-sm leading-relaxed ${
        tone === "amber"
          ? "bg-amber-soft text-amber-ink"
          : "bg-red-soft text-red-ink"
      }`}
    >
      <CircleAlert aria-hidden className="mt-0.5 size-4 shrink-0" />
      <span>{children}</span>
    </p>
  );
}

function Roster({
  household,
  joinCode,
  searchRequested,
}: {
  household: Household;
  joinCode: string;
  searchRequested: boolean;
}) {
  const { housemates, expectedSize } = household;
  const missing = expectedSize - housemates.length;
  return (
    <section aria-labelledby="household-title">
      <div className="flex items-center justify-between gap-4">
        <h1
          id="household-title"
          className="font-display text-2xl font-semibold tracking-tight"
        >
          {expectedSize === 1 ? "Your search" : "Your household"}
        </h1>
        {expectedSize > 1 && (
          <span className="font-mono tabular flex items-center gap-1.5 text-sm text-ink-2">
            <Users aria-hidden className="size-4" />
            {housemates.length} of {expectedSize}
          </span>
        )}
      </div>
      <ul className="mt-5 divide-y divide-line border-y border-line">
        {housemates.map((h) => (
          <li key={h.id} className="py-3">
            <div className="flex items-baseline justify-between gap-3">
              <p className="font-medium text-ink">{h.name}</p>
              {h.calendarConnected ? (
                <span className="flex shrink-0 items-center gap-1.5 text-xs font-medium text-green-ink">
                  <CalendarCheck aria-hidden className="size-3.5 self-center" />{" "}
                  Calendar connected
                </span>
              ) : (
                <span className="flex shrink-0 items-center gap-1.5 text-xs font-medium text-amber-ink">
                  <CalendarX aria-hidden className="size-3.5 self-center" /> No
                  calendar yet
                </span>
              )}
            </div>
            <p className="font-mono tabular mt-0.5 truncate text-sm text-ink-2">
              Up to {usd(h.maxBudgetUsd)} · {h.commute.destination}
            </p>
          </li>
        ))}
        {Array.from({ length: Math.max(missing, 0) }, (_, i) => (
          <li key={`empty-${i}`} className="py-3 text-sm text-ink-3">
            Waiting for housemate {housemates.length + i + 1}
          </li>
        ))}
      </ul>
      {missing > 0 && !searchRequested && (
        <InviteLink path={`/join/${joinCode}`} />
      )}
    </section>
  );
}

type Brief = ReturnType<typeof buildSearchBrief>;

function BriefSection({
  household,
  brief,
}: {
  household: Household;
  brief: Brief | null;
}) {
  const { housemates, expectedSize, conflicts, confirmed } = household;
  const missing = expectedSize - housemates.length;

  return (
    <section aria-labelledby="brief-title" className="max-w-5xl">
      <h2
        id="brief-title"
        className="font-display text-3xl font-semibold tracking-tight"
      >
        What Keyhunt will look for
      </h2>
      <p className="mt-2 text-ink-2">
        {expectedSize === 1 ? "Your answers and interview, as one search." : "Everyone\u2019s answers, merged into one search."}
      </p>
      {brief && <BriefList brief={brief} columns={3} />}

      {conflicts.length > 0 && (
        <div className="mt-12">
          <h3 className="font-display text-xl font-semibold tracking-tight">
            {conflicts.length === 1
              ? "One thing to settle"
              : `${conflicts.length} things to settle`}
          </h3>
          <p className="mt-1 text-sm text-ink-2">
            Until you settle it, Keyhunt leaves the disputed item out of the
            search. Anyone can change their answers.
          </p>
          <div className="mt-5 grid grid-cols-2 gap-4">
            {conflicts.map((c) => (
              <div
                key={c.description}
                className="rounded-2xl border border-line bg-surface px-5 py-4"
              >
                <p className="text-sm text-ink">{c.description}</p>
                <p className="mt-2 text-sm text-ink-2">
                  <span className="font-medium text-amber-ink">
                    Keyhunt suggests:{" "}
                  </span>
                  {c.suggestion}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="mt-12 flex flex-wrap items-center gap-4 border-t border-line pt-8">
        {missing > 0 ? (
          <p className="text-sm text-ink-2">
            The search can start once{" "}
            {missing === 1
              ? "the last housemate has"
              : `${missing} more housemates have`}{" "}
            filled in their preferences.
          </p>
        ) : !confirmed ? (
          <form
            action={confirmHouseholdBrief.bind(null, household.id)}
            className="flex items-center gap-4"
          >
            <input
              type="hidden"
              name="fingerprint"
              value={briefFingerprint(household)}
            />
            <Button type="submit">
              {conflicts.length ? "We agree, use this brief" : "Looks right"}
            </Button>
            {expectedSize > 1 && (
              <span className="text-sm text-ink-2">
                Anyone in the group can confirm.
              </span>
            )}
          </form>
        ) : (
          <form
            action={startSearch.bind(null, household.id)}
            className="flex items-center gap-4"
          >
            <Button type="submit">Start the search</Button>
            <span className="text-sm text-ink-2">
              Keyhunt will find places and call each landlord.
            </span>
          </form>
        )}
      </div>
    </section>
  );
}

function BriefList({ brief, columns }: { brief: Brief; columns: 1 | 3 }) {
  const modes = brief.commute.modes.map(commuteModeLabel).join(" or ");
  return (
    <dl
      className={
        columns === 3
          ? "mt-8 grid grid-cols-3 gap-x-10 gap-y-7 rounded-3xl bg-sunk px-8 py-7"
          : "mt-4 space-y-4"
      }
    >
      <BriefItem label="Rent, all together">
        <span className="font-mono tabular">Up to {usd(brief.maxTotalRentUsd)}/mo</span>
      </BriefItem>
      <BriefItem label="Move in">
        <span className="font-mono tabular">
          {fmtDay(brief.moveInFrom)} – {fmtDay(brief.moveInTo)}
        </span>
      </BriefItem>
      <BriefItem label="Commute">
        {brief.commute.destination}, {brief.commute.maxMinutes} min by {modes}
      </BriefItem>
      {/* Folded into one item so the three-column grid stays even. */}
      <BriefItem label="Where">
        {brief.location || "Anywhere"}, at least {brief.occupants} bedrooms
      </BriefItem>
      <BriefItem label="Must have">
        {brief.mustHaves.join(", ") || "Nothing specific"}
      </BriefItem>
      <BriefItem label="Rule out">
        {brief.dealBreakers.join(", ") || "Nothing"}
      </BriefItem>
      {brief.wishes.length > 0 && (
        <div className={columns === 3 ? "col-span-3" : undefined}>
          <BriefItem label="Also matters, from the interview">
            <ul className={columns === 3 ? "grid grid-cols-2 gap-x-10 gap-y-1" : "space-y-1"}>
              {brief.wishes.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          </BriefItem>
        </div>
      )}
    </dl>
  );
}

function BriefItem({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <dt className="text-xs font-medium text-ink-2">{label}</dt>
      <dd className="mt-1 text-ink">{children}</dd>
    </div>
  );
}

const fmtDay = (iso: string) =>
  new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });

function Pipeline({
  run,
}: {
  run: NonNullable<Awaited<ReturnType<typeof getAgentRun>>>;
}) {
  const counts = pipelineCounts(run);
  const stages = [
    ["Found", counts.found],
    ["Called", counts.called],
    ["Verified", counts.verified],
    ["Tour offered", counts.tourOffered],
  ] as const;
  const out = ruledOut(run);
  return (
    <div className="mt-5">
      <ol className="grid grid-cols-4 overflow-hidden rounded-2xl border border-line bg-surface">
        {stages.map(([label, n], i) => (
          <li
            key={label}
            className={`relative px-5 py-4 ${i > 0 ? "border-l border-line" : ""} ${
              i === stages.length - 1 && n > 0 ? "bg-green-soft" : ""
            }`}
          >
            <p className="tabular font-display text-3xl font-semibold tracking-tight text-ink">
              {n}
            </p>
            <p className="mt-0.5 text-sm text-ink-2">{label}</p>
          </li>
        ))}
      </ol>
      {out.length > 0 && (
        <details className="group mt-3">
          <summary className="cursor-pointer text-sm font-medium text-green-ink select-none">
            Ruled out ({out.length})
          </summary>
          <ul className="mt-3 divide-y divide-line rounded-2xl border border-line bg-surface">
            {out.map((l) => (
              <li
                key={l.id}
                className="grid grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,3fr)] gap-4 px-4 py-2.5 text-sm"
              >
                <span className="truncate text-ink">{l.address}</span>
                <span className="font-medium text-ink-2">
                  {l.ruledOutReason
                    ? RULED_OUT_LABELS[l.ruledOutReason]
                    : "Ruled out"}
                </span>
                <span className="text-ink-2">{l.ruledOutNote}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function ThinResults({
  count,
  household,
}: {
  count: number;
  household: Household;
}) {
  const brief = buildSearchBrief(
    household.id,
    household.housemates,
    household.expectedSize,
  );
  const loosen = brief.mustHaves.length
    ? `dropping “${brief.mustHaves[0]}” to a nice-to-have`
    : `allowing a commute longer than ${brief.commute.maxMinutes} minutes`;
  return (
    <Callout tone="amber">
      {count === 0
        ? "No place passed every call."
        : `Only ${count} ${count === 1 ? "place" : "places"} passed every call.`}{" "}
      The market is tight for this brief. The change most likely to help is{" "}
      {loosen}.
    </Callout>
  );
}
