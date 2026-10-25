# AntiGOAT web demo - runs anywhere, incl. a free Hugging Face Space (CPU).
# With no settings it uses the offline mock model. For the real thing set (as Space secrets):
#   LLM_BASE_URL=https://integrate.api.nvidia.com/v1   LLM_API_KEY=nvapi-...
#   LLM_MODEL=<a Nemotron model id from build.nvidia.com>
#   EMBED_MODEL=nvidia:nvidia/llama-3.2-nv-embedqa-1b-v2   (hosted embeddings, no GPU)
#   SARVAM_API_KEY=...   (optional, voice)
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 MEM0_TELEMETRY=False LLM_BASE_URL=mock EMBED_MODEL=hash \
    MAX_WORKERS=8 SAHAYAK_EXTRACT=llm SAHAYAK_VERIFY=llm PORT=7860
COPY requirements.txt requirements-mem0.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-mem0.txt
COPY . .
# Hugging Face Spaces run as a non-root user and need a writable HOME for Mem0's files
RUN useradd -m -u 1000 user && chown -R user /app
USER user
ENV HOME=/home/user
EXPOSE 7860
CMD ["sh", "-c", "python -m uvicorn web.app:app --host 0.0.0.0 --port ${PORT}"]
