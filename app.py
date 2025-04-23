from flask import Flask, request, jsonify, send_from_directory
from gtts import gTTS
import subprocess
import os
import logging
import uuid
import time
from threading import Thread
import re

app = Flask(__name__)

# Настройка логов
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("Audio-Processor")

# Конфигурация
AUDIO_STORAGE = "temp_audio"
os.makedirs(AUDIO_STORAGE, exist_ok=True)
FILE_LIFETIME = 300  # 5 минут в секундах
MAX_TEXT_LENGTH = 1000  # Максимальная длина текста

# Разрешенные символы
ALLOWED_CHARS = r"[^a-zA-Zа-яА-ЯёЁ0-9\s.,!?;:-—()\"']"

def clean_text(text):
    """Очистка текста от нежелательных символов"""
    if not text:
        return ""
    
    text = text[:MAX_TEXT_LENGTH]
    cleaned = re.sub(ALLOWED_CHARS, '', text)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned

def cleanup_files(*files):
    """Удаление временных файлов"""
    for file_path in files:
        try:
            if file_path and os.path.exists(file_path):
                os.unlink(file_path)
        except Exception as e:
            logger.warning(f"Ошибка удаления файла {file_path}: {str(e)}")

def generate_audio(text, user_id=None, tts_params=None):
    """Генерация аудио из текста для Telegram Voice"""
    start_time = time.time()
    temp_file = None
    
    try:
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
            params.update({k: v for k, v in tts_params.items() if k in params})

        # Валидация параметров
        params['speed'] = max(0.5, min(2.0, float(params['speed'])))
        params['pitch'] = max(0.5, min(1.5, float(params['pitch'])))
        params['volume'] = max(0.1, min(1.0, float(params['volume'])))
        params['format'] = params['format'].lower() if params['format'].lower() in ['ogg', 'mp3'] else 'ogg'

        # Генерация имени файла
        filename = f"voice_{uuid.uuid4().hex}.{params['format']}"
        filepath = os.path.join(AUDIO_STORAGE, filename)

        # Генерация аудио через gTTS
        tts = gTTS(text=text, lang=params['lang'], slow=params['slow'])
        
        # Сохраняем временный файл
        temp_file = os.path.join(AUDIO_STORAGE, f"temp_{uuid.uuid4()}.mp3")
        tts.save(temp_file)

        # Конвертация в OGG/Opus с правильным расположением параметров
        ffmpeg_cmd = [
            "ffmpeg",
            "-i", temp_file,
            "-map_metadata", "-1",  # Правильное расположение параметра удаления метаданных
            "-c:a", "libopus",
            "-b:a", "64k",
            "-ar", "48000",
            "-ac", "1",
            "-vbr", "on",
            "-compression_level", "10",
            "-application", "voip",
            "-y",
            filepath
        ]

        # Запуск конвертации
        subprocess.run(ffmpeg_cmd, check=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE)

        # Запланировать удаление файла
        Thread(target=lambda: (
            time.sleep(FILE_LIFETIME),
            os.path.exists(filepath) and os.remove(filepath)
        )).start()

        audio_url = f"{request.host_url}audio/{filename}"
        
        return {
            "status": "success",
            "audio_url": audio_url,
            "time_operation": round(time.time() - start_time, 2),
            "params": params
        }, 200

    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode('utf-8') if e.stderr else str(e)
        logger.error(f"FFmpeg error: {error_msg}")
        return {
            "status": "error",
            "error": "Ошибка обработки аудио",
            "time_operation": round(time.time() - start_time, 2)
        }, 400
        
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        return {
            "status": "error",
            "error": str(e),
            "time_operation": round(time.time() - start_time, 2)
        }, 400
        
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

@app.route("/textToAudio", methods=["POST"])
def text_to_audio():
    """Синхронная генерация аудио"""
    try:
        # Получаем данные в правильном формате
        data = request.get_json()
        if isinstance(data, list):
            # Поддержка старого формата [text, user_id, params]
            if len(data) >= 3:
                text = data[0]
                user_id = data[1]
                tts_params = data[2] if len(data) > 2 else {}
            else:
                return jsonify({"status": "error", "error": "Неверный формат данных"}), 400
        else:
            # Новый формат {text, user_id, tts_params}
            text = data.get("text")
            user_id = data.get("user_id")
            tts_params = data.get("tts_params", {})
        
        if not text:
            return jsonify({"status": "error", "error": "Текст не может быть пустым"}), 400

        result, status_code = generate_audio(text, user_id, tts_params)
        return jsonify(result), status_code
        
    except Exception as e:
        logger.error(f"Ошибка в обработке запроса: {str(e)}")
        return jsonify({
            "status": "error", 
            "error": str(e),
            "time_operation": 0
        }), 500

@app.route("/audio/<filename>", methods=["GET"])
def get_audio(filename):
    """Получение аудиофайла"""
    try:
        if filename.endswith('.ogg'):
            mimetype = 'audio/ogg; codecs=opus'
        elif filename.endswith('.mp3'):
            mimetype = 'audio/mpeg'
        else:
            mimetype = 'application/octet-stream'
        
        response = send_from_directory(AUDIO_STORAGE, filename, mimetype=mimetype)
        response.headers['Content-Disposition'] = f'inline; filename="{filename}"'
        return response
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 404

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
