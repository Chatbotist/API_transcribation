# Audio Processing API (Vosk + gTTS)

## Описание API

### Основные возможности:
- 🔊 Транскрибация аудио в текст (Vosk)
- 📢 Преобразование текста в аудио (gTTS) с настройками
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
2. Генерация аудио из текста с настройками
Параметры запроса:
json
{
  "text": "Текст для озвучки",
  "user_id": "user123",
  "webhook_url": "https://your-webhook.url", // опционально
  "tts_params": {
    "lang": "ru",           // язык (ru/en/etc)
    "slow": false,          // медленный режим
    "speed": 1.0,           // скорость (0.5-2.0)
    "pitch": 1.0,           // высота тона (0.5-1.5)
    "volume": 1.0           // громкость (0.1-1.0)
  }
}
Синхронный запрос:
http
POST /textToAudio
Content-Type: application/json

{
  "text": "Привет мир",
  "user_id": "user123",
  "tts_params": {
    "speed": 1.5,
    "pitch": 0.8
  }
}
Асинхронный запрос:
http
POST /textToAudioAsync
Content-Type: application/json

{
  "text": "Привет мир",
  "user_id": "user123",
  "webhook_url": "https://your-webhook.url",
  "tts_params": {
    "lang": "en",
    "slow": true
  }
}
Ответ:
json
{
  "status": "success",
  "audio_url": "https://your-service.com/audio/abc123.mp3",
  "id": "task_id",
  "user_id": "user123",
  "time_start": 1713829200,
  "time_end": 1713829215,
  "params": {
    "lang": "ru",
    "slow": false,
    "speed": 1.5,
    "pitch": 0.8,
    "volume": 1.0
  }
}
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
Быстрая генерация аудио:

bash
curl -X POST -H "Content-Type: application/json" \
-d '{"text":"Привет мир", "user_id":"user123"}' \
https://your-service.onrender.com/textToAudio
Генерация аудио с настройками:

bash
curl -X POST -H "Content-Type: application/json" \
-d '{
  "text": "Hello world",
  "user_id": "user123",
  "tts_params": {
    "lang": "en",
    "speed": 1.8,
    "pitch": 1.2
  }
}' \
https://your-service.onrender.com/textToAudio
Асинхронная транскрибация с вебхуком:

bash
curl -X POST -H "Content-Type: application/json" \
-d '{
  "audio_url": "https://example.com/audio.mp3",
  "user_id": "user123",
  "webhook_url": "https://your-webhook.url"
}' \
https://your-service.onrender.com/transcribeAsync
Доступные параметры TTS
Параметр	Тип	Диапазон	Описание
lang	string	ru, en...	Язык озвучки
slow	bool	true/false	Медленная речь
speed	float	0.5-2.0	Скорость воспроизведения
pitch	float	0.5-1.5	Высота голоса
volume	float	0.1-1.0	Уровень громкости
Ограничения
Максимальная длительность аудио: 5 минут

Максимальный размер текста: 1000 символов

Хранение сгенерированного аудио: 1 час

Поддерживаемые форматы аудио: MP3, WAV

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
