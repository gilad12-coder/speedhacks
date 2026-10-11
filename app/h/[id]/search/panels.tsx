"use client";

import { useActionState } from "react";
import { Plus, SlidersHorizontal } from "lucide-react";
import { Button } from "@/components/shell";
import type { Workspace } from "@/lib/workspace";
import { addListing, refineSearch, type ActionState } from "./actions";

const input = "h-10 w-full rounded-md border border-line-strong bg-surface px-3 text-sm";

export function RefineSearch({ householdId, criteria, running }: { householdId: string; criteria: Workspace["search"]["criteria"]; running: boolean }) {
  const [state, action, pending] = useActionState<ActionState, FormData>(refineSearch.bind(null, householdId), {});
  return (
    <details className="rounded-2xl border border-line bg-surface p-5">
      <summary className="flex cursor-pointer list-none items-center gap-2 font-semibold">
        <SlidersHorizontal aria-hidden className="size-4" />Refine the search
      </summary>
      <p className="mt-1 text-sm text-ink-2">Search again with different neighborhoods or limits. Places you&apos;ve called, emailed or starred keep their progress.</p>
      <form action={action} className="mt-4 grid grid-cols-2 gap-3">
        <label className="col-span-2 text-xs font-medium text-ink-2">Neighborhoods <span className="font-normal text-ink-3">(comma separated)</span>
          <input name="neighborhoods" defaultValue={criteria.neighborhoods.join(", ")} placeholder="Mission, Noe Valley" className={`mt-1 ${input}`} />
        </label>
        <label className="text-xs font-medium text-ink-2">Max total rent ($/mo)
          <input name="max_price" type="number" min="1" required defaultValue={criteria.max_price} className={`mt-1 ${input}`} />
        </label>
        <label className="text-xs font-medium text-ink-2">Bedrooms (min)
          <input name="min_beds" type="number" min="0" required defaultValue={criteria.min_beds} className={`mt-1 ${input}`} />
        </label>
        <label className="col-span-2 text-xs font-medium text-ink-2">Must-haves
          <input name="must_haves" defaultValue={criteria.must_haves.join(", ")} placeholder="laundry, parking" className={`mt-1 ${input}`} />
        </label>
        <div className="col-span-2 flex items-center gap-3">
          <Button type="submit" disabled={pending || running}>Search again</Button>
          {running && <span className="text-sm text-ink-2">Wait for the current search to finish.</span>}
          {state.error && <span className="text-sm text-red-ink">{state.error}</span>}
        </div>
      </form>
    </details>
  );
}

export function AddListing({ householdId }: { householdId: string }) {
  const [state, action, pending] = useActionState<ActionState, FormData>(addListing.bind(null, householdId), {});
  return (
    <details className="rounded-2xl border border-line bg-surface p-5">
      <summary className="flex cursor-pointer list-none items-center gap-2 font-semibold">
        <Plus aria-hidden className="size-4" />Add a listing you found
      </summary>
      <p className="mt-1 text-sm text-ink-2">Zillow, Facebook Marketplace, Craigslist, a building&apos;s own site. Craigslist and most building sites fill in automatically.</p>
      <form action={action} className="mt-4 grid grid-cols-3 gap-3">
        <input name="url" type="url" required placeholder="https://…" aria-label="Listing link" className={`col-span-3 ${input}`} />
        <input name="price" inputMode="numeric" placeholder="Rent $/mo" aria-label="Rent" className={input} />
        <input name="beds" inputMode="numeric" placeholder="Beds" aria-label="Bedrooms" className={input} />
        <input name="baths" inputMode="decimal" placeholder="Baths" aria-label="Bathrooms" className={input} />
        <input name="address" placeholder="Address" aria-label="Address" className={`col-span-3 ${input}`} />
        <input name="contact" placeholder="Contact phone or email, if you have it" aria-label="Contact" className={`col-span-3 ${input}`} />
        <div className="col-span-3 flex items-center gap-3">
          <Button type="submit" disabled={pending}>{pending ? "Adding…" : "Add listing"}</Button>
          {state.error && <span className="text-sm text-red-ink">{state.error}</span>}
          {state.ok && !pending && <span className="text-sm text-green-ink">Added.</span>}
        </div>
      </form>
    </details>
  );
}
