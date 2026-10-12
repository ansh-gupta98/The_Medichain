# ─────────────────────────────────────────────────────────────────────────────
# Dockerfile — MediChain FastAPI Backend
# Ultra-lightweight build optimized for Railway / Koyeb / Render
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    WEB_CONCURRENCY=1

# 1. Install build dependencies, build insightface wheels, then purge build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6 \
    libgl1 \
    libgomp1 \
    build-essential \
    g++ \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 2. Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    # Remove compiler packages to drastically shrink image size
    apt-get purge -y --auto-remove build-essential g++ python3-dev && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /root/.cache

# 3. Download buffalo_sc model (~14MB, ~150MB RAM runtime — fits easily within Render 512MB limit)
RUN python -c "\
from insightface.app import FaceAnalysis; \
app = FaceAnalysis(name='buffalo_sc', providers=['CPUExecutionProvider'], allowed_modules=['detection', 'recognition']); \
app.prepare(ctx_id=-1, det_size=(320, 320)); \
print('InsightFace buffalo_sc loaded.')" && \
    rm -f /root/.insightface/models/buffalo_sc.zip && \
    rm -rf /root/.cache

# 4. Copy app code
COPY . .

# 5. Start app using start.py (limits threads and runs 1 worker to prevent OOM)
CMD ["python", "start.py"]