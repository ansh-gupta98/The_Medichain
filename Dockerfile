# ─────────────────────────────────────────────────────────────────────────────
# Dockerfile — MediChain FastAPI Backend
# Optimized for Railway deployment
# Model: InsightFace buffalo_l (ArcFace R100) — BEST accuracy 99.83%
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.11-slim

# Install system libs needed by OpenCV and InsightFace
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6 \
    libgl1 \
    libgomp1 \
    wget \
    build-essential \
    g++ \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install Python dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Pre-download InsightFace buffalo_l model during build
RUN python -c "\
from insightface.app import FaceAnalysis; \
app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider']); \
app.prepare(ctx_id=-1, det_size=(640, 640)); \
print('InsightFace buffalo_l (ArcFace R100) downloaded successfully.')"

# Copy application code
COPY . .

# ✅ FIXED: Python reads PORT directly — no shell expansion needed
CMD ["python", "-c", "import os,uvicorn; uvicorn.run('main:app', host='0.0.0.0', port=int(os.environ.get('PORT',8000)), workers=2)"]