from flask import Flask, request, jsonify
from vosk import Model, KaldiRecognizer
import subprocess
import os
import requests

app = Flask(__name__)

# Путь к модели Vosk (будет скачана скриптом download_model.sh)
MODEL_PATH = "vosk-model-small-ru-0.22"  # Для русского языка
if not os.path.exists(MODEL_PATH):
    raise FileNotFoundError(f"Модель Vosk не найдена! Проверьте скрипт download_model.sh")

model = Model(MODEL_PATH)

def convert_to_wav(audio_url: str) -> str:
    """Скачивает аудио и конвертирует в WAV (16kHz, mono)"""
    temp_input = "temp_audio.mp3"
    temp_output = "temp_audio.wav"
    
    # Скачиваем файл
    response = requests.get(audio_url, stream=True)
    with open(temp_input, "wb") as f:
        for chunk in response.iter_content(chunk_size=1024):
            f.write(chunk)
    
    # Конвертируем через FFmpeg
    subprocess.run([
        "ffmpeg", "-i", temp_input,
        "-ar", "16000",  # Частота дискретизации 16 kHz
        "-ac", "1",      # Моно
        "-y",            # Перезаписать, если файл существует
        temp_output
    ], check=True, capture_output=True)
    
    return temp_output

@app.route("/transcribe", methods=["POST"])
def transcribe():
    try:
        data = request.get_json()
        audio_url = data.get("audio_url")
        
        if not audio_url:
            return jsonify({"error": "Параметр 'audio_url' обязателен!"}), 400
        
        # Конвертируем аудио
        wav_file = convert_to_wav(audio_url)
        
        # Транскрибируем
        recognizer = KaldiRecognizer(model, 16000)
        with open(wav_file, "rb") as f:
            while True:
                data = f.read(4000)
                if len(data) == 0:
                    break
                recognizer.AcceptWaveform(data)
        
        result = recognizer.FinalResult()
        
        # Удаляем временные файлы
        if os.path.exists(wav_file):
            os.remove(wav_file)
        if os.path.exists("temp_audio.mp3"):
            os.remove("temp_audio.mp3")
        
        return jsonify({"text": result})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))