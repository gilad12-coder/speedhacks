"use client";

import { LoaderCircle, MapPin, Search } from "lucide-react";
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { Place } from "@/app/api/places/route";

const OPTION_H = 56;

export function AddressField({
  id,
  name,
  defaultValue = "",
  placeholder,
  kind = "address",
  className = "",
  ...rest
}: {
  kind?: "address" | "area";
  id: string;
  name: string;
  defaultValue?: string;
  placeholder?: string;
  className?: string;
} & React.InputHTMLAttributes<HTMLInputElement> & Record<`data-${string}`, string>) {
  const [query, setQuery] = useState(defaultValue);
  const [places, setPlaces] = useState<Place[]>([]);
  const [status, setStatus] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [pos, setPos] = useState<{ left: number; width: number; maxHeight: number; top?: number; bottom?: number }>();
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const listId = useId();

  useEffect(() => {
    const q = query.trim();
    if (!open || q.length < 3) {
      setPlaces([]);
      setStatus("idle");
      return;
    }
    const ctrl = new AbortController();
    const t = setTimeout(async () => {
      setStatus("loading");
      try {
        const res = await fetch(`/api/places?${new URLSearchParams({ q, kind })}`, { signal: ctrl.signal });
        const data = (await res.json()) as { places: Place[] };
        setPlaces(data.places);
        setActive(-1);
        setStatus(res.ok ? "done" : "error");
      } catch {
        if (!ctrl.signal.aborted) setStatus("error");
      }
    }, 250);
    return () => {
      clearTimeout(t);
      ctrl.abort();
    };
  }, [query, open, kind]);

  // Same portal approach as SelectField: the step's scroll area would clip the list.
  const place = useCallback(() => {
    if (!inputRef.current) return;
    const r = inputRef.current.getBoundingClientRect();
    const below = window.innerHeight - r.bottom;
    const up = below < 4 * OPTION_H && r.top > below;
    const base = { left: r.left, width: r.width, maxHeight: (up ? r.top : below) - 18 };
    setPos(up ? { ...base, bottom: window.innerHeight - r.top + 6 } : { ...base, top: r.bottom + 6 });
  }, []);

  const showList = open && status !== "idle";

  useLayoutEffect(() => {
    if (!showList) return;
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [showList, place]);

  useEffect(() => {
    if (!open) return;
    const close = (e: Event) => {
      const t = e.target as Node;
      if (!listRef.current?.contains(t) && !inputRef.current?.contains(t)) setOpen(false);
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [open]);

  useEffect(() => {
    if (active >= 0) document.getElementById(`${listId}-${active}`)?.scrollIntoView({ block: "nearest" });
  }, [active, listId]);

  const choose = (p: Place) => {
    setQuery(p.label);
    setOpen(false);
    inputRef.current?.focus({ preventScroll: true });
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!showList) {
      if (e.key === "ArrowDown") setOpen(true);
      return;
    }
    const last = places.length - 1;
    if (e.key === "ArrowDown") setActive((a) => (a >= last ? 0 : a + 1));
    else if (e.key === "ArrowUp") setActive((a) => (a <= 0 ? last : a - 1));
    else if (e.key === "Enter" && active >= 0 && places[active]) choose(places[active]);
    else if (e.key === "Escape") setOpen(false);
    else return;
    e.preventDefault();
    // Enter must not reach the form, which treats it as "Next".
    if (e.key === "Enter" || e.key === "Escape") e.stopPropagation();
  };

  return (
    <>
      <div className="relative">
        <Search aria-hidden className="pointer-events-none absolute top-1/2 left-4 size-4 -translate-y-1/2 text-ink-3" />
        <input
          {...rest}
          ref={inputRef}
          id={id}
          name={name}
          value={query}
          placeholder={placeholder}
          autoComplete="off"
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={showList}
          aria-controls={showList ? listId : undefined}
          aria-activedescendant={showList && active >= 0 ? `${listId}-${active}` : undefined}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onKeyDown={onKeyDown}
          className={`${className} pl-10`}
        />
        {status === "loading" && (
          <LoaderCircle aria-hidden className="absolute top-1/2 right-4 size-4 -translate-y-1/2 animate-spin text-ink-3" />
        )}
      </div>
      {showList &&
        createPortal(
          <ul
            ref={listRef}
            id={listId}
            role="listbox"
            aria-label="Matching addresses"
            style={{ ...pos, visibility: pos ? "visible" : "hidden" }}
            className={`select-pop fixed z-50 overflow-y-auto overscroll-contain rounded-xl border border-line bg-surface p-1.5 shadow-lift ${
              pos?.bottom !== undefined ? "select-pop-up" : ""
            }`}
          >
            {places.map((p, i) => (
              <li
                key={p.label}
                id={`${listId}-${i}`}
                role="option"
                aria-selected={i === active}
                onPointerMove={() => setActive(i)}
                // Keep focus in the input so the list doesn't close before the click lands.
                onPointerDown={(e) => e.preventDefault()}
                onClick={() => choose(p)}
                style={{ minHeight: OPTION_H }}
                className={`flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 ${
                  i === active ? "bg-sunk" : ""
                }`}
              >
                <MapPin aria-hidden className="size-4 shrink-0 text-ink-3" />
                <span className="min-w-0">
                  <span className="block truncate text-base text-ink">{p.primary}</span>
                  {p.secondary && <span className="block truncate text-sm text-ink-3">{p.secondary}</span>}
                </span>
              </li>
            ))}
            {status !== "loading" && places.length === 0 && (
              <li role="presentation" className="px-3 py-3 text-sm text-ink-3">
                {status === "error"
                  ? "Address search isn't available right now. You can type the place instead."
                  : "No matching places. You can keep what you typed."}
              </li>
            )}
            {status === "loading" && places.length === 0 && (
              <li role="presentation" className="px-3 py-3 text-sm text-ink-3">Searching…</li>
            )}
          </ul>,
          document.body,
        )}
    </>
  );
}
