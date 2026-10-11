"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Map, Marker, type MapRef } from "@vis.gl/react-maplibre";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import {
  CalendarCheck, Crosshair, ExternalLink, House, List, Maximize2, Minimize2, Minus, Navigation, Phone, Plus, Sparkles, X,
} from "lucide-react";
import type { WorkspaceListing } from "@/lib/workspace";
import { STATUS } from "./listing-card";

// MapLibre 6 runs its tile worker from a separate file; point it at the bundled copy.
maplibregl.setWorkerUrl(new URL("maplibre-gl/dist/maplibre-gl-worker.mjs", import.meta.url).toString());

// Ported from the NYC field guide map: same CARTO Positron tiles, controls, markers and docked place panel.
const MAP_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    "carto-positron": {
      type: "raster",
      tiles: ["a", "b", "c", "d"].map((s) => `https://${s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png?key=cb1_2o7w_1_0c05f842e505d039d00aa039`),
      tileSize: 256,
      maxzoom: 20,
      attribution: "© OpenStreetMap contributors © CARTO",
    },
  },
  layers: [{ id: "carto-positron", type: "raster", source: "carto-positron" }],
};

const FIT = { padding: 78, maxZoom: 14, essential: true } as const;
const RULED_OUT = new Set(["filtered", "not_viable"]);

type Located = WorkspaceListing & { lat: number; lng: number };
const isLocated = (l: WorkspaceListing): l is Located => typeof l.lat === "number" && typeof l.lng === "number";

// Marker colour is rent against the household's budget, the field guide's price bands.
function priceKey(price: number | null, budget: number) {
  if (price === null) return "mid";
  const r = price / budget;
  return r <= 0.75 ? "light" : r <= 0.9 ? "mid" : r <= 1 ? "high" : "splurge";
}

const usd = (n: number | null) => (n === null ? "Rent unknown" : `$${n.toLocaleString()}`);
const when = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

export default function ListingsMap({ listings, budget }: { listings: WorkspaceListing[]; budget: number }) {
  const mapRef = useRef<MapRef | null>(null);
  const [ready, setReady] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const located = useMemo(() => listings.filter(isLocated), [listings]);
  // Auto-refresh hands us new arrays every few seconds; only refit when the set of pins changes.
  const pinKey = located.map((l) => l.id).sort().join("|");
  const selected = located.find((l) => l.id === selectedId) ?? null;

  function fitAll(duration = 500) {
    const map = mapRef.current?.getMap();
    if (!map || located.length === 0) return;
    const bounds = new maplibregl.LngLatBounds();
    located.forEach((l) => bounds.extend([l.lng, l.lat]));
    map.fitBounds(bounds, { ...FIT, duration });
  }

  useEffect(() => {
    if (ready) fitAll(550);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, pinKey]);

  useEffect(() => {
    if (ready) requestAnimationFrame(() => mapRef.current?.getMap().resize());
  }, [fullscreen, ready]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      if (selectedId) setSelectedId(null);
      else setFullscreen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectedId]);

  function select(listing: Located) {
    const map = mapRef.current?.getMap();
    // Keep the pin clear of the panel docked on the map's left edge.
    map?.flyTo({ center: [listing.lng, listing.lat], zoom: Math.max(map.getZoom(), 14), offset: [186, 0], duration: 500, essential: true });
    setSelectedId(listing.id);
  }

  if (located.length === 0) {
    return (
      <p className="rounded-2xl border border-line bg-surface p-8 text-center text-ink-2">
        None of these listings have a location yet.
      </p>
    );
  }

  return (
    <div className="kh-map">
      <div className={`map-card ${fullscreen ? "is-fullscreen" : ""}`}>
        <div className="map-surface">
          <div className="maplibre-map-shell">
            <div className="map-control-cluster" aria-label="Map controls">
              <div className="map-zoom-controls">
                <button type="button" className="map-control-button" onClick={() => mapRef.current?.getMap().zoomIn({ duration: 260 })} aria-label="Zoom in">
                  <Plus aria-hidden className="size-[18px]" strokeWidth={2.5} />
                </button>
                <button type="button" className="map-control-button" onClick={() => mapRef.current?.getMap().zoomOut({ duration: 260 })} aria-label="Zoom out">
                  <Minus aria-hidden className="size-[18px]" strokeWidth={2.5} />
                </button>
              </div>
              <button type="button" className="map-control-button map-control-recenter" onClick={() => fitAll()} aria-label="Show all listings" title="Show all listings">
                <Crosshair aria-hidden className="size-[18px]" />
              </button>
            </div>
            <div className="maplibre-map-host" aria-label="Map of your listings" aria-busy={!ready}>
              <Map
                ref={mapRef}
                mapLib={maplibregl}
                initialViewState={{ longitude: located[0].lng, latitude: located[0].lat, zoom: 12 }}
                mapStyle={MAP_STYLE}
                attributionControl={false}
                onLoad={() => setReady(true)}
                onClick={() => setSelectedId(null)}
                style={{ width: "100%", height: "100%" }}
              >
                {located.map((l) => (
                  <Marker
                    key={l.id}
                    longitude={l.lng}
                    latitude={l.lat}
                    anchor="center"
                    style={{ zIndex: l.id === selectedId ? 2 : 1 }}
                    onClick={(event) => {
                      event.originalEvent.stopPropagation();
                      select(l);
                    }}
                  >
                    <button
                      type="button"
                      className={`maplibre-place-marker price-${priceKey(l.price, budget)} ${l.interested ? "is-visited" : ""} ${RULED_OUT.has(l.status) && !l.interested ? "is-skipped" : ""} ${l.id === selectedId ? "is-selected" : ""}`}
                      aria-label={`${l.title}, ${usd(l.price)}, ${STATUS[l.status]?.label ?? ""}`}
                    >
                      <House aria-hidden className="size-4" strokeWidth={2.25} />
                    </button>
                  </Marker>
                ))}
              </Map>
            </div>
          </div>
          {selected && <PlacePanel listing={selected} onClose={() => setSelectedId(null)} />}
          <div className="map-legend" aria-hidden>
            <span><i style={{ background: "var(--mint)" }} />Well under budget</span>
            <span><i style={{ background: "var(--gold)" }} />Near the top</span>
            <span><i style={{ background: "var(--coral)" }} />Over</span>
          </div>
          {!selected && (
            <a className="map-attribution" href="https://carto.com/attributions" target="_blank" rel="noreferrer">
              © OpenStreetMap contributors · © CARTO
            </a>
          )}
          <button
            type="button"
            className="map-control-button map-control-fullscreen"
            onClick={() => setFullscreen((f) => !f)}
            aria-label={fullscreen ? "Close fullscreen map" : "Open map fullscreen"}
            aria-pressed={fullscreen}
          >
            {fullscreen ? <Minimize2 aria-hidden className="size-[18px]" /> : <Maximize2 aria-hidden className="size-[18px]" />}
          </button>
        </div>
      </div>
      {located.length < listings.length && (
        <p className="mt-3 text-sm text-ink-2">{listings.length - located.length === 1 ? "1 listing has" : `${listings.length - located.length} listings have`} no location yet, so {listings.length - located.length === 1 ? "it's" : "they're"} only in the list.</p>
      )}
    </div>
  );
}

