# Audio Processing API (Vosk + gTTS)

## Описание API

### Основные возможности:
- 🔊 Транскрибация аудио в текст (Vosk)
- 📢 Преобразование текста в аудио (gTTS)
- ⏳ Синхронные и асинхронные запросы
- 🔔 Вебхук-уведомления
- 🩺 Проверка состояния сервера

---

## Эндпоинты

### 1. Транскрибация аудио → текст

#### Синхронный запрос:
```http
POST /transcribe
Content-Type: application/json

{
  "audio_url": "https://example.com/audio.mp3",
  "user_id": "user123"
}
Асинхронный запрос:
http
POST /transcribeAsync
Content-Type: application/json

{
  "audio_url": "https://example.com/audio.mp3",
  "user_id": "user123",
  "webhook_url": "https://your-webhook.url"
}
Ответ:
json
{
  "status": "success",
  "text": "распознанный текст",
  "user_id": "user123",
  "id": "task_id",
  "time_start": 1713829200,
  "time_end": 1713829215,
  "is_full": true,
  "audio_duration": 15.3
}
2. Генерация аудио из текста
Синхронный запрос:
http
POST /textToAudio
Content-Type: application/json

{
  "text": "Привет мир",
  "user_id": "user123"
}
Асинхронный запрос:
http
POST /textToAudioAsync
Content-Type: application/json

{
  "text": "Привет мир",
  "user_id": "user123",
  "webhook_url": "https://your-webhook.url"
}
Ответ:
json
{
  "status": "success",
  "audio_url": "https://your-service.com/audio/abc123.mp3",
  "id": "task_id",
  "user_id": "user123",
  "time_start": 1713829200,
  "time_end": 1713829215
}
Аудио доступно по ссылке 1 час

3. Проверка статуса задачи
http
GET /taskStatus?id=task_id
Ответ:
json
{
  "status": "success",
  "task_id": "task_id",
  "task_status": "processing|completed|failed",
  "result": { ... },
  "last_update": "2025-04-22T18:30:45"
}
4. Получение сгенерированного аудио
http
GET /audio/filename.mp3
5. Проверка здоровья сервера
http
GET /health
Ответ:
json
{
  "status": "available|unavailable",
  "model_loaded": true,
  "last_check": "2025-04-22T18:30:45",
  "active_tasks": 0
}
Примеры использования
1. Синхронная транскрибация
bash
curl -X POST -H "Content-Type: application/json" \
-d '{"audio_url":"https://example.com/audio.mp3", "user_id":"user123"}' \
https://your-service.onrender.com/transcribe
2. Асинхронная генерация аудио
bash
curl -X POST -H "Content-Type: application/json" \
-d '{"text":"Привет мир", "user_id":"user123", "webhook_url":"https://your-webhook.url"}' \
https://your-service.onrender.com/textToAudioAsync
3. Проверка статуса
bash
curl "https://your-service.onrender.com/taskStatus?id=task_id_123"
Развертывание
Скопируйте файлы в репозиторий:

app.py - Основное приложение

render.yaml - Конфигурация сервиса

requirements.txt - Зависимости

runtime.txt - Версия Python

Настройки для Render.com:

yaml
# render.yaml
services:
  - type: web
    name: audio-processor
    env: python
    region: frankfurt
    buildCommand: |
      wget https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip -O model.zip
      unzip model.zip
      # Автодетект структуры архива
      if [ -f "vosk-model-small-ru-0.22/am/final.mdl" ]; then
          echo "Новая структура архива"
      elif [ -f "vosk-model-small-ru-0.22/vosk-model-small-ru-0.22/am/final.mdl" ]; then
          echo "Старая структура - исправляем"
          mv vosk-model-small-ru-0.22/vosk-model-small-ru-0.22/* vosk-model-small-ru-0.22/
          rm -rf vosk-model-small-ru-0.22/vosk-model-small-ru-0.22
      else
          echo "ОШИБКА: Неверная структура архива!"
          exit 1
      fi
      rm model.zip
      pip install -r requirements.txt
    startCommand: python app.py
    plan: free
Ограничения
Максимальная длительность аудио: 5 минут

Формат аудио: MP3, WAV

Хранение сгенерированного аудио: 1 час

Максимальный размер текста: 1000 символов

Устранение неполадок
Ошибки модели Vosk:

Проверьте логи установки в Render.com

Убедитесь, что архив модели доступен

Проблемы с генерацией аудио:

Проверьте длину текста (не более 1000 символов)

Убедитесь, что текст содержит только поддерживаемые символы

Вебхуки не работают:

Проверьте, что URL принимает POST-запросы

Убедитесь в отсутствии таймаутов (макс. 10 сек)

Версия API: 2.0.0 | Последнее обновление: 25.04.2025


### Ключевые обновления в README:

1. Добавлена полная документация по новым эндпоинтам:
   - `/textToAudio`
   - `/textToAudioAsync`
   - `/audio/<filename>`

2. Обновлены примеры запросов для всех функций

3. Добавлена информация о лимитах для генерации аудио

4. Указаны временные рамки хранения аудиофайлов

5. Добавлен раздел по устранению неполадок для новых функций

6. Обновлена версия API и дата последнего обновления
