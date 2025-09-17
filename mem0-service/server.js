require('dotenv').config();
const express = require('express');
const cors = require('cors');
const bodyParser = require('body-parser');
const { Memory } = require('mem0ai/oss');

const app = express();
app.use(cors());
app.use(bodyParser.json({ limit: '2mb' }));

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
  if (embedProvider === 'ollama') {
    options.embedder = {
      provider: 'ollama',
      config: {
        model: process.env.MEM0_EMBED_MODEL || 'all-minilm:latest',
        url: process.env.MEM0_OLLAMA_URL || 'http://127.0.0.1:11434'
      }
    };
  } else if (embedProvider === 'openai') {
    options.embedder = {
      provider: 'openai',
      config: {
        apiKey: process.env.MEM0_OPENAI_API_KEY,
        model: process.env.MEM0_OPENAI_EMBED_MODEL || 'text-embedding-3-small',
        baseURL: process.env.MEM0_OPENAI_BASE_URL || 'https://api.openai.com/v1'
      }
    };
  } else {
    console.warn(`[mem0-service] Unknown MEM0_EMBED_PROVIDER "${embedProvider}". Falling back to Ollama.`);
    options.embedder = {
      provider: 'ollama',
      config: {
        model: process.env.MEM0_EMBED_MODEL || 'all-minilm:latest',
        url: process.env.MEM0_OLLAMA_URL || 'http://127.0.0.1:11434'
      }
    };
  }

  if (process.env.MEM0_OPENAI_API_KEY) {
    options.llm = {
      provider: 'openai',
      config: {
        apiKey: process.env.MEM0_OPENAI_API_KEY,
        model: process.env.MEM0_OPENAI_MODEL || 'gpt-4o-mini'
      }
    };
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
