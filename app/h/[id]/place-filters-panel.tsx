"use client";

import { Check, ChevronDown, Search, X } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Button } from "@/components/shell";
import { FIELDS, type FacetField, type FacetOption, type FieldSpec, type Filters } from "@/lib/place-filters";

// Ported from Skynet's explore FiltersDrawer: one select-style row per field that
// expands in place, with counts that answer "how many places would this leave".

const FOCUS_RING = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-green/45";

export function FiltersPanel({
  open,
  onClose,
  filters,
  facets,
  resultTotal,
  onChange,
  onClearAll,
}: {
  open: boolean;
  onClose: () => void;
  filters: Filters;
  facets: Record<FacetField, FacetOption[]>;
  resultTotal: number;
  onChange: (field: FacetField, next: string[]) => void;
  onClearAll: () => void;
}) {
  const [openField, setOpenField] = useState<FacetField | null>(null);
  const totalActive = Object.values(filters).reduce((n, v) => n + v.length, 0);

  // Escape first collapses the open field, then closes the panel.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (openField) setOpenField(null);
      else onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, openField, onClose]);

  if (!open) return null;
  // A field only shows once some place holds a value for it ("Ruled out for" needs a ruled-out place).
  const fields = FIELDS.filter((spec) => facets[spec.field].length > 0 || filters[spec.field].length > 0);

  return (
    <>
      {/* Wide screens keep the results live beside the panel; narrower ones get a scrim and the footer. */}
      <div aria-hidden onClick={onClose} className="fixed inset-0 z-40 bg-ink/20 lg:hidden" />
      <aside
        aria-label="Filters"
        className="panel-in fixed inset-x-0 bottom-0 z-50 flex max-h-[88dvh] flex-col rounded-t-2xl border-t border-line bg-surface shadow-panel sm:inset-x-auto sm:inset-y-0 sm:right-0 sm:max-h-none sm:w-full sm:max-w-md sm:rounded-none sm:border-t-0 sm:border-l"
      >
        <div className="flex items-center justify-between gap-3 px-6 pt-5 pb-3">
          <h2 className="text-lg font-semibold tracking-tight">Filters</h2>
          <button type="button" onClick={onClose} aria-label="Close filters"
                  className={`inline-flex size-8 items-center justify-center rounded-md text-ink-2 hover:bg-sunk hover:text-ink ${FOCUS_RING}`}>
            <X aria-hidden className="size-4" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 pb-4">
          <div className="divide-y divide-line border-y border-line">
            {fields.map((spec) => (
              <FacetRow
                key={spec.field}
                spec={spec}
                open={openField === spec.field}
                onToggle={() => setOpenField(openField === spec.field ? null : spec.field)}
                options={facets[spec.field]}
                selected={filters[spec.field]}
                onChange={(next) => onChange(spec.field, next)}
              />
            ))}
          </div>
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-line px-6 py-4 lg:hidden">
          <Button variant="quiet" onClick={onClearAll} disabled={totalActive === 0}>Reset</Button>
          <Button onClick={onClose} className="min-w-[9.5rem] tabular-nums">
            Show {resultTotal} {resultTotal === 1 ? "place" : "places"}
          </Button>
        </div>
      </aside>
    </>
  );
}

