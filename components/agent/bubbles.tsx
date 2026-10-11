"use client";

import { useEffect, useState } from "react";

export function UserBubble({ text }: { text: string }) {
  return (
    <div className="msg-in flex w-full justify-end">
      <div dir="auto" className="max-w-[80%] rounded-[22px] rounded-ee-[4px] bg-green px-4 py-2.5 text-[15px] leading-[1.45] whitespace-pre-wrap text-on-green">
        {text}
      </div>
    </div>
  );
}

// No bubble around the agent's side: its words sit straight on the panel at full width.
export function AgentText({ text }: { text: string }) {
  return (
    <p dir="auto" className="msg-in max-w-[62ch] text-[17px] leading-relaxed whitespace-pre-wrap text-ink">
      {text}
    </p>
  );
}

// Before this, a fast reply never flashes a number; longer waits show the honest count.
const TIMER_REVEAL_MS = 600;

// The "Ember": a breathing core in expanding ripples, shown until the agent's reply lands.
export function ThinkingIndicator() {
  const [start] = useState(() => Date.now());
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setElapsed(Date.now() - start), 100);
    return () => clearInterval(id);
  }, [start]);

  return (
    <div role="status" aria-live="polite" className="msg-in inline-flex items-center gap-2.5 rounded-[22px] rounded-es-[4px] bg-sunk px-4 py-3">
      <span aria-hidden className="relative inline-flex size-4 shrink-0 items-center justify-center">
        <span className="ember-ripple absolute inset-0 rounded-full border border-green" />
        <span className="ember-ripple absolute inset-0 rounded-full border border-green [animation-delay:0.8s]" />
        <span className="ember-core relative size-2 rounded-full bg-green" />
      </span>
      <span className="text-xs font-medium text-green-ink">Thinking</span>
      {elapsed >= TIMER_REVEAL_MS && (
        <span aria-hidden className="font-mono tabular fade-in text-[10px] text-ink-3">
          {(elapsed / 1000).toFixed(1)}s
        </span>
      )}
    </div>
  );
}
