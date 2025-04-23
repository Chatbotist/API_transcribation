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
MAX_TEXT_LENGTH = 5000  # Увеличенный лимит до 5000 символов

# Символы для удаления
CHARS_TO_REMOVE = ["#", "/", "\\"]

TASKS = {}
tasks_lock = Lock()
model = None

def clean_text(text):
    """Очистка текста от указанных символов"""
    if not text:
        return ""
    
    # Удаляем только указанные символы
    for char in CHARS_TO_REMOVE:
        text = text.replace(char, '')
    
    # Обрезаем текст до максимальной длины
    text = text[:MAX_TEXT_LENGTH]
    
    # Заменяем множественные пробелы на один
    text = re.sub(r'\s+', ' ', text).strip()
    return text

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

def get_ffmpeg_params(format_type):
    """Возвращает параметры FFmpeg для разных форматов"""
    formats = {
        'ogg': {
            'codec': 'libopus',
            'options': ['-ar', '48000', '-ac', '1', '-vbr', 'on', '-compression_level', '10', '-application', 'voip'],
            'mimetype': 'audio/ogg; codecs=opus'
        },
        'mp3': {
            'codec': 'libmp3lame',
            'options': ['-ar', '44100', '-ac', '2', '-q:a', '2'],
            'mimetype': 'audio/mpeg'
        },
        'wav': {
            'codec': 'pcm_s16le',
            'options': ['-ar', '44100', '-ac', '2'],
            'mimetype': 'audio/wav'
        },
        'm4a': {
            'codec': 'aac',
            'options': ['-ar', '44100', '-ac', '2', '-b:a', '192k'],
            'mimetype': 'audio/mp4'
        }
    }
    return formats.get(format_type.lower(), formats['ogg'])

