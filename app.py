from flask import Flask, request, jsonify
from vosk import Model, KaldiRecognizer, SetLogLevel
import subprocess
import os
import requests
import logging
import json
import tempfile
from threading import Thread, Lock
import time
import uuid
from datetime import datetime

app = Flask(__name__)
SetLogLevel(-1)

# Настройка логов
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Vosk-Transcriber")

# Конфигурация
MODEL_NAME = "model"  # Упрощенное имя директории
MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip"
CHUNK_SIZE = 4000
SAMPLE_RATE = 16000
MAX_AUDIO_DURATION = 180
MAX_SYNC_PROCESSING_TIME = 50

# Глобальные переменные состояния
SERVER_STATUS = {
    "status": "available",
    "last_check": datetime.utcnow().isoformat(),
    "active_tasks": 0
}

TASKS = {}
tasks_lock = Lock()

def download_model():
    """Исправленная функция загрузки модели"""
    try:
        if not os.path.exists(MODEL_NAME):
            logger.info("Скачивание модели...")
            
            # Скачивание и распаковка в текущую директорию
            os.system(f"wget {MODEL_URL} -O model.zip")
            os.system("unzip model.zip -d model_tmp")
            os.system("mv model_tmp/vosk-model-small-ru-0.22 model")
            os.system("rm -rf model_tmp model.zip")
            
            # Проверка критических файлов
            required_files = [
                "model/am/final.mdl",
                "model/conf/mfcc.conf",
                "model/graph/phones.txt"
            ]
            
            if not all(os.path.exists(f) for f in required_files):
                raise Exception("Критические файлы модели отсутствуют!")
            
            logger.info("Модель успешно загружена")
        return True
    except Exception as e:
        logger.error(f"Ошибка загрузки модели: {str(e)}")
        return False

# Инициализация модели
if not download_model():
    logger.error("Не удалось загрузить модель Vosk!")
    SERVER_STATUS["status"] = "unavailable"
else:
    try:
        model = Model(MODEL_NAME)
        logger.info("Модель Vosk инициализирована")
    except Exception as e:
        logger.error(f"Ошибка инициализации модели: {str(e)}")
        SERVER_STATUS["status"] = "unavailable"

def cleanup_files(*files):
    for file in files:
        try:
            if file and os.path.exists(file):
                os.unlink(file)
        except Exception as e:
            logger.warning(f"Ошибка удаления файла {file}: {str(e)}")

