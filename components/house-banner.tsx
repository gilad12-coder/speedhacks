type Box = [x: number, y: number, w: number, h: number];

type Home = {
  w: number;
  peak: number;
  outline: string;
  shade: string;
  windows: Box[];
  doors: Box[];
  bars: string;
};

// Wide enough that height, not width, sets the scale on desktop screens up to 2560px.
const VIEW_W = 3200;
const VIEW_H = 260;
const GROUND = 236;

const BODIES = ["var(--surface)", "var(--green-soft)", "var(--sunk)", "var(--line)"];
const LEAF = "color-mix(in oklab, var(--green) 62%, var(--on-green-2))";

const pick = <T,>(list: readonly T[], i: number) => list[i % list.length];
const boxes = (list: Box[]) => list.map(([x, y, w, h]) => `M${x},${y}h${w}v${h}h${-w}z`).join("");
const vertical = ([x, y, w, h]: Box) => `M${x + w / 2},${y}v${h}`;
const horizontal = ([x, y, w, h]: Box) => `M${x},${y + h / 2}h${w}`;
const vars = (v: Record<string, string>) => v as React.CSSProperties;
const riseDelay = (x: number, extra = 0) => `${Math.round(Math.max(0, x - 400) * 0.3) + extra}ms`;

// Deterministic 0–99 noise: lit windows look scattered but render the same on every load.
function noise(a: number, b: number) {
  let h = Math.imul(a + 1, 0x9e3779b1) ^ Math.imul(b + 1, 0x85ebca6b);
  h = Math.imul(h ^ (h >>> 15), 0x2c1b3c6d);
  return ((h ^ (h >>> 13)) >>> 0) % 100;
}

// Building types found in most cities, so the street doesn't read as any one place.
const BUILD = {
  apartment(x: number, i: number): Home {
    const cols = pick([4, 5], i);
    const floors = pick([3, 4, 4], i);
    const w = cols * 30 + 16;
    const top = GROUND - 46 - floors * 30;
    const parapet: Box = [x - 3, top - 6, w + 6, 6];
    const stair: Box = [x + w - 40, top - 20, 24, 14];
    const windows: Box[] = [];
    const balconies: Box[] = [];
    for (let f = 0; f < floors; f++) {
      for (let c = 0; c < cols; c++) {
        const win: Box = [x + 13 + c * 30, top + 10 + f * 30, 20, 18];
        windows.push(win);
        if ((c + f) % 2 === 0) balconies.push([win[0] - 3, win[1] + 18, 26, 4]);
      }
    }
    const lobby: Box[] = [
      [x + 13, GROUND - 30, 30, 18],
      [x + w - 43, GROUND - 30, 30, 18],
    ];
    return {
      w,
      peak: top - 20,
      outline: boxes([[x, top, w, GROUND - top], parapet, stair]),
      shade: boxes([parapet, stair, ...balconies, [x + w / 2 - 20, GROUND - 40, 40, 4]]),
      windows: [...windows, ...lobby],
      doors: [[x + w / 2 - 14, GROUND - 36, 28, 36]],
      bars: lobby.map(vertical).join(""),
    };
  },
  gable(x: number, i: number): Home {
    const w = 88;
    const top = GROUND - pick([92, 104, 98], i);
    const roof = `M${x - 5},${top}L${x + w / 2},${top - 30}L${x + w + 5},${top}z`;
    const chimney = i % 2 ? boxes([[x + 60, top - 32, 9, 18]]) : "";
    const windows: Box[] = [
      [x + 14, top + 18, 22, 24],
      [x + 52, top + 18, 22, 24],
      [x + 14, top + 56, 22, 24],
    ];
    return {
      w,
      peak: top - 32,
      outline: boxes([[x, top, w, GROUND - top]]) + roof + chimney,
      shade: roof + chimney + boxes([[x, top, w, 5]]),
      windows,
      doors: [[x + 54, GROUND - 36, 18, 36]],
      bars: windows.map((win) => vertical(win) + horizontal(win)).join(""),
    };
  },
  hip(x: number, i: number): Home {
    const w = 112;
    const top = GROUND - pick([70, 78], i);
    const roof = `M${x - 6},${top}L${x + 22},${top - 24}H${x + w - 22}L${x + w + 6},${top}z`;
    const windows: Box[] = [
      [x + 12, top + 18, 30, 22],
      [x + w - 42, top + 18, 30, 22],
    ];
    return {
      w,
      peak: top - 24,
      outline: boxes([[x, top, w, GROUND - top]]) + roof,
      shade: roof + boxes([[x, top, w, 4]]),
      windows,
      doors: [[x + w / 2 - 9, GROUND - 36, 18, 36]],
      bars: windows.map(vertical).join(""),
    };
  },
  shed(x: number, i: number): Home {
    const w = 84;
    const top = GROUND - pick([100, 110], i);
    const fascia = `M${x - 4},${top - 26}L${x + w + 4},${top - 3}V${top + 3}L${x - 4},${top - 20}z`;
    const tall: Box = [x + 12, top - 4, 16, 58];
    const wide: Box = [x + 38, top + 14, 34, 24];
    return {
      w,
      peak: top - 26,
      outline: `M${x},${GROUND}V${top - 22}L${x + w},${top}V${GROUND}z${fascia}`,
      shade: fascia,
      windows: [tall, wide],
      doors: [[x + 50, GROUND - 36, 18, 36]],
      bars: horizontal(tall) + vertical(wide),
    };
  },
  flat(x: number, i: number): Home {
    const w = 96;
    const top = GROUND - pick([116, 126], i);
    const parapet: Box = [x - 3, top - 6, w + 6, 6];
    const picture: Box = [x + 12, GROUND - 40, 40, 28];
    return {
      w,
      peak: top - 6,
      outline: boxes([[x, top, w, GROUND - top], parapet]),
      shade: boxes([parapet]),
      windows: [[x + 12, top + 16, 72, 20], [x + 12, top + 48, 30, 18], [x + 54, top + 48, 30, 18], picture],
      doors: [[x + 66, GROUND - 38, 18, 38]],
      bars: `M${x + 36},${top + 16}v20M${x + 60},${top + 16}v20${vertical(picture)}`,
    };
  },
  row(x: number, i: number): Home {
    const w = 60;
    const top = GROUND - pick([122, 134, 128], i);
    const cornice: Box = [x - 2, top - 6, w + 4, 6];
    const windows: Box[] = [
      [x + 10, top + 14, 16, 26],
      [x + 34, top + 14, 16, 26],
      [x + 10, top + 50, 16, 26],
      [x + 34, top + 50, 16, 26],
      [x + 34, GROUND - 34, 16, 22],
    ];
    return {
      w,
      peak: top - 6,
      outline: boxes([[x, top, w, GROUND - top], cornice]),
      shade: boxes([cornice, [x, GROUND - 44, w, 3]]),
      windows,
      doors: [[x + 10, GROUND - 38, 18, 38]],
      bars: windows.map(horizontal).join(""),
    };
  },
};

