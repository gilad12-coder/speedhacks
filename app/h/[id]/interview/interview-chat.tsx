"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import {
  ArrowRight,
  Ban,
  Check,
  ChevronLeft,
  ChevronRight,
  Flag,
  MessageSquareQuote,
  Pencil,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import { interviewTurn, type InterviewTurnOptions } from "@/app/actions";
import { AgentText, ThinkingIndicator, UserBubble } from "@/components/agent/bubbles";
import { Composer } from "@/components/agent/composer";
import { QuestionChoices } from "@/components/agent/question-choices";
import { AgentThread } from "@/components/agent/thread";
import type { InterviewMessage, InterviewResult } from "@/lib/interview";

const SUMMARY_ROWS: { key: keyof InterviewResult; label: string; hint: string; icon: LucideIcon; tone: string }[] = [
  { key: "mustHaves", label: "Must have", hint: "Every place Keyhunt shows you will have these.", icon: ShieldCheck, tone: "bg-green-soft text-green-ink" },
  { key: "niceToHaves", label: "Nice to have", hint: "Places with these rank higher.", icon: Sparkles, tone: "bg-amber-soft text-amber-ink" },
  { key: "dealBreakers", label: "Rule out", hint: "Places like this never make the list.", icon: Ban, tone: "bg-red-soft text-red-ink" },
  { key: "wishes", label: "Also looking for", hint: "In your own words, so Keyhunt can weigh them too.", icon: MessageSquareQuote, tone: "bg-sunk text-ink" },
];

