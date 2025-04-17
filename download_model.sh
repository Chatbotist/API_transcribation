#!/bin/bash

# Скачиваем и распаковываем модель Vosk для русского языка
wget https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip
unzip vosk-model-small-ru-0.22.zip -d vosk-model-small-ru-0.22
rm vosk-model-small-ru-0.22.zip

# Проверяем, что модель на месте
if [ ! -d "vosk-model-small-ru-0.22" ]; then
  echo "Ошибка: модель не скачалась!"
  exit 1
fi