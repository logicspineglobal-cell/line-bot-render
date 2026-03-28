import os
import json
import hmac
import base64
import hashlib
import html
from datetime import datetime, timezone

import requests
import gspread
from flask import Flask, request, jsonify
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)

# =========================================================
# ENVIRONMENT VARIABLES
# =========================================================
LINE_CHANNEL_ACCESS_TOKEN = (os.getenv("LINE_CHANNEL_ACCESS_TOKEN") or "").strip()
LINE_CHANNEL_SECRET = (os.getenv("LINE_CHANNEL_SECRET") or "").strip()
GOOGLE_API_KEY = (os.getenv("GOOGLE_API_KEY") or "").strip()
GOOGLE_SHEET_ID = (os.getenv("GOOGLE_SHEET_ID") or "").strip()
GOOGLE_SERVICE_ACCOUNT_JSON = (os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON") or "").strip()

# =========================================================
# CONSTANTS
# =========================================================
LINE_REPLY_URL = "https://api.line.me/v2/bot/message/reply"
GOOGLE_TRANSLATE_URL = "https://translation.googleapis.com/language/translate/v2"
USER_LANG_SHEET_NAME = "USER_LANG_MAP"
TRANSLATION_LOG_SHEET_NAME = "TRANSLATION_LOG"

# =========================================================
# BOOT LOGS
# =========================================================
print("==> Running 'python line_webhook.py'")
print("[BOOT] Starting LINE bot on Render...")
print(f"[BOOT] LINE_CHANNEL_ACCESS_TOKEN exists: {bool(LINE_CHANNEL_ACCESS_TOKEN)}")
print(f"[BOOT] LINE_CHANNEL_SECRET exists: {bool(LINE_CHANNEL_SECRET)}")
print(f"[BOOT] GOOGLE_API_KEY exists: {bool(GOOGLE_API_KEY)}")
print(f"[BOOT] GOOGLE_SHEET_ID exists: {bool(GOOGLE_SHEET_ID)}")
print(f"[BOOT] GOOGLE_SERVICE_ACCOUNT_JSON exists: {bool(GOOGLE_SERVICE_ACCOUNT_JSON)}")

# =========================================================
# HEALTH CHECK
# =========================================================
@app.route("/", methods=["GET"])
def home():
    return "LINE webhook is live", 200


# =========================================================
# UTILS
# =========================================================
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_input_text(text: str) -> str:
    clean_text = (text or "").strip()

    if "→" in clean_text:
        clean_text = clean_text.split("→")[0].strip()

    return clean_text


def normalize_target_lang(raw_lang: str):
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


# =========================================================
# SECURITY
# =========================================================
def verify_signature(channel_secret: str, body: str, x_line_signature: str) -> bool:
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


# =========================================================
# LINE REPLY
# =========================================================
def reply_line_message(reply_token: str, text: str) -> bool:
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

    print(f"[LINE REPLY DEBUG] payload={json.dumps(payload, ensure_ascii=False)}")

    try:
        response = requests.post(
            LINE_REPLY_URL,
            headers=headers,
            json=payload,
            timeout=15
        )
        print(f"[LINE REPLY] status={response.status_code}")
        print(f"[LINE REPLY] body={response.text}")
        return response.status_code == 200
    except Exception as exc:
        print(f"[LINE REPLY ERROR] {str(exc)}")
        return False


# =========================================================
# GOOGLE SHEET
# =========================================================
def get_gspread_client():
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        print("[SHEET] GOOGLE_SERVICE_ACCOUNT_JSON missing")
        return None

    try:
        credentials_dict = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)

        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]

        credentials = ServiceAccountCredentials.from_json_keyfile_dict(
            credentials_dict,
            scope
        )

        client = gspread.authorize(credentials)
        return client

    except Exception as exc:
        print(f"[SHEET ERROR] authorize failed: {str(exc)}")
        return None


def get_spreadsheet():
    if not GOOGLE_SHEET_ID:
        print("[SHEET] GOOGLE_SHEET_ID missing")
        return None

    client = get_gspread_client()
    if client is None:
        return None

    try:
        return client.open_by_key(GOOGLE_SHEET_ID)
    except Exception as exc:
        print(f"[SHEET ERROR] open spreadsheet failed: {str(exc)}")
        return None


