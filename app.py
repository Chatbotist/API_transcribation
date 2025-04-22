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
MAX_SYNC_PROCESSING_TIME = 55  # Максимальное время для синхронного ответа (сек)

def download_model():
    """Скачивает и распаковывает улучшенную модель Vosk"""
    try:
        if not os.path.exists(MODEL_NAME):
            logger.info(f"Скачивание улучшенной модели {MODEL_NAME}...")
            
            # Скачивание
            os.system(f"wget {MODEL_URL} -O model.zip")
            
            # Распаковка
            os.system("unzip model.zip")
            
            # Автоматическое определение структуры архива
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

def transcribe_audio(audio_url, processing_start_time):
    """Основная функция транскрибации аудио"""
    try:
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
            return {"error": f"Аудио слишком длинное (максимум {MAX_AUDIO_DURATION//60} минут)"}, 400

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
                
                if time.time() - processing_start_time > MAX_SYNC_PROCESSING_TIME:
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

        return {
            "text": " ".join(result_text),
            "processing_time": round(time.time() - processing_start_time, 2),
            "audio_duration": round(duration, 2)
        }, None

    except TimeoutError as e:
        logger.error(f"Таймаут обработки: {str(e)}")
        return {"error": "Превышено время обработки"}, 408
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка загрузки: {str(e)}")
        return {"error": "Ошибка загрузки аудио"}, 400
        
    except subprocess.CalledProcessError as e:
        logger.error(f"Ошибка FFmpeg: {e.stderr.decode()}")
        return {"error": "Ошибка обработки аудио"}, 500
        
    except Exception as e:
        logger.error(f"Критическая ошибка: {str(e)}")
        return {"error": "Внутренняя ошибка сервера"}, 500

def send_webhook_result(webhook_url, result, user_id=None):
    """Отправляет результат на вебхук"""
    try:
        payload = {
            "result": result,
            "metadata": {
                "user_id": user_id,
                "timestamp": time.time()
            }
        }
        response = requests.post(webhook_url, json=payload, timeout=10)
        response.raise_for_status()
        logger.info(f"Результат успешно отправлен на вебхук: {webhook_url}")
    except Exception as e:
        logger.error(f"Ошибка отправки на вебхук: {str(e)}")

@app.route("/transcribe", methods=["POST"])
def transcribe():
    start_time = time.time()
    try:
        data = request.get_json()
        
        # Проверка обязательных параметров
        audio_url = data.get("audio_url")
        webhook_url = data.get("webhook_url")
        user_id = data.get("user_id")
        
        if not audio_url:
            return jsonify({"error": "Параметр 'audio_url' обязателен"}), 400

        # Асинхронная обработка с вебхуком
        if webhook_url:
            # Генерируем ID задачи для отслеживания
            task_id = str(uuid.uuid4())
            
            # Запускаем в отдельном потоке
            def async_task():
                result, status_code = transcribe_audio(audio_url, time.time())
                if status_code:
                    result["status_code"] = status_code
                send_webhook_result(webhook_url, result, user_id)
            
            Thread(target=async_task).start()
            
            return jsonify({
                "message": "Обработка начата, результат будет отправлен на вебхук",
                "task_id": task_id,
                "webhook_url": webhook_url
            }), 202
        
        # Синхронная обработка
        result, status_code = transcribe_audio(audio_url, start_time)
        if status_code:
            return jsonify(result), status_code
        return jsonify(result)

    except Exception as e:
        logger.error(f"Ошибка в основном обработчике: {str(e)}")
        return jsonify({"error": "Внутренняя ошибка сервера"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
