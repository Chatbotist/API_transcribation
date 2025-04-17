from flask import Flask, request, jsonify
from vosk import Model, KaldiRecognizer, SetLogLevel
import subprocess
import os
import requests
import logging
import json
import tempfile

app = Flask(__name__)

# Настройка логов
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Vosk-Transcriber")
SetLogLevel(-1)  # Отключаем лишние логи Vosk

# Конфигурация
MODEL_NAME = "vosk-model-ru-0.42"  # Более точная модель
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"
AUDIO_TEMP_DIR = tempfile.mkdtemp()

def download_model():
    """Скачивает и распаковывает модель Vosk"""
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
    raise RuntimeError("Не удалось инициализировать модель Vosk!")

model = Model(MODEL_NAME)

def preprocess_audio(input_path, output_path):
    """Обработка аудио с шумоподавлением и нормализацией"""
    try:
        ffmpeg_cmd = [
            "ffmpeg",
            "-i", input_path,
            "-af", "highpass=f=200,lowpass=f=3000,afftdn=nf=-25,volume=2.0",
            "-ar", "16000",
            "-ac", "1",
            "-y",
            output_path
        ]
        subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except Exception as e:
        logger.error(f"Ошибка обработки аудио: {str(e)}")
        return False

@app.route("/transcribe", methods=["POST"])
def transcribe():
    try:
        # Получение URL аудио
        data = request.get_json()
        audio_url = data.get("audio_url")
        
        if not audio_url:
            return jsonify({"error": "Параметр 'audio_url' обязателен"}), 400

        logger.info(f"Начата обработка: {audio_url}")

        # Временные файлы
        temp_input = os.path.join(AUDIO_TEMP_DIR, "input.mp3")
        temp_processed = os.path.join(AUDIO_TEMP_DIR, "processed.wav")

        # Скачивание файла
        response = requests.get(audio_url, stream=True)
        with open(temp_input, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024):
                f.write(chunk)

        # Предобработка аудио
        if not preprocess_audio(temp_input, temp_processed):
            return jsonify({"error": "Ошибка обработки аудио"}), 500

        # Транскрибация с улучшенными параметрами
        recognizer = KaldiRecognizer(model, 16000)
        recognizer.SetWords(True)  # Включаем распознавание отдельных слов
        recognizer.SetPartialWords(True)

        with open(temp_processed, "rb") as f:
            while True:
                data = f.read(4000)
                if len(data) == 0:
                    break
                recognizer.AcceptWaveform(data)

        # Получаем и парсим результат
        result = json.loads(recognizer.FinalResult())
        transcription_text = result.get("text", "")

        # Очистка
        for file in [temp_input, temp_processed]:
            if os.path.exists(file):
                os.remove(file)

        return jsonify({
            "text": transcription_text,
            "status": "success"
        })

    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка загрузки: {str(e)}")
        return jsonify({"error": "Ошибка загрузки аудио", "status": "error"}), 400
        
    except subprocess.CalledProcessError as e:
        logger.error(f"Ошибка FFmpeg: {e.stderr.decode()}")
        return jsonify({"error": "Ошибка обработки аудио", "status": "error"}), 500
        
    except Exception as e:
        logger.error(f"Критическая ошибка: {str(e)}")
        return jsonify({"error": "Внутренняя ошибка сервера", "status": "error"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
