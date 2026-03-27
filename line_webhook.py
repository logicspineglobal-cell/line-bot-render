import os
import json
import csv
from io import StringIO

import requests
from flask import Flask, request

# =========================
# INIT APP
# =========================
app = Flask(__name__)

# =========================
# PATH
# =========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")
USER_LANG_FILE = os.path.join(BASE_DIR, "user_lang_map.json")
PENDING_GLOSSARY_FILE = os.path.join(BASE_DIR, "pending_glossary.txt")
REPORTS_LOG_FILE = os.path.join(BASE_DIR, "reports_log.txt")

# =========================
# LOAD ENV FILE
# =========================
def load_env_file(env_path):
    env_map = {}

    try:
        with open(env_path, "r", encoding="utf-8-sig") as f:
            for raw_line in f:
                line = raw_line.strip()

                if not line:
                    continue

                if line.startswith("#"):
                    continue

                if "=" not in line:
                    continue

                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()

                if key:
                    env_map[key] = value

    except Exception as e:
        print("[ENV READ ERROR]:", str(e))

    return env_map


ENV_MAP = load_env_file(ENV_PATH)

LINE_CHANNEL_ACCESS_TOKEN = ENV_MAP.get("LINE_CHANNEL_ACCESS_TOKEN")
GOOGLE_TRANSLATE_API_KEY = ENV_MAP.get("GOOGLE_TRANSLATE_API_KEY")
GOOGLE_SHEET_ID = ENV_MAP.get("GOOGLE_SHEET_ID")

print("ENV_PATH:", ENV_PATH)
print("ENV_EXISTS:", os.path.exists(ENV_PATH))
print("TOKEN_EXISTS:", bool(LINE_CHANNEL_ACCESS_TOKEN))
print("GOOGLE_KEY_EXISTS:", bool(GOOGLE_TRANSLATE_API_KEY))
print("GOOGLE_SHEET_ID_EXISTS:", bool(GOOGLE_SHEET_ID))

