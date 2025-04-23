from flask import Flask, request, jsonify, send_from_directory
from vosk import Model, KaldiRecognizer, SetLogLevel
from gtts import gTTS
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
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("Audio-Processor")

# Конфигурация
MODEL_NAME = "vosk-model-small-ru-0.22"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"
CHUNK_SIZE = 4000
SAMPLE_RATE = 16000
MAX_AUDIO_DURATION = 300
MAX_SYNC_PROCESSING_TIME = 55
AUDIO_STORAGE = "temp_audio"
os.makedirs(AUDIO_STORAGE, exist_ok=True)

# Глобальные переменные состояния
SERVER_STATUS = {
    "status": "available",
    "last_check": datetime.utcnow().isoformat(),
    "active_tasks": 0
}

TASKS = {}
tasks_lock = Lock()
model = None

def download_model():
    """Установка модели Vosk"""
    try:
        if not os.path.exists(MODEL_NAME):
            logger.info(f"Скачивание модели {MODEL_NAME}...")
            
            # Скачивание
            os.system(f"wget {MODEL_URL} -O model.zip")
            
            # Распаковка
            os.system("unzip model.zip")
            
            # Автоматическое определение структуры
            if os.path.exists(f"{MODEL_NAME}/am/final.mdl"):
                logger.info("Обнаружена новая структура архива")
            elif os.path.exists(f"{MODEL_NAME}/{MODEL_NAME}/am/final.mdl"):
                logger.info("Обнаружена старая структура - исправляем")
                os.system(f"mv {MODEL_NAME}/{MODEL_NAME}/* {MODEL_NAME}/")
                os.system(f"rm -rf {MODEL_NAME}/{MODEL_NAME}")
            else:
                raise Exception("Не удалось определить структуру архива!")

            os.system("rm model.zip")
            
            # Финальная проверка
            if not os.path.exists(f"{MODEL_NAME}/am/final.mdl"):
                raise Exception("Критические файлы модели отсутствуют!")
            
            logger.info("Модель успешно загружена и проверена")
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
        logger.info("Модель Vosk успешно инициализирована")
    except Exception as e:
        logger.error(f"Ошибка инициализации модели: {str(e)}")
        SERVER_STATUS["status"] = "unavailable"

def cleanup_files(*files):
    """Удаление временных файлов"""
    for file_path in files:
        try:
            if file_path and os.path.exists(file_path):
                if os.path.isdir(file_path):
                    shutil.rmtree(file_path)
                else:
                    os.unlink(file_path)
        except Exception as e:
            logger.warning(f"Ошибка удаления файла {file_path}: {str(e)}")

