from flask import Flask, request, jsonify
from vosk import Model, KaldiRecognizer, SetLogLevel
import subprocess
import os
import requests
import logging
import json
import tempfile
from threading import Thread
import time
import uuid
from datetime import datetime

app = Flask(__name__)
SetLogLevel(-1)  # Отключаем лишние логи Vosk

# Настройка логов
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Vosk-Transcriber")

# Конфигурация
MODEL_NAME = "vosk-model-small-ru-0.22"  # Используем меньшую модель для экономии памяти
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"
CHUNK_SIZE = 4000
SAMPLE_RATE = 16000
MAX_AUDIO_DURATION = 180  # 3 минуты (ограничение для бесплатного тарифа)
MAX_SYNC_PROCESSING_TIME = 50  # Максимальное время для синхронного ответа (сек)

# Глобальный статус сервера
SERVER_STATUS = {
    "status": "available",
    "last_check": datetime.utcnow().isoformat(),
    "active_tasks": 0
}

def download_model():
    """Скачивает и распаковывает модель Vosk с оптимизацией памяти"""
    try:
        if not os.path.exists(MODEL_NAME):
            logger.info(f"Скачивание модели {MODEL_NAME}...")
            
            # Скачивание
            os.system(f"wget {MODEL_URL} -O model.zip")
            
            # Распаковка с удалением ненужных файлов
            os.system("unzip -j model.zip '*/am/final.mdl' '*/conf/mfcc.conf' '*/graph/phones.txt' -d ${MODEL_NAME}")
            os.system("rm model.zip")
            
            if not os.path.exists(f"{MODEL_NAME}/final.mdl"):
                raise Exception("Критические файлы модели отсутствуют!")
            
            logger.info("Модель успешно загружена и оптимизирована")
        return True
    except Exception as e:
        logger.error(f"Ошибка загрузки модели: {str(e)}")
        return False

# Инициализация модели
if not download_model():
    raise RuntimeError("Не удалось инициализировать модель Vosk!")

model = Model(MODEL_NAME)

def cleanup_files(*files):
    """Удаление временных файлов"""
    for file in files:
        try:
            if file and os.path.exists(file):
                os.unlink(file)
        except Exception as e:
            logger.warning(f"Ошибка удаления файла {file}: {str(e)}")

def convert_to_wav(audio_url):
    """Конвертирует аудио в WAV с оптимизацией памяти"""
    temp_input = None
    temp_output = None
    try:
        # Скачивание файла потоком
        response = requests.get(audio_url, stream=True)
        temp_input = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        
        with open(temp_input.name, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        # Создаем временный выходной файл
        temp_output = tempfile.NamedTemporaryFile(delete=False, suffix=".wav").name

        # Конвертация с базовыми параметрами
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

def transcribe_audio(audio_url, task_id, user_id=None):
    """Основная функция транскрибации аудио с оптимизацией памяти"""
    start_time = time.time()
    wav_file = None
    try:
        SERVER_STATUS["active_tasks"] += 1
        logger.info(f"Начата обработка задачи {task_id}")

        # Конвертация
        wav_file = convert_to_wav(audio_url)

        # Проверка длительности аудио
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

        # Настройка распознавателя
        recognizer = KaldiRecognizer(model, SAMPLE_RATE)
        recognizer.SetWords(True)

        # Поточная обработка аудио
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

        # Финализация результатов
        final_result = json.loads(recognizer.FinalResult())
        if final_result.get("text"):
            result_text.append(final_result["text"])

        full_text = " ".join(result_text)
        is_full = len(full_text) > 0 and duration < (MAX_AUDIO_DURATION * 0.8)

        return {
            "status": "success",
            "text": full_text,
            "user_id": user_id,
            "id": task_id,
            "time_start": start_time,
            "time_end": time.time(),
            "is_full": is_full,
            "audio_duration": duration
        }, 200 if is_full else 201

    except ValueError as e:
        logger.error(f"Ошибка валидации для задачи {task_id}: {str(e)}")
        return {
            "status": "error",
            "error": str(e),
            "id": task_id,
            "time_start": start_time,
            "time_end": time.time()
        }, 400
    except Exception as e:
        logger.error(f"Критическая ошибка для задачи {task_id}: {str(e)}")
        return {
            "status": "error",
            "error": "Internal server error",
            "id": task_id,
            "time_start": start_time,
            "time_end": time.time()
        }, 500
    finally:
        cleanup_files(wav_file)
        SERVER_STATUS["active_tasks"] -= 1
        SERVER_STATUS["last_check"] = datetime.utcnow().isoformat()

def send_webhook_result(webhook_url, result):
    """Отправляет результат на вебхук"""
    try:
        response = requests.post(webhook_url, json=result, timeout=10)
        response.raise_for_status()
        logger.info(f"Результат для задачи {result.get('id')} отправлен на вебхук")
    except Exception as e:
        logger.error(f"Ошибка отправки вебхука для задачи {result.get('id')}: {str(e)}")

@app.route("/health", methods=["GET"])
def health_check():
    """Проверка статуса сервера"""
    try:
        status_code = 200 if SERVER_STATUS["status"] == "available" else 503
        return jsonify({
            "status": SERVER_STATUS["status"],
            "last_check": SERVER_STATUS["last_check"],
            "active_tasks": SERVER_STATUS["active_tasks"]
        }), status_code
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route("/transcribe", methods=["POST"])
def sync_transcribe():
    """Синхронный эндпоинт для транскрибации"""
    try:
        data = request.get_json()
        audio_url = data.get("audio_url")
        user_id = data.get("user_id")
        
        if not audio_url:
            return jsonify({"status": "error", "error": "audio_url is required"}), 400

        task_id = str(uuid.uuid4())
        result, status_code = transcribe_audio(audio_url, task_id, user_id)
        
        # Форматирование времени для ответа
        result["time_start"] = int(result["time_start"])
        result["time_end"] = int(result["time_end"])
        
        return jsonify(result), status_code

    except Exception as e:
        logger.error(f"Ошибка в синхронном обработчике: {str(e)}")
        return jsonify({
            "status": "error",
            "error": "Internal server error"
        }), 500

@app.route("/transcribeAsync", methods=["POST"])
def async_transcribe():
    """Асинхронный эндпоинт для транскрибации"""
    try:
        data = request.get_json()
        audio_url = data.get("audio_url")
        user_id = data.get("user_id")
        webhook_url = data.get("webhook_url")
        
        if not audio_url or not webhook_url:
            return jsonify({
                "status": "error",
                "error": "audio_url and webhook_url are required"
            }), 400

        task_id = str(uuid.uuid4())
        start_time = time.time()
        
        # Запуск в отдельном потоке
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
        logger.error(f"Ошибка в асинхронном обработчике: {str(e)}")
        return jsonify({
            "status": "error",
            "error": "Internal server error"
        }), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
