FROM python:3.10-slim

WORKDIR /app
COPY . .

RUN apt-get update && \
    apt-get install -y wget unzip ffmpeg && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "app.py"]