def convert_to_wav(audio_url):
    temp_input = None
    temp_output = None
    try:
        response = requests.get(audio_url, stream=True)
        response.raise_for_status()
        
        temp_input = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        
        with open(temp_input.name, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        temp_output = tempfile.NamedTemporaryFile(delete=False, suffix=".wav").name

        ffmpeg_cmd = [
            "ffmpeg",
            "-i", temp_input.name,
            "-ar", str(SAMPLE_RATE),
            "-ac", "1",
            "-y",
            temp_output
        ]
        subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        return temp_output
    except Exception as e:
        logger.error(f"Ошибка конвертации: {str(e)}")
        cleanup_files(temp_input.name if temp_input else None, temp_output)
        raise
    finally:
        cleanup_files(temp_input.name if temp_input else None)

def update_task_status(task_id, status, result=None):
    with tasks_lock:
        TASKS[task_id] = {
            "status": status,
            "result": result,
            "last_update": datetime.utcnow().isoformat()
        }

def transcribe_audio(audio_url, task_id, user_id=None):
    start_time = time.time()
    wav_file = None
    try:
        SERVER_STATUS["active_tasks"] += 1
        update_task_status(task_id, "processing")
        logger.info(f"Начата обработка задачи {task_id}")

        wav_file = convert_to_wav(audio_url)

        duration_cmd = [
            "ffprobe",
            "-i", wav_file,
            "-show_entries", "format=duration",
            "-v", "quiet",
            "-of", "csv=p=0"
        ]
        duration = float(subprocess.run(duration_cmd, capture_output=True, text=True).stdout)
        
        if duration > MAX_AUDIO_DURATION:
            raise ValueError(f"Аудио слишком длинное (максимум {MAX_AUDIO_DURATION//60} минут)")

        recognizer = KaldiRecognizer(model, SAMPLE_RATE)
        recognizer.SetWords(True)

        result_text = []
        with open(wav_file, "rb") as f:
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

        full_text = " ".join(result_text)
        is_full = len(full_text) > 0

        result_data = {
            "status": "success",
            "text": full_text,
            "user_id": user_id,
            "id": task_id,
            "time_start": start_time,
            "time_end": time.time(),
            "is_full": is_full,
            "audio_duration": duration
        }

        update_task_status(task_id, "completed", result_data)
        return result_data, 200 if is_full else 201
    except Exception as e:
        error_data = {
            "status": "error",
            "error": str(e),
            "id": task_id,
            "time_start": start_time,
            "time_end": time.time()
        }
        update_task_status(task_id, "failed", error_data)
        return error_data, 400
    finally:
        cleanup_files(wav_file)
        SERVER_STATUS["active_tasks"] = max(0, SERVER_STATUS["active_tasks"] - 1)
        SERVER_STATUS["last_check"] = datetime.utcnow().isoformat()

def send_webhook_result(webhook_url, result):
    try:
        response = requests.post(webhook_url, json=result, timeout=10)
        response.raise_for_status()
        logger.info(f"Результат отправлен на вебхук для задачи {result.get('id')}")
    except Exception as e:
        logger.error(f"Ошибка отправки вебхука: {str(e)}")

@app.route("/health", methods=["GET"])
def health_check():
    try:
        status_code = 200 if SERVER_STATUS["status"] == "available" else 503
        return jsonify({
            "status": SERVER_STATUS["status"],
            "last_check": SERVER_STATUS["last_check"],
            "active_tasks": SERVER_STATUS["active_tasks"],
            "model_loaded": "model" in globals()
        }), status_code
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route("/taskStatus", methods=["GET"])
def task_status():
    try:
        task_id = request.args.get("id")
        if not task_id:
            return jsonify({"status": "error", "error": "Необходим параметр id"}), 400

        with tasks_lock:
            task_data = TASKS.get(task_id)
        
        if not task_data:
            return jsonify({"status": "error", "error": "Задача не найдена"}), 404

        return jsonify({
            "status": "success",
            "task_id": task_id,
            "task_status": task_data["status"],
            "result": task_data.get("result"),
            "last_update": task_data["last_update"]
        }), 200
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route("/transcribe", methods=["POST"])
def sync_transcribe():
    try:
        if SERVER_STATUS["status"] != "available":
            return jsonify({"status": "error", "error": "Сервер недоступен"}), 503

        data = request.get_json()
        audio_url = data.get("audio_url")
        user_id = data.get("user_id")
        
        if not audio_url or not user_id:
            return jsonify({"status": "error", "error": "Необходимы audio_url и user_id"}), 400

        task_id = str(uuid.uuid4())
        result, status_code = transcribe_audio(audio_url, task_id, user_id)
        
        result["time_start"] = int(result["time_start"])
        result["time_end"] = int(result["time_end"])
        
        return jsonify(result), status_code
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route("/transcribeAsync", methods=["POST"])
def async_transcribe():
    try:
        if SERVER_STATUS["status"] != "available":
            return jsonify({"status": "error", "error": "Сервер недоступен"}), 503

        data = request.get_json()
        audio_url = data.get("audio_url")
        user_id = data.get("user_id")
        webhook_url = data.get("webhook_url")
        
        if not all([audio_url, user_id, webhook_url]):
            return jsonify({"status": "error", "error": "Необходимы audio_url, user_id и webhook_url"}), 400

        task_id = str(uuid.uuid4())
        start_time = time.time()
        
        def async_task():
            result, _ = transcribe_audio(audio_url, task_id, user_id)
            result["webhook_url"] = webhook_url
            result["time_start"] = int(start_time)
            result["time_end"] = int(time.time())
            send_webhook_result(webhook_url, result)
        
        Thread(target=async_task).start()
        
        return jsonify({
            "status": "started",
            "id": task_id,
            "time_start": int(start_time),
            "webhook_url": webhook_url,
            "user_id": user_id
        }), 202
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
