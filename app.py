from flask import Flask, request, jsonify
from vosk import Model, KaldiRecognizer, SetLogLevel
import subprocess
import os
import requests
import logging
import json
import tempfile
import time
import threading
from queue import Queue
import uuid

app = Flask(__name__)
SetLogLevel(-1)  # Отключаем логи Vosk

# Настройка
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Async-Vosk-Transcriber")

# Конфигурация
MODEL_NAME = "vosk-model-ru-0.42"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"
CHUNK_SIZE = 4000
SAMPLE_RATE = 16000
MAX_CONCURRENT_TASKS = 5  # Максимум одновременных обработок
TASK_QUEUE = Queue()

# Загрузка модели
model = Model(MODEL_NAME) if os.path.exists(MODEL_NAME) else None

class TranscriptionWorker(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        self.daemon = True
        self.start()

    def run(self):
        while True:
            task = TASK_QUEUE.get()
            try:
                process_audio_task(task)
            except Exception as e:
                logger.error(f"Ошибка обработки задачи: {str(e)}")
            finally:
                TASK_QUEUE.task_done()

def process_audio_task(task):
    start_time = time.time()
    task_id, audio_url, webhook_url, user_id = task
    
    try:
        # Создаем временные файлы
        temp_wav = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        temp_wav.close()

        # Конвертация аудио
        ffmpeg_cmd = [
            "ffmpeg",
            "-i", audio_url,
            "-af", "arnndn=m=vosk-model-ru-0.42/rnnoise.rnn",
            "-ar", str(SAMPLE_RATE),
            "-ac", "1",
            "-y",
            temp_wav.name
        ]
        subprocess.run(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # Транскрибация
        recognizer = KaldiRecognizer(model, SAMPLE_RATE)
        recognizer.SetWords(True)
        
        result_text = []
        with open(temp_wav.name, "rb") as f:
            while True:
                data = f.read(CHUNK_SIZE)
                if len(data) == 0:
                    break
                
                if recognizer.AcceptWaveform(data):
                    result = json.loads(recognizer.Result())
                    if result.get("text"):
                        result_text.append(result["text"])

        final_result = json.loads(recognizer.FinalResult())
        if final_result.get("text"):
            result_text.append(final_result["text"])

        processing_time = time.time() - start_time

        # Отправка результата на webhook
        payload = {
            "task_id": task_id,
            "user_id": user_id,
            "text": " ".join(result_text),
            "status": "completed",
            "processing_time": round(processing_time, 2),
            "timestamp": time.time()
        }
        
        requests.post(webhook_url, json=payload, timeout=10)

    except Exception as e:
        error_payload = {
            "task_id": task_id,
            "user_id": user_id,
            "status": "error",
            "error": str(e),
            "timestamp": time.time()
        }
        requests.post(webhook_url, json=error_payload, timeout=10)
    finally:
        if os.path.exists(temp_wav.name):
            os.unlink(temp_wav.name)

@app.route("/transcribe", methods=["POST"])
def transcribe():
    try:
        data = request.get_json()
        audio_url = data.get("audio_url")
        webhook_url = data.get("webhook_url")
        user_id = data.get("user_id")
        
        if not all([audio_url, webhook_url, user_id]):
            return jsonify({"error": "Необходимы audio_url, webhook_url и user_id"}), 400

        task_id = str(uuid.uuid4())
        
        # Проверка загрузки системы
        if TASK_QUEUE.qsize() >= MAX_CONCURRENT_TASKS:
            return jsonify({
                "error": "Сервис перегружен",
                "task_id": task_id,
                "status": "queued"
            }), 429

        # Добавляем задачу в очередь
        TASK_QUEUE.put((task_id, audio_url, webhook_url, user_id))
        
        return jsonify({
            "status": "accepted",
            "task_id": task_id,
            "message": "Задача принята в обработку"
        })

    except Exception as e:
        logger.error(f"Ошибка: {str(e)}")
        return jsonify({"error": str(e)}), 500

# Запускаем воркеры
for _ in range(MAX_CONCURRENT_TASKS):
    TranscriptionWorker()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
