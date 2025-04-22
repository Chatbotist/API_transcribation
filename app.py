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
import shutil

app = Flask(__name__)
SetLogLevel(-1)

# Настройка логов
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Vosk-Transcriber")

# Конфигурация
MODEL_DIR = "vosk-model"
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
model = None

def setup_model_directory():
    """Надежная настройка директории модели с улучшенной обработкой ошибок"""
    try:
        logger.info("Начало установки модели Vosk...")
        
        # 1. Скачивание архива
        if not os.path.exists("model.zip"):
            logger.info("Скачивание модели с %s...", MODEL_URL)
            result = subprocess.run(
                ["wget", MODEL_URL, "-O", "model.zip"],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                raise Exception(f"Ошибка скачивания: {result.stderr}")

        # 2. Очистка и создание директории
        if os.path.exists(MODEL_DIR):
            logger.info("Очистка существующей директории модели...")
            shutil.rmtree(MODEL_DIR)
        os.makedirs(MODEL_DIR, exist_ok=True)

        # 3. Распаковка во временную директорию
        logger.info("Распаковка модели...")
        temp_dir = "temp_model"
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        
        result = subprocess.run(
            ["unzip", "model.zip", "-d", temp_dir],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            raise Exception(f"Ошибка распаковки: {result.stderr}")

        # 4. Перемещение файлов в целевую директорию
        logger.info("Перенос файлов модели...")
        src_dir = os.path.join(temp_dir, "vosk-model-small-ru-0.22")
        if not os.path.exists(src_dir):
            raise Exception("Не найдена распакованная директория модели")

        for item in os.listdir(src_dir):
            src_path = os.path.join(src_dir, item)
            dst_path = os.path.join(MODEL_DIR, item)
            
            if os.path.isdir(src_path):
                shutil.copytree(src_path, dst_path)
            else:
                shutil.copy2(src_path, dst_path)

        # 5. Проверка критических файлов
        logger.info("Проверка файлов модели...")
        required_files = [
            os.path.join(MODEL_DIR, "am", "final.mdl"),
            os.path.join(MODEL_DIR, "conf", "mfcc.conf"),
            os.path.join(MODEL_DIR, "graph", "phones.txt")
        ]
        
        missing_files = []
        for file_path in required_files:
            if not os.path.exists(file_path):
                missing_files.append(file_path)
        
        if missing_files:
            raise Exception(f"Отсутствуют критические файлы модели: {missing_files}")

        logger.info("Модель успешно установлена и проверена")
        return True

    except Exception as e:
        logger.error("Ошибка установки модели: %s", str(e))
        return False
    finally:
        # Всегда очищаем временные файлы
        if os.path.exists("temp_model"):
            shutil.rmtree("temp_model", ignore_errors=True)
        if os.path.exists("model.zip"):
            try:
                os.remove("model.zip")
            except:
                pass

# Инициализация модели при старте
if setup_model_directory():
    try:
        logger.info("Инициализация модели Vosk...")
        model = Model(MODEL_DIR)
        logger.info("Модель Vosk успешно инициализирована")
    except Exception as e:
        logger.error("Ошибка инициализации модели: %s", str(e))
        SERVER_STATUS["status"] = "unavailable"
else:
    logger.error("Не удалось установить модель Vosk!")
    SERVER_STATUS["status"] = "unavailable"

def cleanup_files(*files):
    """Безопасное удаление временных файлов"""
    for file_path in files:
        try:
            if file_path and os.path.exists(file_path):
                if os.path.isdir(file_path):
                    shutil.rmtree(file_path)
                else:
                    os.unlink(file_path)
        except Exception as e:
            logger.warning("Ошибка удаления файла %s: %s", file_path, str(e))

def convert_to_wav(audio_url):
    """Конвертация аудио в WAV формат"""
    temp_input = None
    temp_output = None
    try:
        logger.info("Начало конвертации аудио из %s", audio_url)
        
        # Скачивание файла
        response = requests.get(audio_url, stream=True)
        response.raise_for_status()
        
        # Создание временного файла
        temp_input = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        with open(temp_input.name, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        # Конвертация в WAV
        temp_output = tempfile.NamedTemporaryFile(delete=False, suffix=".wav").name
        
        ffmpeg_cmd = [
            "ffmpeg",
            "-i", temp_input.name,
            "-ar", str(SAMPLE_RATE),
            "-ac", "1",
            "-y",
            temp_output
        ]
        
        result = subprocess.run(
            ffmpeg_cmd,
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            raise Exception(f"Ошибка ffmpeg: {result.stderr}")
        
        logger.info("Аудио успешно сконвертировано")
        return temp_output

    except Exception as e:
        logger.error("Ошибка конвертации аудио: %s", str(e))
        cleanup_files(temp_input.name if temp_input else None, temp_output)
        raise
    finally:
        if temp_input and os.path.exists(temp_input.name):
            cleanup_files(temp_input.name)

def update_task_status(task_id, status, result=None):
    """Обновление статуса задачи с блокировкой"""
    with tasks_lock:
        TASKS[task_id] = {
            "status": status,
            "result": result,
            "last_update": datetime.utcnow().isoformat()
        }
        logger.info("Обновлен статус задачи %s: %s", task_id, status)

def transcribe_audio(audio_url, task_id, user_id=None):
    """Основная функция транскрибации аудио"""
    start_time = time.time()
    wav_file = None
    try:
        # Обновление статуса сервера
        SERVER_STATUS["active_tasks"] += 1
        update_task_status(task_id, "processing")
        
        logger.info("Начало обработки задачи %s для %s", task_id, audio_url)

        if not model:
            raise Exception("Модель Vosk не инициализирована")

        # Конвертация аудио
        wav_file = convert_to_wav(audio_url)

        # Проверка длительности
        duration_cmd = [
            "ffprobe",
            "-i", wav_file,
            "-show_entries", "format=duration",
            "-v", "quiet",
            "-of", "csv=p=0"
        ]
        
        result = subprocess.run(
            duration_cmd,
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            raise Exception(f"Ошибка проверки длительности: {result.stderr}")
        
        duration = float(result.stdout)
        logger.info("Длительность аудио: %.2f сек", duration)
        
        if duration > MAX_AUDIO_DURATION:
            raise ValueError(f"Аудио слишком длинное (максимум {MAX_AUDIO_DURATION//60} минут)")

        # Инициализация распознавателя
        recognizer = KaldiRecognizer(model, SAMPLE_RATE)
        recognizer.SetWords(True)

        # Обработка аудио
        result_text = []
        with open(wav_file, "rb") as f:
            while True:
                data = f.read(CHUNK_SIZE)
                if len(data) == 0:
                    break
                
                # Проверка времени выполнения
                if time.time() - start_time > MAX_SYNC_PROCESSING_TIME:
                    raise TimeoutError("Превышено время обработки")
                
                if recognizer.AcceptWaveform(data):
                    result = json.loads(recognizer.Result())
                    if result.get("text"):
                        result_text.append(result["text"])

        # Финализация результатов
        final_result = json.loads(recognizer.FinalResult())
        if final_result.get("text"):
            result_text.append(final_result["text"])

        full_text = " ".join(result_text)
        is_full = len(full_text) > 0

        # Формирование результата
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
        logger.info("Задача %s успешно завершена", task_id)
        return result_data, 200 if is_full else 201

    except Exception as e:
        logger.error("Ошибка обработки задачи %s: %s", task_id, str(e))
        
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
        # Очистка и обновление статуса
        cleanup_files(wav_file)
        SERVER_STATUS["active_tasks"] = max(0, SERVER_STATUS["active_tasks"] - 1)
        SERVER_STATUS["last_check"] = datetime.utcnow().isoformat()

def send_webhook_result(webhook_url, result):
    """Отправка результата на вебхук"""
    try:
        logger.info("Отправка результата на вебхук %s", webhook_url)
        response = requests.post(
            webhook_url,
            json=result,
            timeout=10,
            headers={"Content-Type": "application/json"}
        )
        response.raise_for_status()
        logger.info("Результат для задачи %s отправлен", result.get("id"))
    except Exception as e:
        logger.error("Ошибка отправки вебхука для задачи %s: %s", 
                   result.get("id"), str(e))

@app.route("/health", methods=["GET"])
def health_check():
    """Проверка состояния сервера"""
    try:
        status = "available" if SERVER_STATUS["status"] == "available" and model else "unavailable"
        status_code = 200 if status == "available" else 503
        
        response = {
            "status": status,
            "model_loaded": bool(model),
            "last_check": SERVER_STATUS["last_check"],
            "active_tasks": SERVER_STATUS["active_tasks"],
            "version": "1.0.0"
        }
        
        logger.info("Проверка здоровья: %s", status)
        return jsonify(response), status_code
        
    except Exception as e:
        logger.error("Ошибка проверки здоровья: %s", str(e))
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route("/taskStatus", methods=["GET"])
def task_status():
    """Проверка статуса задачи"""
    try:
        task_id = request.args.get("id")
        if not task_id:
            logger.warning("Запрос статуса без ID задачи")
            return jsonify({
                "status": "error",
                "error": "Параметр id обязателен"
            }), 400

        with tasks_lock:
            task_data = TASKS.get(task_id)
        
        if not task_data:
            logger.warning("Задача %s не найдена", task_id)
            return jsonify({
                "status": "error",
                "error": "Задача не найдена"
            }), 404

        response = {
            "status": "success",
            "task_id": task_id,
            "task_status": task_data["status"],
            "result": task_data.get("result"),
            "last_update": task_data["last_update"]
        }
        
        logger.info("Статус задачи %s: %s", task_id, task_data["status"])
        return jsonify(response), 200
        
    except Exception as e:
        logger.error("Ошибка проверки статуса задачи: %s", str(e))
        return jsonify({
            "status": "error",
            "error": "Внутренняя ошибка сервера"
        }), 500

@app.route("/transcribe", methods=["POST"])
def sync_transcribe():
    """Синхронная транскрибация"""
    try:
        if SERVER_STATUS["status"] != "available" or not model:
            logger.error("Попытка транскрибации при недоступном сервере")
            return jsonify({
                "status": "error",
                "error": "Сервер недоступен"
            }), 503

        data = request.get_json()
        if not data:
            logger.warning("Пустой запрос на транскрибацию")
            return jsonify({
                "status": "error",
                "error": "Необходим JSON в теле запроса"
            }), 400

        audio_url = data.get("audio_url")
        user_id = data.get("user_id")
        
        if not audio_url or not user_id:
            logger.warning("Неполные данные для транскрибации")
            return jsonify({
                "status": "error",
                "error": "Необходимы audio_url и user_id"
            }), 400

        task_id = str(uuid.uuid4())
        logger.info("Начало синхронной обработки задачи %s", task_id)
        
        result, status_code = transcribe_audio(audio_url, task_id, user_id)
        
        # Форматирование времени
        result["time_start"] = int(result["time_start"])
        result["time_end"] = int(result["time_end"])
        
        logger.info("Завершение синхронной обработки задачи %s", task_id)
        return jsonify(result), status_code
        
    except Exception as e:
        logger.error("Ошибка в синхронном обработчике: %s", str(e))
        return jsonify({
            "status": "error",
            "error": "Внутренняя ошибка сервера"
        }), 500

@app.route("/transcribeAsync", methods=["POST"])
def async_transcribe():
    """Асинхронная транскрибация"""
    try:
        if SERVER_STATUS["status"] != "available" or not model:
            logger.error("Попытка асинхронной транскрибации при недоступном сервере")
            return jsonify({
                "status": "error",
                "error": "Сервер недоступен"
            }), 503

        data = request.get_json()
        if not data:
            logger.warning("Пустой запрос на асинхронную транскрибацию")
            return jsonify({
                "status": "error",
                "error": "Необходим JSON в теле запроса"
            }), 400

        audio_url = data.get("audio_url")
        user_id = data.get("user_id")
        webhook_url = data.get("webhook_url")
        
        if not all([audio_url, user_id, webhook_url]):
            logger.warning("Неполные данные для асинхронной транскрибации")
            return jsonify({
                "status": "error",
                "error": "Необходимы audio_url, user_id и webhook_url"
            }), 400

        task_id = str(uuid.uuid4())
        start_time = time.time()
        logger.info("Начало асинхронной обработки задачи %s", task_id)
        
        def async_task():
            try:
                result, _ = transcribe_audio(audio_url, task_id, user_id)
                result["webhook_url"] = webhook_url
                result["time_start"] = int(start_time)
                result["time_end"] = int(time.time())
                send_webhook_result(webhook_url, result)
            except Exception as e:
                logger.error("Ошибка в асинхронной задаче %s: %s", task_id, str(e))
        
        Thread(target=async_task).start()
        
        response = {
            "status": "started",
            "id": task_id,
            "time_start": int(start_time),
            "webhook_url": webhook_url,
            "user_id": user_id
        }
        
        logger.info("Асинхронная задача %s принята в обработку", task_id)
        return jsonify(response), 202
        
    except Exception as e:
        logger.error("Ошибка в асинхронном обработчике: %s", str(e))
        return jsonify({
            "status": "error",
            "error": "Внутренняя ошибка сервера"
        }), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
