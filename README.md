# Асинхронный Audio Transcriber API

## Особенности:
- Асинхронная обработка через webhook
- Поддержка многопользовательского режима (до 3 параллельных запросов)
- Минимальные зависимости
- Быстрое развертывание

## API Endpoint
**POST /transcribe**
```json
{
  "audio_url": "https://example.com/audio.mp3",
  "webhook_url": "https://your-webhook-handler.com",
  "user_id": "12345"
}
