"use client";

import { useActionState, useState } from "react";
import { startHousehold, type FormState } from "./actions";
import { Button } from "@/components/shell";

// Small scenes drawn in the app's palette: one person by a house, or three people under one roof.
function SoloArt() {
  return (
    <svg viewBox="0 0 64 48" aria-hidden className="h-12 w-16">
      <path className="art-roof" pathLength={1} d="M6 20 L32 4 L58 20" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
      <g className="art-person" style={{ "--d": "60ms" } as React.CSSProperties}>
        <circle cx="32" cy="22" r="6" fill="currentColor" />
        <path d="M21 44 C21 34 26 29 32 29 C38 29 43 34 43 44 Z" fill="currentColor" stroke="var(--surface)" strokeWidth="2" />
      </g>
    </svg>
  );
}

function GroupArt() {
  return (
    <svg viewBox="0 0 64 48" aria-hidden className="h-12 w-16">
      <path className="art-roof" pathLength={1} d="M6 20 L32 4 L58 20" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
      <g className="art-person" opacity="0.55" style={{ "--d": "150ms" } as React.CSSProperties}>
        <circle cx="16" cy="25" r="5" fill="currentColor" />
        <path d="M7 44 C7 36 11 32 16 32 C21 32 25 36 25 44 Z" fill="currentColor" />
      </g>
      <g className="art-person" opacity="0.55" style={{ "--d": "210ms" } as React.CSSProperties}>
        <circle cx="48" cy="25" r="5" fill="currentColor" />
        <path d="M39 44 C39 36 43 32 48 32 C53 32 57 36 57 44 Z" fill="currentColor" />
      </g>
      <g className="art-person" style={{ "--d": "60ms" } as React.CSSProperties}>
        <circle cx="32" cy="22" r="6" fill="currentColor" />
        <path d="M21 44 C21 34 26 29 32 29 C38 29 43 34 43 44 Z" fill="currentColor" stroke="var(--surface)" strokeWidth="2" />
      </g>
    </svg>
  );
}

export function StartForm() {
  const [state, action, pending] = useActionState<FormState, FormData>(startHousehold, {});
  const [who, setWho] = useState<"solo" | "group">("group");
  return (
    <form action={action} className="rounded-3xl border border-line bg-surface p-8 shadow-lift">
      <h2 className="font-display text-2xl font-semibold tracking-tight">Start a search</h2>
      <fieldset className="mt-7">
        <legend className="text-sm font-medium text-ink">Who&apos;s moving?</legend>
        <div className="mt-3 grid grid-cols-2 gap-3">
          {(
            [
              { value: "solo", label: "Just me", note: "A place of your own", art: SoloArt },
              { value: "group", label: "With housemates", note: "One search for everyone", art: GroupArt },
            ] as const
          ).map((o) => (
            <label key={o.value} className="group relative">
              <input
                type="radio"
                name="who"
                value={o.value}
                checked={who === o.value}
                onChange={() => setWho(o.value)}
                className="peer sr-only"
              />
              <span className="flex cursor-pointer flex-col items-start gap-3 rounded-2xl border border-line bg-ground p-4 transition-[color,background-color,border-color,transform] duration-150 active:scale-[0.98] peer-checked:border-green peer-checked:bg-green-soft peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-green hover:border-line-strong">
                <span className="flex items-center justify-center rounded-xl bg-sunk px-2 py-1.5 text-ink-3 transition-colors group-has-checked:bg-surface group-has-checked:text-green">
                  <o.art />
                </span>
                <span>
                  <span className="block text-base font-medium text-ink">{o.label}</span>
                  <span className="block text-sm whitespace-nowrap text-ink-2">{o.note}</span>
                </span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>
      <fieldset className="mt-6" hidden={who === "solo"} disabled={who === "solo"}>
        <legend className="text-sm font-medium text-ink">How many of you are moving in?</legend>
        <div className="mt-3 grid grid-cols-5 gap-2">
          {[2, 3, 4, 5, 6].map((n) => (
            <label key={n} className="relative">
              <input type="radio" name="size" value={n} defaultChecked={n === 4} className="peer sr-only" />
              <span className="tabular flex h-12 cursor-pointer items-center justify-center rounded-xl border border-line bg-ground text-base font-medium text-ink-2 transition-colors peer-checked:border-green peer-checked:bg-green-soft peer-checked:text-green-ink peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-green hover:border-line-strong">
                {n}
              </span>
            </label>
          ))}
        </div>
      </fieldset>
      {state.error && (
        <p role="alert" className="mt-4 text-sm text-red-ink">
          {state.error}
        </p>
      )}
      <Button type="submit" disabled={pending} className="mt-7 w-full">
        {pending ? "Creating…" : who === "solo" ? "Start my search" : "Create household"}
      </Button>
    </form>
  );
}
