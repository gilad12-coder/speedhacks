"use client";

import { LogOut, MessagesSquare, Settings, SlidersHorizontal } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

const itemClass =
  "flex h-10 w-full items-center gap-2.5 rounded-lg px-3 text-sm font-medium text-ink-2 outline-none hover:bg-sunk hover:text-ink focus-visible:bg-sunk focus-visible:text-ink";

export function ProfileMenu({
  name,
  email,
  picture,
  joinCode,
  settingsHref,
  preferencesHref,
  interviewHref,
  tone = "ink",
}: {
  name: string;
  email?: string;
  picture?: string;
  joinCode: string;
  settingsHref?: string;
  preferencesHref?: string;
  interviewHref?: string;
  tone?: "ink" | "light";
}) {
  const [open, setOpen] = useState(false);
  const [broken, setBroken] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuId = useId();
  const initials = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]!.toUpperCase())
    .join("");

  useEffect(() => {
    if (!open) return;
    const close = (e: Event) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [open]);

  return (
    <div
      ref={rootRef}
      className="relative"
      onKeyDown={(e) => {
        if (e.key === "Escape" && open) {
          setOpen(false);
          buttonRef.current?.focus();
        }
      }}
    >
      <button
        ref={buttonRef}
        type="button"
        aria-label={`Account: ${name}`}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((o) => !o)}
        className={`flex size-9 items-center justify-center overflow-hidden rounded-full text-sm font-semibold transition-shadow ${
          tone === "light"
            ? "bg-on-green text-green ring-on-green-2/40 hover:ring-4 aria-expanded:ring-4"
            : "bg-green-soft text-green-ink ring-line hover:ring-4 aria-expanded:ring-4"
        }`}
      >
        {picture && !broken ? (
          // Google profile photos refuse requests that carry a referrer.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={picture}
            alt=""
            referrerPolicy="no-referrer"
            onError={() => setBroken(true)}
            className="size-full object-cover"
          />
        ) : (
          initials
        )}
      </button>
      {open && (
        <div
          id={menuId}
          role="menu"
          aria-label="Account"
          className="select-pop absolute top-full right-0 z-50 mt-2 w-64 rounded-xl border border-line bg-surface p-1.5 text-ink shadow-lift"
        >
          <div className="px-3 pt-2 pb-3">
            <p className="truncate font-medium">{name}</p>
            {email && <p className="truncate text-sm text-ink-3">{email}</p>}
          </div>
          {(preferencesHref || settingsHref) && (
            <div className="mb-1.5">
              {preferencesHref && (
                <a href={preferencesHref} role="menuitem" autoFocus className={itemClass}>
                  <SlidersHorizontal aria-hidden className="size-4" />
                  Edit my preferences
                </a>
              )}
              {interviewHref && (
                <a href={interviewHref} role="menuitem" className={itemClass}>
                  <MessagesSquare aria-hidden className="size-4" />
                  My interview
                </a>
              )}
              {settingsHref && (
                <a
                  href={settingsHref}
                  role="menuitem"
                  autoFocus={!preferencesHref}
                  className={itemClass}
                >
                  <Settings aria-hidden className="size-4" />
                  Settings
                </a>
              )}
            </div>
          )}
          <form method="post" action="/api/auth/signout" className="border-t border-line pt-1.5">
            <input type="hidden" name="joinCode" value={joinCode} />
            <button
              type="submit"
              role="menuitem"
              autoFocus={!settingsHref && !preferencesHref}
              className={itemClass}
            >
              <LogOut aria-hidden className="size-4" />
              Sign out
            </button>
          </form>
        </div>
      )}
    </div>
  );
}
