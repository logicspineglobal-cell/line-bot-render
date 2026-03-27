import os
import json
import hmac
import base64
import hashlib
from html import unescape

import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# =========================
# ENVIRONMENT VARIABLES
# =========================
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")  # giữ lại để dùng sau nếu cần

# =========================
# BOOT LOGS
# =========================
print("[BOOT] Starting LINE bot on Render...")
print(f"[BOOT] LINE_CHANNEL_ACCESS_TOKEN exists: {bool(LINE_CHANNEL_ACCESS_TOKEN)}")
print(f"[BOOT] LINE_CHANNEL_SECRET exists: {bool(LINE_CHANNEL_SECRET)}")
print(f"[BOOT] GOOGLE_API_KEY exists: {bool(GOOGLE_API_KEY)}")
print(f"[BOOT] GOOGLE_SHEET_ID exists: {bool(GOOGLE_SHEET_ID)}")

# =========================
# CONFIG
# =========================
DEFAULT_AUTO_TARGET = "vi"

SUPPORTED_COMMANDS = {
    "/zh": "zh-TW",
    "/vi": "vi",
    "/id": "id",
}

# In-memory map (bộ nhớ tạm)
# restart service -> mất dữ liệu
USER_LANG_MAP = {}


# =========================
# HELPERS
# =========================
def verify_line_signature(raw_body: str, signature: str) -> bool:
    """
    Verify LINE signature (xác thực chữ ký LINE)
    """
    if not LINE_CHANNEL_SECRET:
        print("[SECURITY] Missing LINE_CHANNEL_SECRET")
        return False

    if not signature:
        print("[SECURITY] Missing X-Line-Signature header")
        return False

    digest = hmac.new(
        LINE_CHANNEL_SECRET.encode("utf-8"),
        raw_body.encode("utf-8"),
        hashlib.sha256
    ).digest()

    computed_signature = base64.b64encode(digest).decode("utf-8")
    is_valid = hmac.compare_digest(computed_signature, signature)

    print(f"[SECURITY] signature_valid={is_valid}")
    return is_valid


def reply_message(reply_token: str, text: str) -> bool:
    """
    Reply message (phản hồi tin nhắn)
    """
    if not LINE_CHANNEL_ACCESS_TOKEN:
        print("[LINE REPLY ERROR] Missing LINE_CHANNEL_ACCESS_TOKEN")
        return False

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
                "text": text[:5000]
            }
        ]
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=20)
        print(f"[LINE REPLY] status={response.status_code}")
        print(f"[LINE REPLY] body={response.text}")
        return response.status_code == 200

    except Exception as e:
        print(f"[LINE REPLY ERROR] {str(e)}")
        return False


def detect_language(text: str) -> str:
    """
    Detect language (nhận diện ngôn ngữ)
    """
    if not GOOGLE_API_KEY:
        print("[DETECT ERROR] Missing GOOGLE_API_KEY")
        return "unknown"

    url = "https://translation.googleapis.com/language/translate/v2/detect"
    params = {"key": GOOGLE_API_KEY}
    payload = {"q": text}

    try:
        response = requests.post(url, params=params, data=payload, timeout=20)
        print(f"[DETECT] status={response.status_code}")
        print(f"[DETECT] body={response.text}")

        if response.status_code != 200:
            return "unknown"

        data = response.json()
        detections = data.get("data", {}).get("detections", [])

        if not detections or not detections[0]:
            return "unknown"

        lang = detections[0][0].get("language", "unknown")
        return lang

    except Exception as e:
        print(f"[DETECT ERROR] {str(e)}")
        return "unknown"


