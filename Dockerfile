# --- Étape 1 : interface (Vite + Svelte) -> /server/static ---
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# --- Étape 2 : serveur Python (FastAPI + XTTS) ---
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    TTS_HOME=/models COQUI_TOS_AGREED=1 HF_HOME=/models/hf

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libsndfile1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# torch 2.7.1+cu128 : même version que l'application Windows ; contient sm_50 (GTX 9xx) à sm_120 (RTX 50xx)
RUN pip install --no-cache-dir torch==2.7.1 torchaudio==2.7.1 \
    --index-url https://download.pytorch.org/whl/cu128

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Modèle XTTS-v2 (~1,8 Go) téléchargé au build pour fonctionner hors ligne
RUN python -c "from TTS.utils.manage import ModelManager; ModelManager().download_model('tts_models/multilingual/multi-dataset/xtts_v2')"

COPY server ./server
COPY --from=web /server/static ./server/static

ENV DATA_DIR=/data HF_HUB_OFFLINE=1
VOLUME /data
EXPOSE 8000
CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000"]
