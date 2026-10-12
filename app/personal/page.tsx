import Link from "next/link";
import { headers } from "next/headers";
import { notFound } from "next/navigation";
import { personalMode } from "@/lib/personal-mode";
import { sql } from "@/lib/db";
import { Wordmark } from "@/components/shell";

export default async function PersonalHome() {
  if (!personalMode((await headers()).get("host"))) notFound();
  const searches = await sql<{ id: string; location: string; budget: number; beds: number | null; neighborhoods: string[] }[]>`
    select h.id, m.location, m.max_budget_usd as budget, m.min_bedrooms as beds, m.neighborhoods
    from households h join housemates m on m.household_id = h.id
    where m.google_sub = ${process.env.PERSONAL_ACCOUNT_ID ?? "local:reed"}
    order by h.created_at desc limit 20`;
  const input = "mt-2 w-full rounded-xl border border-black/15 bg-white p-3 text-ink";
  return <main className="mx-auto min-h-dvh max-w-3xl px-6 py-12 text-ink">
    <Link href="/"><Wordmark size="xl" /></Link>
    <h1 className="mt-10 font-display text-4xl font-semibold">Your next place, checked for you.</h1>
    <p className="mt-4 text-lg text-ink-2">Reed’s AI assistant will search, cross-check listing details, and call during office hours. You can follow each call and review tour offers here.</p>
    <form action="/api/auth/personal" method="post" className="mt-8 grid gap-5 rounded-2xl border border-black/10 bg-white/60 p-6 sm:grid-cols-2">
      <label>City<input className={input} name="city" defaultValue="San Francisco, CA" required maxLength={120} /></label>
      <label>Neighborhood<input className={input} name="neighborhood" defaultValue="Civic Center" maxLength={120} /></label>
      <label>Minimum bedrooms<input className={input} name="beds" type="number" defaultValue={2} min={0} max={10} required /></label>
      <label>Monthly rent limit ($)<input className={input} name="budget" type="number" defaultValue={5500} min={300} max={100000} required /></label>
      <p className="text-sm text-ink-2 sm:col-span-2">Move-in date is flexible. No extra requirements. Calls identify themselves as Reed’s AI assistant. Calendar connection is optional; a tour is only booked when your availability is known.</p>
      <button className="rounded-xl bg-green px-5 py-4 font-semibold sm:col-span-2">Find my place</button>
    </form>
    {searches.length > 0 && <section className="mt-10"><h2 className="font-display text-2xl font-semibold">Your searches</h2><div className="mt-4 grid gap-3">{searches.map((s) => <form key={s.id} method="post" action="/api/auth/personal" className="flex items-center justify-between gap-4 rounded-xl border border-black/10 p-4">
      <input type="hidden" name="search" value={s.id} /><span>{s.neighborhoods.join(", ") || s.location} · {s.beds ?? 0}+ beds · up to ${s.budget.toLocaleString()}</span><button className="rounded-lg bg-green px-4 py-2 font-semibold">Open</button>
    </form>)}</div></section>}
    <p className="mt-10 text-sm text-ink-2">Personal version · saved on this computer. Keep the app running for searches, queued calls, and callback updates.</p>
  </main>;
}
