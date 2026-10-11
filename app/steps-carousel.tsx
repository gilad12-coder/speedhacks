"use client";

import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

const steps = [
  ["Everyone says what they need", "Budget, commute, move-in dates and deal-breakers, one link per housemate."],
  ["Keyhunt calls the landlords", "It confirms each place is real, available, and right for your group, on the phone."],
  ["You get a short list with proof", "Three to seven places, each check linked to the moment in the call that confirmed it."],
];

const INTERVAL_MS = 6000;

export function StepsCarousel() {
  const [index, setIndex] = useState(0);
  const [dir, setDir] = useState<"forward" | "back">("forward");
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    if (paused || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const id = setTimeout(() => {
      setDir("forward");
      setIndex((i) => (i + 1) % steps.length);
    }, INTERVAL_MS);
    return () => clearTimeout(id);
  }, [index, paused]);

  function go(to: number) {
    setDir(to > index || (index === steps.length - 1 && to === 0) ? "forward" : "back");
    setIndex((to + steps.length) % steps.length);
  }

  const [title, body] = steps[index];

  return (
    <section
      aria-roledescription="carousel"
      aria-label="How Keyhunt works"
      className="mt-12 max-w-[52ch] border-t border-line pt-6"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
    >
      <div className="flex items-center justify-between">
        <div className="flex gap-2" role="group" aria-label="Steps">
          {steps.map(([t], i) => (
            <button
              key={t}
              type="button"
              onClick={() => go(i)}
              aria-label={`Step ${i + 1}: ${t}`}
              aria-current={i === index ? "step" : undefined}
              className={`tabular flex size-8 items-center justify-center rounded-full text-sm font-semibold transition-colors ${
                i === index ? "bg-green text-on-green" : "bg-green-soft text-green-ink hover:bg-sunk"
              }`}
            >
              {i + 1}
            </button>
          ))}
        </div>
        <div className="flex gap-1">
          <button type="button" onClick={() => go(index - 1)} aria-label="Previous step" className="flex size-8 items-center justify-center rounded-lg text-ink-2 hover:bg-sunk">
            <ChevronLeft aria-hidden className="size-5" />
          </button>
          <button type="button" onClick={() => go(index + 1)} aria-label="Next step" className="flex size-8 items-center justify-center rounded-lg text-ink-2 hover:bg-sunk">
            <ChevronRight aria-hidden className="size-5" />
          </button>
        </div>
      </div>
      <div key={index} aria-live={paused ? "polite" : "off"} className={`step-in step-in-${dir} mt-5 min-h-24`}>
        <p className="text-lg font-medium text-ink">{title}</p>
        <p className="mt-1 leading-relaxed text-ink-2">{body}</p>
      </div>
    </section>
  );
}
