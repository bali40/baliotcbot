import os
import time
import logging
import requests
import yfinance as yf

from flask import Flask, request, jsonify

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "TU_WSTAW_TOKEN_BOTA")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://twoj-adres.pl")
PORT = int(os.getenv("PORT", "10000"))

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
WEBHOOK_PATH = f"/{BOT_TOKEN}"
WEBHOOK_FULL_URL = f"{WEBHOOK_URL}{WEBHOOK_PATH}"

app = Flask(__name__)
_LAST_SIGNAL_TS = {}


def normalize_symbol(symbol: str) -> str:
    if not symbol:
        return ""

    s = symbol.upper().strip()
    s = s.replace("/", "")
    s = s.replace("-", "")
    s = s.replace("OTC", "")
    s = s.replace(" ", "")
    return s


def yahoo_symbol(symbol: str) -> str:
    s = normalize_symbol(symbol)

    forex_pairs = {
        "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
        "USDCHF", "NZDUSD", "EURJPY", "EURGBP", "GBPJPY",
        "EURAUD", "GBPCHF", "AUDJPY", "CADJPY",
        "EURCHF", "AUDCAD", "GBPAUD", "GBPCAD", "NZDJPY",
        "CHFJPY", "EURNZD", "AUDNZD", "CADCHF", "NZDCAD",
        "NZDCHF", "AUDCHF", "GBPNZD", "EURCAD"
    }

    if s in forex_pairs:
        return f"{s}=X"

    return s


def escape_markdown(text) -> str:
    if text is None:
        return ""

    special_chars = r"_*[]()~`>#+-=|{}.!"
    escaped = ""
    for ch in str(text):
        if ch in special_chars:
            escaped += "\\" + ch
        else:
            escaped += ch
    return escaped


def format_signal_message(signal: dict) -> str:
    if not signal:
        return "Brak sygnału."

    symbol = escape_markdown(signal.get("symbol", "N/A"))
    action = signal.get("action", "NONE")
    price = escape_markdown(signal.get("price", "N/A"))
    rsi = escape_markdown(signal.get("rsi", "N/A"))
    stoch_k = escape_markdown(signal.get("stoch_k", "N/A"))
    stoch_d = escape_markdown(signal.get("stoch_d", "N/A"))
    ema9 = escape_markdown(signal.get("ema9", "N/A"))
    ema21 = escape_markdown(signal.get("ema21", "N/A"))
    body_ratio = escape_markdown(signal.get("body_ratio", "N/A"))
    expiry_min = escape_markdown(signal.get("expiry_min", "N/A"))
    reason = escape_markdown(signal.get("reason", "Brak powodu"))

    if action == "BUY":
        return (
            f"📡 Sygnał OTC M1\n"
            f"💱 Para: {symbol}\n"
            f"🟢 Kierunek: BUY\n"
            f"⏳ Czas wejścia: {expiry_min} min\n"
            f"💵 Cena: {price}\n"
            f"📊 RSI: {rsi}\n"
            f"📈 Stochastic K/D: {stoch_k} / {stoch_d}\n"
            f"📉 EMA9 / EMA21: {ema9} / {ema21}\n"
            f"🕯 Siła świecy: {body_ratio}\n"
            f"📝 Powód: {reason}"
        )

    if action == "SELL":
        return (
            f"📡 Sygnał OTC M1\n"
            f"💱 Para: {symbol}\n"
            f"🔴 Kierunek: SELL\n"
            f"⏳ Czas wejścia: {expiry_min} min\n"
            f"💵 Cena: {price}\n"
            f"📊 RSI: {rsi}\n"
            f"📈 Stochastic K/D: {stoch_k} / {stoch_d}\n"
            f"📉 EMA9 / EMA21: {ema9} / {ema21}\n"
            f"🕯 Siła świecy: {body_ratio}\n"
            f"📝 Powód: {reason}"
        )

    return (
        f"ℹ️ Brak sygnału OTC M1\n"
        f"💱 Para: {symbol}\n"
        f"💵 Cena: {price}\n"
        f"📊 RSI: {rsi}\n"
        f"📈 Stochastic K/D: {stoch_k} / {stoch_d}\n"
        f"📉 EMA9 / EMA21: {ema9} / {ema21}\n"
        f"📝 Powód: {reason}"
    )


