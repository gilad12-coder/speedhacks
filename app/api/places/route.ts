import { NextResponse } from "next/server";

export interface Place {
  label: string;
  primary: string;
  secondary: string;
  lat: number;
  lng: number;
}

interface PhotonFeature {
  geometry: { coordinates: [number, number] };
  properties: {
    name?: string;
    street?: string;
    housenumber?: string;
    district?: string;
    city?: string;
    state?: string;
    countrycode?: string;
  };
}

// Photon is a free OpenStreetMap geocoder built for type-ahead search.
// Proxying it keeps housemates' IPs and keystrokes away from a third party.
const PHOTON = "https://photon.komoot.io/api/";
// Keyhunt is US-only for now. The box (Alaska to Maine, Hawaii up) also catches bits of Canada
// and Mexico, so results are filtered by country code too.
const US_BBOX = "-179.9,18.5,-66.9,71.5";
// "area" searches cities and neighborhoods, for where someone wants to live.
const AREA_LAYERS = ["city", "district", "locality", "county"];

export async function GET(req: Request) {
  const url = new URL(req.url);
  const q = url.searchParams.get("q")?.trim() ?? "";
  const area = url.searchParams.get("kind") === "area";
  if (q.length < 3 || q.length > 120) return NextResponse.json({ places: [] });

  try {
    const params = new URLSearchParams({ q, limit: "15", lang: "en", bbox: US_BBOX });
    if (area) for (const layer of AREA_LAYERS) params.append("layer", layer);
    const res = await fetch(`${PHOTON}?${params}`, {
      headers: { "User-Agent": "Keyhunt (hackathon app)" },
      next: { revalidate: 86400 },
      signal: AbortSignal.timeout(4000),
    });
    if (!res.ok) return NextResponse.json({ places: [] }, { status: 502 });
    const { features } = (await res.json()) as { features: PhotonFeature[] };

    const seen = new Set<string>();
    const places: Place[] = [];
    for (const f of features) {
      const p = f.properties;
      if (p.countrycode !== "US") continue;
      const street = [p.housenumber, p.street].filter(Boolean).join(" ");
      const primary = p.name ?? street;
      if (!primary) continue;
      const secondary = [p.name && street, p.district, p.city, p.state]
        .filter((part): part is string => !!part && part !== primary)
        .filter((part, i, all) => all.indexOf(part) === i)
        .join(", ");
      const label = secondary ? `${primary}, ${secondary}` : primary;
      if (seen.has(label)) continue;
      seen.add(label);
      const [lng, lat] = f.geometry.coordinates;
      places.push({ label, primary, secondary, lat, lng });
      if (places.length === 6) break;
    }
    return NextResponse.json({ places });
  } catch {
    return NextResponse.json({ places: [] }, { status: 502 });
  }
}
