"use client";

import { Bike, Bus, Car, Check, Footprints, Scooter, Ship, TrainFront, TrainFrontTunnel, TramFront, type LucideIcon } from "lucide-react";
import { COMMUTE_MODES } from "@/lib/features";

const ICONS: Record<string, LucideIcon> = {
  walk: Footprints,
  bike: Bike,
  scooter: Scooter,
  drive: Car,
  caltrain: TrainFront,
  metro: TrainFrontTunnel,
  bus: Bus,
  tram: TramFront,
  ferry: Ship,
};

// Pick every way you'd get there; Keyhunt counts a place as close if any of them is fast enough.
export function CommuteModes({ defaultValue, invalid }: { defaultValue: string[]; invalid?: boolean }) {
  return (
    <div role="group" aria-label="How you get there" className="grid grid-cols-3 gap-2">
      {COMMUTE_MODES.map((m, i) => {
        const Icon = ICONS[m.value];
        return (
          <label key={m.value} className="relative">
            <input
              type="checkbox"
              name="commuteModes"
              value={m.value}
              defaultChecked={defaultValue.includes(m.value)}
              data-field={i === 0 ? "commuteModes" : undefined}
              aria-invalid={invalid || undefined}
              className="peer sr-only"
            />
            <span className="flex h-12 cursor-pointer items-center gap-2.5 rounded-xl border border-line bg-surface px-3.5 text-[15px] font-medium text-ink-2 transition-colors peer-checked:border-green peer-checked:bg-green-soft peer-checked:text-green-ink peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-green peer-aria-invalid:border-red-ink hover:border-line-strong [&_.tick]:opacity-0 peer-checked:[&_.tick]:opacity-100">
              <Icon aria-hidden className="size-[18px] shrink-0" strokeWidth={1.75} />
              <span className="min-w-0 flex-1 truncate">{m.label}</span>
              <Check aria-hidden className="tick size-4 shrink-0 transition-opacity" strokeWidth={2.5} />
            </span>
          </label>
        );
      })}
    </div>
  );
}
