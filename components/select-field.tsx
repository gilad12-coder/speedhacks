"use client";

import { Check, ChevronDown } from "lucide-react";
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

interface Option {
  value: string;
  label: string;
}

const OPTION_H = 44;

export function SelectField({
  id,
  name,
  options,
  defaultValue,
  className = "",
}: {
  id?: string;
  name: string;
  options: readonly Option[];
  defaultValue: string;
  className?: string;
}) {
  const [value, setValue] = useState(defaultValue);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [pos, setPos] = useState<{ left: number; width: number; top?: number; bottom?: number }>();
  const buttonRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const listId = useId();
  const selected = options.find((o) => o.value === value) ?? options[0];

  // The list lives in a portal so the step's scroll container can't clip it;
  // it opens upward when there isn't room below.
  const place = useCallback(() => {
    if (!buttonRef.current) return;
    const r = buttonRef.current.getBoundingClientRect();
    const height = options.length * OPTION_H + 12;
    const below = window.innerHeight - r.bottom;
    setPos(
      below < height + 8 && r.top > below
        ? { left: r.left, width: r.width, bottom: window.innerHeight - r.top + 6 }
        : { left: r.left, width: r.width, top: r.bottom + 6 },
    );
  }, [options.length]);

  useLayoutEffect(() => {
    if (!open) return;
    place();
    listRef.current?.focus({ preventScroll: true });
  }, [open, place]);

  useEffect(() => {
    if (!open) return;
    const close = (e: Event) => {
      const t = e.target as Node;
      if (!listRef.current?.contains(t) && !buttonRef.current?.contains(t)) setOpen(false);
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
    setActive(Math.max(0, options.indexOf(selected)));
    setOpen(true);
  };

  const choose = (i: number) => {
    setValue(options[i].value);
    setOpen(false);
    buttonRef.current?.focus({ preventScroll: true });
  };

  const onListKey = (e: React.KeyboardEvent) => {
    const keys: Record<string, () => void> = {
      ArrowDown: () => setActive((a) => Math.min(options.length - 1, a + 1)),
      ArrowUp: () => setActive((a) => Math.max(0, a - 1)),
      Home: () => setActive(0),
      End: () => setActive(options.length - 1),
      Enter: () => choose(active),
      " ": () => choose(active),
      Escape: () => {
        setOpen(false);
        buttonRef.current?.focus({ preventScroll: true });
      },
      Tab: () => setOpen(false),
    };
    const run = keys[e.key];
    if (!run) return;
    if (e.key !== "Tab") e.preventDefault();
    // Enter must not bubble to the form, which treats it as "Next".
    e.stopPropagation();
    run();
  };

  return (
    <>
      <input type="hidden" name={name} value={value} />
      <button
        ref={buttonRef}
        id={id}
        type="button"
        data-field={name}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        onClick={() => (open ? setOpen(false) : show())}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown" || e.key === "ArrowUp") {
            e.preventDefault();
            show();
          }
        }}
        className={`flex h-12 w-full items-center justify-between gap-3 rounded-xl border border-line bg-surface px-4 text-left text-lg text-ink transition-colors hover:border-line-strong aria-expanded:border-line-strong ${className}`}
      >
        <span className="tabular truncate">{selected.label}</span>
        <ChevronDown
          aria-hidden
          className={`size-4 shrink-0 text-ink-3 transition-transform duration-200 ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open &&
        createPortal(
          <ul
            ref={listRef}
            id={listId}
            role="listbox"
            tabIndex={-1}
            aria-labelledby={id}
            aria-activedescendant={`${listId}-${active}`}
            onKeyDown={onListKey}
            style={{ ...pos, visibility: pos ? "visible" : "hidden" }}
            className={`select-pop fixed z-50 rounded-xl border border-line bg-surface p-1.5 shadow-lift outline-none ${
              pos?.bottom !== undefined ? "select-pop-up" : ""
            }`}
          >
            {options.map((o, i) => (
              <li
                key={o.value}
                id={`${listId}-${i}`}
                role="option"
                aria-selected={o.value === value}
                onPointerMove={() => setActive(i)}
                onClick={() => choose(i)}
                style={{ height: OPTION_H }}
                className={`tabular flex cursor-pointer items-center justify-between gap-3 rounded-lg px-3 text-base ${
                  i === active ? "bg-sunk text-ink" : "text-ink-2"
                } ${o.value === value ? "font-medium text-green-ink" : ""}`}
              >
                {o.label}
                {o.value === value && <Check aria-hidden className="size-4 shrink-0" />}
              </li>
            ))}
          </ul>,
          document.body,
        )}
    </>
  );
}
