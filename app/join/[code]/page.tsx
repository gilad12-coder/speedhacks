import { HouseBanner } from "@/components/house-banner";
import { ProfileMenu } from "@/components/profile-menu";
import { Wordmark } from "@/components/shell";
import { findHouseholdByCode, getHousemateFullName, getHouseholdState } from "@/lib/households";
import { getAccount, getHousemateId } from "@/lib/session";
import { IntakeForm } from "./intake-form";
import { SignIn } from "./sign-in";

export default async function JoinPage({
  params,
  searchParams,
}: {
  params: Promise<{ code: string }>;
  searchParams: Promise<{ signin?: string }>;
}) {
  const { code } = await params;
  const { signin } = await searchParams;
  const found = await findHouseholdByCode(code);
  if (!found)
    return (
      <Notice
        title="This invite link doesn't work"
        body="It may have been mistyped. Ask whoever sent it for a new one."
      />
    );

  const housemateId = await getHousemateId(found.id);
  const state = (await getHouseholdState(found.id))!;
  const me =
    state.household.housemates.find((h) => h.id === housemateId) ?? null;
  const others = state.household.housemates.filter((h) => h.id !== me?.id);

  if (found.searchStarted && !me) {
    return (
      <Notice
        title="This search has already started"
        body="Preferences are locked once the group starts searching. Ask the group to add you to the next one."
      />
    );
  }
  if (!me && found.joined >= found.expectedSize) {
    return (
      <Notice
        title="This household is full"
        body={`All ${found.expectedSize} spots are taken. If that's a mistake, ask the group to start a new household with room for you.`}
      />
    );
  }

  const account = await getAccount();
  const solo = found.expectedSize === 1;
  const intro = (
    <>
      <h1 className="font-display text-5xl leading-[1.05] font-semibold tracking-[-0.02em]">
        {me ? "Your preferences" : "Tell Keyhunt what you need"}
      </h1>
      <p className="mt-5 max-w-[44ch] text-lg leading-relaxed text-ink-2">
        {solo ? (
          <>
            The basics first, then a short interview.
          </>
        ) : (
          <>
            {others.length
              ? `You're joining ${others.map((h) => h.name).join(", ")}. `
              : "You're the first one here. "}
            Only your group sees your answers.
          </>
        )}
      </p>
    </>
  );

  if (!me && !account) {
    return (
      <main className="flex h-dvh flex-col">
        <div className="px-12 pt-6 pb-5">
          <Wordmark />
        </div>
        <div className="h-1 bg-sunk" />
        <HouseBanner />
        <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
          <div className="overflow-y-auto border-r border-line px-12 py-16">{intro}</div>
          <div className="overflow-y-auto px-16 pt-10 pb-8">
            <SignIn code={code} status={signin} />
          </div>
        </div>
      </main>
    );
  }

  const names = (me && (await getHousemateFullName(me.id))) ?? {
    firstName: account?.firstName ?? "",
    lastName: account?.lastName ?? "",
  };

  return (
    <main className="flex h-dvh flex-col">
      {/* The form draws the logo bar and its progress line, so the line sits right under the logo. */}
      <IntakeForm
        code={code}
        me={me}
        names={names}
        solo={solo}
        searchStarted={found.searchStarted}
        header={
          <div className="flex items-center justify-between">
            <Wordmark />
            <ProfileMenu
              name={`${names.firstName} ${names.lastName}`.trim() || (me?.name ?? "")}
              email={account?.email}
              picture={account?.picture}
              joinCode={code}
              settingsHref={me ? `/h/${found.id}/settings` : undefined}
            />
          </div>
        }
        aside={<HouseBanner />}
      >
        {intro}
      </IntakeForm>
    </main>
  );
}

function Notice({ title, body }: { title: string; body: string }) {
  return (
    <main className="mx-auto max-w-xl px-8 py-8">
      <Wordmark />
      <h1 className="mt-16 font-display text-3xl font-semibold tracking-tight">
        {title}
      </h1>
      <p className="mt-3 leading-relaxed text-ink-2">{body}</p>
    </main>
  );
}
