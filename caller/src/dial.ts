import { z } from 'zod';
import type { Call, TranscriptLine } from '../../lib/types.js';

const turnSchema = z.object({ speaker: z.string(), text: z.string(), startMs: z.number().nonnegative().optional(), endMs: z.number().nonnegative().optional() }).passthrough();
export const dialCallSchema = z.object({
  id: z.string(), status: z.union([z.string(), z.object({ state: z.string().optional(), terminationType: z.string().nullable().optional(), label: z.string().optional() }).passthrough()]),
  duration: z.number().nonnegative().nullable().optional(), transcript: z.string().nullable().optional(),
  transcriptTurns: z.array(turnSchema).nullable().optional(), createdAt: z.string().optional(), failureReason: z.string().nullable().optional()
}).passthrough();
export type DialCall = z.infer<typeof dialCallSchema>;
export interface DialProvider {
  place(to: string, instruction: string, idempotencyKey: string): Promise<DialCall>;
  get(id: string): Promise<DialCall>;
}
export function terminal(call: DialCall): boolean {
  const state = typeof call.status === 'string' ? call.status : call.status.state;
  return ['terminated', 'completed', 'failed', 'canceled', 'cancelled', 'no-answer', 'busy', 'ended'].includes((state ?? '').toLowerCase());
}
export function statusLabel(call: DialCall): string {
  return typeof call.status === 'string' ? call.status : [call.status.state, call.status.terminationType, call.status.label, call.failureReason].filter(Boolean).join(' ');
}
export function normalizeCall(raw: DialCall, listingId: string, fallbackStartedAt: string): Call {
  const transcript: TranscriptLine[] = (raw.transcriptTurns ?? []).flatMap(turn => {
    // Missing offsets are NOT replaced with fabricated timestamps. Flat text stays in the private raw record.
    if (!['agent', 'user', 'contact'].includes(turn.speaker) || turn.startMs === undefined || !turn.text.trim()) return [];
    return [{ t: turn.startMs / 1000, speaker: turn.speaker === 'agent' ? 'agent' as const : 'contact' as const, text: turn.text }];
  });
  const label = statusLabel(raw).toLowerCase().replace(/[_-]/g, ' ');
  const outcome = /voicemail|answering machine/.test(label) ? 'voicemail'
    : /no answer|busy|not answered|noanswer/.test(label) ? 'no_answer'
    : transcript.some(t => t.speaker === 'contact') ? 'answered' : 'failed';
  return { id: `call-${raw.id}`, listingId, dialCallId: raw.id, startedAt: raw.createdAt ?? fallbackStartedAt,
    durationSec: raw.duration ?? 0, outcome, audioUrl: null, transcript };
}
export class DialClient implements DialProvider {
  constructor(private apiKey: string, private fromNumber: string, private durationSeconds = 180, private request: typeof fetch = fetch) {
    if (!apiKey || !fromNumber) throw new Error('Set DIAL_API_KEY and DIAL_NUMBER');
  }
  private async send(path: string, init?: RequestInit): Promise<DialCall> {
    const response = await this.request(`https://api.getdial.ai/api/v1${path}`, {
      ...init, signal: AbortSignal.timeout(30_000),
      headers: { authorization: `Bearer ${this.apiKey}`, 'content-type': 'application/json', ...init?.headers }
    });
    if (!response.ok) throw new Error(`Dial HTTP ${response.status}; call state is saved. Do not redial with a new attempt key.`);
    const body = await response.json() as { call: unknown };
    return dialCallSchema.parse(body.call);
  }
  place(to: string, instruction: string, idempotencyKey: string): Promise<DialCall> {
    return this.send('/calls', { method: 'POST', headers: { 'Idempotency-Key': idempotencyKey }, body: JSON.stringify({
      to, fromNumber: this.fromNumber, outboundInstruction: instruction, language: 'en-US', maxCallDurationSeconds: this.durationSeconds
    }) });
  }
  get(id: string): Promise<DialCall> { return this.send(`/calls/${encodeURIComponent(id)}`); }
}
