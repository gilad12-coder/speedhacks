"use client";

import dynamic from "next/dynamic";

// MapLibre touches window on import, so the map only ever renders in the browser.
export const MapView = dynamic(() => import("./listings-map"), {
  ssr: false,
  loading: () => <div className="min-h-[640px] animate-pulse rounded-[17px] bg-sunk" />,
});
