FROM python:3.9-slim

WORKDIR /app

# Google Chrome stable 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg ca-certificates xvfb xauth fonts-noto-cjk \
    && wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update && apt-get install -y --no-install-recommends google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

COPY src/ src/
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

ENV PYTHONPATH=src

ENTRYPOINT ["./entrypoint.sh"]
CMD ["python", "src/purchase_all.py"]
