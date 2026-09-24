const { callOllama, canUseAI, callAI, getAiConfig } = require('../aiService');

jest.mock('../../models/Setting', () => ({
  findOne: jest.fn(() => Promise.resolve(null))
}));

describe('Ollama AI Provider Integration', () => {
  afterEach(() => {
    delete global.fetch;
  });

  const mockFetchResponse = (body, status = 200) => ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body)
  });

  describe('canUseAI provider selection', () => {
    test('ollama is always considered available (no API key required)', () => {
      expect(canUseAI({ provider: 'ollama' })).toBe(true);
    });

    test('gemini requires an API key', () => {
      expect(canUseAI({ provider: 'gemini' })).toBe(false);
      expect(canUseAI({ provider: 'gemini', geminiKey: 'abc' })).toBe(true);
    });

    test('openai requires an API key', () => {
      expect(canUseAI({ provider: 'openai' })).toBe(false);
      expect(canUseAI({ provider: 'openai', openaiKey: 'sk-abc' })).toBe(true);
    });

    test('unknown provider is not available', () => {
      expect(canUseAI({ provider: 'nope' })).toBe(false);
      expect(canUseAI(null)).toBe(false);
    });
  });

  describe('callOllama successful chat', () => {
    test('sends /api/chat payload with system instruction and parses JSON content', async () => {
      let captured = null;
      global.fetch = async (url, opts) => {
        if (url.endsWith('/api/tags')) {
          return mockFetchResponse({ models: [{ name: 'qwen2.5:1.5b' }] });
        }
        captured = JSON.parse(opts.body);
        // Return content as a JSON string (typical when format=json)
        return mockFetchResponse({
          model: 'qwen2.5:1.5b',
          message: { role: 'assistant', content: JSON.stringify({ summary: 'ok' }) },
          done: true
        });
      };

      const result = await callOllama('help me', 'you are strict', 'http://localhost:11434', 'qwen2.5:1.5b');

      expect(result).toEqual({ summary: 'ok' });
      expect(captured.model).toBe('qwen2.5:1.5b');
      expect(captured.stream).toBe(false);
      expect(captured.format).toBe('json');
      expect(captured.messages[0].role).toBe('system');
      expect(captured.messages[0].content).toBe('you are strict');
      expect(captured.messages[1].role).toBe('user');
      expect(captured.messages[1].content).toBe('help me');
    });

    test('handles object content directly (already parsed)', async () => {
      global.fetch = async (url) => {
        if (url.endsWith('/api/tags')) {
          return mockFetchResponse({ models: [{ name: 'qwen2.5:1.5b' }] });
        }
        return mockFetchResponse({ message: { content: { hello: 'world' } } });
      };

      const result = await callOllama('x', '', 'http://localhost:11434', 'qwen2.5:1.5b');
      expect(result).toEqual({ hello: 'world' });
    });

    test('omits system message when none supplied', async () => {
      let captured = null;
      global.fetch = async (url, opts) => {
        if (url.endsWith('/api/tags')) {
          return mockFetchResponse({ models: [{ name: 'qwen2.5:1.5b' }] });
        }
        captured = JSON.parse(opts.body);
        return mockFetchResponse({ message: { content: '{}' } });
      };

      await callOllama('x', '', 'http://localhost:11434', 'qwen2.5:1.5b');
      expect(captured.messages).toHaveLength(1);
      expect(captured.messages[0].role).toBe('user');
    });
  });

  describe('callOllama error handling', () => {
    test('throws controlled error when Ollama is not running (fetch fails)', async () => {
      global.fetch = async () => {
        throw new Error('connect ECONNREFUSED');
      };

      await expect(
        callOllama('x', '', 'http://localhost:11434', 'qwen2.5:1.5b')
      ).rejects.toThrow('Ollama is not running');
    });

    test('throws controlled error when model is unavailable', async () => {
      global.fetch = async (url) => {
        if (url.endsWith('/api/tags')) {
          return mockFetchResponse({ models: [{ name: 'some-other-model' }] });
        }
        return mockFetchResponse({ message: { content: '{}' } });
      };

      await expect(
        callOllama('x', '', 'http://localhost:11434', 'qwen2.5:1.5b')
      ).rejects.toThrow('Ollama model qwen2.5:1.5b is unavailable');
    });

    test('throws controlled error on invalid JSON without crashing', async () => {
      global.fetch = async (url) => {
        if (url.endsWith('/api/tags')) {
          return mockFetchResponse({ models: [{ name: 'qwen2.5:1.5b' }] });
        }
        return mockFetchResponse({ message: { content: 'not valid json at all' } });
      };

      await expect(
        callOllama('x', '', 'http://localhost:11434', 'qwen2.5:1.5b')
      ).rejects.toThrow('Ollama returned invalid JSON');
    });

    test('throws controlled error on empty response', async () => {
      global.fetch = async (url) => {
        if (url.endsWith('/api/tags')) {
          return mockFetchResponse({ models: [{ name: 'qwen2.5:1.5b' }] });
        }
        return mockFetchResponse({ message: { content: '   ' } });
      };

      await expect(
        callOllama('x', '', 'http://localhost:11434', 'qwen2.5:1.5b')
      ).rejects.toThrow('Ollama returned an empty response');
    });
  });

  describe('callAI dispatcher', () => {
    test('routes to ollama when provider is ollama', async () => {
      global.fetch = async (url) => {
        if (url.endsWith('/api/tags')) {
          return mockFetchResponse({ models: [{ name: 'qwen2.5:1.5b' }] });
        }
        return mockFetchResponse({ message: { content: JSON.stringify({ ok: true }) } });
      };

      const result = await callAI('p', 's', { provider: 'ollama', ollamaBaseUrl: 'http://localhost:11434', model: 'qwen2.5:1.5b' });
      expect(result).toEqual({ ok: true });
    });

    test('throws when no usable provider is configured', async () => {
      await expect(callAI('p', 's', { provider: 'gemini', geminiKey: '' })).rejects.toThrow(/No usable AI provider/);
    });
  });

  describe('getAiConfig ollama support', () => {
    test('defaults to ollama base URL and qwen2.5:1.5b when provider is ollama', async () => {
      const oldEnv = { ...process.env };
      process.env.AI_PROVIDER = 'ollama';
      process.env.AI_MODEL = 'qwen2.5:1.5b';
      process.env.OLLAMA_BASE_URL = 'http://localhost:11434';
      process.env.GEMINI_API_KEY = '';

      const config = await getAiConfig();
      expect(config.provider).toBe('ollama');
      expect(config.ollamaBaseUrl).toBe('http://localhost:11434');
      expect(config.model).toBe('qwen2.5:1.5b');
      expect(config.geminiKey).toBeFalsy();

      process.env = oldEnv;
    });
  });
});
