FROM python:3.9-slim

# Playwright + Xvfb 시스템 의존성 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxrandr2 libgbm1 libpango-1.0-0 \
    libcairo2 libasound2 libxshmfence1 libxfixes3 \
    libx11-6 libx11-xcb1 libxcb1 libxext6 libxrender1 \
    libxi6 libxtst6 libglib2.0-0 libdbus-1-3 \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install chromium

COPY src/ src/

ENV PYTHONPATH=src

# Xvfb 가상 디스플레이로 실제 브라우저 모드 실행
CMD ["xvfb-run", "--auto-servernum", "--server-args=-screen 0 1920x1080x24", "python", "src/purchase_all.py"]
