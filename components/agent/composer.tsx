"use client";

import { forwardRef, useRef } from "react";
import { Loader2, Mic, Square, X } from "lucide-react";
import { formatRecSeconds, useDictation } from "./use-dictation";

const MAX_HEIGHT = 120;

function autoResize(el: HTMLTextAreaElement | null) {
  if (!el) return;
  el.style.height = "auto";
  el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`;
}

// One bordered box: a borderless textarea with the mic and the round send button docked under it.
export const Composer = forwardRef<
  HTMLTextAreaElement,
  {
    value: string;
    onChange: (v: string) => void;
    onSubmit: () => void;
    placeholder?: string;
    disabled?: boolean;
    // Shown at the start of the bottom row.
    footer?: React.ReactNode;
  }
>(function Composer({ value, onChange, onSubmit, placeholder, disabled, footer }, ref) {
  const hasDraft = value.trim().length > 0;
  const formRef = useRef<HTMLFormElement>(null);
  // The transcript appends to whatever is in the draft when it lands.
  const valueRef = useRef(value);
  valueRef.current = value;
  const dictation = useDictation((spoken) => {
    const base = valueRef.current.trim();
    onChange(base ? `${base} ${spoken}` : spoken);
    requestAnimationFrame(() => {
      const el = formRef.current?.querySelector("textarea") ?? null;
      autoResize(el);
      el?.focus();
    });
  });
  const recording = dictation.state.kind === "rec";
  const transcribing = dictation.state.kind === "busy";

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (disabled || !hasDraft || recording || transcribing) return;
    onSubmit();
    const el = (e.currentTarget as HTMLFormElement).querySelector("textarea");
    if (el) el.style.height = "";
  };

  return (
    <form ref={formRef} onSubmit={submit} className="shrink-0 pt-3">
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
          dir="auto"
          aria-label="Your answer"
          placeholder={recording ? "Listening…" : transcribing ? "Transcribing…" : placeholder}
          className="block h-[46px] max-h-[120px] w-full resize-none overflow-hidden bg-transparent px-4 py-3 text-[15px] leading-5 text-ink outline-none placeholder:text-ink-3"
        />
        <div className="flex items-center gap-2 px-2 pt-0.5 pb-2">
          {recording ? (
            <span role="status" className="flex items-center gap-2 ps-2 text-xs font-medium text-red-ink">
              <span aria-hidden className="ember-core size-2 rounded-full bg-red" />
              Listening
              <span className="font-mono tabular text-ink-3">{formatRecSeconds(dictation.seconds)}</span>
              <button
                type="button"
                aria-label="Cancel dictation"
                onClick={dictation.cancel}
                className="flex size-6 items-center justify-center rounded-full text-ink-3 hover:bg-sunk hover:text-ink"
              >
                <X aria-hidden className="size-3.5" />
              </button>
            </span>
          ) : transcribing ? (
            <span role="status" className="flex items-center gap-2 ps-2 text-xs font-medium text-ink-2">
              <Loader2 aria-hidden className="size-3.5 animate-spin" />
              Transcribing
            </span>
          ) : dictation.state.kind === "err" ? (
            <span role="alert" className="ps-2 text-xs text-red-ink">
              {dictation.state.message}
            </span>
          ) : (
            footer
          )}
          <button
            type="button"
            aria-label={recording ? "Stop and transcribe" : "Dictate your answer"}
            aria-pressed={recording}
            disabled={disabled || transcribing}
            onClick={() => (recording ? dictation.finish() : void dictation.start())}
            className={`ms-auto flex size-9 shrink-0 items-center justify-center rounded-full transition-colors disabled:text-ink-3 ${
              recording ? "bg-red-soft text-red-ink hover:bg-red-soft/70" : "text-ink-2 hover:bg-sunk hover:text-ink"
            }`}
          >
            {recording ? <Square aria-hidden className="size-3.5 fill-current" /> : <Mic aria-hidden className="size-4" />}
          </button>
          <button
            type="submit"
            aria-label="Send"
            disabled={disabled || !hasDraft || recording || transcribing}
            className="flex size-9 shrink-0 items-center justify-center rounded-full bg-green text-on-green transition-colors hover:bg-green-hover disabled:bg-sunk disabled:text-ink-3"
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
