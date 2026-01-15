import google.generativeai as genai
import requests
import os
import json
import random
import re
from datetime import datetime, timedelta

# ================= 環境變數 =================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

VOCAB_FILE = "vocab.json"
MODEL_NAME = 'models/gemini-2.5-flash'

# 安全設定 (防止 AI 拒絕回答)
SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]

# ================= 工具函式 =================

def load_vocab():
    default_data = {"words": []}
    if os.path.exists(VOCAB_FILE):
        try:
            with open(VOCAB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: return default_data
    return default_data

def save_vocab(data):
    with open(VOCAB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def send_telegram(message):
    if not TG_BOT_TOKEN: print(f"[模擬發送] {message[:50]}..."); return
    
    # 清洗 Markdown 符號
    clean_msg = message.replace("**", "").replace("##", "").replace("__", "")
    
    try:
        requests.post(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage", json={
            "chat_id": TG_CHAT_ID, "text": clean_msg
        })
    except Exception as e: print(f"TG 發送失敗: {e}")

def normalize_text(text):
    return text.strip().replace("　", " ").lower()

# ================= 邏輯：處理使用者輸入 (存單字) =================

def process_updates():
    print("📥 檢查是否有新單字...")
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/getUpdates"
    
    try:
        response = requests.get(url).json()
        if "result" not in response: return load_vocab()
        
        vocab_data = load_vocab()
        is_updated = False
        updates_log = []

        for item in response["result"]:
            if str(item["message"]["chat"]["id"]) != str(TG_CHAT_ID): continue
            
            msg_time = datetime.fromtimestamp(item["message"]["date"])
            if datetime.now() - msg_time > timedelta(hours=24): continue
            
            text = item["message"].get("text", "").strip()
            
            # Regex 解析：漢字 空白 假名 空白 意思
            match = re.search(r"^(\S+)[ \u3000]+(\S+)[ \u3000]+(.+)$", text)
            
            if match:
                kanji, kana, meaning = match.groups()
                
                # 檢查是否已存在
                found = False
                for word in vocab_data["words"]:
                    if normalize_text(word["kanji"]) == normalize_text(kanji) and \
                       normalize_text(word["kana"]) == normalize_text(kana):
                        word["count"] = word.get("count", 0) + 1
                        word["last_review"] = str(datetime.now().date())
                        updates_log.append(f"🔄 強化記憶：{kanji} (累計 {word['count']} 次)")
                        found = True
                        is_updated = True
                        break
                
                if not found:
                    new_word = {
                        "kanji": kanji,
                        "kana": kana,
                        "meaning": meaning,
                        "count": 1,
                        "added_date": str(datetime.now().date())
                    }
                    vocab_data["words"].append(new_word)
                    updates_log.append(f"✅ 收錄新詞：{kanji}")
                    is_updated = True

        if is_updated:
            save_vocab(vocab_data)
            if updates_log:
                send_telegram("\n".join(set(updates_log)))
        
        return vocab_data

    except Exception as e:
        print(f"Update Error: {e}")
        return load_vocab()

# ================= 每日特訓生成 =================

def run_daily_quiz(data):
    if not data.get("words"):
        send_telegram("📭 單字庫是空的！請傳送單字給我 (格式: 漢字 假名 意思)")
        return

    # 1. 權重抽樣
    weights = [w.get("count", 1) * 5 for w in data["words"]]
    k = min(10, len(data["words"]))
    selected_words = random.choices(data["words"], weights=weights, k=k)
    
    word_text = "\n".join([f"{w['kanji']} ({w['kana']}) : {w['meaning']}" for w in selected_words])

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(MODEL_NAME)

    print("🤖 AI 生成測驗中...")
    prompt = f"""
    你是日文 N2 斯巴達教練。請根據以下單字庫製作今日特訓。
    
    【使用者單字庫】
    {word_text}
    
    【任務要求】
    1. **全篇使用繁體中文**。
    2. 嚴禁 Markdown 粗體 (**)，請用 Emoji 排版。
    3. 翻譯題請使用 N2/N3 常見文法，不要太過簡單。
    
    【輸出內容】
    
    🧠 **自動記憶強化 (重點單字)**
    (從單字庫挑選 3 個最難的字，提供例句)
    1. [漢字] ([假名]) - [意思]
       例句：[日文] ([中文])
    
    ⚔️ **斯巴達翻譯特訓 (共 10 題)**
    
    🔹 **Part A: 日翻中 (請翻譯)**
    (利用單字庫的字，造 5 個日文句子)
    1. ...
    
    🔹 **Part B: 中翻日 (請試著用日文說)**
    (出 5 個中文句子，強迫使用者回想單字與文法)
    6. ...
    
    (最後附上參考答案與解析，但在前面加上 "--- 參考解答 ---")
    """
    
    try:
        response = model.generate_content(prompt, safety_settings=SAFETY_SETTINGS)
        send_telegram(response.text)
    except Exception as e:
        print(f"Gemini Error: {e}")
        send_telegram("⚠️ AI 老師今天請假了 (API Error)")

if __name__ == "__main__":
    # 1. 先處理使用者昨天輸入的單字
    current_data = process_updates()
    
    # 2. 執行每日測驗
    run_daily_quiz(current_data)