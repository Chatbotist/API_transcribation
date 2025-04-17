# Vosk Audio Transcriber API

## Требования
- Python 3.10+
- FFmpeg (уже установлен на Render.com)

## Локальный запуск
```bash
pip install -r requirements.txt
wget https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip -O model.zip
unzip model.zip

# Если архив с вложенной структурой:
mv vosk-model-small-ru-0.22/vosk-model-small-ru-0.22/* vosk-model-small-ru-0.22/
rm -rf vosk-model-small-ru-0.22/vosk-model-small-ru-0.22

rm model.zip
python app.py