function PlacePanel({ listing, onClose }: { listing: Located; onClose: () => void }) {
  const status = STATUS[listing.status] ?? STATUS.candidate;
  const where = listing.address ?? listing.neighborhood;
  const directions = `https://www.google.com/maps/search/?api=1&query=${listing.lat},${listing.lng}`;
  return (
    <section key={listing.id} className="gmaps-card" aria-label={`${listing.title} details`}>
      <button type="button" className="gmaps-close" onClick={onClose} aria-label="Close listing details">
        <X aria-hidden className="size-[18px]" strokeWidth={2.5} />
      </button>
      <div className="gmaps-scroll">
        <header className="gmaps-header">
          <h2 className="gmaps-name">{listing.title}</h2>
          <div className="gmaps-rating">
            <span className="gmaps-score">{usd(listing.price)}{listing.price !== null && <small>/mo</small>}</span>
            <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${status.tone}`}>{status.label}</span>
          </div>
          <div className="gmaps-meta">
            <span>{listing.beds ?? "?"} bd · {listing.baths ?? "?"} ba</span>
            {listing.sqft && <><span className="gmaps-dot">·</span><span>{listing.sqft.toLocaleString()} ft²</span></>}
            {where && <><span className="gmaps-dot">·</span><span>{where}</span></>}
          </div>
        </header>

        <div className="gmaps-actions">
          <a className="gmaps-action gmaps-action--primary" href={listing.url} target="_blank" rel="noopener noreferrer">
            <span className="gmaps-action-ic"><ExternalLink aria-hidden className="size-[17px]" /></span>
            Listing
          </a>
          <a className="gmaps-action" href={directions} target="_blank" rel="noopener noreferrer">
            <span className="gmaps-action-ic"><Navigation aria-hidden className="size-[17px]" /></span>
            Directions
          </a>
          <a className="gmaps-action" href={`?view=list#${listing.id}`}>
            <span className="gmaps-action-ic"><List aria-hidden className="size-[17px]" /></span>
            In the list
          </a>
        </div>

        <div className="gmaps-details">
          {listing.nextStep && (
            <div className="gmaps-row">
              <span className="gmaps-row-ic"><Sparkles aria-hidden className="size-4" /></span>
              <p><strong>{listing.nextStep.label}.</strong> {listing.nextStep.why}</p>
            </div>
          )}
          {listing.viewing && (
            <div className="gmaps-row">
              <span className="gmaps-row-ic"><CalendarCheck aria-hidden className="size-4" /></span>
              <p>Viewing <strong>{when(listing.viewing.start)}</strong></p>
            </div>
          )}
          {listing.call?.summary && (
            <div className="gmaps-row">
              <span className="gmaps-row-ic"><Phone aria-hidden className="size-4" /></span>
              <p>{listing.call.summary}</p>
            </div>
          )}
          {listing.notes.slice(-3).map((note, i) => (
            <div key={i} className="gmaps-row">
              <span className="gmaps-row-ic"><House aria-hidden className="size-4" /></span>
              <p>{note}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
