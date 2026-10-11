"use server";

import { revalidatePath } from "next/cache";
import { isMember } from "@/lib/households";
import { getHousemateId } from "@/lib/session";
import { workspacePost } from "@/lib/workspace";

export interface ActionState {
  error?: string;
  ok?: boolean;
}

async function member(householdId: string): Promise<string | null> {
  return (await isMember(householdId, await getHousemateId(householdId))) ? null : "You're not part of this household.";
}

async function post(householdId: string, path: string, body: unknown = {}): Promise<ActionState> {
  const denied = await member(householdId);
  if (denied) return { error: denied };
  const result = await workspacePost(householdId, path, body);
  revalidatePath(`/h/${householdId}/search`);
  return result.error ? { error: result.error } : { ok: true };
}

const key = (listingId: string) => encodeURIComponent(listingId);
const text = (form: FormData, name: string) => String(form.get(name) ?? "").trim();
const list = (value: string) => value.split(",").map((s) => s.trim()).filter(Boolean);

export async function saveContact(householdId: string, listingId: string, _: ActionState, form: FormData) {
  const pasted = text(form, "pasted");
  if (!pasted) return { error: "Paste the phone number or email first." };
  return post(householdId, `/listings/${key(listingId)}/contact`, { pasted });
}

export async function markInterested(householdId: string, listingId: string) {
  return post(householdId, `/listings/${key(listingId)}/interested`);
}

export async function logViewing(householdId: string, listingId: string, _: ActionState, form: FormData) {
  const start = text(form, "start");
  if (!start) return { error: "Pick the date and time of the viewing." };
  return post(householdId, `/listings/${key(listingId)}/viewing`, { start });
}

export async function draftEmail(householdId: string, listingId: string) {
  return post(householdId, `/listings/${key(listingId)}/email`);
}

export async function updateEmail(
  householdId: string,
  emailId: number,
  action: "save" | "sent" | "discard",
  fields: { to: string; subject: string; body: string },
) {
  return post(householdId, `/emails/${emailId}`, { action, ...fields });
}

export async function addListing(householdId: string, _: ActionState, form: FormData) {
  const url = text(form, "url");
  if (!/^https?:\/\/\S+\.\S+/.test(url)) return { error: "Paste the full listing link, starting with https://" };
  return post(householdId, "/listings", {
    url, price: text(form, "price"), beds: text(form, "beds"), baths: text(form, "baths"),
    address: text(form, "address"), pasted: text(form, "contact"),
  });
}

export async function refineSearch(householdId: string, _: ActionState, form: FormData) {
  const maxPrice = Number(text(form, "max_price"));
  const minBeds = Number(text(form, "min_beds"));
  if (!(maxPrice > 0) || !(minBeds >= 0)) return { error: "Enter a budget and a bedroom count." };
  return post(householdId, "/criteria", {
    neighborhoods: list(text(form, "neighborhoods")), must_haves: list(text(form, "must_haves")),
    max_price: maxPrice, min_beds: minBeds, rerun: true,
  });
}
