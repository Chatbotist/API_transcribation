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
