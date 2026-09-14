FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Токен передаётся через переменную окружения при запуске:
#   docker run -d --restart unless-stopped -e TG_TOKEN=... sevastopol-ai-bot
CMD ["python", "sevastopolaibot.py"]
