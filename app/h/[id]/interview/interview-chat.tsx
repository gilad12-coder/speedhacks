"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import { ArrowRight, RotateCcw } from "lucide-react";
import { interviewTurn } from "@/app/actions";
import { AgentText, ThinkingIndicator, UserBubble } from "@/components/agent/bubbles";
import { Composer } from "@/components/agent/composer";
import { QuestionChoices } from "@/components/agent/question-choices";
import { AgentThread } from "@/components/agent/thread";
import type { InterviewMessage } from "@/lib/interview";

export function InterviewChat({
  householdId,
  initial,
  initialDone,
  locked,
}: {
  householdId: string;
  initial: InterviewMessage[];
  initialDone: boolean;
  locked: boolean;
}) {
  const [messages, setMessages] = useState(initial);
  const [done, setDone] = useState(initialDone);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [pending, startTransition] = useTransition();
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const started = useRef(false);

  const run = (answer: string | null, restart = false) => {
    setError(null);
    if (answer) setMessages((m) => [...m, { role: "user", text: answer }]);
    if (restart) setMessages([]);
    startTransition(async () => {
      const turn = await interviewTurn(householdId, answer, restart);
      setMessages(turn.messages);
      setDone(turn.done);
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
  const choices = !done && !pending && last?.role === "agent" ? (last.choices ?? []) : [];
  const send = (text: string) => {
    if (!text.trim() || pending) return;
    setDraft("");
    run(text.trim());
  };

  return (
    <div className="mt-6 flex min-h-0 flex-1 flex-col">
      <AgentThread className="pe-2 pb-2">
        {messages.map((m, i) => (m.role === "user" ? <UserBubble key={i} text={m.text} /> : <AgentText key={i} text={m.text} />))}
        {pending && <ThinkingIndicator />}
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
          <a href={`/h/${householdId}`} className="inline-flex h-12 items-center gap-2 rounded-lg bg-green px-5 font-medium text-on-green hover:bg-green-hover">
            See your household
            <ArrowRight aria-hidden className="size-4" />
          </a>
          <button
            type="button"
            onClick={() => run(null, true)}
            disabled={pending}
            className="inline-flex h-12 items-center gap-2 rounded-lg px-4 font-medium text-ink-2 hover:bg-sunk"
          >
            <RotateCcw aria-hidden className="size-4" />
            Start the interview over
          </button>
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
          />
          <p className="shrink-0 pt-2 text-xs text-ink-3">
            Say &ldquo;that&rsquo;s all&rdquo; whenever you&rsquo;re done and Keyhunt will save what it learned.
          </p>
        </>
      )}
    </div>
  );
}
