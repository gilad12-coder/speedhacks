import { NextResponse } from "next/server";
import { placeAt, searchPlaces } from "@/lib/places";

// ?q= searches; ?lat=&lng= finds the place at a point, for "Use my location".
export async function GET(req: Request) {
  const url = new URL(req.url);
  const lat = Number(url.searchParams.get("lat"));
  const lng = Number(url.searchParams.get("lng"));
  const q = url.searchParams.get("q")?.trim() ?? "";
  const area = url.searchParams.get("kind") === "area";

  try {
    if (url.searchParams.has("lat")) {
      if (!Number.isFinite(lat) || !Number.isFinite(lng) || Math.abs(lat) > 90 || Math.abs(lng) > 180) {
        return NextResponse.json({ places: [] }, { status: 400 });
      }
      const here = await placeAt(lat, lng);
      return NextResponse.json({ places: here ? [here] : [] });
    }
    if (q.length < 3 || q.length > 120) return NextResponse.json({ places: [] });
    return NextResponse.json({ places: await searchPlaces(q, { area }) });
  } catch {
    return NextResponse.json({ places: [] }, { status: 502 });
  }
}
