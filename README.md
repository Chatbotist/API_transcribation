# Audio Transcriber API (Vosk + Flask)

## Описание API

### Эндпоинты:

1. **Синхронная транскрибация** (`POST /transcribe`)
   - Параметры (тело запроса JSON):
     - `audio_url` (обязательный) - URL аудиофайла
     - `user_id` (обязательный) - ID пользователя
   - Ответ:
     ```json
     {
       "status": "success|error",
       "text": "Транскрибированный текст",
       "user_id": "id123",
       "id": "id_операции",
       "time_start": 1713829200,
       "time_end": 1713829215,
       "is_full": true,
       "audio_duration": 15.3
     }
     ```
   - Коды статуса:
     - 200 - Успешно (полный текст)
     - 201 - Успешно (неполный текст)
     - 400 - Ошибка в запросе
     - 503 - Сервер недоступен

2. **Асинхронная транскрибация** (`POST /transcribeAsync`)
   - Параметры (тело запроса JSON):
     - `audio_url` (обязательный)
     - `user_id` (обязательный)
     - `webhook_url` (обязательный)
   - Ответ:
     ```json
     {
       "status": "started",
       "id": "id_операции",
       "time_start": 1713829200,
       "webhook_url": "https://your-webhook.url",
       "user_id": "id123"
     }
     ```
   - Коды статуса:
     - 202 - Задача принята
     - 400 - Ошибка в запросе
     - 503 - Сервер недоступен

3. **Проверка статуса задачи** (`GET /taskStatus`)
   - Параметры (query string):
     - `id` (обязательный) - ID задачи
   - Ответ:
     ```json
     {
       "status": "success",
       "task_status": "processing|completed|failed",
       "result": { ... },
       "last_update": "2025-04-22T18:30:45",
       "id": "id_операции"
     }
     ```
   - Коды статуса:
     - 200 - Успешно
     - 404 - Задача не найдена

4. **Проверка здоровья сервера** (`GET /health`)
   - Ответ:
     ```json
     {
       "status": "available|unavailable",
       "last_check": "2025-04-22T18:30:45",
       "active_tasks": 0,
       "model_loaded": true
     }
     ```

## Примеры запросов

### Синхронная транскрибация:
```bash
curl -X POST -H "Content-Type: application/json" \
-d '{"audio_url":"https://example.com/audio.mp3", "user_id":"id123"}' \
http://your-service.onrender.com/transcribe
