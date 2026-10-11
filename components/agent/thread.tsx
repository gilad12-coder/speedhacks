"use client";

import { useCallback, useEffect, useRef } from "react";

// Within this many px of the bottom still counts as "at the bottom", so
// momentum scrolling and fractional positions don't break follow mode.
const STICKY_BOTTOM_SLACK_PX = 48;

// Follows new messages only while the reader is at the bottom; scrolling up to reread stays put.
export function AgentThread({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);

  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    stickToBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < STICKY_BOTTOM_SLACK_PX;
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (el && stickToBottomRef.current) el.scrollTop = el.scrollHeight;
  }, [children]);

  // Answer choices and a growing composer shrink this box after the effect above ran;
  // re-pin on resize so the question being asked stays in view.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const observer = new ResizeObserver(() => {
      if (stickToBottomRef.current) el.scrollTop = el.scrollHeight;
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <div
      ref={scrollRef}
      onScroll={handleScroll}
      role="log"
      aria-live="polite"
      className={`min-h-0 flex-1 space-y-5 overflow-y-auto overscroll-contain ${className}`}
    >
      {children}
    </div>
  );
}
