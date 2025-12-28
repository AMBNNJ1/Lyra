require('dotenv').config();
const express = require('express');
const cors = require('cors');
const bodyParser = require('body-parser');
const { Memory, LLMFactory, EmbedderFactory } = require('mem0ai/oss');
const OpenAI = require('openai');

const app = express();
app.use(cors());
app.use(bodyParser.json({ limit: '2mb' }));

const DEFAULT_COMPAT_BASE_URL = 'http://127.0.0.1:1234/v1';

function resolveCompatibleBaseUrl() {
  return (
    process.env.MEM0_LMSTUDIO_BASE_URL ||
    process.env.MEM0_LLM_BASE_URL ||
    process.env.MEM0_OPENAI_BASE_URL ||
    process.env.OPENAI_BASE_URL ||
    DEFAULT_COMPAT_BASE_URL
  );
}

function resolveCompatibleApiKey() {
  const key = (
    process.env.MEM0_LMSTUDIO_API_KEY ||
    process.env.MEM0_OPENAI_API_KEY ||
    process.env.OPENAI_API_KEY ||
    process.env.LMSTUDIO_API_KEY ||
    ''
  );
  if (!key) {
    console.warn('[mem0-service] No API key configured. Set MEM0_LMSTUDIO_API_KEY, MEM0_OPENAI_API_KEY, OPENAI_API_KEY, or LMSTUDIO_API_KEY.');
  }
  return key;
}

function resolveEmbedModel() {
  return process.env.MEM0_EMBED_MODEL || process.env.MEM0_OPENAI_EMBED_MODEL || 'all-minilm:latest';
}

function resolveLlmModel() {
  return process.env.MEM0_LLM_MODEL || process.env.MEM0_OPENAI_MODEL || 'gpt-4o-mini';
}

function resolveStructuredModel() {
  return process.env.MEM0_LLM_STRUCTURED_MODEL || process.env.MEM0_STRUCTURED_MODEL || resolveLlmModel();
}

const originalEmbedderCreate = EmbedderFactory.create.bind(EmbedderFactory);
const originalLLMCreate = LLMFactory.create.bind(LLMFactory);

function createOpenAICompatibleEmbedder(config = {}) {
  const apiKey = config.apiKey || resolveCompatibleApiKey();
  if (!apiKey) {
    throw new Error('[mem0-service] Missing API key for embeddings; set MEM0_LMSTUDIO_API_KEY.');
  }
  const baseURL = config.baseURL || resolveCompatibleBaseUrl();
  const model = config.model || resolveEmbedModel();
  const client = new OpenAI({ apiKey, baseURL });

  return {
    async embed(text) {
      const response = await client.embeddings.create({ model, input: text });
      return response.data[0]?.embedding || [];
    },
    async embedBatch(texts) {
      const response = await client.embeddings.create({ model, input: texts });
      return response.data.map((item) => item.embedding);
    }
  };
}

function createOpenAICompatibleStructuredLLM(config = {}) {
  const apiKey = config.apiKey || resolveCompatibleApiKey();
  if (!apiKey) {
    throw new Error('[mem0-service] Missing API key for structured LLM; set MEM0_LMSTUDIO_API_KEY.');
  }
  const baseURL = config.baseURL || resolveCompatibleBaseUrl();
  const model = config.structuredModel || config.model || resolveStructuredModel();
  const client = new OpenAI({ apiKey, baseURL });
  const mapMessage = (msg) => ({
    role: msg.role,
    content: typeof msg.content === 'string' ? msg.content : JSON.stringify(msg.content)
  });

  return {
    async generateResponse(messages, responseFormat, tools) {
      const payload = {
        messages: (messages || []).map(mapMessage),
        model
      };

      if (Array.isArray(tools) && tools.length > 0) {
        payload.tools = tools.map((tool) => ({
          type: 'function',
          function: {
            name: tool.function.name,
            description: tool.function.description,
            parameters: tool.function.parameters
          }
        }));
        payload.tool_choice = 'auto';
      } else if (responseFormat) {
        payload.response_format = { type: responseFormat.type };
      }

      const completion = await client.chat.completions.create(payload);
      const response = completion.choices?.[0]?.message || {};
      if (response.tool_calls) {
        return {
          content: response.content || '',
          role: response.role,
          toolCalls: response.tool_calls.map((call) => ({
            name: call.function.name,
            arguments: call.function.arguments
          }))
        };
      }
      return response.content || '';
    },
    async generateChat(messages) {
      const completion = await client.chat.completions.create({
        messages: (messages || []).map(mapMessage),
        model
      });
      const response = completion.choices?.[0]?.message || {};
      return {
        content: response.content || '',
        role: response.role
      };
    }
  };
}