/** A select-style row: closed, the field's name and value ("Any" when unset); open, its values unfold beneath. */
function FacetRow({
  spec,
  open,
  onToggle,
  options,
  selected,
  onChange,
}: {
  spec: FieldSpec;
  open: boolean;
  onToggle: () => void;
  options: FacetOption[];
  selected: string[];
  onChange: (next: string[]) => void;
}) {
  const panelId = useId();
  const [query, setQuery] = useState("");
  const buttonRef = useRef<HTMLButtonElement>(null);
  const wasOpen = useRef(open);
  // Collapsing unmounts whatever was focused inside; land focus on the row rather than the body.
  useEffect(() => {
    if (wasOpen.current && !open) {
      setQuery("");
      if (document.activeElement === document.body) buttonRef.current?.focus();
    }
    wasOpen.current = open;
  }, [open]);

  const [first] = selected;
  const toggle = (value: string) =>
    onChange(selected.includes(value) ? selected.filter((v) => v !== value) : [...selected, value]);

  // The selection stays pinned at the top of a searchable list however far it ranks.
  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const shown = options.filter((o) => !q || spec.display(o.value).toLowerCase().includes(q));
    if (!spec.searchable) return shown;
    return [...shown.filter((o) => selected.includes(o.value)), ...shown.filter((o) => !selected.includes(o.value))];
  }, [options, query, selected, spec]);

  return (
    <div className={`transition-colors ${open ? "-mx-3 rounded-lg bg-sunk/60 px-3" : ""}`}>
      <div className="flex h-12 w-full items-center gap-1.5">
        <button ref={buttonRef} type="button" aria-expanded={open} aria-controls={panelId} onClick={onToggle}
                className={`flex h-full min-w-0 flex-1 cursor-pointer items-center gap-3 rounded-md text-start ${FOCUS_RING}`}>
          <span className="w-[6.5rem] shrink-0 text-[13px] text-ink-2">{spec.label}</span>
          <span className={`min-w-0 flex-1 truncate text-[13.5px] ${first === undefined ? "text-ink-3" : "font-medium text-ink"}`}>
            {first === undefined ? "Any" : spec.display(first)}
          </span>
          {selected.length > 1 && (
            <span className="shrink-0 rounded-full bg-green-soft px-1.5 py-0.5 font-mono text-[11px] tabular-nums text-green-ink">
              {selected.length}
            </span>
          )}
        </button>
        {selected.length > 0 && (
          <button type="button" onClick={() => onChange([])} aria-label={`Clear ${spec.label}`}
                  className={`inline-flex size-5 shrink-0 items-center justify-center rounded-md text-ink-3 hover:bg-sunk hover:text-ink ${FOCUS_RING}`}>
            <X aria-hidden className="size-3" />
          </button>
        )}
        <button type="button" tabIndex={-1} aria-hidden onClick={onToggle}
                className="flex size-6 shrink-0 cursor-pointer items-center justify-center rounded-md text-ink-3">
          <ChevronDown aria-hidden className={`size-3.5 transition-transform duration-200 ${open ? "rotate-180" : ""}`} />
        </button>
      </div>

      {/* Height glides via grid rows so the field opens and shuts instead of snapping. */}
      <div id={panelId} className={`grid transition-[grid-template-rows,opacity] duration-200 ease-[var(--ease-out-expo)] motion-reduce:transition-none ${open ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"}`}>
        <div className="-mx-3 overflow-hidden px-3">
          {open && (
            <div className="flex flex-col pb-2">
              {spec.searchable && (
                <div className="flex h-10 items-center gap-2 rounded-lg border border-line bg-surface px-3">
                  <Search aria-hidden className="size-3.5 shrink-0 text-ink-3" />
                  <input
                    type="text"
                    aria-label={`Search ${spec.label.toLowerCase()}`}
                    autoComplete="off"
                    spellCheck={false}
                    autoFocus
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder={`Search ${spec.label.toLowerCase()}`}
                    className="h-full min-w-0 flex-1 bg-transparent text-[13px] text-ink outline-none placeholder:text-ink-3"
                  />
                  {query && (
                    <button type="button" onClick={() => setQuery("")} aria-label="Clear search"
                            className={`inline-flex size-7 shrink-0 items-center justify-center rounded-lg text-ink-2 hover:bg-sunk hover:text-ink ${FOCUS_RING}`}>
                      <X aria-hidden className="size-3.5" />
                    </button>
                  )}
                </div>
              )}
              <div role="group" aria-label={spec.label} className={`-mx-3 ${spec.searchable ? "mt-1 max-h-[min(40dvh,18rem)] overflow-y-auto py-1" : ""}`}>
                {rows.map((row) => {
                  const checked = selected.includes(row.value);
                  // A value nothing else would leave is disabled rather than hidden, so the set stays stable.
                  const disabled = row.count === 0 && !checked;
                  return (
                    <button
                      key={row.value}
                      type="button"
                      role="checkbox"
                      aria-checked={checked}
                      disabled={disabled}
                      onClick={() => toggle(row.value)}
                      className={`flex h-9 w-full cursor-pointer items-center gap-2.5 px-3 text-[13px] text-ink hover:bg-sunk disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent ${FOCUS_RING}`}
                    >
                      <span className={`flex size-4 shrink-0 items-center justify-center rounded border ${checked ? "border-green bg-green text-on-green" : "border-line-strong bg-surface"}`}>
                        {checked && <Check aria-hidden className="size-3" strokeWidth={3} />}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-start">{spec.display(row.value)}</span>
                      <span className="shrink-0 font-mono text-[12px] tabular-nums text-ink-3">{row.count}</span>
                    </button>
                  );
                })}
                {rows.length === 0 && (
                  <p className="px-3 py-4 text-center text-[12.5px] text-ink-3">{query ? "No match." : "None in this search."}</p>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/** One line naming the applied filters while the panel is closed: "Area Mission +1 · Call Answered". */
export function FilterSummary({ filters, onOpen, onClearAll }: { filters: Filters; onOpen: () => void; onClearAll: () => void }) {
  const parts = FIELDS.flatMap((spec) => {
    const [first] = filters[spec.field];
    return first === undefined ? [] : [{ label: spec.label, value: spec.display(first), more: filters[spec.field].length - 1 }];
  });
  if (!parts.length) return null;
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 px-1 text-[12px] text-ink-2">
      <button type="button" onClick={onOpen}
              className={`flex min-w-0 max-w-full cursor-pointer flex-wrap items-center gap-x-2 gap-y-1 rounded-md text-start hover:text-ink ${FOCUS_RING}`}>
        {parts.map((part, i) => (
          <span key={part.label} className="inline-flex min-w-0 items-center gap-1">
            {i > 0 && <span aria-hidden className="me-1 text-ink-3">·</span>}
            <span>{part.label}</span>
            <span className="max-w-[14rem] truncate font-medium text-ink">{part.value}</span>
            {part.more > 0 && <span className="tabular-nums">+{part.more}</span>}
          </span>
        ))}
      </button>
      <button type="button" onClick={onClearAll} className={`cursor-pointer rounded-md underline-offset-2 hover:text-ink hover:underline ${FOCUS_RING}`}>
        Clear
      </button>
    </div>
  );
}
