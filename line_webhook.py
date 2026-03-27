import os
import json
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# =========================
# ENVIRONMENT VARIABLES
# =========================
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")

# =========================
# DEBUG LOGS
# =========================
print("[BOOT] Starting LINE bot on Render...")
print(f"[BOOT] LINE_CHANNEL_ACCESS_TOKEN exists: {bool(LINE_CHANNEL_ACCESS_TOKEN)}")
print(f"[BOOT] GOOGLE_API_KEY exists: {bool(GOOGLE_API_KEY)}")
print(f"[BOOT] GOOGLE_SHEET_ID exists: {bool(GOOGLE_SHEET_ID)}")


# =========================
# LINE REPLY
# =========================
def reply_message(reply_token: str, text: str) -> None:
    if not LINE_CHANNEL_ACCESS_TOKEN:
        print("[ERROR] LINE_CHANNEL_ACCESS_TOKEN is missing")
        return

    url = "https://api.line.me/v2/bot/message/reply"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    }
    payload = {
        "replyToken": reply_token,
        "messages": [
            {
                "type": "text",
                "text": text
            }
        ]
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        print(f"[LINE REPLY] status={response.status_code}")
        print(f"[LINE REPLY] body={response.text}")
    except Exception as e:
        print(f"[LINE REPLY ERROR] {e}")


# =========================
# GOOGLE TRANSLATE
# =========================
def translate_text(text: str, target_lang: str) -> str:
    if not GOOGLE_API_KEY:
        return "[LỖI] Thiếu GOOGLE_API_KEY"

    if not text.strip():
        return "[LỖI] Nội dung trống"

    url = "https://translation.googleapis.com/language/translate/v2"
    params = {"key": GOOGLE_API_KEY}
    data = {
        "q": text,
        "target": target_lang,
        "format": "text",
    }

    try:
        response = requests.post(url, params=params, data=data, timeout=20)
        print(f"[TRANSLATE] status={response.status_code}")
        print(f"[TRANSLATE] body={response.text}")

        if response.status_code != 200:
            return f"[LỖI DỊCH] HTTP {response.status_code}"

        result = response.json()
        translated = (
            result.get("data", {})
            .get("translations", [{}])[0]
            .get("translatedText", "")
        )

        if not translated:
            return "[LỖI DỊCH] Không có translatedText"

        return translated

    except Exception as e:
        print(f"[TRANSLATE ERROR] {e}")
        return f"[LỖI DỊCH] {str(e)}"


# =========================
# COMMAND PARSER
# =========================
def handle_translate_command(user_text: str) -> str:
    text = user_text.strip()

    # /zh xin chào
    if text.startswith("/zh"):
        source_text = text.replace("/zh", "", 1).strip()
        if not source_text:
            return "Cú pháp đúng: /zh nội dung"
        translated = translate_text(source_text, "zh-TW")
        return f"[VI → ZH-TW]\n{translated}"

    # /vi 你好
    if text.startswith("/vi"):
        source_text = text.replace("/vi", "", 1).strip()
        if not source_text:
            return "Cú pháp đúng: /vi nội dung"
        translated = translate_text(source_text, "vi")
        return f"[AUTO → VI]\n{translated}"

    # /id chào bạn
    if text.startswith("/id"):
        source_text = text.replace("/id", "", 1).strip()
        if not source_text:
            return "Cú pháp đúng: /id nội dung"
        translated = translate_text(source_text, "id")
        return f"[AUTO → ID]\n{translated}"

    # =========================
    # AUTO DETECT FALLBACK
    # Nếu không có lệnh /zh /vi /id
    # thì tự dịch sang tiếng Việt
    # =========================
    translated = translate_text(text, "vi")
    return f"[AUTO → VI]\n{translated}"


# =========================
# ROUTES
# =========================
@app.route("/", methods=["GET"])
def home():
    return "LINE BOT RENDER OK", 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "line_token_exists": bool(LINE_CHANNEL_ACCESS_TOKEN),
        "google_api_key_exists": bool(GOOGLE_API_KEY),
        "google_sheet_id_exists": bool(GOOGLE_SHEET_ID),
    }), 200


@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        body = request.get_json(silent=True)
        print("[WEBHOOK] Incoming payload:")
        print(json.dumps(body, ensure_ascii=False))

        if not body:
            return "No JSON body", 400

        events = body.get("events", [])
        if not events:
            return "No events", 200

        for event in events:
            print(f"[EVENT] {json.dumps(event, ensure_ascii=False)}")

            if event.get("type") != "message":
                print("[SKIP] event type is not message")
                continue

            message = event.get("message", {})
            if message.get("type") != "text":
                print("[SKIP] message type is not text")
                continue

            reply_token = event.get("replyToken")
            user_text = message.get("text", "").strip()

            print(f"[MESSAGE] user_text={user_text}")

            if not reply_token:
                print("[WARN] Missing replyToken")
                continue

            if not user_text:
                reply_message(reply_token, "Tôi đã nhận được tin nhắn trống.")
                continue

            reply_text = handle_translate_command(user_text)
            print(f"[FINAL REPLY] {reply_text}")
            reply_message(reply_token, reply_text)

        return "OK", 200

    except Exception as e:
        print(f"[WEBHOOK ERROR] {e}")
        return "Internal Server Error", 500


# =========================
# ENTRYPOINT
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"[BOOT] Running on 0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
