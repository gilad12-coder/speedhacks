export interface Interval {
  start: number; // epoch ms
  end: number;
}

const MINUTE = 60_000;
const TOUR_MIN = 45;

// A landlord offering a 30-minute window gets a 30-minute tour, never one that overruns it.
export function tourDurationMs(window: Interval): number {
  return Math.min(TOUR_MIN * MINUTE, window.end - window.start);
}

/**
 * First start inside the offered window where everyone is free for the whole tour.
 * Starts are aligned to the step so proposals land on round times.
 */
export function firstFreeSlot(
  window: Interval,
  busy: Interval[],
  { stepMin = 15, notBefore = Date.now() } = {},
): Interval | null {
  const step = stepMin * MINUTE;
  const duration = tourDurationMs(window);
  let start = Math.ceil(Math.max(window.start, notBefore) / step) * step;
  for (; start + duration <= window.end; start += step) {
    const end = start + duration;
    if (!busy.some((b) => b.start < end && b.end > start)) return { start, end };
  }
  return null;
}
