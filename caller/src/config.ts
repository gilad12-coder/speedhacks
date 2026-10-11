import 'dotenv/config';
import { z } from 'zod';

const envSchema = z.object({
  DIAL_API_KEY: z.string().default(''), DIAL_NUMBER: z.string().default(''),
  EXTRACTION_PROVIDER: z.enum(['auto', 'openai', 'anthropic']).default('auto'),
  OPENAI_API_KEY: z.string().default(''), OPENAI_MODEL: z.string().default('gpt-4.1-mini'),
  ANTHROPIC_API_KEY: z.string().default(''), ANTHROPIC_MODEL: z.string().default('claude-sonnet-5-5'),
  LIVE_CALLS_ENABLED: z.enum(['true', 'false']).default('false').transform(v => v === 'true'),
  DIAL_ALLOWED_NUMBERS: z.string().default('').transform(v => v.split(',').map(n => n.trim()).filter(Boolean)),
  MAX_CALLS_PER_RUN: z.coerce.number().int().min(1).max(20).default(3),
  MAX_CALLS_PER_NUMBER_PER_DAY: z.coerce.number().int().min(1).max(5).default(1),
  CALL_DURATION_SECONDS: z.coerce.number().int().min(60).max(300).default(180),
  CALL_TIMEOUT_SECONDS: z.coerce.number().int().min(60).max(1200).default(420),
  TRANSCRIPT_GRACE_SECONDS: z.coerce.number().int().min(10).max(300).default(60),
  CALLER_TIMEZONE: z.string().default('America/Los_Angeles').refine(v => { try { new Intl.DateTimeFormat('en', { timeZone: v }); return true; } catch { return false; } }, 'Invalid timezone'),
  CALLER_DATA_DIR: z.string().default('./data'), CALLER_API_TOKEN: z.string().default(''),
  PORT: z.coerce.number().int().min(1).max(65535).default(8787), HOST: z.string().default('127.0.0.1')
});
export type Config = z.infer<typeof envSchema>;
export function loadConfig(env: NodeJS.ProcessEnv = process.env): Config { return envSchema.parse(env); }
