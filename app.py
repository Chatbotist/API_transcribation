import os
import json
import tempfile
import threading
import requests
from flask import Flask, request, jsonify
from vosk import Model, KaldiRecognizer

app = Flask(__name__)

# Конфигурация
MODEL_NAME = "vosk-model-ru-0.42"
MODEL_PATH = os.path.join(os.getcwd(), MODEL_NAME)
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"
SAMPLE_RATE = 16000
CHUNK_SIZE = 4000

# Загружаем модель
if not os.path.exists(MODEL_PATH):
    os.system(f"wget {MODEL_URL} -O model.zip")
    os.system(f"unzip model.zip -d {MODEL_PATH}")
    os.system("rm model.zip")

model = Model(MODEL_PATH)

def send_result(webhook_url, user_id, text, error=None):
    """Отправка результата на вебхук"""
    payload = {
        "user_id": user_id,
        "text": text,
        "status": "failed" if error else "completed"
    }
    if error:
        payload["error"] = str(error)
    
    try:
        requests.post(webhook_url, json=payload, timeout=5)
    except Exception as e:
        print(f"Ошибка отправки вебхука: {str(e)}")

def process_audio(audio_url, webhook_url, user_id):
    """Обработка аудио в фоновом режиме"""
    try:
        # Скачивание и сохранение во временный файл
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_wav:
            response = requests.get(audio_url, stream=True)
            for chunk in response.iter_content(chunk_size=1024):
                temp_wav.write(chunk)
            temp_path = temp_wav.name

        # Транскрибация
        recognizer = KaldiRecognizer(model, SAMPLE_RATE)
        result_text = []
        
        with open(temp_path, "rb") as f:
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

        os.unlink(temp_path)
        send_result(webhook_url, user_id, " ".join(result_text))

    except Exception as e:
        send_result(webhook_url, user_id, "", error=str(e))

@app.route("/transcribe", methods=["POST"])
def transcribe():
    """Основной endpoint API"""
    data = request.get_json()
    
    # Валидация входных данных
    if not data or not all(k in data for k in ["audio_url", "webhook_url", "user_id"]):
        return jsonify({"error": "Требуются параметры: audio_url, webhook_url, user_id"}), 400

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
