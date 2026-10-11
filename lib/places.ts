export interface Place {
  label: string;
  primary: string;
  secondary: string;
  // The city (or neighborhood) the place is in, which is what "where you want to live" keeps.
  area: string | null;
  lat: number;
  lng: number;
}

interface PhotonFeature {
  geometry: { coordinates: [number, number] };
  properties: {
    type?: string;
    name?: string;
    street?: string;
    housenumber?: string;
    district?: string;
    city?: string;
    county?: string;
    state?: string;
    countrycode?: string;
  };
}

// Photon is a free OpenStreetMap geocoder built for type-ahead search.
// Calls go through our server so housemates' IPs and keystrokes stay away from a third party.
const PHOTON = "https://photon.komoot.io";
// Keyhunt is US-only for now. The box (Alaska to Maine, Hawaii up) also catches bits of Canada
// and Mexico, so results are filtered by country code too.
const US_BBOX = "-179.9,18.5,-66.9,71.5";
const HEADERS = { "User-Agent": "Keyhunt (hackathon app)" };

// A city or neighborhood result stands for itself; anything finer (a house, a street) is reduced to its city.
function areaOf(p: PhotonFeature["properties"]): string | null {
  const own = p.type === "city" || p.type === "district" || p.type === "locality";
  const parts = own ? [p.name, p.type === "city" ? null : p.city, p.state] : [p.city ?? p.county, p.state];
  return parts[0] ? parts.filter(Boolean).join(", ") : null;
}

function toPlace(f: PhotonFeature): Place | null {
  const p = f.properties;
  if (p.countrycode !== "US") return null;
  const street = [p.housenumber, p.street].filter(Boolean).join(" ");
  const primary = p.name ?? street;
  if (!primary) return null;
  const secondary = [p.name && street, p.district, p.city, p.state]
    .filter((part): part is string => !!part && part !== primary)
    .filter((part, i, all) => all.indexOf(part) === i)
    .join(", ");
  const [lng, lat] = f.geometry.coordinates;
  return { label: secondary ? `${primary}, ${secondary}` : primary, primary, secondary, area: areaOf(p), lat, lng };
}

async function photon(path: string, params: URLSearchParams): Promise<Place[]> {
  const res = await fetch(`${PHOTON}${path}?${params}`, {
    headers: HEADERS,
    next: { revalidate: 86400 },
    signal: AbortSignal.timeout(4000),
  });
  if (!res.ok) throw new Error(`Photon ${res.status}`);
  const { features } = (await res.json()) as { features: PhotonFeature[] };
  return features.map(toPlace).filter((p): p is Place => !!p);
}

// area: for where someone wants to live. Only places with a city, cities and neighborhoods first,
// and one option per city, since picking any of them keeps the same answer.
export async function searchPlaces(q: string, { area = false } = {}): Promise<Place[]> {
  const found = await photon("/api/", new URLSearchParams({ q, limit: "15", lang: "en", bbox: US_BBOX }));
  const isArea = (p: Place) => !!p.area?.startsWith(p.primary);
  const ranked = area ? found.filter((p) => p.area).sort((a, b) => Number(isArea(b)) - Number(isArea(a))) : found;
  const seen = new Set<string>();
  return ranked
    .filter((p) => {
      const key = area ? p.area! : p.label;
      return !seen.has(key) && !!seen.add(key);
    })
    .slice(0, 6);
}

export async function placeAt(lat: number, lng: number): Promise<Place | null> {
  const found = await photon("/reverse", new URLSearchParams({ lat: String(lat), lon: String(lng), lang: "en" }));
  return found[0] ?? null;
}

// Someone may type a full street address and never pick a suggestion. Keep the city it is in instead.
export async function areaFromText(text: string): Promise<string> {
  if (!/^\d/.test(text)) return text;
  try {
    return (await searchPlaces(text, { area: true }))[0]?.area ?? text;
  } catch {
    return text;
  }
}