def send_telegram_message(chat_id: int, text: str):
    url = f"{TELEGRAM_API}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "MarkdownV2"
    }

    try:
        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.exception("Błąd wysyłki wiadomości do Telegrama")
        return {"ok": False, "error": str(e)}


def set_webhook():
    url = f"{TELEGRAM_API}/setWebhook"
    payload = {"url": WEBHOOK_FULL_URL}

    try:
        response = requests.post(url, json=payload, timeout=20)
        response.raise_for_status()
        data = response.json()
        logger.info("setWebhook response: %s", data)
        return data
    except Exception as e:
        logger.exception("Błąd ustawiania webhooka")
        return {"ok": False, "error": str(e)}


def get_signal(symbol: str):
    tf = "1m"
    yf_sym = yahoo_symbol(symbol)

    cooldown_seconds = 180
    pullback_tolerance = 0.0015
    min_body_ratio = 0.40
    max_spike_factor = 1.8

    try:
        df = yf.download(
            tickers=yf_sym,
            interval=tf,
            period="1d",
            progress=False,
            auto_adjust=False
        )

        if df is None or df.empty or len(df) < 50:
            return None, "Brak danych rynkowych"

        if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
            df.columns = df.columns.get_level_values(0)

        required_cols = {"Open", "High", "Low", "Close"}
        if not required_cols.issubset(set(df.columns)):
            return None, "Brakuje wymaganych kolumn danych"

        open_ = df["Open"].dropna()
        high = df["High"].dropna()
        low = df["Low"].dropna()
        close = df["Close"].dropna()

        if hasattr(open_, "ndim") and open_.ndim > 1:
            open_ = open_.iloc[:, 0]
        if hasattr(high, "ndim") and high.ndim > 1:
            high = high.iloc[:, 0]
        if hasattr(low, "ndim") and low.ndim > 1:
            low = low.iloc[:, 0]
        if hasattr(close, "ndim") and close.ndim > 1:
            close = close.iloc[:, 0]

        min_len = min(len(open_), len(high), len(low), len(close))
        if min_len < 30:
            return None, "Za mało danych do analizy"

        open_ = open_.iloc[-min_len:]
        high = high.iloc[-min_len:]
        low = low.iloc[-min_len:]
        close = close.iloc[-min_len:]

        ema9 = close.ewm(span=9, adjust=False).mean()
        ema21 = close.ewm(span=21, adjust=False).mean()

        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.replace(0, 1e-9)
        rsi = 100 - (100 / (1 + rs))

        lowest_low = low.rolling(14).min()
        highest_high = high.rolling(14).max()
        stoch_k_raw = 100 * ((close - lowest_low) / (highest_high - lowest_low).replace(0, 1e-9))
        stoch_k = stoch_k_raw.rolling(3).mean()
        stoch_d = stoch_k.rolling(3).mean()

        i = -1

        last_open = float(open_.iloc[i])
        last_high = float(high.iloc[i])
        last_low = float(low.iloc[i])
        last_close = float(close.iloc[i])

        prev_k = float(stoch_k.iloc[i - 1])
        prev_d = float(stoch_d.iloc[i - 1])

        last_ema9 = float(ema9.iloc[i])
        last_ema21 = float(ema21.iloc[i])
        last_rsi = float(rsi.iloc[i])
        last_k = float(stoch_k.iloc[i])
        last_d = float(stoch_d.iloc[i])

        values_to_check = [
            last_open, last_high, last_low, last_close,
            prev_k, prev_d,
            last_ema9, last_ema21, last_rsi, last_k, last_d
        ]

        if any(v != v for v in values_to_check):
            return None, "Wskaźniki nie są jeszcze gotowe"

        norm_symbol = normalize_symbol(symbol)
        now_ts = time.time()
        last_signal_ts = _LAST_SIGNAL_TS.get(norm_symbol)

        if last_signal_ts and (now_ts - last_signal_ts) < cooldown_seconds:
            remaining = int(cooldown_seconds - (now_ts - last_signal_ts))
            result = {
                "symbol": norm_symbol,
                "action": "NONE",
                "price": round(last_close, 5),
                "rsi": round(last_rsi, 2),
                "stoch_k": round(last_k, 2),
                "stoch_d": round(last_d, 2),
                "ema9": round(last_ema9, 5),
                "ema21": round(last_ema21, 5),
                "body_ratio": None,
                "expiry_min": None,
                "reason": f"Aktywny cooldown - kolejny sygnał możliwy za {remaining} sek."
            }
            result["message"] = format_signal_message(result)
            return result, None

        candle_range = max(last_high - last_low, 1e-9)
        candle_body = abs(last_close - last_open)
        body_ratio = candle_body / candle_range

        recent_ranges = (high - low).tail(6).iloc[:-1]
        avg_range = recent_ranges.mean() if len(recent_ranges) > 0 else candle_range
        spike = candle_range > (avg_range * max_spike_factor)

        bullish_candle = last_close > last_open
        bearish_candle = last_close < last_open

        near_ema9 = abs(last_close - last_ema9) / max(abs(last_close), 1e-9) <= pullback_tolerance
        near_ema21 = abs(last_close - last_ema21) / max(abs(last_close), 1e-9) <= pullback_tolerance

        touched_ema_buy = (
            last_low <= last_ema9
            or last_low <= last_ema21
            or near_ema9
            or near_ema21
        )

        touched_ema_sell = (
            last_high >= last_ema9
            or last_high >= last_ema21
            or near_ema9
            or near_ema21
        )

        stoch_cross_up = prev_k <= prev_d and last_k > last_d
        stoch_cross_down = prev_k >= prev_d and last_k < last_d

        valid_candle = body_ratio >= min_body_ratio

        action = "NONE"
        reason = "Brak wyraźnej przewagi"
        expiry_min = None

        if (
            last_ema9 > last_ema21
            and touched_ema_buy
            and last_rsi > 50
            and stoch_cross_up
            and prev_k < 30
            and bullish_candle
            and valid_candle
            and not spike
            and last_k < 80
        ):
            expiry_min = 2
            action = "BUY"
            reason = "Trend wzrostowy, cofnięcie do EMA, RSI powyżej 50 i przecięcie Stochastic w górę"

        elif (
            last_ema9 < last_ema21
            and touched_ema_sell
            and last_rsi < 50
            and stoch_cross_down
            and prev_k > 70
            and bearish_candle
            and valid_candle
            and not spike
            and last_k > 20
        ):
            expiry_min = 2
            action = "SELL"
            reason = "Trend spadkowy, cofnięcie do EMA, RSI poniżej 50 i przecięcie Stochastic w dół"

        else:
            fail_reasons = []

            if spike:
                fail_reasons.append("świeca jest zbyt gwałtowna")
            if not valid_candle:
                fail_reasons.append("korpus świecy jest zbyt mały")
            if 40 <= last_k <= 60:
                fail_reasons.append("Stochastic jest w neutralnej strefie")
            if not fail_reasons:
                fail_reasons.append("warunki wejścia nie zostały spełnione")

            reason = ", ".join(fail_reasons)

        result = {
            "symbol": norm_symbol,
            "action": action,
            "price": round(last_close, 5),
            "rsi": round(last_rsi, 2),
            "stoch_k": round(last_k, 2),
            "stoch_d": round(last_d, 2),
            "ema9": round(last_ema9, 5),
            "ema21": round(last_ema21, 5),
            "body_ratio": round(body_ratio, 2),
            "expiry_min": expiry_min if action in ("BUY", "SELL") else None,
            "reason": reason
        }

        result["message"] = format_signal_message(result)

        if action in ("BUY", "SELL"):
            _LAST_SIGNAL_TS[norm_symbol] = now_ts

        return result, None

    except Exception as e:
        logger.exception("Błąd podczas analizy sygnału")
        return None, f"Błąd podczas analizy sygnału: {str(e)}"