// What the finish tool saved, shown once the agent ends the interview: one slide per kind of preference.
function Summary({ result }: { result: InterviewResult }) {
  const rows = SUMMARY_ROWS.filter((r) => result[r.key].length);
  const [index, setIndex] = useState(0);
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);
  if (!rows.length) return null;
  const go = (i: number, focus = false) => {
    const next = (i + rows.length) % rows.length;
    setIndex(next);
    if (focus) tabs.current[next]?.focus();
  };

  return (
    <section aria-label="What Keyhunt will look for" aria-roledescription="carousel" className="msg-in overflow-hidden rounded-2xl border border-line bg-surface">
      <header className="flex items-center gap-3 px-5 pt-4">
        <span className="summary-badge flex size-7 items-center justify-center rounded-full bg-green text-on-green">
          <Check aria-hidden className="size-4" strokeWidth={2.5} />
        </span>
        <h3 className="font-semibold text-ink">What Keyhunt will look for</h3>
        {rows.length > 1 && (
          <div className="ms-auto flex items-center gap-1">
            <button type="button" aria-label="Previous" onClick={() => go(index - 1)} className="flex size-8 items-center justify-center rounded-md text-ink-3 transition-colors hover:bg-sunk hover:text-ink">
              <ChevronLeft aria-hidden className="size-4" />
            </button>
            <button type="button" aria-label="Next" onClick={() => go(index + 1)} className="flex size-8 items-center justify-center rounded-md text-ink-3 transition-colors hover:bg-sunk hover:text-ink">
              <ChevronRight aria-hidden className="size-4" />
            </button>
          </div>
        )}
      </header>

      <div
        role="tablist"
        aria-label="Preferences"
        className="relative mx-5 mt-4 grid rounded-lg bg-sunk p-1"
        style={{ gridTemplateColumns: `repeat(${rows.length}, minmax(0, 1fr))` }}
        onKeyDown={(e) => {
          if (e.key === "ArrowRight") go(index + 1, true);
          else if (e.key === "ArrowLeft") go(index - 1, true);
        }}
      >
        <span
          aria-hidden
          className="summary-indicator absolute inset-y-1 left-1 rounded-md bg-surface shadow-sm"
          style={{ width: `calc((100% - 0.5rem) / ${rows.length})`, transform: `translateX(${index * 100}%)` }}
        />
        {rows.map((r, i) => (
          <button
            key={r.key}
            ref={(el) => {
              tabs.current[i] = el;
            }}
            type="button"
            role="tab"
            id={`summary-tab-${r.key}`}
            aria-selected={i === index}
            aria-controls={`summary-panel-${r.key}`}
            tabIndex={i === index ? 0 : -1}
            onClick={() => go(i)}
            className={`relative z-10 flex h-9 items-center justify-center gap-1.5 truncate rounded-md px-2 text-sm font-medium transition-colors ${
              i === index ? "text-ink" : "text-ink-3 hover:text-ink-2"
            }`}
          >
            {r.label}
            <span className={`rounded-full px-1.5 text-xs tabular-nums ${i === index ? r.tone : "bg-surface/60"}`}>{result[r.key].length}</span>
          </button>
        ))}
      </div>

      <div className="summary-track flex" style={{ transform: `translateX(-${index * 100}%)` }}>
        {rows.map((r, i) => {
          const Icon = r.icon;
          return (
            <div
              key={r.key}
              role="tabpanel"
              id={`summary-panel-${r.key}`}
              aria-labelledby={`summary-tab-${r.key}`}
              aria-hidden={i !== index}
              inert={i !== index}
              className="w-full shrink-0 px-5 pt-5 pb-5"
            >
              <div className="flex items-center gap-3">
                <span className={`flex size-9 shrink-0 items-center justify-center rounded-xl ${r.tone}`}>
                  <Icon aria-hidden className="size-[18px]" />
                </span>
                <p className="text-sm text-ink-2">{r.hint}</p>
              </div>
              <ul key={i === index ? "on" : "off"} className="mt-4 flex flex-wrap gap-2">
                {result[r.key].map((item, n) => (
                  <li
                    key={item}
                    className={`summary-chip rounded-full px-3.5 py-1.5 text-sm font-medium ${r.tone}`}
                    style={{ animationDelay: `${120 + n * 50}ms` }}
                  >
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </div>

      {rows.length > 1 && (
        <div className="flex justify-center gap-1.5 pb-4" aria-hidden>
          {rows.map((r, i) => (
            <span key={r.key} className={`summary-dot h-1.5 rounded-full ${i === index ? "w-5 bg-green" : "w-1.5 bg-line-strong"}`} />
          ))}
        </div>
      )}
    </section>
  );
}

function ActionButton({ label, onClick, children }: { label: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className="flex size-7 items-center justify-center rounded-md text-ink-3 transition-colors hover:bg-sunk hover:text-ink"
    >
      {children}
    </button>
  );
}

// Edit an earlier answer in place; sending it drops everything after and asks again from there.
function EditBox({ initial, onSave, onCancel }: { initial: string; onSave: (text: string) => void; onCancel: () => void }) {
  const [text, setText] = useState(initial);
  return (
    <form
      className="msg-in ms-auto flex w-[80%] flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (text.trim()) onSave(text.trim());
      }}
    >
      <textarea
        autoFocus
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") onCancel();
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            e.currentTarget.form?.requestSubmit();
          }
        }}
        rows={2}
        dir="auto"
        aria-label="Edit your answer"
        className="w-full resize-none rounded-2xl border border-green bg-surface px-4 py-3 text-[15px] leading-5 text-ink outline-none"
      />
      <div className="flex justify-end gap-2">
        <button type="button" onClick={onCancel} className="h-9 rounded-lg px-3 text-sm font-medium text-ink-2 hover:bg-sunk">
          Cancel
        </button>
        <button
          type="submit"
          disabled={!text.trim()}
          className="h-9 rounded-lg bg-green px-4 text-sm font-medium text-on-green hover:bg-green-hover disabled:bg-sunk disabled:text-ink-3"
        >
          Send
        </button>
      </div>
    </form>
  );
}

export function InterviewChat({
  householdId,
  initial,
  initialDone,
  initialResult,
  locked,
}: {
  householdId: string;
  initial: InterviewMessage[];
  initialDone: boolean;
  initialResult: InterviewResult | null;
  locked: boolean;
}) {
  const [messages, setMessages] = useState(initial);
  const [done, setDone] = useState(initialDone);
  const [result, setResult] = useState(initialDone ? initialResult : null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState<number | null>(null);
  const [pending, startTransition] = useTransition();
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const started = useRef(false);

  const run = (answer: string | null, options: InterviewTurnOptions = {}) => {
    setError(null);
    setEditing(null);
    setMessages((m) => {
      const kept = options.restart ? [] : options.rewindTo === undefined ? m : m.slice(0, options.rewindTo);
      return answer ? [...kept, { role: "user", text: answer }] : kept;
    });
    if (options.restart) {
      setDone(false);
      setResult(null);
    }
    startTransition(async () => {
      const turn = await interviewTurn(householdId, answer, options);
      setMessages(turn.messages);
      setDone(turn.done);
      if (turn.result) setResult(turn.result);
      if (turn.error) setError(turn.error);
      else composerRef.current?.focus();
    });
  };

  // A fresh interview, or one whose last answer never got a reply, asks the agent to speak first.
  useEffect(() => {
    if (started.current || locked || initialDone) return;
    started.current = true;
    if (initial.at(-1)?.role !== "agent") run(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const last = messages.at(-1);
  const active = !done && !pending && !locked;
  const choices = active && last?.role === "agent" ? (last.choices ?? []) : [];
  const answered = messages.some((m) => m.role === "user");
  const send = (text: string) => {
    if (!text.trim() || pending) return;
    setDraft("");
    run(text.trim());
  };

  return (
    <div className="mt-8 flex min-h-0 w-full max-w-2xl flex-1 flex-col">
      <AgentThread className="pe-2 pb-2">
        {messages.map((m, i) => {
          if (m.role === "user") {
            if (editing === i) {
              return <EditBox key={i} initial={m.text} onCancel={() => setEditing(null)} onSave={(text) => run(text, { rewindTo: i })} />;
            }
            return (
              <div key={i} className="group flex flex-col items-end gap-1">
                <UserBubble text={m.text} />
                {active && (
                  <div className="opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
                    <ActionButton label="Edit this answer" onClick={() => setEditing(i)}>
                      <Pencil aria-hidden className="size-3.5" />
                    </ActionButton>
                  </div>
                )}
              </div>
            );
          }
          const isLatest = i === messages.length - 1;
          return (
            <div key={i} className="flex flex-col items-start gap-1">
              <AgentText text={m.text} />
              {active && isLatest && (
                <ActionButton label="Ask a different question" onClick={() => run(null, { rewindTo: i })}>
                  <RefreshCw aria-hidden className="size-3.5" />
                </ActionButton>
              )}
            </div>
          );
        })}
        {pending && <ThinkingIndicator />}
        {done && result && <Summary result={result} />}
        {error && (
          <div role="alert" className="msg-in flex items-center gap-3 rounded-xl bg-red-soft px-4 py-3 text-sm text-red-ink">
            <span>{error}</span>
            {!locked && (
              <button type="button" onClick={() => run(null)} className="ms-auto font-medium underline">
                Try again
              </button>
            )}
          </div>
        )}
      </AgentThread>

      {locked ? (
        <p className="shrink-0 border-t border-line pt-4 text-ink-2">The search has started, so your answers are locked.</p>
      ) : done ? (
        <div className="choices-in flex shrink-0 items-center gap-3 border-t border-line pt-4">
          <button
            type="button"
            aria-label="Start the interview over"
            title="Start the interview over"
            onClick={() => run(null, { restart: true })}
            disabled={pending}
            className="flex size-12 items-center justify-center rounded-lg text-ink-2 hover:bg-sunk hover:text-ink disabled:text-ink-3"
          >
            <RotateCcw aria-hidden className="size-5" />
          </button>
          <a
            href={`/h/${householdId}`}
            className="ms-auto inline-flex h-12 items-center gap-2 rounded-lg bg-green px-5 font-medium text-on-green hover:bg-green-hover"
          >
            See your household
            <ArrowRight aria-hidden className="size-4" />
          </a>
        </div>
      ) : (
        <>
          <QuestionChoices options={choices} onSelect={send} disabled={pending} />
          <Composer
            ref={composerRef}
            value={draft}
            onChange={setDraft}
            onSubmit={() => send(draft)}
            disabled={pending}
            placeholder={choices.length ? "Or answer in your own words…" : "Type your answer…"}
            footer={
              answered && (
                <button
                  type="button"
                  onClick={() => run(null, { wrapUp: true })}
                  disabled={pending}
                  className="inline-flex h-8 items-center gap-1.5 rounded-full px-3 text-xs font-medium text-ink-2 hover:bg-sunk hover:text-ink disabled:text-ink-3"
                >
                  <Flag aria-hidden className="size-3.5" />
                  That&apos;s everything, wrap up
                </button>
              )
            }
          />
        </>
      )}
    </div>
  );
}