def translate_text(text: str, target_lang: str) -> str:
    """
    Translate text (dịch văn bản)
    """
    if not GOOGLE_API_KEY:
        return "[LỖI] Thiếu GOOGLE_API_KEY"

    url = "https://translation.googleapis.com/language/translate/v2"
    params = {"key": GOOGLE_API_KEY}
    payload = {
        "q": text,
        "target": target_lang,
        "format": "text",
    }

    try:
        response = requests.post(url, params=params, data=payload, timeout=20)
        print(f"[TRANSLATE] status={response.status_code}")
        print(f"[TRANSLATE] body={response.text}")

        if response.status_code != 200:
            return f"[LỖI DỊCH] HTTP {response.status_code}"

        data = response.json()
        translated = (
            data.get("data", {})
            .get("translations", [{}])[0]
            .get("translatedText")
        )

        if not translated:
            return "[LỖI DỊCH] Không có dữ liệu trả về"

        return unescape(translated)

    except Exception as e:
        print(f"[TRANSLATE ERROR] {str(e)}")
        return f"[LỖI DỊCH] {str(e)}"


def detect_source_label(lang_code: str) -> str:
    """
    Map source language label (gắn nhãn ngôn ngữ nguồn)
    """
    if not lang_code:
        return "AUTO"

    lang_code = lang_code.lower()

    if lang_code.startswith("zh"):
        return "ZH"
    if lang_code == "vi":
        return "VI"
    if lang_code == "id":
        return "ID"
    if lang_code == "en":
        return "EN"
    if lang_code == "unknown":
        return "AUTO"

    return lang_code.upper()


def normalize_target_lang(lang: str) -> str:
    """
    Normalize language code (chuẩn hóa mã ngôn ngữ)
    """
    lang = (lang or "").strip()

    mapping = {
        "zh": "zh-TW",
        "zh-tw": "zh-TW",
        "tw": "zh-TW",
        "vi": "vi",
        "id": "id",
        "en": "en",
    }

    return mapping.get(lang.lower(), "")


def extract_event_context(event: dict) -> dict:
    """
    Extract event context (rút ngữ cảnh event)
    """
    source = event.get("source", {}) or {}
    message = event.get("message", {}) or {}

    return {
        "event_type": event.get("type"),
        "reply_token_exists": bool(event.get("replyToken")),
        "source_type": source.get("type"),
        "user_id": source.get("userId"),
        "group_id": source.get("groupId"),
        "room_id": source.get("roomId"),
        "message_type": message.get("type"),
        "message_id": message.get("id"),
        "text": message.get("text", ""),
    }


def build_actor_key(ctx: dict) -> str:
    """
    Build actor key (tạo khóa định danh)
    Ưu tiên:
    1. user_id
    2. group_id
    3. room_id
    """
    user_id = ctx.get("user_id")
    group_id = ctx.get("group_id")
    room_id = ctx.get("room_id")

    if user_id:
        return f"user:{user_id}"
    if group_id:
        return f"group:{group_id}"
    if room_id:
        return f"room:{room_id}"

    return ""


def handle_lang_command(actor_key: str, user_text: str) -> str:
    """
    /lang vi
    /lang zh
    /lang id
    /lang en
    """
    text = (user_text or "").strip()
    parts = text.split()

    print(f"[LANG CMD] raw_text={text}")
    print(f"[LANG CMD] parts={parts}")
    print(f"[LANG CMD] actor_key={actor_key}")

    if len(parts) != 2:
        print("[LANG CMD] skip_invalid_parts")
        return ""

    if parts[0].lower() != "/lang":
        print("[LANG CMD] skip_not_lang_command")
        return ""

    if not actor_key:
        print("[LANG CMD] missing_actor_key")
        return "Không xác định được khóa người dùng / nhóm để lưu ngôn ngữ."

    target = normalize_target_lang(parts[1])
    print(f"[LANG CMD] normalized_target={target}")

    if not target:
        return "Ngôn ngữ không hợp lệ. Dùng: /lang vi | /lang zh | /lang id | /lang en"

    USER_LANG_MAP[actor_key] = target
    print(f"[LANG MAP] set actor_key={actor_key} target={target}")

    return f"Đã lưu ngôn ngữ đích = {target}"


def handle_show_lang_command(actor_key: str, user_text: str) -> str:
    """
    /mylang
    """
    text = (user_text or "").strip().lower()
    if text != "/mylang":
        return ""

    if not actor_key:
        return "Không xác định được khóa người dùng / nhóm."

    current = USER_LANG_MAP.get(actor_key, DEFAULT_AUTO_TARGET)
    return f"Ngôn ngữ đích hiện tại = {current}"


