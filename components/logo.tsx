// The Keyhunt logo: the key with a house in its bow, and the wordmark.
// Colors come from the app tokens, so the logo follows the theme.
const KEY = "m98.6 33.4c32.6 0 59.5 23.9 64.4 55.5h88.5c7.3 0 13.2 5.4 13.2 12.3 0 7-5.6 12.1-13.3 12.1h-1v18c0 3.3-2 5.4-5.3 5.4h-10.8c-3.4 0-5.5-2.2-5.5-5.4v-18h-8.8v18c0 3.4-2.1 5.4-5.5 5.4h-11.5c-3.5 0-5.6-2.1-5.6-5.5v-17.9h-35.4c-6.7 29-32.2 50.4-62.9 50.4-36 0-65.1-29-65.1-65.1 0-35.7 28.7-65.2 64.6-65.2z";
const HOUSE = "m93.9 54.2c2.9-2.1 5.8-2.2 8.8-0.1l32.5 25.8c2.4 1.8 3.3 3.3 3.3 5.8v39.2c0 5.4-3.8 9.7-8.9 9.7h-19v-28.2c0-6.6-5.5-11.9-12.2-11.9s-12.4 5.5-12.4 11.9v28.2h-17c-5.7 0-10.4-4.2-10.4-9.6v-39.3c0-2.7 0.9-4.4 3.2-6.2l32.1-25.3z";
const WORD = [
  "m293.9 53.7h16.9q0.6 0 0.6 0.6v32.5l30.5-32.6q0.5-0.5 1.3-0.5h20.1v1.7l-34.3 37.1c9 13 22.2 27.5 35.4 41.2v1.4h-21.2c-12.3-10.3-23.8-23.4-31.8-35v34.5q0 0.5-0.5 0.5h-17q-0.6 0-0.6-0.6v-80.2q0-0.6 0.6-0.6z",
  "m417.3 110.1h-41.2c0.9 6.5 6.7 11.3 13 11.3 4.6 0 8.6-2.3 11.8-5.7l14.3 4.7q0.8 0.3 0.3 1.5c-5.1 9.2-14.8 14.7-26.3 14.7-17.9 0-30.2-13.2-30.2-30.6 0-17.5 12.5-31.2 29.8-31.2 16.7 0 28.6 12.8 28.6 30.4l-0.1 4.9zm-40.9-11.7h24.4c-1.4-5.7-5.8-9.3-12-9.3s-10.7 3.5-12.4 9.3z",
  "m415.4 75.8h15.9q1.2 0 1.7 1.3l13.2 34.9q0.5 1.4 1 0l11.6-34.9q0.4-1.3 1.7-1.3h15.9q1.5 0 0.9 1.6l-25 69.7c-3.8 10.8-10.5 15.4-21.9 15.4-3.2 0-6.4-0.2-9.1-1q-1.3-0.4-1.3-1.6v-12.8q0-1.4 1.4-0.9c1.8 0.6 3.5 0.8 5.1 0.8 5.6 0 8.8-4.5 10.9-11.7l-22.8-57.9q-0.6-1.6 0.8-1.6z",
  "m481.4 52.7h14.6q1.4 0 1.4 1.4v27.1c4.1-4.2 9.2-6.4 15-6.4 13.8 0 23.7 10.9 23.7 25v34.1q0 1.3-1.4 1.3h-14.4q-1.4 0-1.4-1.3v-32.2c0-6.9-3.9-11-9.9-11-6.3 0-11.6 5-11.6 11.5v31.6q0 1.4-1.4 1.4h-14.6q-1.5 0-1.5-1.4v-79.6q0-1.5 1.5-1.5z",
  "m544 75.8h14.5q1.5 0 1.5 1.5v33.2c0 6 4.5 10.1 10.8 10.1 5.6 0 11-4.6 11-9.6v-33.7q0-1.5 1.5-1.5h13.8q1.5 0 1.5 1.5v56.5q0 1.4-1.4 1.4h-13.1q-1.2 0-1.4-1.3l-0.5-4.3c-4.7 4.3-10.2 6.9-16.8 6.9-13 0-22.9-10-22.9-24.2v-35q0-1.5 1.5-1.5z",
  "m608.2 75.8h13q1.3 0 1.6 1.3l0.6 4c4.1-4.1 9.5-6.4 15.3-6.4 13.7 0 23.2 11.1 23.2 25.1v34q0 1.4-1.4 1.4h-14q-1.4 0-1.4-1.4v-32.1c0-6.9-4-11-10.1-11-6.4 0-11.2 4.9-11.2 11.3v31.8q0 1.4-1.4 1.4h-14.2q-1.5 0-1.5-1.4v-56.5q0-1.5 1.5-1.5z",
  "m672.7 57.6h14.4q1.4 0 1.4 1.4v16.8h12.2q1.3 0 1.3 1.3v12.3q0 1.2-1.2 1.2h-12.3v23c0 4.6 2.5 7.1 6.7 7.1 1.8 0 3.4-0.4 5-1q1.7-0.7 1.7 1v12.2q0 1.2-1.3 1.7c-3.1 1.3-6.3 1.9-9.8 1.9-12.1 0-19.6-6.8-19.6-18.9v-27h-6.9q-1.2 0-1.2-1.2v-12.1q0-1.5 1.4-1.5h6.7v-16.8q0-1.4 1.5-1.4z",
];

function Key({ light, stacked, className }: { light: boolean; stacked: boolean; className: string }) {
  return (
    <svg aria-hidden viewBox={stacked ? "30 30 238 136" : "33 33 232 131"} className={`logo-key overflow-visible ${className}`}>
      <path fill="currentColor" d={KEY} />
      <path className="logo-house" fill={light ? "var(--green)" : "var(--amber-soft)"} d={HOUSE} />
    </svg>
  );
}

function Word({ light, tight, className }: { light: boolean; tight: boolean; className: string }) {
  // Side by side, the box is cropped so the capitals sit centered on the key and a little larger than the original lockup.
  // White on the cream ground would vanish, so there it gets a green outline drawn behind the fill.
  return (
    <svg aria-hidden viewBox={tight ? "290 50 415 115" : "289 34.7 417 119.4"} className={`logo-word overflow-visible ${className}`}>
      <g fill="#fff" stroke={light ? "none" : "var(--green)"} strokeWidth={10} strokeLinejoin="round" paintOrder="stroke">
        {WORD.map((d, i) => (
          <path key={d.slice(0, 12)} d={d} fillRule="evenodd" className="logo-letter" style={{ "--i": i } as React.CSSProperties} />
        ))}
      </g>
    </svg>
  );
}

// stacked puts the key above the word, for the big title; otherwise they sit side by side.
export function Logo({ light = false, stacked = false, size }: { light?: boolean; stacked?: boolean; size: string }) {
  return (
    <span role="img" aria-label="Keyhunt" className={`inline-flex items-center ${light ? "text-on-green" : "text-green"} ${stacked ? "logo-stacked flex-col gap-2" : "gap-2"}`}>
      <Key light={light} stacked={stacked} className={stacked ? "h-20" : size} />
      <Word light={light} tight={stacked} className={stacked ? "h-11" : size} />
    </span>
  );
}
