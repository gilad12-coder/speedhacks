"use server";

import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { z } from "zod";
import {
  confirmBrief,
  createHousehold,
  findHouseholdByCode,
  findHousemateByAccount,
  getAgentRun,
  getHouseholdState,
  getInterview,
  HouseholdError,
  isMember,
  requestSearch,
  saveInterview,
  upsertHousemate,
} from "@/lib/households";
import { InterviewError, nextAgentStep, type InterviewMessage, type InterviewResult } from "@/lib/interview";
import { areaFromText } from "@/lib/places";
import { intakeSchema } from "@/lib/schemas";
import { getAccount, getHousemateId, setHousemateSession } from "@/lib/session";
import { acceptTour, TourError } from "@/lib/tours";
import { GoogleError } from "@/lib/google";
import { workerRequest } from "@/lib/agent-worker";

export interface FormState {
  error?: string;
  fieldErrors?: Record<string, string>;
}

export async function startHousehold(_: FormState, form: FormData): Promise<FormState> {
  if (!(await getAccount())) return { error: "Sign in with Google before starting a search." };
  const size = z.coerce.number().int().min(1).max(6).safeParse(form.get("who") === "solo" ? 1 : form.get("size"));
  if (!size.success) return { error: "Pick how many of you are moving in, from 2 to 6." };
  const { joinCode } = await createHousehold(size.data);
  redirect(`/join/${joinCode}`);
}

export async function submitIntake(joinCode: string, _: FormState, form: FormData): Promise<FormState> {
  const household = await findHouseholdByCode(joinCode);
  if (!household) return { error: "This invite link doesn't work anymore. Ask for a new one." };

  const parsed = intakeSchema.safeParse({ ...Object.fromEntries(form), commuteModes: form.getAll("commuteModes") });
  if (!parsed.success) {
    const fieldErrors: Record<string, string> = {};
    for (const issue of parsed.error.issues) fieldErrors[String(issue.path[0])] ??= issue.message;
    // Each field shows its own message and the form jumps to that step, so no banner on top.
    return { fieldErrors };
  }

  parsed.data.location = await areaFromText(parsed.data.location);

  const account = await getAccount();
  const existing =
    (await getHousemateId(household.id)) ?? (account && (await findHousemateByAccount(household.id, account.sub)));
  if (!existing && !account) return { error: "Sign in with Google before joining." };

  let housemateId: string;
  try {
    housemateId = await upsertHousemate(household.id, existing, parsed.data, account);
  } catch (error) {
    if (error instanceof HouseholdError) return { error: error.message };
    throw error;
  }
  await setHousemateSession(household.id, housemateId);
  redirect(`/h/${household.id}/interview`);
}

export interface InterviewTurn {
  messages: InterviewMessage[];
  done: boolean;
  // What the finish tool saved, once the interview is done.
  result?: InterviewResult;
  error?: string;
}

export interface InterviewTurnOptions {
  restart?: boolean;
  // The person asked to stop: the agent must call finish now.
  wrapUp?: boolean;
  // Drop the transcript from this index on before answering: an edited answer, or a regenerated question.
  rewindTo?: number;
}

// One turn of the interview: record the answer (if any), then get the agent's next question or its wrap-up.
export async function interviewTurn(householdId: string, answer: string | null, options: InterviewTurnOptions = {}): Promise<InterviewTurn> {
  const { restart = false, wrapUp = false, rewindTo } = options;
  const housemateId = await getHousemateId(householdId);
  const state = await getHouseholdState(householdId);
  const me = state?.household.housemates.find((h) => h.id === housemateId);
  if (!state || !me || !housemateId) return { messages: [], done: false, error: "You're not part of this household." };

  const saved = await getInterview(housemateId);
  if (saved.done && !restart) return { ...saved, error: "This interview is finished. Start it over to change your answers." };
  let messages = restart ? [] : rewindTo === undefined ? saved.messages : saved.messages.slice(0, Math.max(0, rewindTo));
  const text = answer?.trim().slice(0, 1000);
  if (text) messages = [...messages, { role: "user", text }];
  // Nothing new to say and the agent already spoke last: just show where things stand.
  else if (messages.at(-1)?.role === "agent" && !wrapUp) return { ...saved };

  try {
    const step = await nextAgentStep({ me, groupSize: state.household.expectedSize }, messages, wrapUp);
    messages = [...messages, { role: "agent", text: step.text, ...(step.kind === "ask" && step.choices.length && { choices: step.choices }) }];
    if (step.kind === "finish") {
      const { mustHaves, niceToHaves, dealBreakers, wishes } = step;
      await saveInterview(householdId, housemateId, messages, step);
      return { messages, done: true, result: { mustHaves, niceToHaves, dealBreakers, wishes } };
    }
    await saveInterview(householdId, housemateId, messages, null);
    return { messages, done: false };
  } catch (error) {
    if (error instanceof InterviewError || error instanceof HouseholdError) {
      // Keep the answer so a retry picks up where it failed.
      if (text || rewindTo !== undefined) await saveInterview(householdId, housemateId, messages, null).catch(() => {});
      return { messages, done: false, error: error.message };
    }
    throw error;
  }
}

async function requireMember(householdId: string) {
  if (!(await isMember(householdId, await getHousemateId(householdId)))) {
    throw new Error("You're not part of this household.");
  }
}

export async function confirmHouseholdBrief(householdId: string, formData: FormData) {
  await requireMember(householdId);
  await confirmBrief(householdId, String(formData.get("fingerprint") ?? ""));
  revalidatePath(`/h/${householdId}`);
}

export async function startSearch(householdId: string) {
  await requireMember(householdId);
  const state = await getHouseholdState(householdId);
  if (!state || state.household.housemates.length < state.household.expectedSize || !state.household.confirmed) return;
  await requestSearch(householdId);
  revalidatePath(`/h/${householdId}`);
  // Nudge the search engine so sourcing starts now; its worker also polls, so a miss is fine.
  await workerRequest(`/agent/households/${encodeURIComponent(householdId)}/start`, { method: "POST" }).catch(() => null);
  // Onboarding is done: continue in the household's search workspace.
  redirect(`/h/${householdId}/search`);
}

export async function bookTour(householdId: string, listingId: string, start: string, end: string): Promise<FormState> {
  try {
    await requireMember(householdId);
    const [state, run] = await Promise.all([getHouseholdState(householdId), getAgentRun(householdId)]);
    if (!state || !run) return { error: "There's no search to book from yet." };
    await acceptTour(state.household, run, listingId, start, end);
  } catch (error) {
    if (error instanceof TourError) return { error: error.message };
    if (error instanceof GoogleError) return { error: "Google Calendar didn't respond. Try again in a moment." };
    console.error("bookTour failed", error);
    return { error: "Something went wrong booking the tour. Try again in a moment." };
  } finally {
    revalidatePath(`/h/${householdId}`);
  }
  return {};
}

export async function callRental(householdId: string, listingId: string): Promise<FormState> {
  try {
    await requireMember(householdId);
    // The workspace can contain a newly added contact before the next AgentRun snapshot.
    // The worker validates the current listing, phone, allowlist and saved call attempt.
    const response = await workerRequest(`/agent/households/${encodeURIComponent(householdId)}/listings/${encodeURIComponent(listingId)}/call`, { method: "POST" });
    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      return { error: typeof result.detail === "string" ? result.detail : "The saved call could not be started. Check the agent worker." };
    }
    revalidatePath(`/h/${householdId}`);
    revalidatePath(`/h/${householdId}/search`);
    return {};
  } catch {
    return { error: "The calling worker is unavailable or not connected. Your call has not been confirmed." };
  }
}
