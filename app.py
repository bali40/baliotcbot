import os
import json
from datetime import datetime, timedelta, timezone

import requests
import yfinance as yf
from flask import Flask, request, jsonify

app = Flask(_name_)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "MOJ_SEKRET_123")
BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

DATA_FILE = "user_data.json"

DEFAULT_DATA = {
    "enabled": True,
    "timeframe": "5m",
    "symbols": ["EURUSD", "GBPUSD"]
}


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
                data["symbols"] = ["EURUSD", "GBPUSD"]
            return data
    except Exception:
        save_data(DEFAULT_DATA)
        return DEFAULT_DATA.copy()


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def send_telegram_message(text):
    url = f"{BASE_URL}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text
    }
    requests.post(url, json=payload, timeout=15)


def normalize_symbol(symbol: str) -> str:
    symbol = symbol.upper().replace("/", "").replace("-", "").strip()
    return symbol


def yahoo_symbol(symbol: str) -> str:
    symbol = normalize_symbol(symbol)
    if len(symbol) == 6:
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
            "/signal
