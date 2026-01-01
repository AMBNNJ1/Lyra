# RunPod LLM Integration

## Files

| File | Description |
|------|-------------|
| `src/neuro_mvp/runpod_client.py` | Python client for RunPod LLM endpoint |
| `config.yaml` | Added `provider: runpod` option for LLM |
| `src/neuro_mvp/web_session.py` | RunPod LLM provider support |
| `requirements.txt` | Added `runpod>=1.6.0` |

## Setup Steps

### 1. Create RunPod Account
Go to https://runpod.io → Sign up → Settings → API Keys → Create key

### 2. Deploy LLM Endpoint
In RunPod Console:
1. Click **Serverless** in left sidebar
2. Click **+ New Endpoint**
3. Select **vLLM** template
4. Pick a model like `Qwen/Qwen2.5-3B-Instruct`
5. Deploy → Copy the **Endpoint ID**

### 3. Configure Environment
Add these environment variables (Railway Dashboard → Variables, or `.env` locally):

```
RUNPOD_API_KEY=your_api_key
RUNPOD_LLM_ENDPOINT=your_llm_endpoint_id
```

### 4. Update config.yaml

```yaml
models:
  llm:
    provider: runpod
```

Commit and push to trigger deployment.

## Where Each Step Happens

| Step | Where |
|------|-------|
| 1. Create RunPod account | https://runpod.io (web browser) |
| 2. Deploy LLM (vLLM) | RunPod Console → Serverless (web browser) |
| 3. Add env vars | Railway Dashboard or local `.env` |
| 4. Update config.yaml | Your local repo (commit & push to deploy) |
