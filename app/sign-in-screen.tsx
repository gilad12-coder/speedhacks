import { Wordmark } from "@/components/shell";
import { GoogleMark, MESSAGES } from "./join/[code]/sign-in";

type Pos = { top?: string; bottom?: string; left?: string; right?: string };

// Decorative only: the kind of things Keyhunt checks, scattered around the panel like Skynet's login halo.
// Positions keep a clear centre column; the wings hug the panel instead of drifting to the viewport edges.
const HALO: { text: string; pos: Pos; rot: number }[] = [
  { text: "Pets OK, confirmed by phone", pos: { top: "-2%", left: "2%" }, rot: -5 },
  { text: "In-unit laundry", pos: { top: "-3%", left: "20%" }, rot: 3 },
  { text: "Landlord called back", pos: { top: "-2%", left: "40%" }, rot: -4 },
  { text: "Move-in June 1", pos: { top: "-3%", left: "60%" }, rot: 4 },
  { text: "Tour booked, Saturday 11am", pos: { top: "-2%", right: "2%" }, rot: -5 },
  { text: "18 min to work by bike", pos: { top: "9%", left: "7%" }, rot: 4 },
  { text: "Three bedrooms, two baths", pos: { top: "11%", left: "29%" }, rot: -3 },
  { text: "Still available", pos: { top: "9%", left: "52%" }, rot: 5 },
  { text: "Utilities included", pos: { top: "11%", left: "76%" }, rot: -4 },
  { text: "No broker fee", pos: { top: "20%", left: "5%" }, rot: -4 },
  { text: "Fits everyone's budget", pos: { top: "21%", right: "5%" }, rot: 3 },
  { text: "Quiet street", pos: { top: "32%", left: "3%" }, rot: 5 },
  { text: "Parking spot included", pos: { top: "46%", left: "2%" }, rot: 6 },
  { text: "Near the train", pos: { top: "60%", left: "4%" }, rot: 4 },
  { text: "Sunny living room", pos: { top: "39%", left: "17%" }, rot: -4 },
  { text: "Dishwasher", pos: { top: "66%", left: "16%" }, rot: -3 },
  { text: "Lease starts when you need it", pos: { top: "32%", right: "3%" }, rot: -5 },
  { text: "Two housemates agree", pos: { top: "46%", right: "4%" }, rot: -6 },
  { text: "Deposit is one month", pos: { top: "60%", right: "5%" }, rot: -4 },
  { text: "Backyard", pos: { top: "39%", right: "18%" }, rot: 4 },
  { text: "Elevator building", pos: { top: "66%", right: "16%" }, rot: 3 },
  { text: "Rent checked against listing", pos: { bottom: "19%", left: "6%" }, rot: 4 },
  { text: "Everyone's free Thursday", pos: { bottom: "20%", left: "44%" }, rot: -3 },
  { text: "Bike storage", pos: { bottom: "19%", right: "7%" }, rot: 5 },
  { text: "Furnished", pos: { bottom: "10%", left: "12%" }, rot: -4 },
  { text: "Walk to the park", pos: { bottom: "11%", left: "33%" }, rot: 4 },
  { text: "Gas stove", pos: { bottom: "9%", left: "55%" }, rot: -5 },
  { text: "Answered on the first ring", pos: { bottom: "11%", right: "6%" }, rot: 3 },
  { text: "Hardwood floors", pos: { bottom: "-2%", left: "4%" }, rot: 4 },
  { text: "Shortlist ready", pos: { bottom: "2%", left: "24%" }, rot: 5 },
  { text: "Washer and dryer", pos: { bottom: "-2%", left: "46%" }, rot: -3 },
  { text: "Close to groceries", pos: { bottom: "2%", left: "66%" }, rot: 4 },
  { text: "Viewing confirmed", pos: { bottom: "-2%", right: "3%" }, rot: 5 },
];

export function SignInScreen({ status }: { status?: string }) {
  return (
    <main className="relative flex min-h-dvh w-full items-center justify-center overflow-hidden bg-ground px-4 py-10">
      <div aria-hidden className="pointer-events-none absolute inset-0 z-0">
        {HALO.map((chip, i) => (
          <div key={chip.text} className="absolute" style={chip.pos}>
            <div
              className="halo-chip rounded-xl border border-line bg-surface px-3 py-2 text-[0.8rem] font-medium whitespace-nowrap text-ink-2 shadow-lift"
              style={
                {
                  "--rot": `${chip.rot}deg`,
                  "--amp": `${4 + (i % 3) * 2}px`,
                  "--xamp": `${i % 2 === 0 ? 3 : -3}px`,
                  "--wob": `${chip.rot + (i % 2 === 0 ? 0.8 : -0.8)}deg`,
                  "--dur": `${5 + (i % 6)}s`,
                  "--enter": `${150 + i * 30}ms`,
                  "--float": `${(i % 5) * 0.5}s`,
                } as React.CSSProperties
              }
            >
              {chip.text}
            </div>
          </div>
        ))}
      </div>
      {/* Clears a vertical band behind the panel so the chips frame it instead of crowding it. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 z-[1]"
        style={{
          background:
            "linear-gradient(90deg, transparent 0%, transparent 24%, var(--ground) 31%, var(--ground) 69%, transparent 76%, transparent 100%)",
        }}
      />

      <div className="signin-panel relative z-10 flex w-full max-w-[440px] flex-col items-center text-center">
        <Wordmark size="xl" />
        <div className="mt-9 w-full rounded-2xl border border-line bg-surface px-8 py-9 shadow-lift">
          <h1 className="font-display text-3xl leading-tight font-semibold tracking-tight text-ink">
            Sign in to get started
          </h1>
          <p className="mx-auto mt-3 max-w-[36ch] text-[0.9375rem] leading-relaxed text-ink-2">
            Keyhunt uses your Google account so you can come back to your search from any device, and so your
            housemates know it&apos;s really you. Keyhunt only sees your name and email.
          </p>
          {status && MESSAGES[status] && (
            <p role="alert" className="mt-5 rounded-xl bg-red-soft px-4 py-3 text-left text-sm text-red-ink">
              {MESSAGES[status]}
            </p>
          )}
          <a
            href="/api/auth/google/signin"
            className="mt-7 flex h-12 w-full items-center justify-center gap-3 rounded-xl border border-line-strong bg-surface text-base font-medium text-ink transition-colors hover:border-ink-3 hover:bg-ground"
          >
            <GoogleMark />
            Continue with Google
          </a>
        </div>
      </div>
    </main>
  );
}
