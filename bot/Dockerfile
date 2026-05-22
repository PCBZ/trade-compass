FROM python:3.14-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot source as a package: /app/bot/
COPY . ./bot/

ENV PYTHONUNBUFFERED=1

# main.py lives at /app/bot/main.py; import path is bot.main:app
CMD ["uvicorn", "bot.main:app", "--host", "0.0.0.0", "--port", "8080"]
