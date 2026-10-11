"use client";

import { useEffect, useRef, useState } from "react";

// Columns that keep the cards in even rows: 2 side by side, 3 in a row, 4 as two pairs, 5–6 in rows of three.
const COLUMNS = ["", "grid-cols-1", "grid-cols-2", "grid-cols-3", "grid-cols-2", "grid-cols-3", "grid-cols-3"];

export interface Choice {
  label: string;
  description?: string;
}

// However many option cards the agent sends (up to 6) under its question, picked by click, digit key, or arrows then Enter.
// The composer below is always the "something else" path, so there's no "other" card.
export function QuestionChoices({
  options,
  onSelect,
  disabled,
}: {
  options: Choice[];
  onSelect: (label: string) => void;
  disabled?: boolean;
}) {
  const buttonsRef = useRef<(HTMLButtonElement | null)[]>([]);
  const [focused, setFocused] = useState(0);

  useEffect(() => setFocused(0), [options]);

  const move = (delta: number) => {
    const next = (focused + delta + options.length) % options.length;
    setFocused(next);
    buttonsRef.current[next]?.focus();
  };

  if (!options.length) return null;

  return (
    <div
      role="group"
      aria-label="Suggested answers"
      onKeyDown={(e) => {
        if (disabled) return;
        if (e.key === "ArrowDown" || e.key === "ArrowRight") {
          e.preventDefault();
          move(1);
        } else if (e.key === "ArrowUp" || e.key === "ArrowLeft") {
          e.preventDefault();
          move(-1);
        } else if (/^[1-9]$/.test(e.key) && options[Number(e.key) - 1]) {
          e.preventDefault();
          onSelect(options[Number(e.key) - 1].label);
        }
      }}
      className={`choices-in grid gap-2 border-t border-line pt-3 ${COLUMNS[Math.min(options.length, 6)]}`}
    >
      {options.map((o, i) => (
        <button
          key={`${i}-${o.label}`}
          ref={(el) => {
            buttonsRef.current[i] = el;
          }}
          type="button"
          disabled={disabled}
          tabIndex={i === focused ? 0 : -1}
          onFocus={() => setFocused(i)}
          onClick={() => onSelect(o.label)}
          className="group flex w-full items-start gap-2.5 rounded-xl border border-line bg-surface px-3 py-2.5 text-start transition-colors hover:border-green/50 hover:bg-green-soft/50 focus-visible:border-green focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-green/20 disabled:pointer-events-none disabled:opacity-50"
        >
          <span
            aria-hidden
            className="font-mono tabular mt-px flex size-5 shrink-0 items-center justify-center rounded-md border border-line bg-sunk text-[11px] font-medium text-ink-2 transition-colors group-hover:border-green/40 group-hover:bg-green-soft group-hover:text-green-ink"
          >
            {i + 1}
          </span>
          <span className="flex min-w-0 flex-col gap-0.5">
            <span className="text-sm leading-snug font-medium text-ink">{o.label}</span>
            {o.description && <span className="text-xs leading-snug text-ink-2">{o.description}</span>}
          </span>
        </button>
      ))}
    </div>
  );
}
