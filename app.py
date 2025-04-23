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
import re

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
AUDIO_STORAGE = "temp_audio"
os.makedirs(AUDIO_STORAGE, exist_ok=True)
FILE_LIFETIME = 300  # 5 минут в секундах
MAX_TEXT_LENGTH = 1000  # Максимальная длина текста

# Разрешенные символы
ALLOWED_CHARS = r"[^a-zA-Zа-яА-ЯёЁ0-9\s.,!?;:-—()\"']"

TASKS = {}
tasks_lock = Lock()
model = None

def clean_text(text):
    """Очистка текста от нежелательных символов"""
    if not text:
        return ""
    
    text = text[:MAX_TEXT_LENGTH]
    cleaned = re.sub(ALLOWED_CHARS, '', text)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned

def download_model():
    """Установка модели Vosk"""
    try:
        if not os.path.exists(MODEL_NAME):
            logger.info(f"Скачивание модели {MODEL_NAME}...")
            os.system(f"wget {MODEL_URL} -O model.zip")
            os.system("unzip model.zip")
            
            if os.path.exists(f"{MODEL_NAME}/am/final.mdl"):
                logger.info("Новая структура архива")
            elif os.path.exists(f"{MODEL_NAME}/{MODEL_NAME}/am/final.mdl"):
                logger.info("Старая структура - исправляем")
                os.system(f"mv {MODEL_NAME}/{MODEL_NAME}/* {MODEL_NAME}/")
                os.system(f"rm -rf {MODEL_NAME}/{MODEL_NAME}")
            else:
                raise Exception("Неверная структура архива!")

            os.system("rm model.zip")
            
            if not os.path.exists(f"{MODEL_NAME}/am/final.mdl"):
                raise Exception("Критические файлы отсутствуют!")
            
            logger.info("Модель успешно загружена")
        return True
    except Exception as e:
        logger.error(f"Ошибка загрузки модели: {str(e)}")
        return False

# Инициализация модели
if not download_model():
    logger.error("Не удалось загрузить модель Vosk!")
else:
    try:
        model = Model(MODEL_NAME)
        logger.info("Модель Vosk успешно инициализирована")
    except Exception as e:
        logger.error(f"Ошибка инициализации модели: {str(e)}")

def cleanup_files(*files):
    """Удаление временных файлов"""
    for file_path in files:
        try:
            if file_path and os.path.exists(file_path):
                os.unlink(file_path)
        except Exception as e:
            logger.warning(f"Ошибка удаления файла {file_path}: {str(e)}")

def update_task_status(task_id, status, result=None):
    """Обновление статуса задачи"""
    with tasks_lock:
        TASKS[task_id] = {
            "status": status,
            "result": result,
            "last_update": datetime.utcnow().isoformat()
        }

def apply_audio_effects(input_file, output_file, params):
    """Применение аудио эффектов через FFmpeg"""
    try:
        ffmpeg_cmd = [
            "ffmpeg",
            "-i", input_file,
            "-map_metadata", "-1",
            "-c:a", "libopus",
            "-b:a", "64k",
            "-ar", "48000",
            "-ac", "1",
            "-vbr", "on",
            "-compression_level", "10",
            "-application", "voip",
            "-filter:a", 
            f"atempo={params['speed']},asetrate=44100*{params['pitch']},volume={params['volume']}",
            "-y",
            output_file
        ]
        
        subprocess.run(ffmpeg_cmd, check=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
        return True
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode('utf-8') if e.stderr else str(e)
        logger.error(f"FFmpeg error: {error_msg}")
        return False
    except Exception as e:
        logger.error(f"Audio effects error: {str(e)}")
        return False

def generate_audio(text, task_id, user_id=None, tts_params=None):
    """Генерация аудио из текста для Telegram Voice"""
    start_time = time.time()
    temp_file = None
    
    try:
        update_task_status(task_id, "processing")

        if not text:
            raise ValueError("Текст не может быть пустым")

        text = clean_text(text)
        
        # Параметры по умолчанию
        params = {
            'lang': 'ru',
            'slow': False,
            'speed': 1.0,
            'pitch': 1.0,
            'volume': 1.0,
            'format': 'ogg'
        }

        # Обновляем параметры из запроса
        if isinstance(tts_params, dict):
            for key in tts_params:
                if key in params:
                    params[key] = tts_params[key]

        # Валидация параметров
        params['speed'] = max(0.5, min(2.0, float(params['speed'])))
        params['pitch'] = max(0.5, min(1.5, float(params['pitch'])))
        params['volume'] = max(0.1, min(1.0, float(params['volume'])))
        params['format'] = params['format'].lower() if params['format'].lower() in ['ogg', 'mp3'] else 'ogg'

        # Генерация имени файла
        filename = f"voice_{uuid.uuid4().hex}.{params['format']}"
        filepath = os.path.join(AUDIO_STORAGE, filename)

        # Генерация аудио через gTTS
        tts = gTTS(
            text=text,
            lang=params['lang'],
            slow=params['slow']
        )
        
        # Сохраняем временный файл
        temp_file = os.path.join(AUDIO_STORAGE, f"temp_{uuid.uuid4()}.mp3")
        tts.save(temp_file)

        # Применяем аудио эффекты
        if not apply_audio_effects(temp_file, filepath, params):
            raise Exception("Ошибка применения аудио эффектов")

        # Запланировать удаление файла
        Thread(target=lambda: (
            time.sleep(FILE_LIFETIME),
            os.path.exists(filepath) and os.remove(filepath)
        )).start()

        audio_url = f"{request.host_url}audio/{filename}"
        
        result_data = {
            "status": "success",
            "audio_url": audio_url,
            "id": task_id,
            "user_id": user_id,
            "time_operation": round(time.time() - start_time, 2),
            "params": params
        }

        update_task_status(task_id, "completed", result_data)
        return result_data, 200

    except Exception as e:
        error_data = {
            "status": "error",
            "error": str(e),
            "id": task_id,
            "time_operation": round(time.time() - start_time, 2)
        }
        update_task_status(task_id, "failed", error_data)
        return error_data, 400
        
    finally:
        cleanup_files(temp_file)

@app.route("/textToAudio", methods=["POST"])
def text_to_audio():
    """Синхронная генерация аудио"""
    try:
        data = request.get_json()
        if not data or not isinstance(data, dict):
            return jsonify({"status": "error", "error": "Неверный формат данных"}), 400

        text = data.get("text")
        user_id = data.get("user_id")
        tts_params = data.get("tts_params", {})
        
        if not text:
            return jsonify({"status": "error", "error": "Текст не может быть пустым"}), 400

        task_id = str(uuid.uuid4())
        result, status_code = generate_audio(text, task_id, user_id, tts_params)
        return jsonify(result), status_code
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
