import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { expect, it } from 'vitest';

it('stops browser audio capture at exactly two minutes with complete PCM chunks', () => {
  const chunks: { chunk: Float32Array; done: boolean }[] = [];
  let createProcessor: (() => { process: (input: Float32Array[][]) => boolean }) | undefined;
  const code = readFileSync('househunt/web/static/voice-capture.js', 'utf8');
  class AudioWorkletProcessor { port = { postMessage: (data: { chunk: Float32Array; done: boolean }) => chunks.push(data) }; }
  vm.runInNewContext(code, { AudioWorkletProcessor, sampleRate:16000, Float32Array,
    registerProcessor: (_: string, Capture: new () => { process: (input: Float32Array[][]) => boolean }) => { createProcessor = () => new Capture(); } });
  const processor = createProcessor!();
  const block = new Float32Array(128).fill(.1);
  let running = true;
  for (let i = 0; i < 15000; i++) running = processor.process([[block]]);
  expect(running).toBe(false);
  expect(chunks.reduce((n, data) => n + data.chunk.length, 0)).toBe(16000 * 120);
  expect(chunks.at(-1)?.done).toBe(true);
  expect(chunks.filter((data) => data.done)).toHaveLength(1);
});
