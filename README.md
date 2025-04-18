# Асинхронный Audio Transcriber API

## Особенности:
- Асинхронная обработка через webhook
- Поддержка множества пользователей
- Очередь задач с приоритетом
- Шумоподавление и улучшенное качество
- Отслеживание статуса задач

## API Endpoint
**POST /transcribe**
```json
{
  "audio_url": "https://example.com/audio.mp3",
  "webhook_url": "https://your-service.com/webhook",
  "user_id": "12345"
}
