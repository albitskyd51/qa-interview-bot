# 🚀 Бесплатный хостинг Telegram бота - Полная инструкция

## 📋 Содержание
1. [Render.com (Рекомендуется)](#1-rendercom-рекомендуется)
2. [PythonAnywhere](#2-pythonanywhere)
3. [Railway.app](#3-railwayapp)
4. [Vercel (с ограничениями)](#4-vercel)
5. [Heroku альтернативы](#5-другие-варианты)

---

## 1. Render.com (Рекомендуется) ⭐

### Преимущества:
- ✅ 750 часов бесплатно в месяц
- ✅ Автоматическое развертывание из GitHub
- ✅ Простая настройка
- ✅ Поддержка Python

### Шаг 1: Подготовка проекта

Создайте файл `render.yaml` в корне проекта:

```yaml
services:
  - type: web
    name: qa-interview-bot
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: python bot_improved.py
    envVars:
      - key: BOT_TOKEN
        sync: false
```

### Шаг 2: Регистрация на Render

1. Перейдите на [render.com](https://render.com)
2. Нажмите "Get Started" и зарегистрируйтесь через GitHub
3. Подтвердите email

### Шаг 3: Загрузка кода на GitHub

```bash
# Инициализация git репозитория
cd qa-interview-bot
git init

# Создание .gitignore
echo ".env
__pycache__/
*.pyc
.DS_Store" > .gitignore

# Коммит файлов
git add .
git commit -m "Initial commit"

# Создайте репозиторий на GitHub и подключите его
git remote add origin https://github.com/ваш_username/qa-interview-bot.git
git branch -M main
git push -u origin main
```

### Шаг 4: Развертывание на Render

1. В Render Dashboard нажмите "New +" → "Web Service"
2. Подключите ваш GitHub репозиторий
3. Настройте параметры:
   - **Name:** qa-interview-bot
   - **Environment:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python bot_improved.py`
4. Добавьте переменную окружения:
   - **Key:** BOT_TOKEN
   - **Value:** [ваш токен от BotFather]
5. Выберите Free план
6. Нажмите "Create Web Service"

### Шаг 5: Проверка работы

Бот автоматически запустится. Проверьте в Telegram!

⚠️ **Важно:** На бесплатном плане сервис "засыпает" после 15 минут неактивности.

---

## 2. PythonAnywhere

### Преимущества:
- ✅ Полностью бесплатный план
- ✅ Работает 24/7
- ✅ Простая веб-консоль

### Шаг 1: Регистрация

1. Перейдите на [pythonanywhere.com](https://www.pythonanywhere.com)
2. Нажмите "Start running Python online in less than a minute"
3. Создайте бесплатный аккаунт (Beginner account)

### Шаг 2: Загрузка кода

1. Перейдите в "Files" → "Upload a file"
2. Загрузите все файлы проекта
3. Или склонируйте из GitHub через консоль:

```bash
# Откройте Bash консоль в PythonAnywhere
git clone https://github.com/ваш_username/qa-interview-bot.git
cd qa-interview-bot
```

### Шаг 3: Установка зависимостей

В консоли PythonAnywhere:

```bash
pip3 install --user -r requirements.txt
```

### Шаг 4: Настройка переменных окружения

Создайте файл `.env`:

```bash
nano .env
```

Добавьте:
```
BOT_TOKEN=ваш_токен_здесь
```

Сохраните: Ctrl+O, Enter, Ctrl+X

### Шаг 5: Создание Always-On Task

1. Перейдите в "Tasks"
2. Добавьте новую задачу:
   ```
   python3 /home/ваш_username/qa-interview-bot/bot_improved.py
   ```
3. Установите время: каждый час (или реже для экономии CPU)

⚠️ **Ограничение:** На бесплатном плане нет Always-On tasks. Нужно использовать scheduled tasks.

### Альтернатива: Постоянный запуск

Создайте файл `run_bot.sh`:

```bash
#!/bin/bash
while true; do
    python3 /home/ваш_username/qa-interview-bot/bot_improved.py
    sleep 10
done
```

Запустите в консоли:
```bash
chmod +x run_bot.sh
nohup ./run_bot.sh &
```

---

## 3. Railway.app

### Преимущества:
- ✅ $5 бесплатных кредитов в месяц
- ✅ Автоматическое развертывание
- ✅ Простая настройка

### Шаг 1: Подготовка

Создайте файл `Procfile`:

```
worker: python bot_improved.py
```

### Шаг 2: Настройка Railway

1. Перейдите на [railway.app](https://railway.app)
2. Зарегистрируйтесь через GitHub
3. Нажмите "New Project" → "Deploy from GitHub repo"
4. Выберите ваш репозиторий
5. Добавьте переменную `BOT_TOKEN`
6. Railway автоматически обнаружит Python и запустит бота

---

## 4. Vercel (с ограничениями)

⚠️ **Внимание:** Vercel предназначен для serverless функций, не для long-polling ботов.

Лучше использовать webhook вместо polling для Vercel.

### Модификация для webhook

Создайте файл `bot_webhook.py`:

```python
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler
import os
from http.server import BaseHTTPRequestHandler
import json

# Ваш код бота здесь...

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        body = self.rfile.read(content_length)
        update = Update.de_json(json.loads(body.decode('utf-8')), application.bot)
        
        application.process_update(update)
        
        self.send_response(200)
        self.end_headers()

# Инициализация приложения
application = Application.builder().token(os.getenv('BOT_TOKEN')).build()
# ... добавьте обработчики ...
```

**Вывод:** Vercel не рекомендуется для простых ботов.

---

## 5. Другие варианты

### A) Google Cloud Platform (Free Tier)
- 90 дней $300 кредитов
- Потом очень дорого

### B) Oracle Cloud (Always Free)
- Бесплатные VM навсегда
- Требует кредитную карту
- Сложная настройка

### C) Replit
1. Создайте Repl на [replit.com](https://replit.com)
2. Загрузите файлы
3. Добавьте Secrets (BOT_TOKEN)
4. Нажмите "Run"

⚠️ Repl засыпает на бесплатном плане

---

## 🎯 Рекомендация для вашего бота

### Лучший вариант: **Render.com**

**Почему:**
1. Простая настройка (5 минут)
2. Автообновление из GitHub
3. 750 часов/месяц хватит для небольшого бота
4. Можно настроить keep-alive ping

### Решение проблемы "засыпания" на Render

Создайте файл `keep_alive.py`:

```python
from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()
```

Добавьте в `requirements.txt`:
```
flask
```

В `bot_improved.py` добавьте в начале:
```python
from keep_alive import keep_alive
keep_alive()
```

Используйте [UptimeRobot](https://uptimerobot.com) для пинга вашего Render URL каждые 5 минут.

---

## 📝 Итоговая инструкция (Render.com)

### 1. Подготовьте проект локально

```bash
cd qa-interview-bot

# Создайте .gitignore
echo ".env
__pycache__/
*.pyc
.DS_Store
venv/" > .gitignore

# Убедитесь что requirements.txt содержит:
echo "python-telegram-bot==20.7
flask" > requirements.txt
```

### 2. Загрузите на GitHub

```bash
git init
git add .
git commit -m "Ready for deployment"
git branch -M main
git remote add origin https://github.com/username/qa-interview-bot.git
git push -u origin main
```

### 3. Разверните на Render

1. Зарегистрируйтесь на render.com
2. New Web Service → Connect GitHub
3. Выберите репозиторий
4. Настройки:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python bot_improved.py`
5. Environment Variables:
   - BOT_TOKEN = [ваш токен]
6. Create Web Service

### 4. Настройте UptimeRobot (опционально)

1. Зарегистрируйтесь на [uptimerobot.com](https://uptimerobot.com)
2. Add New Monitor:
   - Monitor Type: HTTP(s)
   - URL: [ваш Render URL]
   - Monitoring Interval: 5 minutes

Готово! Ваш бот работает 24/7 бесплатно! 🎉

---

## ⚠️ Важные замечания

1. **Render бесплатный план:**
   - 750 часов/месяц
   - Сервис засыпает после 15 мин бездействия
   - Просыпается при запросе (~30 сек)

2. **PythonAnywhere:**
   - Нет always-on для бесплатных аккаунтов
   - Можно использовать workaround с scheduled tasks

3. **Railway:**
   - Только $5/месяц бесплатно
   - Может не хватить на весь месяц

4. **Для production:**
   - Рассмотрите платные варианты ($5-10/месяц)
   - Render ($7/мес), Railway ($5/мес)
   - VPS: Digital Ocean ($4/мес), Hetzner (€4/мес)

---

## 🔧 Устранение проблем

### Бот не отвечает
1. Проверьте логи в Render Dashboard
2. Убедитесь что BOT_TOKEN правильный
3. Проверьте что процесс запущен

### Бот падает
1. Добавьте обработку ошибок
2. Проверьте совместимость версий библиотек

### Бот засыпает
1. Используйте UptimeRobot для keep-alive
2. Добавьте Flask сервер для health checks

---

Удачи с запуском! 🚀
