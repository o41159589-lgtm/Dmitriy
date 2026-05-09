import requests
from flask import Flask, request, render_template_string

app = Flask(__name__)

# --- КОНФИГУРАЦИЯ ---
BOT_TOKEN = "8686326767:AAH7u-K9e3oGhf6ZjlobZ98zAv5YYx7R3JQ"  # Возьми из bot.py
ADMIN_ID = "1840233118"  # Твой ID, куда придут уведомления
HTML_FILE = "not_telegram2.html"


def send_to_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": ADMIN_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Ошибка отправки в TG: {e}")


@app.route('/')
def index():
    # Получаем IP
    user_ip = request.headers.get('X-Forwarded-For', request.remote_addr)

    # Формируем сообщение
    msg = f"🔔 <b>Новый переход на сайт!</b>\n🌐 IP: <code>{user_ip}</code>"

    # Отправляем в бота
    send_to_telegram(msg)

    # Отдаем страницу
    with open(HTML_FILE, "r", encoding="utf-8") as f:
        return render_template_string(f.read())


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)