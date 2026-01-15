import google.generativeai as genai
import requests
import os
import json
import random
import re
from datetime import datetime, timedelta
import time

# ================= 環境變數 =================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

# 檔案設定
VOCAB_FILE = "vocab.json"
USER_DATA_FILE = "user_data.json"
MODEL_NAME = 'models/gemini-2.5-flash' # 穩定且額度較高

# 安全設定
SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]

# ================= 檔案存取工具 =================

def load_json(filename, default_content):
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                data = json.load(f)
                # 簡單合併預設值
                if isinstance(data, dict) and isinstance(default_content, dict):
                    for k, v in default_content.items():
                        if k not in data: data[k] = v
                return data
        except: return default_content
    return default_content

def save_json(filename, data):
    # Log 截斷 (保留最近 30 筆翻譯紀錄)
    if filename == USER_DATA_FILE and "translation_log" in data:
        if len(data["translation_log"]) > 30:
            data["translation_log"] = data["translation_log"][-30:]
            
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def send_telegram(message):
    if not TG_BOT_TOKEN: print(f"[模擬發送] {message[:50]}..."); return
    clean_msg = message.replace("**", "").replace("##", "").replace("__", "")
    try:
        requests.post(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage", json={
            "chat_id": TG_CHAT_ID, "text": clean_msg
        })
    except Exception as e: print(f"TG 發送失敗: {e}")

def normalize_text(text):
    if not text: return ""
    return text.strip().replace("　", " ").lower()

# ================= AI 核心：批改與分析 =================

def ai_correction(user_text, translation_history):
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(MODEL_NAME)
    
    print(f"🤖 AI 正在批改: {user_text[:20]}...")
    
    # 組合歷史紀錄字串
    history_str = "\n".join(translation_history[-10:]) if translation_history else "(尚無歷史紀錄)"
    
    prompt = f"""
    使用者正在練習日文（包含作業回答與隨堂練習），這是她剛剛傳來的內容：
    「{user_text}」
    
    【使用者的歷史翻譯紀錄 (由舊到新)】
    {history_str}
    
    請扮演一位【觀察入微且嚴格的日文教授】，完成以下任務：
    
    1. **📈 進度評估 (重點)**：
       - 比較今天的句子與歷史紀錄。
       - **判斷進步**：文法是否變精準？詞彙量是否增加？
       - **給予回饋**：請在開頭明確給予鼓勵 (如：「看到妳開始嘗試長難句了，很棒！」) 或是警惕 (如：「怎麼助詞還是用錯？」)。
       
    2. **🎯 批改與修正**：
       - 如果是多句回答，請逐一簡單批改。
       - 修正錯誤 (✅ 或 ❌)。
    
    3. **✨ 三種多樣化表達 (針對其中一句主要意思)**：
       請提供以下三種說法：
       - 👔 **正式 (Formal)**
       - 🍻 **口語 (Casual)**
       - 🔄 **換句話說 (Paraphrase)**
    
    【輸出格式】
    繁體中文，Emoji 排版，**不要** Markdown 粗體。
    """
    
    try:
        response = model.generate_content(prompt, safety_settings=SAFETY_SETTINGS)
        return response.text if response.text else "⚠️ AI 批改失敗"
    except Exception as e:
        return f"⚠️ AI 批改錯誤: {e}"

# ================= 邏輯核心：處理訊息 =================

