FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Секреты — только из окружения, в образ они не попадают (.env в .dockerignore):
#   docker run -d --restart unless-stopped -e TG_TOKEN=... -e ADMIN_ID=... \
#     -e STATE_FILE=/data/bot_state.json -v sevastopol-state:/data sevastopol-ai-bot
# либо:  docker run --env-file /etc/sevastopol-ai-bot.env ...   (chmod 600 на файл)
CMD ["python", "sevastopolaibot.py"]
