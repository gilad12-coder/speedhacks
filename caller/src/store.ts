import { existsSync, mkdirSync, readFileSync, readdirSync, renameSync, unlinkSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
import type { AgentRun } from '../../lib/types.js';
import type { DialCall } from './dial.js';
import type { RunInput } from './schema.js';
import type { Verification } from './verify.js';

export interface Attempt {
  listingId: string; key: string; phase: 'queued' | 'placing' | 'waiting' | 'extracting' | 'done' | 'attention';
  startedAt?: string; terminalAt?: string; dialCallId?: string; raw?: DialCall;
  verification?: Verification; error?: string;
}
export interface RunRecord {
  id: string; inputHash: string; input: RunInput; mode: 'live';
  phase: 'queued' | 'running' | 'done' | 'attention'; run: AgentRun; attempts: Attempt[]; issues: string[];
}
export const hash = (value: string): string => createHash('sha256').update(value).digest('hex');
export class FileStore {
  constructor(readonly dir: string) { mkdirSync(dir, { recursive: true, mode: 0o700 }); }
  private path(id: string): string {
    if (!/^[a-f0-9]{24}$/.test(id)) throw new Error('Invalid run ID');
    return join(this.dir, `${id}.json`);
  }
  get(id: string): RunRecord | undefined {
    const path = this.path(id); return existsSync(path) ? JSON.parse(readFileSync(path, 'utf8')) as RunRecord : undefined;
  }
  save(record: RunRecord): void { this.atomic(this.path(record.id), record); }
  all(): RunRecord[] {
    return readdirSync(this.dir).filter(f => /^[a-f0-9]{24}\.json$/.test(f)).map(f => this.get(f.slice(0, -5))!);
  }
  private atomic(path: string, value: unknown): void {
    const temp = `${path}.${process.pid}.tmp`;
    writeFileSync(temp, JSON.stringify(value, null, 2), { mode: 0o600 }); renameSync(temp, path);
  }
  isBlocked(phone: string): boolean {
    const path = join(this.dir, 'do-not-call.json');
    return existsSync(path) && (JSON.parse(readFileSync(path, 'utf8')) as string[]).includes(phone);
  }
  block(phone: string): void {
    const path = join(this.dir, 'do-not-call.json');
    const previous: string[] = existsSync(path) ? JSON.parse(readFileSync(path, 'utf8')) : [];
    this.atomic(path, [...new Set([...previous, phone])]);
  }
  acquireWorker(): (() => void) | undefined {
    const path = join(this.dir, 'worker.lock');
    if (existsSync(path)) {
      let owner: number;
      try { owner = Number(readFileSync(path, 'utf8')); } catch { return undefined; }
      if (!Number.isInteger(owner) || owner <= 0) throw new Error('Invalid worker lock; inspect the data directory');
      try { process.kill(owner, 0); return undefined; }
      catch (error) { if ((error as NodeJS.ErrnoException).code !== 'ESRCH') return undefined; }
      unlinkSync(path);
    }
    try { writeFileSync(path, String(process.pid), { flag: 'wx', mode: 0o600 }); }
    catch (error) { if ((error as NodeJS.ErrnoException).code === 'EEXIST') return undefined; throw error; }
    return () => unlinkSync(path);
  }
}
