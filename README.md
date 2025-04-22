# Audio Transcriber API (Vosk + Flask)

## Описание API

### Эндпоинты:

1. **Синхронная транскрибация** (`POST /transcribe`)
   - Параметры (JSON):
     - `audio_url` (обязательный) - URL аудиофайла
     - `user_id` (обязательный) - ID пользователя
   - Ответ:
     ```json
     {
       "status": "success|error",
       "text": "Транскрибированный текст",
       "user_id": "user123",
       "id": "task_id",
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
   - Параметры (JSON):
     - `audio_url` (обязательный)
     - `user_id` (обязательный)
     - `webhook_url` (обязательный) - URL для callback
   - Ответ:
     ```json
     {
       "status": "started",
       "id": "task_id",
       "time_start": 1713829200,
       "webhook_url": "https://your-webhook.url",
       "user_id": "user123"
     }
     ```
   - Вебхук получит результат в формате синхронного ответа

3. **Проверка статуса задачи** (`GET /taskStatus`)
   - Параметры (query):
     - `id` (обязательный) - ID задачи
   - Ответ:
     ```json
     {
       "status": "success",
       "task_id": "task_id",
       "task_status": "processing|completed|failed",
       "result": { ... },
       "last_update": "2025-04-22T18:30:45"
     }
     ```

4. **Проверка здоровья** (`GET /health`)
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

### Синхронный запрос:
```bash
curl -X POST -H "Content-Type: application/json" \
-d '{"audio_url":"https://example.com/audio.mp3", "user_id":"user123"}' \
http://your-service.onrender.com/transcribe
