import os
from flask import Flask, request, jsonify
import requests

app = Flask(_name_)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text
    }
    requests.post(url, json=data)

@app.route("/")
def home():
    return "Bot działa"

@app.route("/health")
def health():
    return jsonify({"ok": True})

@app.route("/tv-webhook", methods=["POST"])
def webhook():
    data = request.json

    if data.get("secret") != WEBHOOK_SECRET:
        return jsonify({"error": "unauthorized"}), 401

    text = f"""
📊 SYGNAŁ OTC
Para: {data.get("symbol")}
Kierunek: {data.get("action")}
Cena: {data.get("price")}
TF: {data.get("timeframe")}
"""

    send_telegram_message(text)
    return jsonify({"ok": True})

if _name_ == "_main_":
    app.run()
