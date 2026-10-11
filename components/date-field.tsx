"use client";

import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const POPOVER_H = 372;

// Dates stay as YYYY-MM-DD strings in local time, so no timezone can shift a move-in day.
function toIso(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function fromIso(iso: string) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}
function addDays(iso: string, days: number) {
  const d = fromIso(iso);
  d.setDate(d.getDate() + days);
  return toIso(d);
}
function addMonths(iso: string, months: number) {
  const d = fromIso(iso);
  const day = d.getDate();
  d.setDate(1);
  d.setMonth(d.getMonth() + months);
  // Jan 31 + 1 month lands on the last day of February, not in March.
  d.setDate(Math.min(day, new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate()));
  return toIso(d);
}

export function todayIso() {
  return toIso(new Date());
}

export function DateField({
  id,
  name,
  defaultValue,
  min,
  invalid,
  requiredMessage,
  onChange,
}: {
  id: string;
  name: string;
  defaultValue?: string;
  min?: string;
  invalid?: boolean;
  requiredMessage?: string;
  onChange?: (iso: string) => void;
}) {
  const [value, setValue] = useState(defaultValue ?? "");
  const [open, setOpen] = useState(false);
  const [focused, setFocused] = useState(value || min || todayIso());
  const [pos, setPos] = useState<{ left: number; top?: number; bottom?: number }>();
  const buttonRef = useRef<HTMLButtonElement>(null);
  const popRef = useRef<HTMLDivElement>(null);
  const gridRef = useRef<HTMLDivElement>(null);
  const titleId = useId();

  const disabled = (iso: string) => Boolean(min && iso < min);

  const place = useCallback(() => {
    if (!buttonRef.current) return;
    const r = buttonRef.current.getBoundingClientRect();
    const left = Math.min(r.left, window.innerWidth - 320 - 8);
    const below = window.innerHeight - r.bottom;
    setPos(
      below < POPOVER_H + 8 && r.top > below
        ? { left, bottom: window.innerHeight - r.top + 6 }
        : { left, top: r.bottom + 6 },
    );
  }, []);

  useLayoutEffect(() => {
    if (open) place();
  }, [open, place]);

  // Keeps keyboard focus on the highlighted day as it moves, including across months.
  useEffect(() => {
    if (!open) return;
    gridRef.current?.querySelector<HTMLButtonElement>(`[data-day="${focused}"]`)?.focus({ preventScroll: true });
  }, [open, focused]);

  useEffect(() => {
    if (!open) return;
    const close = (e: Event) => {
      const t = e.target as Node;
      if (!popRef.current?.contains(t) && !buttonRef.current?.contains(t)) setOpen(false);
    };
    document.addEventListener("pointerdown", close);
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      document.removeEventListener("pointerdown", close);
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open, place]);

  const show = () => {
    const start = value || min || todayIso();
    setFocused(min && start < min ? min : start);
    setOpen(true);
  };

  const close = () => {
    setOpen(false);
    buttonRef.current?.focus({ preventScroll: true });
  };

  const choose = (iso: string) => {
    if (disabled(iso)) return;
    setValue(iso);
    onChange?.(iso);
    close();
  };

  const onGridKey = (e: React.KeyboardEvent) => {
    const weekday = fromIso(focused).getDay();
    const moves: Record<string, () => string> = {
      ArrowLeft: () => addDays(focused, -1),
      ArrowRight: () => addDays(focused, 1),
      ArrowUp: () => addDays(focused, -7),
      ArrowDown: () => addDays(focused, 7),
      Home: () => addDays(focused, -weekday),
      End: () => addDays(focused, 6 - weekday),
      PageUp: () => addMonths(focused, -1),
      PageDown: () => addMonths(focused, 1),
    };
    if (moves[e.key]) {
      e.preventDefault();
      setFocused(moves[e.key]());
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      // Enter must not bubble to the form, which treats it as "Next".
      e.stopPropagation();
      choose(focused);
    }
  };

  const view = fromIso(focused);
  const year = view.getFullYear();
  const month = view.getMonth();
  const lead = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const cells = [
    ...Array<null>(lead).fill(null),
    ...Array.from({ length: daysInMonth }, (_, i) => toIso(new Date(year, month, i + 1))),
  ];
  const today = todayIso();
  const monthLabel = view.toLocaleDateString("en-US", { month: "long", year: "numeric" });
  const canGoBack = !min || toIso(new Date(year, month, 0)) >= min;

  return (
    <>
      <input type="hidden" name={name} value={value} data-required={requiredMessage} />
      <button
        ref={buttonRef}
        id={id}
        type="button"
        data-field={name}
        aria-haspopup="dialog"
        aria-expanded={open}
        data-invalid={invalid || undefined}
        onClick={() => (open ? setOpen(false) : show())}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            e.preventDefault();
            show();
          }
        }}
        className="flex h-12 w-full items-center justify-between gap-3 rounded-xl border border-line bg-surface px-4 text-left text-lg text-ink transition-colors hover:border-line-strong aria-expanded:border-line-strong data-invalid:border-red-ink"
      >
        <span className={`tabular truncate ${value ? "" : "text-ink-3"}`}>
          {value
            ? fromIso(value).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
            : "Pick a date"}
        </span>
        <CalendarDays aria-hidden className="size-4 shrink-0 text-ink-3" />
      </button>
      {open &&
        createPortal(
          <div
            ref={popRef}
            role="dialog"
            aria-modal="false"
            aria-labelledby={titleId}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                e.preventDefault();
                close();
              }
            }}
            style={{ ...pos, visibility: pos ? "visible" : "hidden" }}
            className={`select-pop fixed z-50 w-80 rounded-xl border border-line bg-surface p-3 shadow-lift ${
              pos?.bottom !== undefined ? "select-pop-up" : ""
            }`}
          >
            <div className="flex items-center justify-between px-1 pb-2">
              <p id={titleId} aria-live="polite" className="font-display text-lg font-semibold text-ink">
                {monthLabel}
              </p>
              <div className="flex gap-1">
                <button
                  type="button"
                  aria-label="Previous month"
                  disabled={!canGoBack}
                  onClick={() => setFocused(addMonths(focused, -1))}
                  className="flex size-8 items-center justify-center rounded-md text-ink-2 hover:bg-sunk hover:text-ink disabled:pointer-events-none disabled:opacity-30"
                >
                  <ChevronLeft aria-hidden className="size-4" />
                </button>
                <button
                  type="button"
                  aria-label="Next month"
                  onClick={() => setFocused(addMonths(focused, 1))}
                  className="flex size-8 items-center justify-center rounded-md text-ink-2 hover:bg-sunk hover:text-ink"
                >
                  <ChevronRight aria-hidden className="size-4" />
                </button>
              </div>
            </div>
            <div ref={gridRef} role="grid" aria-labelledby={titleId} onKeyDown={onGridKey}>
              <div role="row" className="grid grid-cols-7">
                {WEEKDAYS.map((d) => (
                  <span key={d} role="columnheader" aria-label={d} className="py-1.5 text-center text-xs font-medium text-ink-3">
                    {d.slice(0, 2)}
                  </span>
                ))}
              </div>
              {Array.from({ length: Math.ceil(cells.length / 7) }, (_, row) => (
                <div key={row} role="row" className="grid grid-cols-7">
                  {cells.slice(row * 7, row * 7 + 7).map((iso, i) =>
                    iso ? (
                      <span key={iso} role="gridcell" className="flex justify-center py-0.5">
                        <button
                          type="button"
                          data-day={iso}
                          tabIndex={iso === focused ? 0 : -1}
                          disabled={disabled(iso)}
                          aria-pressed={iso === value}
                          aria-current={iso === today ? "date" : undefined}
                          aria-label={fromIso(iso).toLocaleDateString("en-US", {
                            weekday: "long",
                            month: "long",
                            day: "numeric",
                            year: "numeric",
                          })}
                          onClick={() => choose(iso)}
                          className={`tabular relative flex size-10 items-center justify-center rounded-lg text-sm transition-colors outline-none disabled:pointer-events-none disabled:text-ink-3/50 ${
                            iso === value
                              ? "bg-green font-semibold text-on-green hover:bg-green-hover"
                              : iso === focused
                                ? "bg-sunk text-ink"
                                : "text-ink hover:bg-sunk"
                          }`}
                        >
                          {fromIso(iso).getDate()}
                          {iso === today && (
                            <span
                              aria-hidden
                              className={`absolute bottom-1.5 size-1 rounded-full ${iso === value ? "bg-on-green" : "bg-green"}`}
                            />
                          )}
                        </button>
                      </span>
                    ) : (
                      <span key={`blank-${i}`} role="gridcell" />
                    ),
                  )}
                </div>
              ))}
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}
