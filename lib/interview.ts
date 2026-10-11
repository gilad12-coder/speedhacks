import { z } from "zod";
import { commuteModeLabel, FEATURE_LABELS } from "./features";
import type { Housemate } from "./types";

export interface InterviewChoice {
  label: string;
  description?: string;
}

export interface InterviewMessage {
  role: "agent" | "user";
  text: string;
  choices?: InterviewChoice[];
}

export interface InterviewResult {
  mustHaves: string[];
  niceToHaves: string[];
  dealBreakers: string[];
  wishes: string[];
}

export type AgentStep =
  | { kind: "ask"; text: string; choices: InterviewChoice[] }
  | ({ kind: "finish"; text: string } & InterviewResult);

export class InterviewError extends Error {}

const MODEL = process.env.INTERVIEW_MODEL ?? "anthropic/claude-sonnet-5.5";
// Past this many answers the agent is told to wrap up, so the interview can't run on forever.
const MAX_ANSWERS = 10;

const choiceSchema = z.object({
  label: z.string().trim().min(1).max(60),
  description: z.string().trim().max(120).optional(),
});

const askSchema = z.object({
  message: z.string().trim().min(1).max(600),
  choices: z.array(choiceSchema).max(4).default([]),
});

const featureList = z.array(z.string()).default([]).transform((list) => [...new Set(list)].filter((f) => FEATURE_LABELS.includes(f)));

const finishSchema = z.object({
  message: z.string().trim().min(1).max(600),
  mustHaves: featureList,
  niceToHaves: featureList,
  dealBreakers: featureList,
  wishes: z.array(z.string().trim().min(1).max(140)).max(10).default([]),
});

