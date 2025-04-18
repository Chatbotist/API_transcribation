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

app = Flask(__name__)
SetLogLevel(-1)  # Отключаем лишние логи Vosk

# Настройка логов
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Vosk-Transcriber")

# Конфигурация
MODEL_NAME = "vosk-model-ru-0.42"  # Более точная модель
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"
CHUNK_SIZE = 4000
SAMPLE_RATE = 16000
MAX_AUDIO_DURATION = 300  # 5 минут (ограничение обработки)

def download_model():
    """Скачивает и распаковывает улучшенную модель Vosk"""
    try:
        if not os.path.exists(MODEL_NAME):
            logger.info(f"Скачивание улучшенной модели {MODEL_NAME}...")
            
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

def process_audio_chunk(recognizer, audio_data):
    """Обрабатывает кусок аудио"""
    if recognizer.AcceptWaveform(audio_data):
        return json.loads(recognizer.Result())
    return None

def convert_to_wav(audio_url, output_file):
    """Конвертирует аудио в WAV с шумоподавлением"""
    try:
        # Скачивание файла
        response = requests.get(audio_url, stream=True)
        temp_input = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        
        with open(temp_input.name, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024):
                f.write(chunk)

        # Конвертация с шумоподавлением
        ffmpeg_cmd = [
            "ffmpeg",
            "-i", temp_input.name,
            "-af", "arnndn=m=vosk-model-ru-0.42/rnnoise.rnn",  # Шумоподавление
            "-ar", str(SAMPLE_RATE),
            "-ac", "1",
            "-y",
            output_file
        ]
        subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        os.unlink(temp_input.name)
        return output_file

    except Exception as e:
        logger.error(f"Ошибка конвертации: {str(e)}")
        raise

@app.route("/transcribe", methods=["POST"])
def transcribe():
    start_time = time.time()
    try:
        data = request.get_json()
        audio_url = data.get("audio_url")
        
        if not audio_url:
            return jsonify({"error": "Параметр 'audio_url' обязателен"}), 400

        logger.info(f"Начата обработка: {audio_url}")

        # Создаем временные файлы
        temp_wav = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        temp_wav.close()

        # Конвертация с шумоподавлением
        wav_file = convert_to_wav(audio_url, temp_wav.name)

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
            os.unlink(wav_file)
            return jsonify({"error": f"Аудио слишком длинное (максимум {MAX_AUDIO_DURATION//60} минут)"}), 400

        # Настройка распознавателя
        recognizer = KaldiRecognizer(model, SAMPLE_RATE)
        recognizer.SetWords(True)  # Для лучшего распознавания слов

        # Поточная обработка аудио
        result_text = []
        with open(wav_file, "rb") as f:
            while True:
                data = f.read(CHUNK_SIZE)
                if len(data) == 0:
                    break
                
                if time.time() - start_time > 55:  # Ограничение 60 сек
                    raise TimeoutError("Превышено время обработки")
                
                if recognizer.AcceptWaveform(data):
                    result = json.loads(recognizer.Result())
                    if result.get("text"):
                        result_text.append(result["text"])

        # Финализация результатов
        final_result = json.loads(recognizer.FinalResult())
        if final_result.get("text"):
            result_text.append(final_result["text"])

        # Очистка
        os.unlink(wav_file)

        return jsonify({
            "text": " ".join(result_text),
            "processing_time": round(time.time() - start_time, 2),
            "audio_duration": round(duration, 2)
        })

    except TimeoutError as e:
        logger.error(f"Таймаут обработки: {str(e)}")
        return jsonify({"error": "Превышено время обработки"}), 408
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка загрузки: {str(e)}")
        return jsonify({"error": "Ошибка загрузки аудио"}), 400
        
    except subprocess.CalledProcessError as e:
        logger.error(f"Ошибка FFmpeg: {e.stderr.decode()}")
        return jsonify({"error": "Ошибка обработки аудио"}), 500
        
    except Exception as e:
        logger.error(f"Критическая ошибка: {str(e)}")
        return jsonify({"error": "Внутренняя ошибка сервера"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
