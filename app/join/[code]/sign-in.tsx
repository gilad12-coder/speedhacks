import { LogIn } from "lucide-react";

export const MESSAGES: Record<string, string> = {
  declined: "Google sign-in was cancelled. Try again when you're ready.",
  failed: "Google couldn't confirm your account. Try again, or use a different Google account.",
};

export function SignIn({
  code,
  status,
  title = "Sign in to join",
  intro = "Your Google account shows your housemates it's really you, and lets you come back to your answers from any device. Keyhunt only sees your name and email.",
  footnote = "Then five short steps about rent, move-in, commute and the place itself.",
}: {
  code?: string;
  status?: string;
  title?: string;
  intro?: string;
  footnote?: string;
}) {
  return (
    <div className="step-in step-in-forward w-full max-w-2xl">
      <span className="mb-4 flex size-10 items-center justify-center rounded-xl bg-green-soft text-green-ink">
        <LogIn aria-hidden className="size-5" strokeWidth={1.75} />
      </span>
      <h2 className="font-display text-4xl leading-[1.05] font-semibold tracking-tight text-ink">
        {title}
      </h2>
      <p className="mt-3 max-w-[52ch] text-lg text-ink-2">{intro}</p>
      {status && MESSAGES[status] && (
        <p role="alert" className="mt-6 max-w-xl rounded-xl bg-red-soft px-4 py-3 text-sm text-red-ink">
          {MESSAGES[status]}
        </p>
      )}
      <a
        href={code ? `/api/auth/google/signin?code=${encodeURIComponent(code)}` : "/api/auth/google/signin"}
        className="mt-8 inline-flex h-12 items-center gap-3 rounded-xl border border-line-strong bg-surface pr-5 pl-4 text-base font-medium text-ink shadow-lift transition-colors hover:border-ink-3 hover:bg-ground"
      >
        <GoogleMark />
        Continue with Google
      </a>
      <p className="mt-4 text-sm text-ink-3">{footnote}</p>
    </div>
  );
}

export function GoogleMark() {
  return (
    <svg aria-hidden viewBox="0 0 48 48" className="size-5 shrink-0">
      <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z" />
      <path fill="#FF3D00" d="m6.3 14.7 6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
      <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-7.9l-6.5 5C9.5 39.6 16.2 44 24 44z" />
      <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z" />
    </svg>
  );
}
