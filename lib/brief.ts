import { FEATURES } from "./features";
import type { CommuteMode, Conflict, Housemate, SearchBrief } from "./types";

function joinNames(names: string[]): string {
  if (names.length <= 1) return names.join("");
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

function formatDate(iso: string): string {
  return new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

export function detectConflicts(housemates: Housemate[]): Conflict[] {
  const conflicts: Conflict[] = [];

  for (const feature of FEATURES) {
    const need = housemates.filter((h) => h.mustHaves.includes(feature.label));
    const no = housemates.filter((h) => h.dealBreakers.includes(feature.label));
    if (need.length && no.length) {
      conflicts.push({
        field: "mustHaves",
        housemateIds: [...need, ...no].map((h) => h.id),
        description: `${joinNames(need.map((h) => h.name))} ${need.length > 1 ? "need" : "needs"} “${feature.label}”; ${joinNames(no.map((h) => h.name))} ruled it out.`,
        suggestion: feature.compromise,
      });
    }
  }

  if (housemates.length > 1) {
    const latestFrom = housemates.reduce((a, h) => (h.moveInFrom > a.moveInFrom ? h : a));
    const earliestTo = housemates.reduce((a, h) => (h.moveInTo < a.moveInTo ? h : a));
    if (latestFrom.moveInFrom > earliestTo.moveInTo) {
      conflicts.push({
        field: "moveInFrom",
        housemateIds: [latestFrom.id, earliestTo.id],
        description: `${latestFrom.name} can't move in before ${formatDate(latestFrom.moveInFrom)}, but ${earliestTo.name} needs to be in by ${formatDate(earliestTo.moveInTo)}.`,
        suggestion: `Search for move-in from ${formatDate(latestFrom.moveInFrom)}; ${earliestTo.name} would need a short bridge stay.`,
      });
    }

    const places = preferredLocation(housemates);
    if (places.others.length) {
      conflicts.push({
        field: "location",
        housemateIds: housemates.map((h) => h.id),
        description: `You want to live in different places: ${joinNames([places.main, ...places.others])}.`,
        suggestion: `Search in ${places.main}, where most of you want to be.`,
      });
    }

    const destinations = commuteDestination(housemates);
    if (destinations.others.length) {
      conflicts.push({
        field: "commute",
        housemateIds: housemates.map((h) => h.id),
        description: `You commute to different places: ${joinNames(
          [destinations.main, ...destinations.others].map((d) => d.destination),
        )}.`,
        suggestion: `Search by commute to ${destinations.main.destination}, where most of you are headed.`,
      });
    }
  }

  return conflicts;
}

function normalize(place: string): string {
  return place.trim().toLowerCase().replace(/\s+/g, " ");
}

// Most common answer wins; ties go to whoever joined first. Rows from before the question have no location.
function preferredLocation(housemates: Housemate[]) {
  const groups = new Map<string, string[]>();
  for (const h of housemates) {
    if (!h.location.trim()) continue;
    const key = normalize(h.location);
    groups.set(key, [...(groups.get(key) ?? []), h.location.trim()]);
  }
  const ranked = [...groups.values()].sort((a, b) => b.length - a.length).map((g) => g[0]);
  return { main: ranked[0] ?? "", others: ranked.slice(1) };
}

// Most common destination wins; ties go to whoever joined first.
function commuteDestination(housemates: Housemate[]) {
  const groups = new Map<string, Housemate[]>();
  for (const h of housemates) {
    const key = normalize(h.commute.destination);
    groups.set(key, [...(groups.get(key) ?? []), h]);
  }
  const ranked = [...groups.values()].sort((a, b) => b.length - a.length);
  const pick = (group: Housemate[]) => {
    const counts = new Map<CommuteMode, number>();
    for (const h of group) counts.set(h.commute.mode, (counts.get(h.commute.mode) ?? 0) + 1);
    const mode = [...counts].reduce((best, entry) => (entry[1] > best[1] ? entry : best))[0];
    return {
      destination: group[0].commute.destination.trim(),
      mode,
      modes: [...new Set(group.flatMap((h) => h.commute.modes))],
      maxMinutes: Math.min(...group.map((h) => h.commute.maxMinutes)),
    };
  };
  return { main: pick(ranked[0]), others: ranked.slice(1).map(pick) };
}

export function buildSearchBrief(householdId: string, housemates: Housemate[], occupants = housemates.length): SearchBrief {
  const conflicted = new Set(
    FEATURES.filter(
      (f) => housemates.some((h) => h.mustHaves.includes(f.label)) && housemates.some((h) => h.dealBreakers.includes(f.label)),
    ).map((f) => f.label as string),
  );
  const union = (pick: (h: Housemate) => string[]) => [...new Set(housemates.flatMap(pick))];
  const mustHaves = union((h) => h.mustHaves).filter((f) => !conflicted.has(f));
  const dealBreakers = union((h) => h.dealBreakers).filter((f) => !conflicted.has(f));
  const niceToHaves = union((h) => h.niceToHaves).filter((f) => !mustHaves.includes(f) && !dealBreakers.includes(f));
  const moveInFrom = housemates.map((h) => h.moveInFrom).sort().at(-1)!;
  const moveInTo = housemates.map((h) => h.moveInTo).sort()[0];
  const { main } = commuteDestination(housemates);

  return {
    householdId,
    occupants,
    location: preferredLocation(housemates).main,
    maxTotalRentUsd: housemates.reduce((sum, h) => sum + h.maxBudgetUsd, 0),
    // Disjoint windows are reported as a conflict; the agent still gets a usable range.
    moveInFrom,
    moveInTo: moveInTo < moveInFrom ? moveInFrom : moveInTo,
    commute: main,
    mustHaves,
    dealBreakers,
    niceToHaves,
    householdIncomeBandUsd: {
      min: housemates.reduce((sum, h) => sum + h.incomeBandUsd.min, 0),
      max: housemates.reduce((sum, h) => sum + h.incomeBandUsd.max, 0),
    },
    // A solo search needs no names on its own wishes.
    wishes: housemates.flatMap((h) => h.wishes.map((w) => (housemates.length > 1 ? `${h.name}: ${w}` : w))),
  };
}