def get_user_lang_worksheet():
    spreadsheet = get_spreadsheet()
    if spreadsheet is None:
        return None

    try:
        return spreadsheet.worksheet(USER_LANG_SHEET_NAME)
    except Exception as exc:
        print(f"[SHEET ERROR] open USER_LANG_MAP failed: {str(exc)}")
        return None


def get_translation_log_worksheet():
    spreadsheet = get_spreadsheet()
    if spreadsheet is None:
        return None

    try:
        return spreadsheet.worksheet(TRANSLATION_LOG_SHEET_NAME)
    except Exception as exc:
        print(f"[SHEET ERROR] open TRANSLATION_LOG failed: {str(exc)}")
        return None


def get_user_target_lang(user_id: str, default_lang: str = "en") -> str:
    worksheet = get_user_lang_worksheet()
    if worksheet is None:
        print(f"[SHEET] fallback target_lang={default_lang}")
        return default_lang

    try:
        records = worksheet.get_all_records()
        for row in records:
            row_user_id = str(row.get("user_id", "")).strip()
            if row_user_id == user_id:
                target_lang = str(row.get("target_lang", "")).strip()
                if target_lang:
                    print(f"[SHEET] found target_lang={target_lang} for user_id={user_id}")
                    return target_lang

        print(f"[SHEET] user_id not found, fallback target_lang={default_lang}")
        return default_lang

    except Exception as exc:
        print(f"[SHEET ERROR] get_user_target_lang failed: {str(exc)}")
        return default_lang


def save_user_target_lang(user_id: str, target_lang: str) -> bool:
    worksheet = get_user_lang_worksheet()
    if worksheet is None:
        return False

    try:
        values = worksheet.get_all_values()

        if not values:
            worksheet.append_row(["user_id", "target_lang", "updated_at"])
            values = worksheet.get_all_values()

        found_row_index = None

        for idx, row in enumerate(values[1:], start=2):
            current_user_id = row[0].strip() if len(row) > 0 else ""
            if current_user_id == user_id:
                found_row_index = idx
                break

        timestamp = now_iso()

        if found_row_index:
            worksheet.update(
                f"A{found_row_index}:C{found_row_index}",
                [[user_id, target_lang, timestamp]]
            )
            print(f"[SHEET] updated row={found_row_index} user_id={user_id} target_lang={target_lang}")
        else:
            worksheet.append_row([user_id, target_lang, timestamp])
            print(f"[SHEET] appended user_id={user_id} target_lang={target_lang}")

        return True

    except Exception as exc:
        print(f"[SHEET ERROR] save_user_target_lang failed: {str(exc)}")
        return False


def log_translation_event(
    user_id: str,
    source_type: str,
    group_id: str,
    room_id: str,
    target_lang: str,
    input_text: str
) -> bool:
    worksheet = get_translation_log_worksheet()
    if worksheet is None:
        print("[LOG] TRANSLATION_LOG unavailable")
        return False

    try:
        worksheet.append_row([
            now_iso(),
            user_id or "",
            source_type or "",
            group_id or "",
            room_id or "",
            target_lang or "",
            input_text or ""
        ])
        print(f"[LOG] saved user_id={user_id} source_type={source_type} group_id={group_id} room_id={room_id}")
        return True

    except Exception as exc:
        print(f"[LOG ERROR] {str(exc)}")
        return False


# =========================================================
# GOOGLE TRANSLATE
# =========================================================
def translate_text(text: str, target_lang: str):
    if not GOOGLE_API_KEY:
        print("[TRANSLATE] GOOGLE_API_KEY missing")
        return None

    payload = {
        "q": text,
        "target": target_lang,
        "format": "text",
        "key": GOOGLE_API_KEY
    }

    print(f"[TRANSLATE] input_text={text}")
    print(f"[TRANSLATE] target_lang={target_lang}")

    try:
        response = requests.post(
            GOOGLE_TRANSLATE_URL,
            data=payload,
            timeout=20
        )

        print(f"[TRANSLATE] status={response.status_code}")
        print(f"[TRANSLATE] body={response.text}")

        if response.status_code != 200:
            return None

        data = response.json()
        translated = data["data"]["translations"][0]["translatedText"]
        translated = html.unescape(translated)

        print(f"[TRANSLATE] translated_text={translated}")
        return translated

    except Exception as exc:
        print(f"[TRANSLATE ERROR] {str(exc)}")
        return None


