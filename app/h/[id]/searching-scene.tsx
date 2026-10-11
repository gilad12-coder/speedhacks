// Shown while a search has nothing to list yet: a lens sweeps a small street and each house's windows
// light as it passes, so the wait reads as Keyhunt looking rather than the page hanging.
const GROUND = 150;
const SWEEP_MS = 4200;
const STREET_W = 720;

// [x, width, height, roof]: flat roofs read as apartments, peaks as houses.
const HOMES: [number, number, number, "flat" | "peak"][] = [
  [20, 74, 92, "flat"],
  [108, 62, 58, "peak"],
  [184, 92, 112, "flat"],
  [290, 66, 64, "peak"],
  [370, 84, 98, "flat"],
  [468, 60, 54, "peak"],
  [542, 96, 120, "flat"],
  [652, 56, 60, "peak"],
];

function windowsFor(x: number, w: number, h: number) {
  const cols = Math.max(1, Math.floor((w - 16) / 22));
  const rows = Math.max(1, Math.floor((h - 34) / 24));
  const gap = (w - cols * 14) / (cols + 1);
  const wins: [number, number][] = [];
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) wins.push([x + gap + c * (14 + gap), GROUND - h + 12 + r * 24]);
  }
  return wins;
}

export function SearchingScene({ status }: { status?: string }) {
  return (
    <div className="searching overflow-hidden rounded-3xl border border-line bg-surface">
      <svg viewBox={`0 0 ${STREET_W} 172`} className="block h-auto w-full" aria-hidden>
        {HOMES.map(([x, w, h, roof], i) => {
          // Each house lights when the lens reaches its middle, on the same loop as the sweep.
          const delay = `${Math.round(((x + w / 2 + 40) / (STREET_W + 80)) * SWEEP_MS) - SWEEP_MS}ms`;
          return (
            <g key={i}>
              {roof === "peak" ? (
                <path
                  d={`M${x - 4},${GROUND - h + 22}L${x + w / 2},${GROUND - h - 6}L${x + w + 4},${GROUND - h + 22}`}
                  fill="var(--sunk)"
                  stroke="var(--line-strong)"
                  strokeWidth="2"
                  strokeLinejoin="round"
                />
              ) : null}
              <rect
                x={x}
                y={GROUND - h + (roof === "peak" ? 20 : 0)}
                width={w}
                height={h - (roof === "peak" ? 20 : 0)}
                rx="3"
                fill={i % 2 ? "var(--green-soft)" : "var(--sunk)"}
                stroke="var(--line-strong)"
                strokeWidth="2"
              />
              {windowsFor(x, w, h - (roof === "peak" ? 20 : 0)).map(([wx, wy], j) => (
                <g key={j}>
                  <rect x={wx} y={wy} width="14" height="12" rx="1.5" fill="var(--line)" />
                  <rect
                    x={wx}
                    y={wy}
                    width="14"
                    height="12"
                    rx="1.5"
                    fill="color-mix(in oklab, var(--amber-soft) 55%, #f2bf5e)"
                    stroke="color-mix(in oklab, var(--amber-ink) 45%, transparent)"
                    className="searching-lit"
                    style={{ animationDelay: delay }}
                  />
                </g>
              ))}
            </g>
          );
        })}
        <path d={`M0,${GROUND + 1}H${STREET_W}`} stroke="var(--line-strong)" strokeWidth="2" />
        <g className="searching-lens">
          <circle cx="0" cy="92" r="30" fill="color-mix(in oklab, var(--surface) 55%, transparent)" stroke="var(--green)" strokeWidth="5" />
          <path d="M21,113L42,136" stroke="var(--green)" strokeWidth="8" strokeLinecap="round" />
        </g>
      </svg>
      <div className="flex items-center gap-3 border-t border-line px-6 py-4">
        <span aria-hidden className="searching-pulse size-2 shrink-0 rounded-full bg-green" />
        <p role="status" aria-live="polite" className="text-sm text-ink-2">
          {status ?? "Finding listings that fit your brief. Places appear here as they're found."}
        </p>
      </div>
    </div>
  );
}
