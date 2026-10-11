// Each housemate marks every feature as need / nice / no (rules a place out) or leaves it blank.
// `does` finishes "Places that …" in the interview summary.
// Conflicts are a "need" from one housemate against a "no" from another.
export const FEATURES = [
  { label: "Pets allowed", does: "allow pets", compromise: "Look for places that allow pets and have a yard or a separate room, then decide together on the tour." },
  { label: "In-unit laundry", does: "have laundry in the unit", compromise: "Treat it as a nice-to-have and favor places with laundry in the building." },
  { label: "Parking", does: "come with parking", compromise: "Keep places with one spot or easy street parking, and split the spot by need." },
  { label: "Furnished", does: "come furnished", compromise: "Allow both, and prefer places where the landlord can remove furniture before move-in." },
  { label: "Private bathroom per person", does: "have a private bathroom for each person", compromise: "Prefer places with at least one bathroom per two people." },
  { label: "Outdoor space", does: "have outdoor space", compromise: "Treat it as a nice-to-have rather than a requirement." },
  { label: "Smoking allowed", does: "allow smoking", compromise: "Look for places that allow smoking only outdoors." },
] as const;

export type FeatureLabel = (typeof FEATURES)[number]["label"];

export const FEATURE_LABELS: readonly string[] = FEATURES.map((f) => f.label);

export const COMMUTE_MODES = [
  { value: "walk", label: "Walk" },
  { value: "bike", label: "Bike" },
  { value: "scooter", label: "Scooter" },
  { value: "drive", label: "Drive" },
  { value: "caltrain", label: "Train" },
  { value: "metro", label: "Metro or subway" },
  { value: "bus", label: "Bus" },
  { value: "tram", label: "Tram or light rail" },
  { value: "ferry", label: "Ferry" },
] as const;

// Includes the retired combined answer so older rows still read well.
export function commuteModeLabel(mode: string): string {
  if (mode === "transit") return "Bus or metro";
  return COMMUTE_MODES.find((m) => m.value === mode)?.label ?? mode;
}