# =========================================================
# COMMAND HANDLERS
# =========================================================
def handle_lang_command(user_id: str, text: str, reply_token: str):
    print(f"[LANG CMD] raw_text={text}")

    parts = text.strip().split()
    print(f"[LANG CMD] parts={parts}")

    if len(parts) != 2:
        ok = reply_line_message(reply_token, "Sai cú pháp. Dùng: /lang zh")
        print(f"[REPLY DEBUG] /lang syntax result={ok}")
        return

    target_lang = normalize_target_lang(parts[1])
    print(f"[LANG CMD] normalized_target={target_lang}")

    if not target_lang:
        ok = reply_line_message(reply_token, "Ngôn ngữ chưa hỗ trợ. Dùng ví dụ: /lang zh")
        print(f"[REPLY DEBUG] /lang unsupported result={ok}")
        return

    saved = save_user_target_lang(user_id, target_lang)
    print(f"[LANG CMD] sheet_save_result={saved}")

    if not saved:
        ok = reply_line_message(
            reply_token,
            "Lưu ngôn ngữ thất bại. Kiểm tra kết nối Google Sheet."
        )
        print(f"[REPLY DEBUG] /lang save failed result={ok}")
        return

    ok = reply_line_message(reply_token, f"Đã lưu ngôn ngữ đích = {target_lang}")
    print(f"[REPLY DEBUG] /lang success result={ok}")


def handle_normal_message(
    user_id: str,
    text: str,
    reply_token: str,
    source_type: str,
    group_id: str,
    room_id: str
):
    print(f"[MESSAGE FLOW] raw_input_text={text}")

    clean_text = clean_input_text(text)
    print(f"[MESSAGE FLOW] clean_input_text={clean_text}")

    if not clean_text:
        ok = reply_line_message(reply_token, "Tin nhắn rỗng sau khi làm sạch input.")
        print(f"[REPLY DEBUG] empty_input result={ok}")
        return

    target_lang = get_user_target_lang(user_id, default_lang="en")
    print(f"[MESSAGE FLOW] target_lang={target_lang}")

    translated = translate_text(clean_text, target_lang)

    if translated is None:
        ok = reply_line_message(
            reply_token,
            "Dịch thất bại. Kiểm tra GOOGLE_API_KEY hoặc Google Sheet credentials."
        )
        print(f"[REPLY DEBUG] translate failed result={ok}")
        return

    log_saved = log_translation_event(
        user_id=user_id,
        source_type=source_type,
        group_id=group_id,
        room_id=room_id,
        target_lang=target_lang,
        input_text=clean_text
    )
    print(f"[LOG] translation_log_saved={log_saved}")

    output_text = f"[AUTO → {target_lang}]\n{translated}"
    ok = reply_line_message(reply_token, output_text)
    print(f"[REPLY DEBUG] normal success result={ok}")


# =========================================================
# WEBHOOK
# =========================================================
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
    except Exception as exc:
        print(f"[WEBHOOK JSON ERROR] {str(exc)}")
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

        if not user_id:
            print("[MESSAGE] user_id missing")
            if reply_token:
                reply_line_message(reply_token, "Không lấy được user_id từ LINE event.")
            continue

        print(f"[MESSAGE] source_type={source_type}")
        print(f"[MESSAGE] group_id={group_id}")
        print(f"[MESSAGE] room_id={room_id}")
        print(f"[MESSAGE] user_id={user_id}")
        print(f"[MESSAGE] text={text}")

        if text.startswith("/lang"):
            handle_lang_command(user_id, text, reply_token)
        else:
            handle_normal_message(
                user_id=user_id,
                text=text,
                reply_token=reply_token,
                source_type=source_type,
                group_id=group_id,
                room_id=room_id
            )

    return jsonify({"ok": True}), 200


# =========================================================
# MAIN
# =========================================================
if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    print(f"[BOOT] Running on 0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port)