EmbedderFactory.create = (provider, config = {}) => {
  if (!provider) {
    throw new Error('[mem0-service] Embedder provider is required');
  }
  const normalized = provider.toLowerCase();
  if (normalized === 'lmstudio' || normalized === 'openai' || normalized === 'openai_compatible') {
    const mergedConfig = {
      ...config,
      apiKey: config.apiKey || resolveCompatibleApiKey(),
      baseURL: config.baseURL || resolveCompatibleBaseUrl(),
      model: config.model || resolveEmbedModel()
    };
    return createOpenAICompatibleEmbedder(mergedConfig);
  }
  return originalEmbedderCreate(provider, config);
};

LLMFactory.create = (provider, config = {}) => {
  if (!provider) {
    throw new Error('[mem0-service] LLM provider is required');
  }
  const normalized = provider.toLowerCase();
  if (normalized === 'openai_structured') {
    return createOpenAICompatibleStructuredLLM(config);
  }
  if (normalized === 'lmstudio' || normalized === 'openai_compatible') {
    const mergedConfig = {
      ...config,
      apiKey: config.apiKey || resolveCompatibleApiKey(),
      baseURL: config.baseURL || resolveCompatibleBaseUrl(),
      model: config.model || resolveLlmModel(),
      structuredModel: config.structuredModel || resolveStructuredModel()
    };
    return originalLLMCreate('openai', mergedConfig);
  }
  if (normalized === 'openai') {
    const mergedConfig = {
      ...config,
      apiKey: config.apiKey || resolveCompatibleApiKey(),
      baseURL: config.baseURL || resolveCompatibleBaseUrl(),
      model: config.model || resolveLlmModel(),
      structuredModel: config.structuredModel || resolveStructuredModel()
    };
    return originalLLMCreate(provider, mergedConfig);
  }
  return originalLLMCreate(provider, config);
};

