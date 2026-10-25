# Host the demo on a free Hugging Face Space

The `Dockerfile` runs the web app (Sahayak + Memory X-ray + findings) on port 7860 with no GPU. The model
is called over NVIDIA's hosted API, so the Space itself stays on free CPU hardware.

## One-time setup
1. Create a Hugging Face account and an access token with **write** permission
   (huggingface.co → Settings → Access Tokens).
2. Install the CLI on your laptop: `pip install -U huggingface_hub`, then `hf auth login` (paste the token).
3. Get an NVIDIA API key from build.nvidia.com (it starts with `nvapi-`).

## Deploy (and redeploy after every change)
```bash
bash scripts/deploy_space.sh <your-hf-username>/antigoat
```
The script creates the Space if needed (Docker SDK) and uploads the code, including published results
(`results/final-*` and `results/demo-*`), but never your `.env`.

## Secrets (Space → Settings → Variables and secrets)
| Name | Value |
|---|---|
| `LLM_BASE_URL` | `https://integrate.api.nvidia.com/v1` |
| `LLM_API_KEY` | your `nvapi-...` key (as a **secret**) |
| `LLM_MODEL` | a Nemotron model id copied from its build.nvidia.com page |
| `EMBED_MODEL` | `nvidia:nvidia/llama-3.2-nv-embedqa-1b-v2` |
| `SARVAM_API_KEY` | optional, enables voice |
| `ATTACKER_THINKING` | `false` (faster live verification) |

Without secrets the Space still runs, on the offline mock model, which is useful to check the page works.

## Notes
- Each visitor gets their own Sahayak (in memory, up to 60 at once); nothing is written to disk except
  Mem0's temporary files.
- Hosted API calls are rate limited. For the live finals demo prefer the Brev GPU (docs/RUNBOOK.md) and keep
  the Space as the always-on public link.
