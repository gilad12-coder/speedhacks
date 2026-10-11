import { loadConfig } from './config.js';
import { DialClient } from './dial.js';
import { ClaudeExtractor, OpenAIExtractor } from './extract.js';
import { CallerEngine } from './engine.js';
import { FileStore } from './store.js';

export function liveRuntime() {
  const config = loadConfig();
  const provider = config.EXTRACTION_PROVIDER === 'auto'
    ? (config.OPENAI_API_KEY ? 'openai' : config.ANTHROPIC_API_KEY ? 'anthropic' : null)
    : config.EXTRACTION_PROVIDER;
  if (!provider) throw new Error('Set OPENAI_API_KEY or ANTHROPIC_API_KEY in caller/.env before live calls');
  const extractor = provider === 'openai'
    ? new OpenAIExtractor(config.OPENAI_API_KEY, config.OPENAI_MODEL)
    : new ClaudeExtractor(config.ANTHROPIC_API_KEY, config.ANTHROPIC_MODEL);
  const engine = new CallerEngine(new FileStore(config.CALLER_DATA_DIR),
    new DialClient(config.DIAL_API_KEY, config.DIAL_NUMBER, config.CALL_DURATION_SECONDS),
    extractor, config);
  return { config, engine };
}
