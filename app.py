from flask import Flask, request, jsonify
from vosk import Model, KaldiRecognizer
import os
import tempfile
import requests
import json
import threading

app = Flask(__name__)

# Конфигурация
MODEL_NAME = "vosk-model-small-ru-0.22"  # Более легкая модель
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"
MODEL_PATH = os.path.join(os.getcwd(), MODEL_NAME)

# Загрузка модели
if not os.path.exists(MODEL_PATH):
    os.system(f"wget {MODEL_URL} -O model.zip")
    os.system(f"unzip model.zip -d {MODEL_PATH}")
    os.system("rm model.zip")

model = Model(MODEL_PATH)

def process_audio(audio_url, webhook_url, user_id):
    try:
        # Скачивание аудио
        response = requests.get(audio_url, stream=True)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            for chunk in response.iter_content(chunk_size=1024):
                f.write(chunk)
            temp_path = f.name

        # Транскрибация
        recognizer = KaldiRecognizer(model, 16000)
        text_parts = []
        
        with open(temp_path, "rb") as f:
            while True:
                data = f.read(4000)
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
        requests.post(webhook_url, json={
            "user_id": user_id,
            "text": " ".join(text_parts),
            "status": "success"
        })

    except Exception as e:
        requests.post(webhook_url, json={
            "user_id": user_id,
            "error": str(e),
            "status": "error"
        })
    finally:
        if 'temp_path' in locals():
            os.unlink(temp_path)

@app.route("/transcribe", methods=["POST"])
def transcribe():
    data = request.get_json()
    if not all(k in data for k in ["audio_url", "webhook_url", "user_id"]):
        return jsonify({"error": "Missing parameters"}), 400

    thread = threading.Thread(
        target=process_audio,
        args=(data["audio_url"], data["webhook_url"], data["user_id"])
    )
    thread.start()

    return jsonify({"status": "processing_started"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
