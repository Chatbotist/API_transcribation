# Audio Processing API

## Основные возможности
- Транскрибация аудио в текст (Vosk)
- Генерация аудио из текста (gTTS)
- Поддержка форматов: OGG (по умолчанию), MP3, OPUS
- Автоматическая очистка файлов через 5 минут
- Синхронные и асинхронные запросы

## Эндпоинты

### Транскрибация
`POST /transcribe` - синхронная транскрибация  
`POST /transcribeAsync` - асинхронная транскрибация

Пример запроса:
```json
{
  "audio_url": "https://example.com/audio.mp3",
  "user_id": "user123"
}
Генерация аудио
POST /textToAudio - синхронная генерация
POST /textToAudioAsync - асинхронная генерация

Пример запроса с параметрами:

json
{
  "text": "Привет мир!",
  "user_id": "user123",
  "tts_params": {
    "lang": "ru",
    "slow": false,
    "speed": 1.5,
    "pitch": 0.9,
    "volume": 0.95,
    "format": "mp3"
  }
}
Проверка статуса
GET /taskStatus?id=<task_id>

Получение аудио
GET /audio/<filename>

Параметры генерации
lang: язык (ru/en/др.)

slow: медленная речь (true/false)

speed: скорость (0.5-2.0)

pitch: высота тона (0.5-1.5)

volume: громкость (0.1-1.0)

format: формат (ogg/mp3/opus)

Развертывание
Скопируйте все файлы в репозиторий

Настройте render.yaml

Запустите сервис на Render.com
