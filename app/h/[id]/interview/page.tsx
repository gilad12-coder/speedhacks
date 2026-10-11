import { notFound } from "next/navigation";
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

  return (
    <div className="flex h-dvh flex-col">
      <header className="shrink-0 bg-green text-on-green">
        <div className="flex items-center justify-between gap-6 px-8 py-4">
          <Wordmark tone="light" />
          <ProfileMenu
            name={account?.firstName ? `${account.firstName} ${account.lastName}`.trim() : me.name}
            email={account?.email}
            picture={account?.picture}
            joinCode={state.joinCode}
            tone="light"
            preferencesHref={`/join/${state.joinCode}`}
            settingsHref={`/h/${id}/settings`}
          />
        </div>
      </header>
      <main className="mx-auto flex min-h-0 w-full max-w-3xl flex-1 flex-col px-8 pt-8 pb-6">
        <h1 className="font-display text-3xl text-ink">Tell Keyhunt the rest</h1>
        <p className="mt-2 max-w-[60ch] text-ink-2">
          Your basics are saved. Now a few questions about everything else that makes a place right for you
          {solo ? "" : ". Your housemates each do their own"}. Answer in your own words, or pick a suggestion.
        </p>
        <InterviewChat
          householdId={id}
          initial={interview.messages}
          initialDone={interview.done}
          locked={Boolean(state.searchRequestedAt)}
        />
      </main>
    </div>
  );
}