const STREET: (keyof typeof BUILD | "tree")[] = [
  "apartment", "tree", "gable", "gable", "shed", "row", "row", "row", "flat", "hip",
  "tree", "apartment", "flat", "gable", "tree", "row", "row", "shed", "hip",
];
const GAPS = [18, 26, 14, 22, 30, 16];

const homes: (Home & { i: number; x: number; body: string })[] = [];
const trees: { i: number; x: number }[] = [];
for (let i = 0, x = -60; x < VIEW_W + 60; i++) {
  const kind = pick(STREET, i);
  if (kind === "tree") {
    trees.push({ i, x });
    x += 50;
    continue;
  }
  const home = BUILD[kind](x, i);
  homes.push({ ...home, i, x, body: pick(BODIES, i) });
  // Terraced houses share walls; everything else gets a little air.
  x += home.w + (kind === "row" && pick(STREET, i + 1) === "row" ? 0 : pick(GAPS, i));
}

const TOWER_W = [72, 54, 96, 62, 84, 110, 58];
const TOWER_H = [150, 186, 132, 170, 204, 140, 178, 124];
const TOWER_GAP = [16, 34, 10, 24, 42, 14];

const towers: { x: number; peak: number; shape: string; lights: string }[] = [];
for (let i = 0, x = -30; x < VIEW_W + 30; i++) {
  const w = pick(TOWER_W, i);
  const top = GROUND - pick(TOWER_H, i);
  const roof = i % 3 === 0 ? top - 12 : top;
  const parts: Box[] = [[x, top, w, GROUND - top]];
  if (roof < top) parts.push([x + w * 0.2, roof, w * 0.6, 12]);
  const mast = i % 5 === 2;
  if (mast) parts.push([x + w / 2 - 1, roof - 26, 2, 26]);
  const lights: Box[] = [];
  for (let y = top + 12; y < GROUND - 24; y += 16) {
    for (let wx = x + 8; wx + 5 <= x + w - 8; wx += 12) {
      if (noise(i + 400, y * 7 + wx) < 9) lights.push([wx, y, 5, 8]);
    }
  }
  towers.push({ x, peak: mast ? roof - 26 : roof, shape: boxes(parts), lights: boxes(lights) });
  x += w + pick(TOWER_GAP, i);
}