def process_data():
    print("📥 開始處理資料...")
    
    vocab_data = load_json(VOCAB_FILE, {"words": []})
    user_data = load_json(USER_DATA_FILE, {
        "stats": {
            "last_active": "2000-01-01", 
            "streak_days": 0,
            "last_quiz_date": "2000-01-01",
            "last_quiz_questions_count": 0, # 昨天出了幾題
            "yesterday_answers_count": 0    # 昨天回了幾題 (含隨堂練習)
        },
        "translation_log": [] 
    })
    
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/getUpdates"
    
    try:
        response = requests.get(url).json()
        if "result" not in response: return vocab_data, user_data
        
        is_vocab_updated = False
        is_user_updated = False
        updates_log = []
        correction_msgs = []
        
        today_str = str(datetime.now().date())
        today_answers_accumulated = 0

        for item in response["result"]:
            if str(item["message"]["chat"]["id"]) != str(TG_CHAT_ID): continue
            
            msg_time = datetime.fromtimestamp(item["message"]["date"])
            if datetime.now() - msg_time > timedelta(hours=24): continue
            
            text = item["message"].get("text", "").strip()
            if not text: continue

            # === Case A: JSON 文字匯入 (以 [ 開頭) ===
            if text.startswith("["):
                try:
                    imported = json.loads(text)
                    if isinstance(imported, list):
                        added = 0
                        for word in imported:
                            if "kanji" not in word: continue
                            kanji = word.get("kanji")
                            if not any(normalize_text(w["kanji"]) == normalize_text(kanji) for w in vocab_data["words"]):
                                vocab_data["words"].append({
                                    "kanji": kanji, "kana": word.get("kana", ""),
                                    "meaning": word.get("meaning", ""),
                                    "count": 1, "added_date": today_str
                                })
                                added += 1
                                is_vocab_updated = True
                        updates_log.append(f"📂 匯入 {added} 個新單字")
                except: pass
                continue

            # === Case B: 存單字指令 (格式: 漢字 假名 意思) ===
            match = re.search(r"^(\S+)[ \u3000]+(\S+)[ \u3000]+(.+)$", text)
            # 必須確保它不像是一句日文 (簡單判斷：是否有助詞或標點，這裡用 Regex 強制三個區塊)
            # 如果符合存單字格式
            if match and len(text.split()) == 3:
                kanji, kana, meaning = match.groups()
                found = False
                for word in vocab_data["words"]:
                    if normalize_text(word["kanji"]) == normalize_text(kanji):
                        word["count"] += 1 
                        updates_log.append(f"🔄 強化記憶：{kanji}")
                        found = True
                        is_vocab_updated = True
                        break
                if not found:
                    vocab_data["words"].append({
                        "kanji": kanji, "kana": kana, "meaning": meaning, 
                        "count": 1, "added_date": today_str
                    })
                    updates_log.append(f"✅ 收錄：{kanji}")
                    is_vocab_updated = True
                continue

            # === Case C: 翻譯/交作業/隨堂練習 (所有其他文字) ===
            elif not text.startswith("/"):
                # 1. 計算答題量 (簡單算法：以換行符號判斷回答了幾題，至少算 1 題)
                lines_count = len([l for l in text.split('\n') if len(l.strip()) > 1])
                lines_count = max(1, lines_count)
                today_answers_accumulated += lines_count
                
                # 2. AI 批改 & 分析
                result = ai_correction(text, user_data["translation_log"])
                correction_msgs.append(f"📝 **批改與分析：**\n{result}")
                
                # 3. 寫入 Log (只存前 50 字避免過長)
                user_data["translation_log"].append(f"{today_str}: {text[:50]}")
                is_user_updated = True
                
                time.sleep(2) # 避免 API 過熱

        # === 結算數據 ===
        if user_data["stats"]["last_active"] != today_str:
            # 結算昨天的努力程度
            user_data["stats"]["yesterday_answers_count"] = today_answers_accumulated
            
            # 更新 Streak (只要有互動就算)
            if today_answers_accumulated > 0 or is_vocab_updated or is_user_updated:
                 yesterday = str((datetime.now() - timedelta(days=1)).date())
                 if user_data["stats"]["last_active"] == yesterday:
                     user_data["stats"]["streak_days"] += 1
                 else:
                     user_data["stats"]["streak_days"] = 1
                 user_data["stats"]["last_active"] = today_str
                 is_user_updated = True

        # === 發送訊息 ===
        if updates_log: send_telegram("\n".join(set(updates_log)))
        for msg in correction_msgs:
            send_telegram(msg)
            time.sleep(1)

        return vocab_data, user_data

    except Exception as e:
        print(f"Error: {e}")
        return load_json(VOCAB_FILE, {}), load_json(USER_DATA_FILE, {})

# ================= 每日特訓生成 =================

def run_daily_quiz(vocab, user):
    if not vocab.get("words"):
        send_telegram("📭 單字庫空的！快傳單字給我！")
        return

    # 1. 判斷偷懶程度
    questions_given = user["stats"].get("last_quiz_questions_count", 0)
    answers_given = user["stats"].get("yesterday_answers_count", 0)
    
    answer_rate = 0
    if questions_given > 0:
        answer_rate = answers_given / questions_given
    
    # 情緒 Prompt
    emotion_prompt = ""
    if questions_given == 0:
        emotion_prompt = "這是第一次出題，請用充滿活力與希望的語氣歡迎使用者。"
    elif answer_rate >= 0.8:
        emotion_prompt = f"昨日出題 {questions_given}，她回覆 {answers_given} (及以上)。太棒了！請大力誇獎她的自律，並鼓勵保持。"
    elif answer_rate >= 0.3:
        emotion_prompt = f"昨日出題 {questions_given}，她回覆 {answers_given}。請用「勉強接受」的語氣，肯定她有練習，但提醒題數還可以更多。"
    else:
        emotion_prompt = f"昨日出題 {questions_given}，她只回覆 {answers_given} (甚至可能為 0)。請開啟【情勒模式 😈】，質問她為什麼無視作業？是不是想放棄日文？"

    # 2. 出題
    weights = [w.get("count", 1) * 5 for w in vocab["words"]]
    k = min(10, len(vocab["words"]))
    selected_words = random.choices(vocab["words"], weights=weights, k=k)
    word_list = "\n".join([f"{w['kanji']} ({w['meaning']})" for w in selected_words])
    
    today_questions_count = 10
    user["stats"]["last_quiz_questions_count"] = today_questions_count
    user["stats"]["last_quiz_date"] = str(datetime.now().date())

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(MODEL_NAME)

    print("🤖 AI 生成測驗中...")
    prompt = f"""
    你是日文 N2 斯巴達教練。
    
    【情緒設定】
    {emotion_prompt}
    
    【題目生成】
    單字庫：
    {word_list}
    
    請製作 **10 題** 翻譯測驗：
    - **7 題：中翻日** (強迫輸出)
    - **3 題：日翻中**
    
    【格式】
    繁體中文 + Emoji。題目與解答分開。
    """
    
    try:
        response = model.generate_content(prompt, safety_settings=SAFETY_SETTINGS)
        if response.text:
            send_telegram(response.text)
    except:
        send_telegram("⚠️ 測驗生成失敗")
    
    return user

if __name__ == "__main__":
    # 1. 處理資料
    v_data, u_data = process_data()
    
    # 2. 執行測驗
    u_data_updated = run_daily_quiz(v_data, u_data)
    
    # 3. 存檔
    save_json(VOCAB_FILE, v_data)
    if u_data_updated:
        save_json(USER_DATA_FILE, u_data_updated)
    else:
        save_json(USER_DATA_FILE, u_data)