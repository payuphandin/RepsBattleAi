FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_ENV=production

WORKDIR /app

# Runtime libraries required by OpenCV and MediaPipe on Debian.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libglib2.0-0 \
        libgl1 \
        libegl1 \
        libgles2 \
        libgomp1 \
        libsm6 \
        libxext6 \
        libxrender1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt \
    && python -c "import cv2, mediapipe, fastapi; print('Backend dependencies ready')"

COPY . .

# Fail the image build if the deployed model file is missing.
RUN python -c "from pushup_detector import MODEL_PATH; assert MODEL_PATH.is_file(), f'Missing model: {MODEL_PATH}'"

EXPOSE 10000

# Render/Railway provide PORT; 10000 is the local/container fallback.
CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port ${PORT:-10000}"]
