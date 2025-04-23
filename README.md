Audio Processing API (Vosk + gTTS)
Описание API
Основные возможности:

Транскрибация аудио в текст (Vosk)

Преобразование текста в аудио (gTTS) с настройками голоса

Синхронные и асинхронные запросы

Вебхук-уведомления

Проверка состояния сервера

Эндпоинты
1. Транскрибация аудио → текст
Синхронный запрос:
POST /transcribe
Content-Type: application/json
{
"audio_url": "https://example.com/audio.mp3",
"user_id": "user123"
}

Асинхронный запрос:
POST /transcribeAsync
Content-Type: application/json
{
"audio_url": "https://example.com/audio.mp3",
"user_id": "user123",
"webhook_url": "https://your-webhook.url"
}

2. Генерация аудио из текста с настройками
Пример запроса с полным набором параметров:
POST /textToAudio
Content-Type: application/json
{
"text": "Привет мир! Это тестовая генерация речи с настройками.",
"user_id": "user123",
"tts_params": {
"lang": "ru",
"slow": false,
"speed": 1.3,
"pitch": 1.1,
"volume": 0.9
}
}

Доступные параметры:

lang: язык (ru, en и др.)

slow: медленная речь (true/false)

speed: скорость (0.5-2.0)

pitch: высота тона (0.5-1.5)

volume: громкость (0.1-1.0)

3. Проверка статуса задачи
GET /taskStatus?id=task_id

4. Получение сгенерированного аудио
GET /audio/filename.mp3

5. Проверка здоровья сервера
GET /health

Примеры использования
Генерация аудио с ускоренной речью:
{
"text": "Этот текст будет озвучен быстрее обычного",
"user_id": "user123",
"tts_params": {
"speed": 1.8
}
}

Генерация аудио с низким голосом:
{
"text": "Этот текст будет звучать ниже",
"user_id": "user456",
"tts_params": {
"pitch": 0.7,
"volume": 0.8
}
}

Английская речь с эффектом "медленно":
{
"text": "This text will be read slowly",
"user_id": "user789",
"tts_params": {
"lang": "en",
"slow": true
}
}

Ограничения
Максимальная длительность аудио: 5 минут

Максимальный размер текста: 1000 символов

Хранение аудио: 1 час

Поддерживаемые форматы: MP3, WAV

Версия API: 2.1.0 | Последнее обновление: 25.04.2025

Пример cURL запроса с новыми параметрами:

curl -X POST -H "Content-Type: application/json"
-d '{
"text": "Это демонстрация всех параметров генерации",
"user_id": "demo_user",
"tts_params": {
"lang": "ru",
"slow": false,
"speed": 1.5,
"pitch": 0.9,
"volume": 0.7
}
}'
https://your-service.onrender.com/textToAudio
