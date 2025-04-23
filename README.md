###Документация API для обработки аудио
Обзор API
Этот API предоставляет функциональность для:

Преобразования текста в аудио (TTS)

Транскрибации аудио в текст (STT)

Управления задачами и получения статуса

Базовый URL
https://api.example.com (замените на ваш реальный URL)

Аутентификация
API не требует аутентификации для базового использования. Для ограничения доступа рекомендуется настроить API Gateway или аналогичное решение.

Ограничения
Максимальная длина текста для генерации аудио: 5000 символов

Максимальная длительность аудио для транскрибации: 5 минут

Временные файлы хранятся 5 минут

1. Генерация аудио из текста
Синхронный запрос
Endpoint: POST /textToAudio

Параметры запроса (JSON):

json
{
  "text": "Текст для преобразования в аудио",
  "user_id": "идентификатор пользователя",
  "tts_params": {
    "lang": "ru",
    "slow": false,
    "speed": 1.0,
    "pitch": 1.0,
    "volume": 1.0,
    "format": "ogg"
  }
}
Все параметры в tts_params опциональны. Если не указаны, используются значения по умолчанию.

Поддерживаемые форматы: ogg (по умолчанию), mp3, wav, m4a

Пример успешного ответа (200 OK):

```json
{
  "status": "success",
  "audio_url": "https://api.example.com/audio/voice_1a2b3c4d.ogg",
  "id": "task-id-123",
  "user_id": "user-123",
  "time_operation": 1.25,
  "params": {
    "lang": "ru",
    "slow": false,
    "speed": 1.5,
    "pitch": 1.0,
    "volume": 1.0,
    "format": "ogg"
  }
}
```
Пример ошибки (400 Bad Request):

```json
{
  "status": "error",
  "error": "Текст не может быть пустым",
  "id": "task-id-123",
  "time_operation": 0.01
}
```
Асинхронный запрос
Endpoint: POST /textToAudioAsync

Параметры запроса (JSON):

```json
{
  "text": "Текст для преобразования",
  "user_id": "user-123",
  "webhook_url": "https://your-webhook.url/endpoint",
  "tts_params": {
    "format": "mp3",
    "speed": 1.8
  }
}
```
Ответ (202 Accepted):

```json
{
  "status": "started",
  "id": "task-id-123",
  "time_operation": 0.05,
  "webhook_url": "https://your-webhook.url/endpoint",
  "user_id": "user-123"
}
```
Webhook будет отправлен на указанный URL при завершении задачи:

```json
{
  "status": "success",
  "audio_url": "https://api.example.com/audio/voice_1a2b3c4d.mp3",
  "id": "task-id-123",
  "user_id": "user-123",
  "time_operation": 2.1,
  "params": {
    "lang": "ru",
    "slow": false,
    "speed": 1.8,
    "pitch": 1.0,
    "volume": 1.0,
    "format": "mp3"
  },
  "webhook_url": "https://your-webhook.url/endpoint"
}
```
2. Транскрибация аудио
Синхронный запрос
Endpoint: POST /transcribe

Параметры запроса (JSON):

```json
{
  "audio_url": "https://example.com/audio/file.ogg",
  "user_id": "user-123"
}
```
Пример успешного ответа (200 OK):

```json
{
  "status": "success",
  "text": "распознанный текст из аудио",
  "user_id": "user-123",
  "id": "task-id-456",
  "time_operation": 3.45,
  "is_full": true,
  "audio_duration": 12.5
}
```
Асинхронный запрос
Endpoint: POST /transcribeAsync

Параметры запроса (JSON):

```json
{
  "audio_url": "https://example.com/audio/file.mp3",
  "user_id": "user-123",
  "webhook_url": "https://your-webhook.url/transcribe"
}
```
Ответ (202 Accepted):

```json
{
  "status": "started",
  "id": "task-id-456",
  "time_operation": 0.07,
  "webhook_url": "https://your-webhook.url/transcribe",
  "user_id": "user-123"
}
```
Webhook будет содержать результат транскрибации:

```json
{
  "status": "success",
  "text": "распознанный текст",
  "user_id": "user-123",
  "id": "task-id-456",
  "time_operation": 4.2,
  "is_full": true,
  "audio_duration": 15.3,
  "webhook_url": "https://your-webhook.url/transcribe"
}
```
3. Получение аудиофайла
Endpoint: GET /audio/{filename}

Пример:
GET https://api.example.com/audio/voice_1a2b3c4d.mp3

Ответ:
Аудиофайл в выбранном формате с соответствующими HTTP-заголовками.

4. Проверка статуса задачи
Endpoint: GET /taskStatus?id={task_id}

Пример:
GET https://api.example.com/taskStatus?id=task-id-123

Ответ (200 OK):

```json
{
  "status": "success",
  "task_id": "task-id-123",
  "task_status": "completed",
  "result": {
    "audio_url": "https://api.example.com/audio/voice_1a2b3c4d.ogg",
    "params": {
      "format": "ogg",
      "speed": 1.5
    }
  },
  "last_update": "2023-06-15T12:34:56.789Z"
}
```
5. Получение аудиофайла
Endpoint: GET /audio/{filename}

Пример запроса:
GET /audio/voice_1a2b3c4d.ogg

Ответ:
Аудиофайл в бинарном виде с соответствующим Content-Type.

Примеры использования
Пример 1: Быстрая генерация голосового сообщения для Telegram
```bash
curl -X POST "https://api.example.com/textToAudio" \
-H "Content-Type: application/json" \
-d '{
  "text": "Привет! Это тестовое сообщение.",
  "user_id": "tg-user-123",
  "tts_params": {
    "format": "ogg",
    "speed": 1.2
  }
}'
```
Пример 2: Транскрибация голосового сообщения
```bash
curl -X POST "https://api.example.com/transcribe" \
-H "Content-Type: application/json" \
-d '{
  "audio_url": "https://example.com/voice_message.ogg",
  "user_id": "user-456"
}'
```
Пример 3: Асинхронная генерация MP3 с webhook
```bash
curl -X POST "https://api.example.com/textToAudioAsync" \
-H "Content-Type: application/json" \
-d '{
  "text": "Длинный текст для преобразования...",
  "user_id": "user-789",
  "webhook_url": "https://my-service.com/audio-callback",
  "tts_params": {
    "format": "mp3",
    "volume": 0.9
  }
}'
```
Обработка ошибок
Все ошибки возвращаются с соответствующим HTTP-статусом и JSON-объектом:

```json
{
  "status": "error",
  "error": "Описание ошибки",
  "details": "Дополнительная информация (опционально)"
}
```
Распространённые ошибки:

400 - Неверные параметры запроса

404 - Файл или задача не найдена

503 - Сервис недоступен (например, модель не загружена)