function makeMemory() {
  const options = {};
  const qdrantUrl = process.env.QDRANT_URL;
  if (!qdrantUrl) {
    console.warn('[mem0-service] QDRANT_URL not set. Memories will be in-memory only.');
  } else {
    options.vectorStore = {
      provider: 'qdrant',
      config: {
        url: qdrantUrl,
        apiKey: process.env.QDRANT_API_KEY || undefined,
        collectionName: process.env.QDRANT_COLLECTION || 'memory_items',
        distance: process.env.QDRANT_DISTANCE || 'Cosine',
        dimension: process.env.QDRANT_DIM ? Number(process.env.QDRANT_DIM) : undefined
      }
    };
  }

  const embedProvider = (process.env.MEM0_EMBED_PROVIDER || 'ollama').toLowerCase();
  const embedModel = resolveEmbedModel();
  const compatibleApiKey = resolveCompatibleApiKey();
  const compatibleBaseUrl = resolveCompatibleBaseUrl();

  if (embedProvider === 'ollama') {
    options.embedder = {
      provider: 'ollama',
      config: {
        model: embedModel,
        url: process.env.MEM0_OLLAMA_URL || 'http://127.0.0.1:11434'
      }
    };
  } else if (embedProvider === 'lmstudio' || embedProvider === 'openai' || embedProvider === 'openai_compatible') {
    options.embedder = {
      provider: 'lmstudio',
      config: {
        apiKey: compatibleApiKey,
        baseURL: compatibleBaseUrl,
        model: embedModel
      }
    };
  } else {
    console.warn(`[mem0-service] Unknown MEM0_EMBED_PROVIDER "${embedProvider}". Falling back to Ollama.`);
    options.embedder = {
      provider: 'ollama',
      config: {
        model: embedModel,
        url: process.env.MEM0_OLLAMA_URL || 'http://127.0.0.1:11434'
      }
    };
  }

  const llmProvider = (process.env.MEM0_LLM_PROVIDER || (compatibleApiKey ? 'lmstudio' : '')).toLowerCase();
  const llmModel = resolveLlmModel();
  const structuredModel = resolveStructuredModel();

  if (llmProvider === 'ollama') {
    options.llm = {
      provider: 'ollama',
      config: {
        model: llmModel,
        url: process.env.MEM0_OLLAMA_URL || 'http://127.0.0.1:11434'
      }
    };
  } else if (llmProvider === 'lmstudio' || llmProvider === 'openai' || llmProvider === 'openai_compatible') {
    options.llm = {
      provider: 'lmstudio',
      config: {
        apiKey: compatibleApiKey,
        baseURL: compatibleBaseUrl,
        model: llmModel,
        structuredModel
      }
    };
  } else if (llmProvider) {
    console.warn(`[mem0-service] Unknown MEM0_LLM_PROVIDER "${llmProvider}". LLM-backed summarisation disabled.`);
  } else {
    console.warn('[mem0-service] MEM0_LLM_PROVIDER not set. Summaries will rely on default embedding output only.');
  }

  if (options.vectorStore && options.vectorStore.provider === 'qdrant') {
    const cfg = options.vectorStore.config || {};
    console.log(`[mem0-service] Qdrant store: ${cfg.url || 'http://localhost:6333'} collection=${cfg.collectionName || 'memory_items'}`);
  }
  return new Memory(options);
}

const memory = makeMemory();

app.get('/health', (req, res) => {
  res.json({ status: 'ok' });
});

app.post('/search', async (req, res) => {
  try {
    const { userId, query, limit } = req.body || {};
    const uid = String(userId || 'default');
    const q = String(query || '');
    const results = await memory.search(q, { userId: uid, limit: limit || 12 });
    res.json({ results });
  } catch (err) {
    console.error('[mem0-service] search failed', err);
    res.status(500).json({ error: 'search_failed', details: String(err.message || err) });
  }
});

app.post('/add', async (req, res) => {
  try {
    const { userId, messages, metadata } = req.body || {};
    if (!Array.isArray(messages) || messages.length === 0) {
      return res.status(400).json({ error: 'messages_required' });
    }
    const uid = String(userId || 'default');
    const normalized = messages.map((m) => ({
      role: m.role || 'assistant',
      content: m.content || ''
    }));
    const result = await memory.add(normalized, { userId: uid, metadata: metadata || {} });
    res.json({ result });
  } catch (err) {
    console.error('[mem0-service] add failed', err);
    res.status(500).json({ error: 'add_failed', details: String(err.message || err) });
  }
});

app.post('/history', async (req, res) => {
  try {
    const { userId, limit } = req.body || {};
    const uid = String(userId || 'default');
    const items = await memory.history(uid, { limit: limit || 200 });
    res.json({ items });
  } catch (err) {
    console.error('[mem0-service] history failed', err);
    res.status(500).json({ error: 'history_failed', details: String(err.message || err) });
  }
});

app.post('/delete', async (req, res) => {
  try {
    const { userId, memoryId } = req.body || {};
    if (!memoryId) {
      return res.status(400).json({ error: 'memoryId_required' });
    }
    const uid = String(userId || 'default');
    await memory.delete(memoryId, { userId: uid });
    res.json({ ok: true });
  } catch (err) {
    console.error('[mem0-service] delete failed', err);
    res.status(500).json({ error: 'delete_failed', details: String(err.message || err) });
  }
});

const port = Number(process.env.MEM0_PORT || 4040);
app.listen(port, () => {
  console.log(`[mem0-service] listening on ${port}`);
});
