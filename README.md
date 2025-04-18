# Улучшенный Audio Transcriber API

## Особенности:
- Использует улучшенную модель **vosk-model-ru-0.42**
- Автоматическое шумоподавление (RNNoise)
- Ограничение времени обработки (60 сек)
- Поддержка длинных аудио (до 5 минут)
- Поточная обработка для быстрого ответа

## API Endpoint
**POST /transcribe**
```json
{
  "audio_url": "https://example.com/audio.mp3"
}
