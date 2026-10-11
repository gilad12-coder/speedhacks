import { MessagesSquare } from "lucide-react";
import { notFound } from "next/navigation";
import { HouseBanner } from "@/components/house-banner";
import { ProfileMenu } from "@/components/profile-menu";
import { Wordmark } from "@/components/shell";
import { getHouseholdState, getInterview, isMember } from "@/lib/households";
import { getAccount, getHousemateId } from "@/lib/session";
import { InterviewChat } from "./interview-chat";

export default async function InterviewPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const state = await getHouseholdState(id);
  if (!state) notFound();
  const meId = await getHousemateId(id);
  if (!(await isMember(id, meId))) notFound();

  const me = state.household.housemates.find((h) => h.id === meId)!;
  const account = await getAccount();
  const interview = await getInterview(me.id);
  const solo = state.household.expectedSize === 1;

  // Laid out like the intake form (same bar, progress line, banner and columns), so the interview reads
  // as the form's last part rather than a new page.
  return (
    <main className="flex h-dvh flex-col">
      <div className="flex items-center justify-between px-12 pt-6 pb-5">
        <Wordmark />
        <ProfileMenu
          name={account?.firstName ? `${account.firstName} ${account.lastName}`.trim() : me.name}
          email={account?.email}
          picture={account?.picture}
          joinCode={state.joinCode}
          preferencesHref={`/join/${state.joinCode}`}
          settingsHref={`/h/${id}/settings`}
        />
      </div>
      <div className="h-1 bg-green" />
      <HouseBanner />
      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <div className="overflow-y-auto border-r border-line px-12 py-16">
          <h1 className="font-display text-5xl leading-[1.05] font-semibold tracking-[-0.02em]">Tell Keyhunt the rest</h1>
          <p className="mt-5 max-w-[44ch] text-lg leading-relaxed text-ink-2">
            Your basics are saved. Now a few questions about everything else that makes a place right for you
            {solo ? "" : ". Your housemates each do their own"}. Answer in your own words, or pick a suggestion.
          </p>
        </div>
        <div className="flex min-h-0 flex-col px-16 pt-16 pb-8">
          <div className="flex w-full max-w-2xl items-center gap-4">
            <span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-green-soft text-green-ink">
              <MessagesSquare aria-hidden className="size-5" strokeWidth={1.75} />
            </span>
            <h2 className="font-display text-4xl leading-[1.05] font-semibold tracking-tight text-ink">A short interview</h2>
          </div>
          <InterviewChat
            householdId={id}
            initial={interview.messages}
            initialDone={interview.done}
            locked={Boolean(state.searchRequestedAt)}
          />
        </div>
      </div>
    </main>
  );
}
