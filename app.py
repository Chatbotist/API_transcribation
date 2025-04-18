from flask import Flask, request, jsonify
from vosk import Model, KaldiRecognizer, SetLogLevel
import subprocess
import os
import requests
import logging
import json
import tempfile
import threading
from queue import Queue
import uuid
import time

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
MAX_CONCURRENT_TASKS = 5

# Глобальная модель
model = None
model_lock = threading.Lock()
TASK_QUEUE = Queue()

def init_model():
    """Инициализация модели с блокировкой"""
    global model
    with model_lock:
        if model is None:
            if not os.path.exists(MODEL_NAME):
                download_model()
            logger.info("Инициализация модели Vosk...")
            model = Model(MODEL_NAME)
            logger.info("Модель успешно загружена")

def download_model():
    """Скачивание и распаковка модели"""
    try:
        logger.info(f"Скачивание модели {MODEL_NAME}...")
        os.system(f"wget {MODEL_URL} -O model.zip")
        os.system("unzip model.zip")
        
        # Исправление структуры папок
        if os.path.exists(f"{MODEL_NAME}/{MODEL_NAME}"):
            os.system(f"mv {MODEL_NAME}/{MODEL_NAME}/* {MODEL_NAME}/")
            os.system(f"rm -rf {MODEL_NAME}/{MODEL_NAME}")
        
        os.system("rm model.zip")
        
        if not os.path.exists(f"{MODEL_NAME}/am/final.mdl"):
            raise Exception("Файлы модели не найдены")
    except Exception as e:
        logger.error(f"Ошибка загрузки модели: {str(e)}")
        raise

class TranscriptionWorker(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        self.daemon = True
        self.start()

    def run(self):
        init_model()  # Инициализация модели для каждого воркера
        while True:
            task = TASK_QUEUE.get()
            try:
                self.process_task(task)
            except Exception as e:
                logger.error(f"Ошибка обработки задачи: {str(e)}")
                self.send_error(task, str(e))
            finally:
                TASK_QUEUE.task_done()

    def process_task(self, task):
        task_id, audio_url, webhook_url, user_id = task
        start_time = time.time()
        
        try:
            # Создание временного файла
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_wav:
                temp_wav_path = temp_wav.name

            # Конвертация аудио
            ffmpeg_cmd = [
                "ffmpeg",
                "-i", audio_url,
                "-ar", str(SAMPLE_RATE),
                "-ac", "1",
                "-y",
                temp_wav_path
            ]
            subprocess.run(ffmpeg_cmd, check=True, 
                         stdout=subprocess.PIPE, 
                         stderr=subprocess.PIPE)

            # Транскрибация
            recognizer = KaldiRecognizer(model, SAMPLE_RATE)
            recognizer.SetWords(True)
            
            result_text = []
            with open(temp_wav_path, "rb") as f:
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

            self.send_result(
                task_id,
                user_id,
                webhook_url,
                " ".join(result_text),
                time.time() - start_time
            )

        finally:
            if os.path.exists(temp_wav_path):
                os.unlink(temp_wav_path)

    def send_result(self, task_id, user_id, webhook_url, text, processing_time):
        payload = {
            "task_id": task_id,
            "user_id": user_id,
            "text": text,
            "status": "completed",
            "processing_time": round(processing_time, 2),
            "timestamp": time.time()
        }
        try:
            requests.post(webhook_url, json=payload, timeout=10)
        except Exception as e:
            logger.error(f"Ошибка отправки webhook: {str(e)}")

    def send_error(self, task, error_msg):
        task_id, _, webhook_url, user_id = task
        payload = {
            "task_id": task_id,
            "user_id": user_id,
            "status": "error",
            "error": error_msg,
            "timestamp": time.time()
        }
        try:
            requests.post(webhook_url, json=payload, timeout=10)
        except Exception as e:
            logger.error(f"Ошибка отправки ошибки: {str(e)}")

@app.route("/transcribe", methods=["POST"])
def transcribe():
    try:
        data = request.get_json()
        audio_url = data.get("audio_url")
        webhook_url = data.get("webhook_url")
        user_id = data.get("user_id")
        
        if not all([audio_url, webhook_url, user_id]):
            return jsonify({"error": "Missing required parameters"}), 400

        if TASK_QUEUE.qsize() >= MAX_CONCURRENT_TASKS:
            return jsonify({
                "error": "Service overloaded",
                "status": "queued"
            }), 429

        task_id = str(uuid.uuid4())
        TASK_QUEUE.put((task_id, audio_url, webhook_url, user_id))
        
        return jsonify({
            "status": "accepted",
            "task_id": task_id,
            "message": "Task queued for processing"
        })

    except Exception as e:
        logger.error(f"API error: {str(e)}")
        return jsonify({"error": str(e)}), 500

# Запуск воркеров
for _ in range(MAX_CONCURRENT_TASKS):
    TranscriptionWorker()

if __name__ == "__main__":
    init_model()  # Предварительная инициализация
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
