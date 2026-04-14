import os
import json
import requests
import yfinance as yf
from flask import Flask, request, jsonify

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

DATA_FILE = "user_data.json"

DEFAULT_DATA = {
    "enabled": True,
    "timeframe": "5m",
    "symbols": ["EURUSD=X", "GBPUSD=X"]
}


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_data():
    if not os.path.exists(DATA_FILE):
        save_data(DEFAULT_DATA)
        return DEFAULT_DATA.copy()

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if "enabled" not in data:
            data["enabled"] = True
        if "timeframe" not in data:
            data["timeframe"] = "5m"
        if "symbols" not in data:
            data["symbols"] = ["EURUSD=X", "GBPUSD=X"]

        return data

    except Exception:
        save_data(DEFAULT_DATA)
        return DEFAULT_DATA.copy()


def send_telegram_message(text, chat_id=None):
    try:
        target_chat_id = chat_id or TELEGRAM_CHAT_ID
        url = f"{BASE_URL}/sendMessage"
        payload = {
            "chat_id": target_chat_id,
            "text": text
        }
        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status()
    except Exception as e:
        print("Telegram error:", e)


def normalize_symbol(symbol: str) -> str:
    return symbol.upper().replace("/", "").replace("-", "").strip()


def yahoo_symbol(symbol: str) -> str:
    symbol = normalize_symbol(symbol)
    if not symbol.endswith("=X"):
        return f"{symbol}=X"
    return symbol


def get_signal(symbol: str):
    tf = "5m"
    yf_symbol = yahoo_symbol(symbol)

    try:
        df = yf.download(
            tickers=yf_symbol,
            interval=tf,
            period="1d",
            progress=False,
            auto_adjust=False
        )

        if df is None or df.empty or len(df) < 25:
            return None, "Brak danych"

        close = df["Close"].dropna()
        high = df["High"].dropna()
        low = df["Low"].dropna()

        if len(close) < 20 or len(high) < 14 or len(low) < 14:
            return None, "Za mało danych"

        ema9 = close.ewm(span=9, adjust=False).mean()
        ema21 = close.ewm(span=21, adjust=False).mean()

        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.replace(0, 1e-9)
        rsi = 100 - (100 / (1 + rs))

        last_close = float(close.iloc[-1])
        last_ema9 = float(ema9.iloc[-1])
        last_ema21 = float(ema21.iloc[-1])
        last_rsi = float(rsi.iloc[-1])

        action = "WAIT"
        reason = "Brak przewagi"

        if last_close > last_ema9 > last_ema21 and last_rsi > 55:
            action = "BUY"
            reason = "trend up + momentum"
        elif last_close < last_ema9 < last_ema21 and last_rsi < 45:
            action = "SELL"
            reason = "trend down + momentum"

        return {
            "symbol": normalize_symbol(symbol),
            "action": action,
            "price": round(last_close, 5),
            "rsi": round(last_rsi, 2),
            "reason": reason
        }, None

    except Exception as e:
        return None, str(e)


def handle_command(text: str):
    data = load_data()
    parts = text.strip().split()

    if not parts:
        return "Brak komendy"

    cmd = parts[0].lower()

    if cmd == "/start":
        return (
            "Bot OTC 5m działa.\n\n"
            "Komendy:\n"
            "/help\n"
            "/list\n"
            "/add EURUSD\n"
            "/remove EURUSD\n"
            "/signal EURUSD\n"
            "/on\n"
            "/off"
        )

    if cmd == "/help":
        return (
            "Dostępne komendy:\n"
            "/list - lista par\n"
            "/add EURUSD - dodaj parę\n"
            "/remove EURUSD - usuń parę\n"
            "/signal EURUSD - sprawdź sygnał\n"
            "/on - włącz sygnały\n"
            "/off - wyłącz sygnały"
        )

    if cmd == "/list":
        return "Pary:\n" + "\n".join(data["symbols"])

    if cmd == "/add" and len(parts) > 1:
        symbol = yahoo_symbol(parts[1])
        if symbol not in data["symbols"]:
            data["symbols"].append(symbol)
            save_data(data)
        return f"Dodano: {symbol}"

    if cmd == "/remove" and len(parts) > 1:
        symbol = yahoo_symbol(parts[1])
        if symbol in data["symbols"]:
            data["symbols"].remove(symbol)
            save_data(data)
            return f"Usunięto: {symbol}"
        return "Nie znaleziono"

    if cmd == "/signal" and len(parts) > 1:
        result, error = get_signal(parts[1])
        if error:
            return f"Błąd: {error}"
        return (
            f"Para: {result['symbol']}\n"
            f"Sygnał: {result['action']}\n"
            f"Cena: {result['price']}\n"
            f"RSI: {result['rsi']}\n"
            f"Powód: {result['reason']}"
        )

    if cmd == "/on":
        data["enabled"] = True
        save_data(data)
        return "Włączono"

    if cmd == "/off":
        data["enabled"] = False
        save_data(data)
        return "Wyłączono"

    return "Nieznana komenda"


@app.route("/", methods=["GET"])
def home():
    return "Bot działa", 200


@app.route(f"/{TELEGRAM_BOT_TOKEN}", methods=["POST"])
def telegram_webhook():
    update = request.json or {}

    print("UPDATE:", update)

    message = update.get("message", {})
    chat = message.get("chat", {})
    chat_id = str(chat.get("id", ""))

    print("CHAT ID:", chat_id)

    text = message.get("text", "").strip()
    if not text:
        return jsonify({"ok": True})

    response = handle_command(text)
    send_telegram_message(response, chat_id=chat_id)

    return jsonify({"ok": True})


if _name_ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
