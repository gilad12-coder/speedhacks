import { test } from 'node:test';
import assert from 'node:assert/strict';
import { OpenAIExtractor } from '../src/extract.js';
import { demoFixture } from '../src/demo.js';
import { normalizeCall } from '../src/dial.js';

const fixture = demoFixture();
const args = [normalizeCall(fixture.raw, fixture.input.listings[0].id, fixture.raw.createdAt!),
  fixture.input.listings[0], fixture.input.brief, 'America/Los_Angeles'] as const;
const completed = (text: string) => ({ status: 'completed', output: [{ type: 'message', content: [{ type: 'output_text', text }] }] });

test('OpenAI submits a strict schema and parses an assessment from Responses output', async () => {
  const request: typeof fetch = async (url, options) => {
    assert.equal(url, 'https://api.openai.com/v1/responses');
    const body = JSON.parse(options!.body as string);
    assert.equal(body.store, false);
    assert.equal(body.text.format.type, 'json_schema');
    assert.equal(body.text.format.strict, true);
    const checkObjects = (schema: any): void => {
      if (schema.type === 'object') {
        assert.equal(schema.additionalProperties, false);
        assert.deepEqual([...schema.required].sort(), Object.keys(schema.properties).sort());
        Object.values(schema.properties).forEach(checkObjects);
      }
      if (schema.items) checkObjects(schema.items);
      schema.anyOf?.forEach(checkObjects);
    };
    checkObjects(body.text.format.schema);
    const input = JSON.parse(body.input);
    assert.equal(input.transcript[0].turnIndex, 0);
    assert.equal(input.transcript[0].speaker, 'contact');
    assert.equal(input.brief, undefined);
    return Response.json(completed(JSON.stringify(fixture.assessment)));
  };
  assert.deepEqual(await new OpenAIExtractor('test-key', undefined, request).extract(...args), fixture.assessment);
});

test('OpenAI refuses incomplete, refused, missing or invalid assessments', async () => {
  for (const payload of [
    { ...completed(JSON.stringify(fixture.assessment)), status: 'incomplete' },
    { status: 'completed', output: [{ type: 'message', content: [{ type: 'refusal', refusal: 'No' }] }] },
    { status: 'completed', output: [] },
    completed('{}'), completed('invalid JSON')
  ]) {
    await assert.rejects(new OpenAIExtractor('test-key', undefined, async () => Response.json(payload)).extract(...args));
  }
});

test('OpenAI HTTP errors do not echo provider error bodies or credentials', async () => {
  const extractor = new OpenAIExtractor('private-key', undefined,
    async () => new Response('sensitive provider body', { status: 401 }));
  await assert.rejects(extractor.extract(...args), { message: 'OpenAI extraction HTTP 401; transcript retained for retry' });
});
