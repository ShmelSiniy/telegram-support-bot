FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /bot
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

RUN useradd -r -u 10001 bot && mkdir -p /bot/data && chown bot /bot/data
USER bot
CMD ["python", "-m", "app"]