def handle_start(chat_id: int):
    text = (
        "Witaj 👋\n\n"
        "Bot działa i obsługuje sygnały OTC na M1.\n\n"
        "Dostępne komendy:\n"
        "/start - uruchomienie bota\n"
        "/help - pomoc\n"
        "/signal EURUSD - analiza pary\n\n"
        "Przykład:\n"
        "/signal EURUSD"
    )
    send_telegram_message(chat_id, escape_markdown(text))


def handle_help(chat_id: int):
    text = (
        "📘 Pomoc\n\n"
        "Komenda do analizy:\n"
        "/signal EURUSD\n\n"
        "Możesz też wpisać:\n"
        "/signal GBPUSD\n"
        "/signal USDJPY\n"
        "/signal EURUSD OTC\n\n"
        "Bot zwraca:\n"
        "- BUY lub SELL\n"
        "- sugerowany czas wejścia 2 / 3 / 5 min\n"
        "- RSI\n"
        "- Stochastic\n"
        "- EMA9 / EMA21\n"
        "- powód decyzji"
    )
    send_telegram_message(chat_id, escape_markdown(text))


def handle_signal(chat_id: int, text: str):
    parts = text.strip().split(maxsplit=1)

    if len(parts) < 2:
        send_telegram_message(
            chat_id,
            escape_markdown("Podaj symbol.\n\nPrzykład:\n/signal EURUSD")
        )
        return

    raw_symbol = parts[1]
    raw_symbol = raw_symbol.replace("OTC", "").replace("otc", "").strip()

    signal, err = get_signal(raw_symbol)

    if err:
        send_telegram_message(chat_id, escape_markdown(err))
        return

    send_telegram_message(chat_id, signal["message"])


