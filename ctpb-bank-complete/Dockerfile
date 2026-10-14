# ---- CTPB Bank app image -------------------------------------------------
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

# Boot: ensure schema + seed demo data if empty, then serve.
CMD ["sh", "-c", "python -m scripts.seed --seed && python app.py"]
