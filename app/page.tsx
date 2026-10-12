import { HouseBanner } from "@/components/house-banner";
import { Wordmark } from "@/components/shell";
import { getAccount } from "@/lib/session";
import { SignInScreen } from "./sign-in-screen";
import { StartForm } from "./start-form";
import { StepsCarousel } from "./steps-carousel";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { personalMode } from "@/lib/personal-mode";

export default async function Home({ searchParams }: { searchParams: Promise<{ signin?: string }> }) {
  if (personalMode((await headers()).get("host"))) redirect("/personal");
  if (!(await getAccount())) {
    const { signin } = await searchParams;
    return <SignInScreen status={signin} />;
  }

  return (
    <div className="flex min-h-dvh flex-col">
      {/* The banner replaces the nav bar. */}
      <header className="bg-green">
        <HouseBanner className="" />
      </header>
      <main className="mx-auto flex w-full max-w-[110rem] flex-1 flex-col px-12 pb-8">
        <div className="grid flex-1 grid-cols-[minmax(0,7fr)_minmax(24rem,5fr)] items-center gap-24 py-16">
          <div>
            <Wordmark size="xl" />
            <h1 className="mt-6 max-w-[20ch] font-display text-5xl leading-[1.02] font-semibold tracking-[-0.02em] text-balance text-ink">
              A place for all of you, already checked by phone.
            </h1>
            <p className="mt-8 max-w-[52ch] text-xl leading-relaxed text-ink-2">
              Keyhunt finds US listings that fit your whole group, calls every
              landlord, and hands you the few that are real, available and
              willing to show you around.
            </p>
            <StepsCarousel />
          </div>
          <div className="max-w-md">
            <StartForm />
          </div>
        </div>
      </main>
    </div>
  );
}
