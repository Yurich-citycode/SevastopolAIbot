FROM python:3.12-slim

WORKDIR /app

# Логи сразу в stdout — видно в `docker logs`
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Токен и остальные настройки передаются переменными окружения:
#   docker run -d --restart unless-stopped -e TG_TOKEN=... sevastopol-ai-bot
CMD ["python", "sevastopolaibot.py"]
