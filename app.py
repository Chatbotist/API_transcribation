import os
import json
import tempfile
import threading
import time
import subprocess
import requests
from flask import Flask, request, jsonify
from vosk import Model, KaldiRecognizer

app = Flask(__name__)

# Конфигурация
MODEL_NAME = "vosk-model-ru-0.42"
MODEL_PATH = os.path.join(os.getcwd(), MODEL_NAME)  # Путь относительно рабочей директории
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"
SAMPLE_RATE = 16000
CHUNK_SIZE = 4000
MAX_WORKERS = 3  # Максимум одновременных обработок

# Очередь задач
tasks = {}
lock = threading.Lock()

def download_model():
    if not os.path.exists(MODEL_PATH):
        os.makedirs(MODEL_PATH, exist_ok=True)
        os.system(f"wget {MODEL_URL} -O model.zip")
        os.system(f"unzip model.zip -d {MODEL_PATH}")
        os.system("rm model.zip")
        
        # Проверка успешной распаковки
        if not os.path.exists(os.path.join(MODEL_PATH, "am", "final.mdl")):
            raise Exception("Failed to extract model files")

# Загружаем модель при старте
try:
    download_model()
    model = Model(MODEL_PATH)
except Exception as e:
    print(f"Failed to initialize model: {str(e)}")
    raise

def process_audio(task_id, audio_url, webhook_url, user_id):
    try:
        start_time = time.time()
        temp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        temp_wav.close()
        
        # Скачивание
        response = requests.get(audio_url, stream=True)
        with open(temp_wav.name, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024):
                f.write(chunk)

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
                    res = json.loads(recognizer.Result())
                    if res.get("text"):
                        result_text.append(res["text"])

        final_res = json.loads(recognizer.FinalResult())
        if final_res.get("text"):
            result_text.append(final_res["text"])

        os.unlink(temp_wav.name)
        processing_time = round(time.time() - start_time, 2)

        # Отправка результата
        payload = {
            "user_id": user_id,
            "text": " ".join(result_text),
            "processing_time": processing_time,
            "status": "completed",
            "task_id": task_id
        }
        requests.post(webhook_url, json=payload)

    except Exception as e:
        payload = {
            "user_id": user_id,
            "error": str(e),
            "status": "failed",
            "task_id": task_id
        }
        requests.post(webhook_url, json=payload)
    finally:
        with lock:
            del tasks[task_id]

@app.route("/transcribe", methods=["POST"])
def transcribe():
    data = request.get_json()
    if not all(k in data for k in ["audio_url", "webhook_url", "user_id"]):
        return jsonify({"error": "Missing required parameters"}), 400

    with lock:
        if len(tasks) >= MAX_WORKERS:
            return jsonify({"error": "Server busy, try again later"}), 429

        task_id = str(int(time.time() * 1000))
        tasks[task_id] = {
            "status": "processing",
            "start_time": time.time()
        }

    thread = threading.Thread(
        target=process_audio,
        args=(task_id, data["audio_url"], data["webhook_url"], data["user_id"])
    )
    thread.start()

    return jsonify({
        "task_id": task_id,
        "status": "queued",
        "message": "Processing started"
    })

@app.route("/status/<task_id>", methods=["GET"])
def get_status(task_id):
    with lock:
        task = tasks.get(task_id, None)
    if not task:
        return jsonify({"error": "Task not found"}), 404
    return jsonify(task)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