def apply_audio_effects(input_file, output_file, params, format_type):
    """Применение аудио эффектов через FFmpeg"""
    try:
        ffmpeg_params = get_ffmpeg_params(format_type)
        
        ffmpeg_cmd = [
            "ffmpeg",
            "-i", input_file,
            "-map_metadata", "-1",
            "-c:a", ffmpeg_params['codec'],
            *ffmpeg_params['options'],
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

def transcribe_audio(audio_url, task_id, user_id=None):
    """Транскрибация аудио в текст"""
    start_time = time.time()
    wav_file = None
    temp_input = None
    
    try:
        update_task_status(task_id, "processing")
        
        # Скачивание и конвертация
        temp_input = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        response = requests.get(audio_url, stream=True)
        response.raise_for_status()
        
        with open(temp_input.name, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        wav_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav").name
        subprocess.run([
            "ffmpeg", "-i", temp_input.name,
            "-ar", str(SAMPLE_RATE), "-ac", "1", "-y", wav_file
        ], check=True)

        # Проверка длительности
        duration = float(subprocess.run([
            "ffprobe", "-i", wav_file,
            "-show_entries", "format=duration",
            "-v", "quiet", "-of", "csv=p=0"
        ], capture_output=True, text=True).stdout)
        
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
                
                if recognizer.AcceptWaveform(data):
                    result = json.loads(recognizer.Result())
                    if result.get("text"):
                        result_text.append(result["text"])

        final_result = json.loads(recognizer.FinalResult())
        if final_result.get("text"):
            result_text.append(final_result["text"])

        full_text = " ".join(result_text)
        result_data = {
            "status": "success",
            "text": full_text,
            "user_id": user_id,
            "id": task_id,
            "time_operation": round(time.time() - start_time, 2),
            "is_full": len(full_text) > 0,
            "audio_duration": duration
        }

        update_task_status(task_id, "completed", result_data)
        return result_data, 200 if len(full_text) > 0 else 201

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
        cleanup_files(wav_file, temp_input.name if temp_input else None)

def generate_audio(text, task_id, user_id=None, tts_params=None):
    """Генерация аудио из текста"""
    start_time = time.time()
    temp_file = None
    
    try:
        update_task_status(task_id, "processing")

        if not text:
            raise ValueError("Текст не может быть пустым")

        text = clean_text(text)
        
        # Параметры по умолчанию (оптимизированы для Telegram Voice)
        params = {
            'lang': 'ru',
            'slow': False,
            'speed': 1.0,
            'pitch': 1.0,
            'volume': 1.0,
            'format': 'ogg'  # OGG по умолчанию для Telegram
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
        params['format'] = params['format'].lower() if params['format'].lower() in ['ogg', 'mp3', 'wav', 'm4a'] else 'ogg'

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
        if not apply_audio_effects(temp_file, filepath, params, params['format']):
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

def cleanup_old_audio():
    """Фоновая задача для очистки старых файлов"""
    while True:
        time.sleep(60)
        try:
            now = time.time()
            for f in os.listdir(AUDIO_STORAGE):
                filepath = os.path.join(AUDIO_STORAGE, f)
                if os.path.isfile(filepath) and (now - os.path.getmtime(filepath)) > FILE_LIFETIME:
                    os.remove(filepath)
        except Exception as e:
            logger.error(f"Ошибка очистки файлов: {str(e)}")

# Запускаем фоновую задачу очистки
Thread(target=cleanup_old_audio, daemon=True).start()

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
        if not model:
            return jsonify({"status": "error", "error": "Модель не загружена"}), 503

        data = request.get_json()
        audio_url = data.get("audio_url")
        user_id = data.get("user_id")
        
        if not audio_url or not user_id:
            return jsonify({"status": "error", "error": "Необходимы audio_url и user_id"}), 400

        task_id = str(uuid.uuid4())
        result, status_code = transcribe_audio(audio_url, task_id, user_id)
        return jsonify(result), status_code
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route("/transcribeAsync", methods=["POST"])
def async_transcribe():
    """Асинхронная транскрибация"""
    try:
        if not model:
            return jsonify({"status": "error", "error": "Модель не загружена"}), 503

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
                try:
                    requests.post(webhook_url, json=result, timeout=10)
                except Exception as e:
                    logger.error(f"Ошибка отправки webhook: {str(e)}")
        
        Thread(target=async_task).start()
        
        return jsonify({
            "status": "started",
            "id": task_id,
            "time_operation": round(time.time() - start_time, 2),
            "webhook_url": webhook_url,
            "user_id": user_id
        }), 202
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route("/textToAudio", methods=["POST"])
def text_to_audio():
    """Синхронная генерация аудио"""
    try:
        data = request.get_json()
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

@app.route("/textToAudioAsync", methods=["POST"])
def async_text_to_audio():
    """Асинхронная генерация аудио"""
    try:
        data = request.get_json()
        text = data.get("text")
        user_id = data.get("user_id")
        webhook_url = data.get("webhook_url")
        tts_params = data.get("tts_params", {})
        
        if not text:
            return jsonify({"status": "error", "error": "Текст не может быть пустым"}), 400

        task_id = str(uuid.uuid4())
        start_time = time.time()
        
        def async_task():
            result, _ = generate_audio(text, task_id, user_id, tts_params)
            if webhook_url:
                result["webhook_url"] = webhook_url
                try:
                    requests.post(webhook_url, json=result, timeout=10)
                except Exception as e:
                    logger.error(f"Ошибка отправки webhook: {str(e)}")
        
        Thread(target=async_task).start()
        
        return jsonify({
            "status": "started",
            "id": task_id,
            "time_operation": round(time.time() - start_time, 2),
            "webhook_url": webhook_url,
            "user_id": user_id
        }), 202
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route("/audio/<filename>", methods=["GET"])
def get_audio(filename):
    """Получение аудиофайла"""
    try:
        # Определяем Content-Type по расширению файла
        ext = filename.split('.')[-1].lower()
        ffmpeg_params = get_ffmpeg_params(ext)
        mimetype = ffmpeg_params['mimetype']
        
        response = send_from_directory(AUDIO_STORAGE, filename, mimetype=mimetype)
        response.headers['Content-Disposition'] = f'inline; filename="{filename}"'
        return response
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 404

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
