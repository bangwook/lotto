FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

COPY src/ src/

ENV PYTHONPATH=src

CMD ["python", "src/purchase_all.py"]
