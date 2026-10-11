import { notFound } from "next/navigation";
import { ArrowLeft, CalendarCheck, CalendarDays, CircleAlert } from "lucide-react";
import { ProfileMenu } from "@/components/profile-menu";
import { Wordmark } from "@/components/shell";
import { getHouseholdState, isMember } from "@/lib/households";
import { getAccount, getHousemateId } from "@/lib/session";
import { mainAppUrl } from "@/lib/agent-worker";

const CALENDAR_NOTICES: Record<string, { tone: "green" | "amber"; text: string }> = {
  connected: { tone: "green", text: "Google Calendar is connected." },
  declined: { tone: "amber", text: "Google Calendar wasn't connected. You can try again below." },
  failed: {
    tone: "amber",
    text: "Google Calendar didn't connect. Make sure you allow both seeing when you're busy and adding events, then try again.",
  },
};

export default async function SettingsPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ calendar?: string }>;
}) {
  const { id } = await params;
  const { calendar } = await searchParams;
  const state = await getHouseholdState(id);
  if (!state) notFound();
  const meId = await getHousemateId(id);
  if (!(await isMember(id, meId))) notFound();

  const me = state.household.housemates.find((h) => h.id === meId)!;
  const account = await getAccount();
  const name = account?.firstName ? `${account.firstName} ${account.lastName}`.trim() : me.name;
  const notice = calendar ? CALENDAR_NOTICES[calendar] : undefined;
  const voiceUrl = state.searchRequestedAt ? mainAppUrl(id) : null;

  return (
    <div className="min-h-dvh">
      <header className="bg-green text-on-green">
        <div className="flex items-center justify-between gap-6 px-8 py-4">
          <Wordmark tone="light" />
          <ProfileMenu
            name={name}
            email={account?.email}
            picture={account?.picture}
            joinCode={state.joinCode}
            preferencesHref={`/join/${state.joinCode}`}
            tone="light"
          />
        </div>
      </header>

      <main className="mx-auto max-w-2xl px-8 pt-12 pb-24">
        <a
          href={`/h/${id}`}
          className="inline-flex items-center gap-1.5 text-sm font-medium text-ink-2 hover:text-ink"
        >
          <ArrowLeft aria-hidden className="size-4" />
          Back to the household
        </a>
        <h1 className="mt-6 font-display text-4xl font-semibold tracking-tight">Settings</h1>

        {notice && (
          <p
            role="status"
            className={`mt-8 flex items-start gap-3 rounded-2xl px-5 py-4 text-sm leading-relaxed ${
              notice.tone === "green" ? "bg-green-soft text-green-ink" : "bg-amber-soft text-amber-ink"
            }`}
          >
            {notice.tone === "green" ? (
              <CalendarCheck aria-hidden className="mt-0.5 size-4 shrink-0" />
            ) : (
              <CircleAlert aria-hidden className="mt-0.5 size-4 shrink-0" />
            )}
            <span>{notice.text}</span>
          </p>
        )}

        <section aria-labelledby="account-title" className="mt-10">
          <h2 id="account-title" className="text-sm font-medium text-ink-3">
            Account
          </h2>
          <div className="mt-3 rounded-2xl border border-line bg-surface px-6 py-5">
            <p className="font-medium">{name}</p>
            {account?.email && <p className="mt-0.5 text-sm text-ink-3">{account.email}</p>}
          </div>
        </section>

        <section aria-labelledby="voice-title" className="mt-10">
          <h2 id="voice-title" className="text-sm font-medium text-ink-3">Your assistant’s voice</h2>
          <div className="mt-3 rounded-2xl border border-line bg-surface px-6 py-5">
            <p className="font-medium">Let your AI assistant sound like you</p>
            <p className="mt-2 text-sm leading-relaxed text-ink-3">Record two minutes so calls use your voice. It always says it’s an AI.</p>
            {voiceUrl ? <a href={`${voiceUrl}/voice`} className="mt-4 inline-block text-sm font-semibold text-green-ink underline">Record my voice in KeyHunt</a>
              : <p className="mt-3 text-sm text-ink-3">Start your household search to set up its voice.</p>}
          </div>
        </section>

        <section aria-labelledby="calendar-title" className="mt-10">
          <h2 id="calendar-title" className="text-sm font-medium text-ink-3">
            Calendar
          </h2>
          <div className="mt-3 flex items-center gap-5 rounded-2xl border border-line bg-surface px-6 py-5">
            <span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-green-soft text-green-ink">
              <CalendarDays aria-hidden className="size-5" strokeWidth={1.75} />
            </span>
            <div className="min-w-0 flex-1">
              <p className="font-medium">
                Google Calendar
                <span className="ml-2 text-sm font-normal text-ink-3">
                  {me.calendarConnected ? "Connected" : "Not connected"}
                </span>
              </p>
              <p className="mt-0.5 text-sm text-ink-2">
                Reads only when you&apos;re busy, never event details.
              </p>
            </div>
            <a
              href={`/api/auth/google/start?household=${encodeURIComponent(id)}`}
              className={`inline-flex h-10 shrink-0 items-center justify-center rounded-md px-4 text-sm font-medium transition-colors duration-150 ${
                me.calendarConnected
                  ? "border border-line-strong bg-surface text-ink hover:border-ink-3"
                  : "bg-green text-on-green shadow-lift hover:bg-green-hover"
              }`}
            >
              {me.calendarConnected ? "Reconnect" : "Connect"}
            </a>
          </div>
        </section>
      </main>
    </div>
  );
}
