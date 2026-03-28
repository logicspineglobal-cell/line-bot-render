import os
import json
import hmac
import base64
import hashlib
import html
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# =====================================
# ENVIRONMENT VARIABLES
# =====================================
LINE_CHANNEL_ACCESS_TOKEN = (os.getenv("LINE_CHANNEL_ACCESS_TOKEN") or "").strip()
LINE_CHANNEL_SECRET = (os.getenv("LINE_CHANNEL_SECRET") or "").strip()
GOOGLE_API_KEY = (os.getenv("GOOGLE_API_KEY") or "").strip()

# =====================================
# RUNTIME MEMORY
# =====================================
user_lang_map = {}

# =====================================
# BOOT LOGS
# =====================================
print("==> Running 'python line_webhook.py'")
print("[BOOT] Starting LINE bot on Render...")
print(f"[BOOT] LINE_CHANNEL_ACCESS_TOKEN exists: {bool(LINE_CHANNEL_ACCESS_TOKEN)}")
print(f"[BOOT] LINE_CHANNEL_SECRET exists: {bool(LINE_CHANNEL_SECRET)}")
print(f"[BOOT] GOOGLE_API_KEY exists: {bool(GOOGLE_API_KEY)}")


# =====================================
# ROOT
# =====================================
@app.route("/", methods=["GET"])
def home():
    return "LINE webhook is live", 200


# =====================================
# SIGNATURE VALIDATION
# =====================================
def verify_signature(channel_secret, body, x_line_signature):
    if not channel_secret:
        print("[SECURITY] LINE_CHANNEL_SECRET missing")
        return False

    if not x_line_signature:
        print("[SECURITY] X-Line-Signature missing")
        return False

    digest = hmac.new(
        channel_secret.encode("utf-8"),
        body.encode("utf-8"),
        hashlib.sha256
    ).digest()

    computed_signature = base64.b64encode(digest).decode("utf-8")
    is_valid = hmac.compare_digest(computed_signature, x_line_signature)
    print(f"[SECURITY] signature_valid={is_valid}")
    return is_valid


# =====================================
# LINE REPLY
# =====================================
def reply_line_message(reply_token, text):
    url = "https://api.line.me/v2/bot/message/reply"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
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

    print(f"[REPLY DEBUG] about to reply: {text}")
    print(f"[LINE REPLY DEBUG] payload={json.dumps(payload, ensure_ascii=False)}")

    try:
        res = requests.post(url, headers=headers, json=payload, timeout=15)
        print(f"[LINE REPLY] status={res.status_code}")
        print(f"[LINE REPLY] body={res.text}")
        return res.status_code == 200
    except Exception as e:
        print(f"[LINE REPLY ERROR] {str(e)}")
        return False


# =====================================
# GOOGLE TRANSLATE
# =====================================
def translate_text(text, target_lang):
    if not GOOGLE_API_KEY:
        print("[TRANSLATE] GOOGLE_API_KEY missing")
        return None

    url = "https://translation.googleapis.com/language/translate/v2"

    payload = {
        "q": text,
        "target": target_lang,
        "format": "text",
        "key": GOOGLE_API_KEY
    }

    print(f"[TRANSLATE] target_lang={target_lang}")
    print(f"[TRANSLATE] input_text={text}")

    try:
        res = requests.post(url, data=payload, timeout=20)
        print(f"[TRANSLATE] status={res.status_code}")
        print(f"[TRANSLATE] body={res.text}")

        if res.status_code != 200:
            return None

        data = res.json()
        translated = data["data"]["translations"][0]["translatedText"]
        translated = html.unescape(translated)

        print(f"[TRANSLATE] translated_text={translated}")
        return translated

    except Exception as e:
        print(f"[TRANSLATE ERROR] {str(e)}")
        return None


# =====================================
# LANGUAGE NORMALIZER
# =====================================
def normalize_target_lang(raw_lang):
    lang = (raw_lang or "").strip().lower()

    mapping = {
        "zh": "zh-TW",
        "zh-tw": "zh-TW",
        "tw": "zh-TW",
        "en": "en",
        "vi": "vi",
        "ja": "ja",
        "jp": "ja",
        "ko": "ko",
        "th": "th",
        "id": "id"
    }

    return mapping.get(lang)