def process_telegram_update(data: dict):
    try:
        message = data.get("message") or data.get("edited_message")
        if not message:
            return

        chat = message.get("chat", {})
        chat_id = chat.get("id")
        text = message.get("text", "")

        if not chat_id or not text:
            return

        if text.startswith("/start"):
            handle_start(chat_id)
        elif text.startswith("/help"):
            handle_help(chat_id)
        elif text.startswith("/signal"):
            handle_signal(chat_id, text)
        else:
            send_telegram_message(
                chat_id,
                escape_markdown("Nieznana komenda.\n\nUżyj:\n/start\n/help\n/signal EURUSD")
            )

    except Exception as e:
        logger.exception("Błąd podczas przetwarzania update")
        try:
            chat_id = data.get("message", {}).get("chat", {}).get("id")
            if chat_id:
                send_telegram_message(
                    chat_id,
                    escape_markdown(f"Wystąpił błąd: {str(e)}")
                )
        except Exception:
            pass


@app.route("/", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "message": "Bot Telegram OTC działa"
    }), 200


@app.route(WEBHOOK_PATH, methods=["POST"])
def webhook():
    data = request.get_json(silent=True)

    if not data:
        return jsonify({"ok": False, "error": "Brak danych JSON"}), 400

    process_telegram_update(data)
    return jsonify({"ok": True}), 200


@app.route("/set_webhook", methods=["GET"])
def setup_webhook_route():
    result = set_webhook()
    return jsonify(result), 200


if __name-__ == "__main__":
    if BOT_TOKEN == "TU_WSTAW_TOKEN_BOTA":
        raise ValueError("Ustaw BOT_TOKEN w zmiennych środowiskowych albo w pliku.")

    if WEBHOOK_URL == "https://twoj-adres.pl":
        raise ValueError("Ustaw WEBHOOK_URL w zmiennych środowiskowych albo w pliku.")

    logger.info("Ustawiam webhook: %s", WEBHOOK_FULL_URL)
    set_webhook()

    logger.info("Start Flask na porcie %s", PORT)
    app.run(host="0.0.0.0", port=PORT)