# =========================
# PERSISTENT MEMORY (FILE)
# =========================
def load_user_lang_map():
    try:
        with open(USER_LANG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            print("[LOAD USER MAP]:", data)
            return data

        print("[LOAD USER MAP ERROR]: invalid format")
        return {}

    except FileNotFoundError:
        print("[LOAD USER MAP]: file not found -> start empty")
        return {}

    except Exception as e:
        print("[LOAD USER MAP ERROR]:", str(e))
        return {}


def save_user_lang_map(data):
    try:
        with open(USER_LANG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print("[SAVE USER MAP]: OK")

    except Exception as e:
        print("[SAVE USER MAP ERROR]:", str(e))


user_lang_map = load_user_lang_map()

# =========================
# DICTIONARY FROM GOOGLE SHEET
# NOTE:
# - Reads CSV export from first sheet tab (gid=0)
# - Keep your main dictionary in the first tab
# =========================
def load_dictionary():
    if not GOOGLE_SHEET_ID:
        print("[DICT ERROR] Missing GOOGLE_SHEET_ID")
        return {}

    url = f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}/export?format=csv&gid=0"

    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()

        csv_data = StringIO(response.content.decode("utf-8"))
        reader = csv.reader(csv_data)

        dictionary = {}

        for i, row in enumerate(reader):
            if i == 0:
                continue

            if len(row) >= 2:
                source = row[0].strip().lower()
                target = row[1].strip()

                if source and target:
                    dictionary[source] = target

        print("[DICT SIZE]:", len(dictionary))
        return dictionary

    except Exception as e:
        print("[DICT ERROR]:", str(e))
        return {}

# =========================
# CACHE
# =========================
translation_cache = {}

# =========================
# GOOGLE TRANSLATE
# =========================
def translate_text_google(text, target_lang="zh-TW"):
    if not GOOGLE_TRANSLATE_API_KEY:
        print("[GOOGLE ERROR] Missing GOOGLE_TRANSLATE_API_KEY")
        return text

    clean_text = text.strip()
    cache_key = f"{target_lang}::{clean_text.lower()}"

    if cache_key in translation_cache:
        print("[CACHE HIT]:", cache_key)
        return translation_cache[cache_key]

    url = "https://translation.googleapis.com/language/translate/v2"
    params = {"key": GOOGLE_TRANSLATE_API_KEY}
    data = {
        "q": clean_text,
        "target": target_lang,
        "format": "text"
    }

    response = requests.post(url, params=params, data=data, timeout=20)

    print("[GOOGLE STATUS]:", response.status_code)
    print("[GOOGLE TEXT]:", response.text)

    response.raise_for_status()

    result = response.json()
    translated = result["data"]["translations"][0]["translatedText"]

    translation_cache[cache_key] = translated
    return translated

# =========================
# LINE REPLY
# =========================
def reply_message(reply_token, text):
    if not LINE_CHANNEL_ACCESS_TOKEN:
        print("[LINE ERROR] Missing LINE_CHANNEL_ACCESS_TOKEN")
        return

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

    response = requests.post(url, headers=headers, json=payload, timeout=20)

    print("[REPLY STATUS]:", response.status_code)
    print("[REPLY TEXT]:", response.text)

    response.raise_for_status()

# =========================
# HELPERS
# =========================
def normalize_target_lang(lang_code):
    lang_code = (lang_code or "").strip().lower()

    mapping = {
        "vi": "vi",
        "en": "en",
        "zh": "zh-TW",
        "zh-tw": "zh-TW",
        "tw": "zh-TW",
        "th": "th",
        "id": "id"
    }

    return mapping.get(lang_code)


def get_user_id_from_event(event):
    source = event.get("source", {})
    return source.get("userId")


def get_client_id_from_event(event):
    source = event.get("source", {})

    if source.get("groupId"):
        return source.get("groupId")

    if source.get("roomId"):
        return source.get("roomId")

    return "private"


def get_target_lang_for_user(user_id):
    if not user_id:
        print("[TARGET LANG]: default zh-TW (missing userId)")
        return "zh-TW"

    target_lang = user_lang_map.get(user_id, "zh-TW")
    print("[TARGET LANG]:", target_lang)
    return target_lang

# =========================
# COMMAND: /lang
# =========================
def handle_lang_command(user_text, user_id):
    parts = user_text.strip().split()

    if len(parts) != 2:
        return "Sai cú pháp. Dùng: /lang vi hoặc /lang zh hoặc /lang en hoặc /lang th hoặc /lang id"

    requested = normalize_target_lang(parts[1])

    if not requested:
        return "Ngôn ngữ không hỗ trợ. Dùng: vi | en | zh | th | id"

    if not user_id:
        return "Không tìm thấy userId để lưu ngôn ngữ."

    user_lang_map[user_id] = requested
    save_user_lang_map(user_lang_map)

    print("[SAVE USER LANG]:", user_id, requested)

    label_map = {
        "vi": "Tiếng Việt",
        "en": "English",
        "zh-TW": "繁體中文",
        "th": "ไทย",
        "id": "Bahasa Indonesia"
    }

    return f"Đã lưu ngôn ngữ cá nhân: {label_map.get(requested, requested)}"

# =========================
# COMMAND: /menu
# =========================
def handle_menu():
    return (
        "🤖 LINE Translator PRO\n\n"
        "1️⃣ Gửi tin nhắn → tự dịch\n"
        "2️⃣ /lang vi | en | zh | th | id\n"
        "3️⃣ /add abc = xyz (thêm từ chuyên ngành)\n"
        "4️⃣ /report nội dung (báo cáo sự cố)\n"
        "5️⃣ /help (xem hướng dẫn)\n\n"
        "💡 Ví dụ test:\n"
        "- sensor error\n"
        "- /lang vi\n"
        "- /add overtime = tăng ca\n"
        "- /report máy 05 bị lỗi cảm biến"
    )

# =========================
# COMMAND: /help
# =========================
def handle_help():
    return (
        "📘 HƯỚNG DẪN NHANH\n\n"
        "• Gửi tin nhắn bất kỳ để bot dịch.\n"
        "• Dùng /lang để chọn ngôn ngữ cá nhân.\n"
        "• Dùng /add để đề xuất thuật ngữ mới.\n"
        "• Dùng /report để báo lỗi / báo việc.\n\n"
        "Ví dụ:\n"
        "/lang zh\n"
        "/add ARC card = thẻ cư trú\n"
        "/report máy số 3 bị rung mạnh"
    )

# =========================
# COMMAND: /add
# =========================
def handle_add_command(user_text):
    try:
        if "=" not in user_text:
            return "Sai cú pháp. Dùng: /add abc = xyz"

        content = user_text.replace("/add", "", 1).strip()
        parts = content.split("=", 1)

        source = parts[0].strip().lower()
        target = parts[1].strip()

        if not source or not target:
            return "Sai cú pháp. Dùng: /add abc = xyz"

        print("[ADD NEW TERM]:", source, "->", target)

        with open(PENDING_GLOSSARY_FILE, "a", encoding="utf-8") as f:
            f.write(f"{source}={target}\n")

        return f"Đã ghi nhận: {source} → {target} (chờ duyệt)"

    except Exception as e:
        print("[ADD ERROR]:", str(e))
        return "Lỗi khi thêm từ"

# =========================
# COMMAND: /report
# =========================
def handle_report_command(user_text, user_id, client_id):
    try:
        content = user_text.replace("/report", "", 1).strip()

        if not content:
            return "Sai cú pháp. Dùng: /report nội dung"

        print("[REPORT]:", user_id, content)
        print("[REPORT CLIENT]:", client_id)

        with open(REPORTS_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{client_id} | {user_id} | {content}\n")

        return f"Đã gửi báo cáo: {content}"

    except Exception as e:
        print("[REPORT ERROR]:", str(e))
        return "Lỗi khi gửi báo cáo"

# =========================
# WEBHOOK
# =========================
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)
        print("[WEBHOOK HIT]")
        print("[DATA]:", data)

        dictionary = load_dictionary()
        events = data.get("events", [])

        for event in events:
            if event.get("type") != "message":
                continue

            message = event.get("message", {})
            if message.get("type") != "text":
                continue

            reply_token = event.get("replyToken")
            user_text = message.get("text", "").strip()
            user_id = get_user_id_from_event(event)
            client_id = get_client_id_from_event(event)

            print("[CLIENT]:", client_id)
            print("[USER]:", user_text)
            print("[USER ID]:", user_id)

            if not reply_token:
                print("[SKIP] Missing replyToken")
                continue

            if user_text.lower() == "/menu":
                reply_message(reply_token, handle_menu())
                continue

            if user_text.lower() == "/help":
                reply_message(reply_token, handle_help())
                continue

            if user_text.lower().startswith("/add"):
                result = handle_add_command(user_text)
                reply_message(reply_token, result)
                continue

            if user_text.lower().startswith("/report"):
                result = handle_report_command(user_text, user_id, client_id)
                reply_message(reply_token, result)
                continue

            if user_text.lower().startswith("/lang"):
                result_text = handle_lang_command(user_text, user_id)
                reply_message(reply_token, result_text)
                continue

            target_lang = get_target_lang_for_user(user_id)
            lookup_key = user_text.lower()

            if lookup_key in dictionary:
                translated_text = dictionary[lookup_key]
                print("[DICT HIT]:", translated_text)
            else:
                translated_text = translate_text_google(user_text, target_lang=target_lang)
                print("[GOOGLE HIT]:", translated_text)

            reply_message(reply_token, translated_text)

        return "OK", 200

    except Exception as e:
        print("[ERROR]:", str(e))
        return "ERROR", 500

# =========================
# HEALTH CHECK
# =========================
@app.route("/", methods=["GET"])
def home():
    return "LINE BOT RUNNING", 200

# =========================
# RUN
# =========================
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)