# =====================================
# /lang COMMAND
# =====================================
def handle_lang_command(user_id, text, reply_token):
    print(f"[LANG CMD] raw_text={text}")

    parts = text.strip().split()
    print(f"[LANG CMD] parts={parts}")

    if len(parts) != 2:
        ok = reply_line_message(reply_token, "Sai cú pháp. Dùng: /lang zh")
        print(f"[REPLY DEBUG] reply_message CALLED /lang syntax result={ok}")
        return

    target = normalize_target_lang(parts[1])
    print(f"[LANG CMD] actor_key=user:{user_id}")
    print(f"[LANG CMD] normalized_target={target}")

    if not target:
        ok = reply_line_message(reply_token, "Ngôn ngữ chưa hỗ trợ. Dùng ví dụ: /lang zh")
        print(f"[REPLY DEBUG] reply_message CALLED /lang unsupported result={ok}")
        return

    user_lang_map[user_id] = target
    print(f"[LANG MAP] set actor_key=user:{user_id} target={target}")

    ok = reply_line_message(reply_token, f"Đã lưu ngôn ngữ đích = {target}")
    print(f"[REPLY DEBUG] reply_message CALLED /lang result={ok}")


# =====================================
# NORMAL MESSAGE HANDLER
# =====================================
def handle_normal_message(user_id, text, reply_token):
    actor_key = f"user:{user_id}"
    target_lang = user_lang_map.get(user_id, "en")

    print(f"[MESSAGE FLOW] actor_key={actor_key}")
    print(f"[MESSAGE FLOW] target_lang={target_lang}")
    print(f"[MESSAGE FLOW] input_text={text}")

    translated = translate_text(text, target_lang)

    if translated is None:
        ok = reply_line_message(
            reply_token,
            "Dịch thất bại. Kiểm tra GOOGLE_API_KEY hoặc Google Translate API."
        )
        print(f"[REPLY DEBUG] reply_message CALLED normal fallback result={ok}")
        return

    output_text = f"[VI → {target_lang}]\n{translated}"
    ok = reply_line_message(reply_token, output_text)
    print(f"[REPLY DEBUG] reply_message CALLED normal result={ok}")


# =====================================
# WEBHOOK
# =====================================
@app.route("/webhook", methods=["POST"])
def webhook():
    body = request.get_data(as_text=True)
    print(f"[WEBHOOK RAW BODY] {body}")

    x_line_signature = request.headers.get("X-Line-Signature", "")
    print(f"[WEBHOOK HEADER] x_line_signature_exists={bool(x_line_signature)}")

    if not verify_signature(LINE_CHANNEL_SECRET, body, x_line_signature):
        return jsonify({"ok": False, "error": "invalid signature"}), 400

    try:
        data = request.get_json(force=True)
        print("[WEBHOOK PARSED]")
        print(json.dumps(data, ensure_ascii=False))
    except Exception as e:
        print(f"[WEBHOOK JSON ERROR] {str(e)}")
        return jsonify({"ok": False, "error": "invalid json"}), 400

    events = data.get("events", [])
    print(f"[WEBHOOK] events_count={len(events)}")

    for event in events:
        event_type = event.get("type")
        source = event.get("source", {})
        message = event.get("message", {})
        reply_token = event.get("replyToken")
        user_id = source.get("userId")
        group_id = source.get("groupId")
        room_id = source.get("roomId")
        source_type = source.get("type")
        message_type = message.get("type")
        text = (message.get("text") or "").strip()

        print(
            f"[EVENT] "
            f'{{"event_type":"{event_type}",'
            f'"reply_token_exists":{bool(reply_token)},'
            f'"source_type":"{source_type}",'
            f'"user_id":"{user_id}",'
            f'"group_id":"{group_id}",'
            f'"room_id":"{room_id}",'
            f'"message_type":"{message_type}",'
            f'"text":"{text}"}}'
        )

        if event_type != "message":
            continue

        if message_type != "text":
            continue

        print(f"[MESSAGE] source_type={source_type}")
        print(f"[MESSAGE] group_id={group_id}")
        print(f"[MESSAGE] room_id={room_id}")
        print(f"[MESSAGE] user_id={user_id}")
        print(f"[MESSAGE] actor_key=user:{user_id}")
        print(f"[MESSAGE] text={text}")

        if text.startswith("/lang"):
            handle_lang_command(user_id, text, reply_token)
        else:
            handle_normal_message(user_id, text, reply_token)

    return jsonify({"ok": True}), 200


# =====================================
# MAIN
# =====================================
if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    print(f"[BOOT] Running on 0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port)
