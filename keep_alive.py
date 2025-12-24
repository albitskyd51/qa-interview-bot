from flask import Flask
from threading import Thread
import logging

logger = logging.getLogger(__name__)

app = Flask('')

@app.route('/')
def home():
    return "QA Interview Bot is alive and running! 🤖"

@app.route('/health')
def health():
    return {"status": "healthy", "bot": "running"}, 200

def run():
    try:
        app.run(host='0.0.0.0', port=8080)
    except Exception as e:
        logger.error(f"Flask server error: {e}")

def keep_alive():
    """
    Запускает Flask сервер в отдельном потоке.
    Это позволяет Render определить, что приложение работает.
    """
    t = Thread(target=run)
    t.daemon = True
    t.start()
    logger.info("Keep-alive server started on port 8080")
