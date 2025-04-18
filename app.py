import os
import json
import time
import queue
import threading
import requests
from flask import Flask, request, jsonify
from vosk import Model, KaldiRecognizer

app = Flask(__name__)

# Конфигурация
MODEL_NAME = "vosk-model-small-ru-0.22"  # Облегченная модель
SAMPLE_RATE = 16000
CHUNK_SIZE = 4000
MAX_WORKERS = 3  # Максимальное количество параллельных обработчиков

# Очередь задач и модель
task_queue = queue.Queue()
model = Model(MODEL_NAME)

def worker():
    """Фоновый обработчик задач"""
    while True:
        task = task_queue.get()
        try:
            process_audio_task(task)
        except Exception as e:
            send_webhook(task['webhook_url'], {
                'user_id': task['user_id'],
                'status': 'error',
                'error': str(e)
            })
        finally:
            task_queue.task_done()

def process_audio_task(task):
    """Обрабатывает аудио и отправляет результат"""
    start_time = time.time()
    
    try:
        # Скачивание аудио
        audio_data = requests.get(task['audio_url'], stream=True).raw
        
        # Инициализация распознавателя
        rec = KaldiRecognizer(model, SAMPLE_RATE)
        rec.SetWords(True)
        
        # Поточная обработка
        result = []
        while True:
            data = audio_data.read(CHUNK_SIZE)
            if not data:
                break
            if rec.AcceptWaveform(data):
                part = json.loads(rec.Result())
                if part.get('text'):
                    result.append(part['text'])
        
        # Финализация
        final = json.loads(rec.FinalResult())
        if final.get('text'):
            result.append(final['text'])
        
        # Отправка результата
        send_webhook(task['webhook_url'], {
            'user_id': task['user_id'],
            'status': 'completed',
            'text': ' '.join(result),
            'processing_time': round(time.time() - start_time, 2)
        })
        
    except Exception as e:
        send_webhook(task['webhook_url'], {
            'user_id': task['user_id'],
            'status': 'error',
            'error': str(e)
        })

def send_webhook(url, data):
    """Отправка результата на webhook"""
    try:
        requests.post(url, json=data, timeout=5)
    except Exception as e:
        app.logger.error(f"Webhook error: {str(e)}")

@app.route('/transcribe', methods=['POST'])
def transcribe():
    data = request.get_json()
    
    # Валидация
    if not data.get('audio_url') or not data.get('webhook_url') or not data.get('user_id'):
        return jsonify({'error': 'Missing required parameters'}), 400
    
    # Добавляем задачу в очередь
    task_queue.put({
        'audio_url': data['audio_url'],
        'webhook_url': data['webhook_url'],
        'user_id': data['user_id']
    })
    
    return jsonify({
        'status': 'queued',
        'message': 'Request accepted for processing'
    })

# Запуск фоновых обработчиков
for _ in range(MAX_WORKERS):
    threading.Thread(target=worker, daemon=True).start()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
