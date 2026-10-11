"use client";

import { Minus, Plus } from "lucide-react";
import { useState } from "react";

export function NumberStepper({
  id,
  name,
  label,
  min,
  max,
  step,
  defaultValue,
  prefix,
  suffix,
  invalid,
}: {
  id?: string;
  name: string;
  label: string;
  min: number;
  max: number;
  step: number;
  defaultValue: number;
  prefix?: string;
  suffix?: string;
  invalid?: boolean;
}) {
  const [value, setValue] = useState(String(defaultValue));
  const n = Number(value);
  // Snap to the step grid so +/- from a typed value lands on round numbers.
  const nudge = (dir: 1 | -1) => {
    const base = Number.isFinite(n) && value !== "" ? n : defaultValue;
    const snapped = dir > 0 ? Math.floor(base / step) * step + step : Math.ceil(base / step) * step - step;
    setValue(String(Math.min(max, Math.max(min, snapped))));
  };
  const button =
    "flex w-12 shrink-0 items-center justify-center text-ink-2 transition-colors hover:bg-sunk hover:text-ink disabled:cursor-not-allowed disabled:opacity-35 disabled:hover:bg-transparent";

  return (
    <div
      className="flex h-12 w-full items-stretch overflow-hidden rounded-xl border border-line bg-surface hover:border-line-strong has-[input:focus]:border-line-strong has-aria-invalid:border-red-ink"
    >
      <button type="button" aria-label={`Less ${label.toLowerCase()}`} onClick={() => nudge(-1)} disabled={n <= min} className={`${button} border-r border-line`}>
        <Minus aria-hidden className="size-4" />
      </button>
      <label className="flex min-w-0 flex-1 items-center justify-center gap-1 text-lg text-ink">
        {prefix && <span className="text-ink-3">{prefix}</span>}
        <input
          id={id}
          name={name}
          aria-label={label}
          type="number"
          inputMode="numeric"
          min={min}
          max={max}
          step={1}
          required
          value={value}
          onChange={(e) => setValue(e.target.value)}
          aria-invalid={invalid || undefined}
          style={{ width: `${Math.max(2, value.length) + 0.5}ch` }}
          className="stepper-input tabular bg-transparent text-center outline-none"
        />
        {suffix && <span className="text-ink-3">{suffix}</span>}
      </label>
      <button type="button" aria-label={`More ${label.toLowerCase()}`} onClick={() => nudge(1)} disabled={n >= max} className={`${button} border-l border-line`}>
        <Plus aria-hidden className="size-4" />
      </button>
    </div>
  );
}