const CLOUDS = [
  { y: 50, scale: 1, dur: 220, delay: -80, rest: 1250 },
  { y: 86, scale: 0.7, dur: 300, delay: -185, rest: 2250 },
];

export function HouseBanner({ className = "border-t-[3px] border-ground" }: { className?: string }) {
  return (
    <div className={`h-[clamp(7rem,19vh,13rem)] shrink-0 overflow-hidden bg-green ${className}`}>
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        preserveAspectRatio="xMidYMax slice"
        className="block h-full w-full"
        aria-hidden
      >
        <circle className="sun" cx="2060" cy="46" r="18" fill="var(--amber-soft)" opacity="0.9" />
        {CLOUDS.map((c, i) => (
          <g
            key={i}
            className="cloud"
            style={vars({ "--dur": `${c.dur}s`, "--delay": `${c.delay}s`, "--rest": `${c.rest}px` })}
          >
            <g transform={`translate(0 ${c.y}) scale(${c.scale})`} fill="var(--surface)" opacity="0.13">
              <ellipse cx="0" cy="0" rx="90" ry="14" />
              <ellipse cx="-30" cy="-10" rx="40" ry="16" />
              <ellipse cx="28" cy="-14" rx="48" ry="20" />
            </g>
          </g>
        ))}
        {towers.map((t, i) => (
          <g
            key={i}
            className="house tower"
            style={vars({ "--rise-delay": riseDelay(t.x, 150), "--rise-from": `${GROUND - t.peak + 40}px` })}
          >
            <path d={t.shape} fill="var(--green-hover)" />
            <path d={t.lights} fill="var(--amber-soft)" opacity="0.45" />
          </g>
        ))}
        {homes.map(({ i, x, body, peak, outline, shade, windows, doors, bars }) => {
          const lit: Box[] = [];
          const glow: Box[] = [];
          const dark: Box[] = [...doors];
          windows.forEach((win, j) => {
            const n = noise(i, j);
            (n < 22 ? lit : n < 30 ? glow : dark).push(win);
          });
          return (
            <g
              key={i}
              className="house"
              style={vars({ "--rise-delay": riseDelay(x), "--rise-from": `${GROUND - peak + 40}px` })}
            >
              <path d={outline} fill={body} />
              <path d={shade} fill="var(--green)" opacity="0.16" />
              <path d={boxes(dark)} fill="var(--green)" opacity="0.85" />
              <path d={boxes(lit)} fill="var(--amber-soft)" />
              {glow.map(([gx, gy, gw, gh], j) => {
                const t = noise(i + 99, j);
                return (
                  <rect
                    key={j}
                    className="window-glow"
                    x={gx}
                    y={gy}
                    width={gw}
                    height={gh}
                    fill="var(--green)"
                    opacity="0.85"
                    style={vars({ "--dur": `${11 + (t % 9)}s`, "--delay": `-${t % 13}s` })}
                  />
                );
              })}
              <path d={bars} fill="none" stroke={body} strokeWidth="2" />
            </g>
          );
        })}
        {trees.map(({ i, x }) => {
          const r = pick([20, 17, 23], i);
          const cx = x + 22;
          const cy = GROUND - 24 - r;
          return (
            <g
              key={i}
              className="house"
              style={vars({ "--rise-delay": riseDelay(x), "--rise-from": `${GROUND - cy + r + 40}px` })}
            >
              <rect x={cx - 2} y={cy} width="4" height={GROUND - cy} fill="var(--green-hover)" />
              <g style={{ fill: LEAF }}>
                <circle cx={cx} cy={cy} r={r} />
                <circle cx={cx - r * 0.7} cy={cy + r * 0.5} r={r * 0.65} />
                <circle cx={cx + r * 0.72} cy={cy + r * 0.45} r={r * 0.7} />
              </g>
            </g>
          );
        })}
        {/* Solid street so buildings stay hidden until they rise past it. */}
        <rect y={GROUND} width={VIEW_W} height={VIEW_H - GROUND} fill="var(--green-hover)" />
        <rect y={GROUND} width={VIEW_W} height={VIEW_H - GROUND} fill="var(--ink)" opacity="0.4" />
      </svg>
    </div>
  );
}