def handle_translate_command(user_text: str) -> str:
    """
    Command mode (chế độ lệnh)
    /zh xin chào
    /vi 你好
    /id chào bạn
    """
    text = (user_text or "").strip()
    if not text:
        return ""

    for cmd, target_lang in SUPPORTED_COMMANDS.items():
        prefix = f"{cmd} "
        if text.startswith(prefix):
            source_text = text[len(prefix):].strip()

            if not source_text:
                return f"Cú pháp đúng: {cmd} nội dung"

            source_lang = detect_language(source_text)
            translated = translate_text(source_text, target_lang)
            source_label = detect_source_label(source_lang)

            return f"[{source_label} → {target_lang.upper()}]\n{translated}"

    return ""


def handle_auto_translate(actor_key: str, user_text: str) -> str:
    """
    Auto mode (chế độ tự động)
    Không có lệnh -> dịch theo ngôn ngữ đích đã lưu
    """
    target_lang = USER_LANG_MAP.get(actor_key, DEFAULT_AUTO_TARGET)

    source_lang = detect_language(user_text)
    translated = translate_text(user_text, target_lang)
    source_label = detect_source_label(source_lang)

    return f"[{source_label} → {target_lang.upper()}]\n{translated}"


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
        "line_secret_exists": bool(LINE_CHANNEL_SECRET),
        "google_api_key_exists": bool(GOOGLE_API_KEY),
        "google_sheet_id_exists": bool(GOOGLE_SHEET_ID),
        "default_auto_target": DEFAULT_AUTO_TARGET,
        "user_lang_map_count": len(USER_LANG_MAP),
    }), 200


@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        raw_body = request.get_data(as_text=True)
        signature = request.headers.get("X-Line-Signature", "")

        print("[WEBHOOK RAW BODY]", raw_body)
        print(f"[WEBHOOK HEADER] x_line_signature_exists={bool(signature)}")

        if not verify_line_signature(raw_body, signature):
            return "Invalid signature", 403

        body = json.loads(raw_body)
        print("[WEBHOOK PARSED]")
        print(json.dumps(body, ensure_ascii=False))

        events = body.get("events", [])
        print(f"[WEBHOOK] events_count={len(events)}")

        if not events:
            return "OK", 200

        for idx, event in enumerate(events, start=1):
            ctx = extract_event_context(event)
            print(f"[EVENT {idx}] {json.dumps(ctx, ensure_ascii=False)}")

            if ctx["event_type"] != "message":
                print(f"[EVENT {idx}] skip_non_message_event")
                continue

            if ctx["message_type"] != "text":
                print(f"[EVENT {idx}] skip_non_text_message")
                continue

            reply_token = event.get("replyToken")
            user_text = (ctx["text"] or "").strip()
            actor_key = build_actor_key(ctx)

            if not reply_token:
                print(f"[EVENT {idx}] missing_reply_token")
                continue

            if not user_text:
                reply_message(reply_token, "Tôi đã nhận được tin nhắn trống.")
                continue

            print(f"[MESSAGE] source_type={ctx['source_type']}")
            print(f"[MESSAGE] group_id={ctx['group_id']}")
            print(f"[MESSAGE] room_id={ctx['room_id']}")
            print(f"[MESSAGE] user_id={ctx['user_id']}")
            print(f"[MESSAGE] actor_key={actor_key}")
            print(f"[MESSAGE] text={user_text}")

            # 1) /lang
            result = handle_lang_command(actor_key, user_text)
            if result:
                reply_message(reply_token, result)
                continue

            # 2) /mylang
            result = handle_show_lang_command(actor_key, user_text)
            if result:
                reply_message(reply_token, result)
                continue

            # 3) command translate
            result = handle_translate_command(user_text)
            if result:
                reply_message(reply_token, result)
                continue

            # 4) auto translate
            result = handle_auto_translate(actor_key, user_text)
            reply_message(reply_token, result)

        return "OK", 200

    except Exception as e:
        print(f"[WEBHOOK ERROR] {str(e)}")
        return "Internal Server Error", 500


# =========================
# ENTRYPOINT
# =========================
if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    print(f"[BOOT] Running on 0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
