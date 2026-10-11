"use client";

import { forwardRef } from "react";

const MAX_HEIGHT = 120;

function autoResize(el: HTMLTextAreaElement | null) {
  if (!el) return;
  el.style.height = "auto";
  el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`;
}

// One bordered box: a borderless textarea with the round send button docked under it.
export const Composer = forwardRef<
  HTMLTextAreaElement,
  {
    value: string;
    onChange: (v: string) => void;
    onSubmit: () => void;
    placeholder?: string;
    disabled?: boolean;
  }
>(function Composer({ value, onChange, onSubmit, placeholder, disabled }, ref) {
  const hasDraft = value.trim().length > 0;
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (disabled || !hasDraft) return;
    onSubmit();
    const el = (e.currentTarget as HTMLFormElement).querySelector("textarea");
    if (el) el.style.height = "";
  };

  return (
    <form onSubmit={submit} className="shrink-0 pt-3">
      <div className="rounded-2xl border border-line bg-surface transition-colors focus-within:border-green">
        <textarea
          ref={ref}
          value={value}
          onChange={(e) => {
            onChange(e.target.value);
            autoResize(e.target);
          }}
          onKeyDown={(e) => {
            if (e.nativeEvent.isComposing) return;
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              e.currentTarget.form?.requestSubmit();
            }
          }}
          rows={1}
          aria-label="Your answer"
          placeholder={placeholder}
          className="block h-[46px] max-h-[120px] w-full resize-none overflow-hidden bg-transparent px-4 py-3 text-[15px] leading-5 text-ink outline-none placeholder:text-ink-3"
        />
        <div className="flex items-center gap-2 px-2 pt-0.5 pb-2">
          <span className="ps-2 text-xs text-ink-3">Enter to send, Shift+Enter for a new line</span>
          <button
            type="submit"
            aria-label="Send"
            disabled={disabled || !hasDraft}
            className="ms-auto flex size-9 shrink-0 items-center justify-center rounded-full bg-green text-on-green transition-colors hover:bg-green-hover disabled:bg-sunk disabled:text-ink-3"
          >
            <svg viewBox="0 0 24 24" fill="none" className="size-4" aria-hidden>
              <path d="M12 2L12 22M12 2L5 9M12 2L19 9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        </div>
      </div>
    </form>
  );
});
