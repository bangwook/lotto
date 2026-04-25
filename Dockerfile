FROM python:3.9-slim

# Playwright + Xvfb 시스템 의존성
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb xauth wget \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

COPY src/ src/

ENV PYTHONPATH=src

# Xvfb 가상 디스플레이로 실제 브라우저 모드 실행
CMD ["xvfb-run", "--auto-servernum", "--server-args=-screen 0 1920x1080x24", "python", "src/purchase_all.py"]