const tools = [
  {
    type: "function",
    function: {
      name: "ask",
      description: "Ask the person one question. Offer 2–4 short choices when the answer is likely one of a few; they can always type their own.",
      parameters: {
        type: "object",
        properties: {
          message: { type: "string", description: "A short acknowledgement of their last answer, if any, then one question. Plain text, no markdown." },
          choices: {
            type: "array",
            maxItems: 4,
            items: {
              type: "object",
              properties: {
                label: { type: "string", description: "1–5 words" },
                description: { type: "string", description: "Optional, one short line" },
              },
              required: ["label"],
            },
          },
        },
        required: ["message"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "finish",
      description: "End the interview and save what you learned.",
      parameters: {
        type: "object",
        properties: {
          message: { type: "string", description: "A one or two sentence wrap-up for the person. Plain text." },
          mustHaves: { type: "array", items: { type: "string", enum: FEATURE_LABELS }, description: "Fixed features they need" },
          niceToHaves: { type: "array", items: { type: "string", enum: FEATURE_LABELS } },
          dealBreakers: { type: "array", items: { type: "string", enum: FEATURE_LABELS }, description: "Features that rule a place out for them" },
          wishes: {
            type: "array",
            items: { type: "string" },
            description: "Everything else that matters to them, each a short phrase a listing or landlord could be checked against, e.g. \"Quiet street\", \"Bedroom gets morning light\".",
          },
        },
        required: ["message", "mustHaves", "niceToHaves", "dealBreakers", "wishes"],
      },
    },
  },
];

export interface InterviewContext {
  me: Housemate;
  groupSize: number;
}

export function systemPrompt({ me, groupSize }: InterviewContext, answers: number): string {
  const solo = groupSize === 1;
  const known = [
    `Name: ${me.name}`,
    solo ? "Searching alone." : `Searching with ${groupSize - 1} housemate${groupSize > 2 ? "s" : ""}; each does their own interview.`,
    `Wants to live in: ${me.location || "not given"}`,
    `Rent: up to $${me.maxBudgetUsd}/month${solo ? "" : " for their share"}`,
    `Move-in: between ${me.moveInFrom} and ${me.moveInTo}`,
    `Commute: to ${me.commute.destination}, by ${me.commute.modes.map(commuteModeLabel).join(" or ")}, at most ${me.commute.maxMinutes} min`,
  ];
  const earlier = [...me.mustHaves.map((f) => `needs ${f}`), ...me.niceToHaves.map((f) => `would like ${f}`), ...me.dealBreakers.map((f) => `rules out ${f}`), ...me.wishes];

  return `You are Keyhunt's interviewer. Keyhunt finds rentals in the United States and phones landlords to check them. The person already filled in a form with these hard filters, so never ask about them again:
${known.map((k) => `- ${k}`).join("\n")}
${earlier.length ? `\nFrom an earlier interview they said: ${earlier.join("; ")}. Confirm or update these rather than starting over.\n` : ""}
Your job is to learn everything else that makes a place right or wrong for them, in a short, friendly conversation.

Cover, in an order that feels natural:
- These fixed features, as need / nice to have / rule out / don't mind: ${FEATURE_LABELS.join(", ")}.
- Their life at home: working from home, pets, cooking, guests, noise, sleep schedule, light.
- The building and area: floor, elevator, accessibility, safety, nearby shops, parks or nightlife.
${solo ? "- Whether they want a whole place, or a room in a shared place." : "- Living with the others: shared spaces, bedroom sizes, how chores and guests should work."}
- Anything else they care about. Let them lead; they may want things no form would ask.

Rules:
- Call a tool on every turn: "ask" for one question at a time, "finish" when done.
- Keep each message under 40 words. Plain text, no markdown, no lists.
- Offer choices when they fit, but treat a typed answer as just as good.
- If they say they're done, or you have covered the list, call "finish".
- In "finish", map answers to the fixed features exactly as named, and put everything else in "wishes".
- Never invent a preference they didn't state.${answers >= MAX_ANSWERS ? '\n\nYou have asked enough. Call "finish" now.' : ""}`;
}

export function parseToolCall(name: string, rawArgs: string): AgentStep {
  let args: unknown;
  try {
    args = JSON.parse(rawArgs || "{}");
  } catch {
    throw new InterviewError("The interviewer sent a reply Keyhunt couldn't read.");
  }
  if (name === "ask") {
    const parsed = askSchema.safeParse(args);
    if (!parsed.success) throw new InterviewError("The interviewer sent a question Keyhunt couldn't read.");
    return { kind: "ask", text: parsed.data.message, choices: parsed.data.choices };
  }
  if (name === "finish") {
    const parsed = finishSchema.safeParse(args);
    if (!parsed.success) throw new InterviewError("The interviewer's summary was incomplete.");
    const { message, mustHaves, dealBreakers } = parsed.data;
    // A feature can only sit in one list; the stronger answer wins.
    const niceToHaves = parsed.data.niceToHaves.filter((f) => !mustHaves.includes(f) && !dealBreakers.includes(f));
    return { kind: "finish", text: message, mustHaves, niceToHaves, dealBreakers: dealBreakers.filter((f) => !mustHaves.includes(f)), wishes: parsed.data.wishes };
  }
  throw new InterviewError("The interviewer called an unknown tool.");
}

export async function nextAgentStep(ctx: InterviewContext, history: InterviewMessage[]): Promise<AgentStep> {
  const key = process.env.OPENROUTER_API_KEY;
  if (!key) throw new InterviewError("The interview isn't set up yet: OPENROUTER_API_KEY is missing.");

  const answers = history.filter((m) => m.role === "user").length;
  const messages = [
    { role: "system", content: systemPrompt(ctx, answers) },
    // The model needs a user turn to start from; the person never sees this one.
    ...(history[0]?.role === "user" ? [] : [{ role: "user", content: "Hi, I'm ready." }]),
    ...history.map((m) => ({
      role: m.role === "agent" ? "assistant" : "user",
      content: m.choices?.length ? `${m.text}\nChoices: ${m.choices.map((c) => c.label).join(" / ")}` : m.text,
    })),
  ];

  let res: Response;
  try {
    res = await fetch("https://openrouter.ai/api/v1/chat/completions", {
      method: "POST",
      headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json", "X-Title": "Keyhunt" },
      body: JSON.stringify({ model: MODEL, messages, tools, tool_choice: "required", max_tokens: 1200 }),
      signal: AbortSignal.timeout(45_000),
    });
  } catch {
    throw new InterviewError("The interviewer took too long to answer.");
  }
  if (!res.ok) {
    console.error("interview model call failed", res.status, (await res.text()).slice(0, 300));
    throw new InterviewError("The interviewer isn't answering right now.");
  }
  const body = (await res.json()) as {
    choices?: { message?: { tool_calls?: { function?: { name?: string; arguments?: string } }[] } }[];
  };
  const call = body.choices?.[0]?.message?.tool_calls?.[0]?.function;
  if (!call?.name) throw new InterviewError("The interviewer sent an empty reply.");
  return parseToolCall(call.name, call.arguments ?? "{}");
}