def convert_to_wav(audio_url):
    """Конвертация аудио в WAV"""
    temp_input = None
    temp_output = None
    try:
        # Скачивание файла
        response = requests.get(audio_url, stream=True)
        response.raise_for_status()
        
        temp_input = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        
        with open(temp_input.name, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        # Конвертация
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
        raise
    finally:
        cleanup_files(temp_input.name if temp_input else None)

def update_task_status(task_id, status, result=None):
    """Обновление статуса задачи"""
    with tasks_lock:
        TASKS[task_id] = {
            "status": status,
            "result": result,
            "last_update": datetime.utcnow().isoformat()
        }

def transcribe_audio(audio_url, task_id, user_id=None):
    """Транскрибация аудио в текст"""
    start_time = time.time()
    wav_file = None
    try:
        SERVER_STATUS["active_tasks"] += 1
        update_task_status(task_id, "processing")
        
        # Конвертация
        wav_file = convert_to_wav(audio_url)

        # Проверка длительности
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

        # Транскрибация
        recognizer = KaldiRecognizer(model, SAMPLE_RATE)
        recognizer.SetWords(True)

        result_text = []
        with open(wav_file, "rb") as f:
            while True:
                data = f.read(CHUNK_SIZE)
                if len(data) == 0:
                    break
                
                if time.time() - start_time > MAX_SYNC_PROCESSING_TIME:
                    raise TimeoutError("Превышено время обработки")
                
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

def generate_audio(text, task_id, user_id=None, tts_params=None):
    """Генерация аудио из текста"""
    start_time = time.time()
    try:
        SERVER_STATUS["active_tasks"] += 1
        update_task_status(task_id, "processing")

        if not text or len(text) > 1000:
            raise ValueError("Текст должен быть от 1 до 1000 символов")

        # Если параметры не переданы, используем базовую генерацию без обработки
        if not tts_params:
            tts = gTTS(text=text, lang='ru')
            filename = f"{uuid.uuid4()}.mp3"
            filepath = os.path.join(AUDIO_STORAGE, filename)
            tts.save(filepath)
            
            audio_url = f"{request.host_url}audio/{filename}"
            
            result_data = {
                "status": "success",
                "audio_url": audio_url,
                "id": task_id,
                "user_id": user_id,
                "time_start": start_time,
                "time_end": time.time(),
                "params": {
                    "message": "Использованы параметры по умолчанию без обработки"
                }
            }
        else:
            # Если параметры переданы, применяем их с обработкой через ffmpeg
            params = {
                'speed': float(tts_params.get('speed', 1.0)),
                'pitch': float(tts_params.get('pitch', 1.0)),
                'volume': float(tts_params.get('volume', 1.0))
            }

            # Генерация исходного аудио
            tts = gTTS(
                text=text,
                lang=tts_params.get('lang', 'ru'),
                slow=tts_params.get('slow', False)
            )
            
            # Сохраняем исходный файл
            raw_file = os.path.join(AUDIO_STORAGE, f"raw_{uuid.uuid4()}.mp3")
            tts.save(raw_file)

            # Обработка через ffmpeg
            processed_file = os.path.join(AUDIO_STORAGE, f"processed_{uuid.uuid4()}.mp3")
            
            ffmpeg_cmd = [
                "ffmpeg",
                "-i", raw_file,
                "-filter:a",
                f"atempo={params['speed']},"  # Скорость
                f"asetrate=44100*{params['pitch']},"  # Высота тона
                f"volume={params['volume']}",  # Громкость
                "-y",
                processed_file
            ]
            
            subprocess.run(ffmpeg_cmd, check=True)
            cleanup_files(raw_file)
            
            audio_url = f"{request.host_url}audio/{os.path.basename(processed_file)}"
            
            result_data = {
                "status": "success",
                "audio_url": audio_url,
                "id": task_id,
                "user_id": user_id,
                "time_start": start_time,
                "time_end": time.time(),
                "params": params
            }

        update_task_status(task_id, "completed", result_data)
        return result_data, 200

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
        SERVER_STATUS["active_tasks"] = max(0, SERVER_STATUS["active_tasks"] - 1)
        SERVER_STATUS["last_check"] = datetime.utcnow().isoformat()

def send_webhook_result(webhook_url, result):
    """Отправка результата на вебхук"""
    try:
        response = requests.post(
            webhook_url,
            json=result,
            timeout=10,
            headers={"Content-Type": "application/json"}
        )
        response.raise_for_status()
    except Exception as e:
        logger.error(f"Ошибка отправки вебхука: {str(e)}")

def cleanup_old_audio():
    """Очистка старых аудиофайлов"""
    while True:
        time.sleep(3600)  # Каждый час
        try:
            now = time.time()
            for f in os.listdir(AUDIO_STORAGE):
                filepath = os.path.join(AUDIO_STORAGE, f)
                if os.path.isfile(filepath) and (now - os.path.getmtime(filepath)) > 3600:
                    os.remove(filepath)
        except Exception as e:
            logger.error(f"Ошибка очистки аудио: {str(e)}")

# Запуск очистки в фоне
Thread(target=cleanup_old_audio, daemon=True).start()

@app.route("/health", methods=["GET"])
def health_check():
    """Проверка состояния сервера"""
    try:
        status = "available" if SERVER_STATUS["status"] == "available" and model else "unavailable"
        return jsonify({
            "status": status,
            "model_loaded": bool(model),
            "last_check": SERVER_STATUS["last_check"],
            "active_tasks": SERVER_STATUS["active_tasks"]
        }), 200 if status == "available" else 503
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route("/taskStatus", methods=["GET"])
def task_status():
    """Проверка статуса задачи"""
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
    """Синхронная транскрибация"""
    try:
        if SERVER_STATUS["status"] != "available" or not model:
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
    """Асинхронная транскрибация"""
    try:
        if SERVER_STATUS["status"] != "available" or not model:
            return jsonify({"status": "error", "error": "Сервер недоступен"}), 503

        data = request.get_json()
        audio_url = data.get("audio_url")
        user_id = data.get("user_id")
        webhook_url = data.get("webhook_url")
        
        if not audio_url or not user_id:
            return jsonify({"status": "error", "error": "Необходимы audio_url и user_id"}), 400

        task_id = str(uuid.uuid4())
        start_time = time.time()
        
        def async_task():
            result, _ = transcribe_audio(audio_url, task_id, user_id)
            if webhook_url:
                result["webhook_url"] = webhook_url
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

@app.route("/textToAudio", methods=["POST"])
def text_to_audio():
    """Синхронное преобразование текста в аудио"""
    try:
        data = request.get_json()
        text = data.get("text")
        user_id = data.get("user_id")
        tts_params = data.get("tts_params")
        
        if not text or not user_id:
            return jsonify({"status": "error", "error": "Необходимы text и user_id"}), 400

        task_id = str(uuid.uuid4())
        result, status_code = generate_audio(text, task_id, user_id, tts_params)
        
        result["time_start"] = int(result["time_start"])
        result["time_end"] = int(result["time_end"])
        
        return jsonify(result), status_code
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route("/textToAudioAsync", methods=["POST"])
def async_text_to_audio():
    """Асинхронное преобразование текста в аудио"""
    try:
        data = request.get_json()
        text = data.get("text")
        user_id = data.get("user_id")
        webhook_url = data.get("webhook_url")
        tts_params = data.get("tts_params")
        
        if not text or not user_id:
            return jsonify({"status": "error", "error": "Необходимы text и user_id"}), 400

        task_id = str(uuid.uuid4())
        start_time = time.time()
        
        def async_task():
            result, _ = generate_audio(text, task_id, user_id, tts_params)
            if webhook_url:
                result["webhook_url"] = webhook_url
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

@app.route("/audio/<filename>", methods=["GET"])
def get_audio(filename):
    """Получение сгенерированного аудио"""
    try:
        return send_from_directory(AUDIO_STORAGE, filename)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 404

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
