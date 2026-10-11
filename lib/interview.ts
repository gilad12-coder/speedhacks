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
// A short interview: past this many answers only the finish tool is offered.
export const MAX_ANSWERS = 6;

const choiceSchema = z.object({
  label: z.string().trim().min(1).max(60),
  description: z.string().trim().max(120).optional(),
});

const askSchema = z.object({
  message: z.string().trim().min(1).max(600),
  choices: z.array(choiceSchema).max(6).default([]),
});

const featureList = z.array(z.string()).default([]).transform((list) => [...new Set(list)].filter((f) => FEATURE_LABELS.includes(f)));

const finishSchema = z.object({
  message: z.string().trim().min(1).max(600),
  mustHaves: featureList,
  niceToHaves: featureList,
  dealBreakers: featureList,
  wishes: z.array(z.string().trim().min(1).max(140)).max(10).default([]),
});

const askTool = {
  type: "function",
  function: {
    name: "ask",
    description: "Ask the person one question. Offer exactly as many choices as the real answers to it: 2 for yes/no, up to 6 when there are more. Send no choices for an open question. They can always type their own.",
    parameters: {
      type: "object",
      properties: {
        message: { type: "string", description: "A short acknowledgement of their last answer, if any, then one question. Plain text, no markdown." },
        choices: {
          type: "array",
          maxItems: 6,
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
};

const finishTool = {
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
};

export interface InterviewContext {
  me: Housemate;
  groupSize: number;
}

export function systemPrompt({ me, groupSize }: InterviewContext, mustFinish: boolean): string {
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

  const unasked = FEATURE_LABELS.filter((f) => ![...me.mustHaves, ...me.niceToHaves, ...me.dealBreakers].includes(f));

  return `You are Keyhunt's interviewer. Keyhunt finds rentals in the United States and phones landlords to check them. Everything below is already known, from their form${earlier.length ? " and an earlier interview" : ""}. Never ask about any of it again, not even to confirm:
${known.map((k) => `- ${k}`).join("\n")}${earlier.length ? `\n- Already said: ${earlier.join("; ")}` : ""}

Your job is a short, friendly interview, 3 to 5 questions, about only what Keyhunt doesn't know yet. Pick the questions that would change which places fit them most, and skip the rest:
${unasked.length ? `- These fixed features, as need / nice to have / rule out / don't mind: ${unasked.join(", ")}. Group several into one question.\n` : ""}- Their life at home: working from home, pets, guests, noise, light.
${solo ? "- Whether they want a whole place, or a room in a shared place." : "- Living with the others: shared spaces, bedroom sizes, chores and guests."}
- Anything else they care about. Let them lead.

Rules:
- Call a tool on every turn: "ask" for one question at a time, "finish" when done. Plain-text replies never reach the person, and options always go in "choices", never in the message.
- Exactly one question per message, never two joined with "and" or "also".
- If they answer something else or skip a question, take that as their answer and move on; never repeat a question.
- Use what they already told you, in the form and in this conversation. Never ask something they have answered, and build on their earlier picks instead of starting a topic over.
- Keep each message under 40 words. Plain text, no markdown, no lists.
- Fit the choices to the question: as many as its real answers, 2 to 6, each distinct, with no filler or "Other" (they can always type). No choices for an open question. A typed answer is just as good.
- The interview always ends with "finish". Call it when they say they're done, or once you have covered the list.
- Before finishing on your own, ask one last "Anything else?" with a "That's everything" choice.
- In "finish", map answers to the fixed features exactly as named, and put everything else in "wishes".
- Never invent a preference they didn't state.${mustFinish ? '\n\nThe interview is over. Call "finish" now with everything you learned; do not ask anything else.' : ""}`;
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

type ModelMessage = { content?: string | null; tool_calls?: { function?: { name?: string; arguments?: string } }[] };

async function callModel(messages: object[], tools: object[]): Promise<ModelMessage | undefined> {
  const key = process.env.OPENROUTER_API_KEY;
  if (!key) throw new InterviewError("The interview isn't set up yet: OPENROUTER_API_KEY is missing.");

  let res: Response;
  try {
    // tool_choice stays "auto": the provider behind this model rejects a forced tool call.
    res = await fetch("https://openrouter.ai/api/v1/chat/completions", {
      method: "POST",
      headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json", "X-Title": "Keyhunt" },
      body: JSON.stringify({ model: MODEL, messages, tools, tool_choice: "auto", max_tokens: 1200 }),
      signal: AbortSignal.timeout(45_000),
    });
  } catch {
    throw new InterviewError("The interviewer took too long to answer.");
  }
  if (!res.ok) {
    console.error("interview model call failed", res.status, (await res.text()).slice(0, 300));
    throw new InterviewError("The interviewer isn't answering right now.");
  }
  const body = (await res.json()) as { choices?: { message?: ModelMessage }[] };
  return body.choices?.[0]?.message;
}

// wrapUp: the person asked to stop. Either way, past MAX_ANSWERS only "finish" is on offer.
export async function nextAgentStep(ctx: InterviewContext, history: InterviewMessage[], wrapUp = false): Promise<AgentStep> {
  const mustFinish = wrapUp || history.filter((m) => m.role === "user").length >= MAX_ANSWERS;
  const messages = [
    { role: "system", content: systemPrompt(ctx, mustFinish) },
    // The model needs a user turn to start from; the person never sees this one.
    ...(history[0]?.role === "user" ? [] : [{ role: "user", content: "Hi, I'm ready." }]),
    // Earlier questions go back as real ask calls: replayed as plain text, the model copies
    // that format and starts writing "Choices: ..." into its message instead of calling the tool.
    ...history.flatMap((m, i) =>
      m.role === "user"
        ? [{ role: "user", content: m.text }]
        : [
            {
              role: "assistant",
              content: "",
              tool_calls: [{ id: `ask_${i}`, type: "function", function: { name: "ask", arguments: JSON.stringify({ message: m.text, choices: m.choices ?? [] }) } }],
            },
            { role: "tool", tool_call_id: `ask_${i}`, content: "Shown to the person." },
          ],
    ),
    ...(wrapUp ? [{ role: "user", content: "That's all I want to say. Please wrap up." }] : []),
  ];

  // Every turn must be a tool call (the model can't be forced into one), so a plain-text reply
  // goes back to it with a nudge to resend it through the tool.
  const tools = mustFinish ? [finishTool] : [askTool, finishTool];
  const toolNames = mustFinish ? '"finish"' : '"ask" or "finish"';
  for (let attempt = 0; attempt < 3; attempt++) {
    const message = await callModel(messages, tools);
    const call = message?.tool_calls?.[0]?.function;
    if (call?.name) {
      const step = parseToolCall(call.name, call.arguments ?? "{}");
      if (!mustFinish || step.kind === "finish") return step;
    }
    messages.push(
      { role: "assistant", content: message?.content?.trim() || "(no tool call)" },
      { role: "user", content: `That didn't reach me. Send it again as a ${toolNames} tool call, with any options in "choices", never in the message text.` },
    );
  }
  throw new InterviewError("The interviewer couldn't send its question. Try again.");
}
