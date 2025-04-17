from flask import Flask, request, jsonify
from vosk import Model, KaldiRecognizer
import subprocess
import os
import requests
import logging

app = Flask(__name__)

# Настройка логов
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Vosk-Transcriber")

# Конфигурация
MODEL_NAME = "vosk-model-small-ru-0.22"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"
AUDIO_TEMP_IN = "temp_audio.mp3"
AUDIO_TEMP_OUT = "temp_audio.wav"

def download_model():
    """Скачивает и распаковывает модель Vosk с исправлением структуры"""
    try:
        if not os.path.exists(MODEL_NAME):
            logger.info(f"Скачивание модели {MODEL_NAME}...")
            
            # Скачивание
            os.system(f"wget {MODEL_URL} -O model.zip")
            
            # Распаковка и исправление структуры
            os.system("unzip model.zip")
            os.system(f"mv {MODEL_NAME}/{MODEL_NAME}/* {MODEL_NAME}/")
            os.system(f"rm -rf {MODEL_NAME}/{MODEL_NAME}")
            os.system("rm model.zip")
            
            # Проверка наличия ключевых файлов
            if not os.path.exists(f"{MODEL_NAME}/am/final.mdl"):
                raise Exception("Модель не распаковалась корректно!")
            
            logger.info("Модель успешно загружена и проверена")
        return True
    except Exception as e:
        logger.error(f"Ошибка загрузки модели: {str(e)}")
        return False

# Инициализация модели
if not download_model():
    raise RuntimeError("Не удалось загрузить модель Vosk!")

model = Model(MODEL_NAME)

def convert_to_wav(audio_url):
    """Конвертирует аудио в WAV формат"""
    try:
        # Скачивание файла
        response = requests.get(audio_url, stream=True)
        with open(AUDIO_TEMP_IN, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024):
                f.write(chunk)

        # Конвертация через FFmpeg
        ffmpeg_cmd = [
            "ffmpeg",
            "-i", AUDIO_TEMP_IN,
            "-ar", "16000",
            "-ac", "1",
            "-y",  # Перезаписать если существует
            AUDIO_TEMP_OUT
        ]
        subprocess.run(ffmpeg_cmd, check=True, capture_output=True)
        
        return AUDIO_TEMP_OUT

    except Exception as e:
        logger.error(f"Ошибка конвертации: {str(e)}")
        raise

@app.route("/transcribe", methods=["POST"])
def transcribe():
    try:
        # Получение URL аудио
        data = request.get_json()
        audio_url = data.get("audio_url")
        
        if not audio_url:
            return jsonify({"error": "Не указан audio_url"}), 400

        logger.info(f"Обработка аудио: {audio_url}")

        # Конвертация аудио
        wav_file = convert_to_wav(audio_url)

        # Транскрибация
        recognizer = KaldiRecognizer(model, 16000)
        with open(wav_file, "rb") as f:
            while True:
                data = f.read(4000)
                if len(data) == 0:
                    break
                recognizer.AcceptWaveform(data)

        result = recognizer.FinalResult()

        # Очистка временных файлов
        for file in [AUDIO_TEMP_IN, AUDIO_TEMP_OUT]:
            if os.path.exists(file):
                os.remove(file)

        return jsonify({"text": result})

    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка загрузки аудио: {str(e)}")
        return jsonify({"error": "Не удалось загрузить аудио"}), 400
        
    except subprocess.CalledProcessError as e:
        logger.error(f"Ошибка FFmpeg: {e.stderr.decode()}")
        return jsonify({"error": "Ошибка обработки аудио"}), 500
        
    except Exception as e:
        logger.error(f"Неизвестная ошибка: {str(e)}")
        return jsonify({"error": "Внутренняя ошибка сервера"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
