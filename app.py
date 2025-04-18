from flask import Flask, request, jsonify
from vosk import Model, KaldiRecognizer
import os
import tempfile
import requests
import json
import subprocess
import threading

app = Flask(__name__)

# Конфигурация
MODEL_NAME = "vosk-model-small-ru-0.22"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"
MODEL_PATH = os.path.join(os.getcwd(), MODEL_NAME)
SAMPLE_RATE = 16000
CHUNK_SIZE = 4000

# Проверка и загрузка модели
if not os.path.exists(MODEL_PATH):
    print(f"Скачивание модели {MODEL_NAME}...")
    os.system(f"wget {MODEL_URL} -O model.zip")
    os.system(f"unzip model.zip -d {MODEL_PATH}")
    os.system("rm model.zip")
    
    # Проверка правильности распаковки
    if not os.path.exists(os.path.join(MODEL_PATH, "am", "final.mdl")):
        raise Exception("Модель распакована неправильно!")

print("Инициализация модели...")
model = Model(MODEL_PATH)

def send_to_webhook(webhook_url, data):
    try:
        requests.post(webhook_url, json=data, timeout=5)
    except Exception as e:
        print(f"Ошибка отправки вебхука: {str(e)}")

def process_audio(audio_url, webhook_url, user_id):
    try:
        # Скачивание аудио
        response = requests.get(audio_url, stream=True)
        temp_audio = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        
        with temp_audio as f:
            for chunk in response.iter_content(chunk_size=1024):
                f.write(chunk)
        
        # Транскрибация
        recognizer = KaldiRecognizer(model, SAMPLE_RATE)
        text_parts = []
        
        with open(temp_audio.name, "rb") as f:
            while True:
                data = f.read(CHUNK_SIZE)
                if len(data) == 0:
                    break
                if recognizer.AcceptWaveform(data):
                    result = json.loads(recognizer.Result())
                    if result.get("text"):
                        text_parts.append(result["text"])
        
        final_result = json.loads(recognizer.FinalResult())
        if final_result.get("text"):
            text_parts.append(final_result["text"])
        
        # Отправка результата
        send_to_webhook(webhook_url, {
            "user_id": user_id,
            "text": " ".join(text_parts),
            "status": "success"
        })
        
    except Exception as e:
        send_to_webhook(webhook_url, {
            "user_id": user_id,
            "error": str(e),
            "status": "error"
        })
    finally:
        if 'temp_audio' in locals():
            os.unlink(temp_audio.name)

@app.route("/transcribe", methods=["POST"])
def transcribe():
    data = request.get_json()
    
    # Валидация входных данных
    required_fields = ["audio_url", "webhook_url", "user_id"]
    if not all(field in data for field in required_fields):
        return jsonify({"error": "Не хватает обязательных параметров"}), 400
    
    # Запуск обработки в фоне
    thread = threading.Thread(
        target=process_audio,
        args=(data["audio_url"], data["webhook_url"], data["user_id"])
    )
    thread.start()
    
    return jsonify({
        "status": "processing_started",
        "message": "Аудио принято в обработку"
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
