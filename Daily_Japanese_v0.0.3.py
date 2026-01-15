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
MODEL_NAME = 'models/gemini-2.5-flash' 

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
                if isinstance(data, dict) and isinstance(default_content, dict):
                    for k, v in default_content.items():
                        if k not in data: data[k] = v
                return data
        except: return default_content
    return default_content

def save_json(filename, data):
    if filename == USER_DATA_FILE and "translation_log" in data:
        if len(data["translation_log"]) > 30:
            data["translation_log"] = data["translation_log"][-30:]
            
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def send_telegram(message):
    if not TG_BOT_TOKEN: print(f"[模擬發送] {message[:50]}..."); return
    if not message: return

    clean_msg = message.replace("**", "").replace("##", "").replace("__", "")
    clean_msg = re.sub(r'<br\s*/?>', '\n', clean_msg)
    
    try:
        requests.post(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage", json={
            "chat_id": TG_CHAT_ID, "text": clean_msg
        })
    except Exception as e: print(f"TG 發送失敗: {e}")

def normalize_text(text):
    if not text: return ""
    return text.strip().replace("　", " ").lower()

# ================= AI 核心 =================

def ai_correction(user_text, translation_history):
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(MODEL_NAME)
    
    print(f"🤖 AI 正在批改 (合併後長度 {len(user_text)}): {user_text[:20]}...")
    history_str = "\n".join(translation_history[-10:]) if translation_history else "(尚無歷史紀錄)"
    
    prompt = f"""
    使用者正在練習日文，這是她剛剛傳來的內容（可能包含多則訊息的合併）：
    「{user_text}」
    
    【歷史紀錄】
    {history_str}
    
    請扮演日文教授完成批改：
    1. **📈 進度評估**：比較歷史紀錄，判斷是否有進步？給予鼓勵或警惕。
    2. **🎯 批改**：請針對上述內容進行批改，修正錯誤 (✅/❌)。
    3. **✨ 三種多樣化表達**：
       - 👔 正式
       - 🍻 口語
       - 🔄 換句話說
    
    【格式要求】
    - 繁體中文 + Emoji。
    - **嚴禁使用 HTML 標籤 (如 <br>)**，請直接換行。
    - 不要使用 Markdown 粗體。
    """
    
    try:
        response = model.generate_content(prompt, safety_settings=SAFETY_SETTINGS)
        return response.text if response.text else "⚠️ AI 批改失敗"
    except Exception as e:
        return f"⚠️ AI 批改錯誤: {e}"

# ================= 邏輯核心 (關鍵修改：加入 update_id 判斷) =================

def process_data():
    print("📥 開始處理資料...")
    
    vocab_data = load_json(VOCAB_FILE, {"words": []})
    user_data = load_json(USER_DATA_FILE, {
        "stats": {
            "last_active": "2000-01-01", 
            "streak_days": 0,
            "execution_count": 0,
            "last_quiz_date": "2000-01-01",
            "last_quiz_questions_count": 0,
            "yesterday_answers_count": 0,
            "last_update_id": 0 # ✅ 新增：紀錄上次處理到的最後一則訊息 ID
        },
        "pending_answers": "",
        "translation_log": []
    })
    
    # 防呆初始化
    if "execution_count" not in user_data["stats"]: user_data["stats"]["execution_count"] = 0
    if "streak_days" not in user_data["stats"]: user_data["stats"]["streak_days"] = 0
    if "last_update_id" not in user_data["stats"]: user_data["stats"]["last_update_id"] = 0

    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/getUpdates"
    
    try:
        response = requests.get(url).json()
        if "result" not in response: return vocab_data, user_data
        
        is_updated = False
        updates_log = []
        correction_msgs = []
        
        today_str = str(datetime.now().date())
        today_answers_accumulated = 0
        
        pending_correction_texts = []
        
        # 取得目前記錄的最後 ID
        last_processed_id = user_data["stats"]["last_update_id"]
        # 用來追蹤這次執行處理到的最大 ID
        max_id_in_this_run = last_processed_id

        for item in response["result"]:
            # ✅ 關鍵邏輯：如果這則訊息的 ID 小於等於上次處理過的，直接跳過
            current_update_id = item["update_id"]
            if current_update_id <= last_processed_id:
                continue
            
            # 更新本次最大 ID
            if current_update_id > max_id_in_this_run:
                max_id_in_this_run = current_update_id

            if str(item["message"]["chat"]["id"]) != str(TG_CHAT_ID): continue
            
            # 雖然有 ID 判斷，但保留 24h 限制以防萬一
            msg_time = datetime.fromtimestamp(item["message"]["date"])
            if datetime.now() - msg_time > timedelta(hours=24): continue
            
            text = item["message"].get("text", "").strip()
            if not text: continue

            # Case A: JSON 匯入
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
                                is_updated = True
                        updates_log.append(f"📂 匯入 {added} 個新單字")
                except: pass
                continue

            # Case B: 存單字
            match = re.search(r"^([^/\s]+)(?:[ \u3000]+|/)([^/\s]+)(?:[ \u3000]+|/)(.+)$", text)
            if match:
                kanji, kana, meaning = match.groups()
                if not kanji.lower().startswith("part") and len(text) < 50: 
                    found = False
                    for word in vocab_data["words"]:
                        if normalize_text(word["kanji"]) == normalize_text(kanji):
                            word["count"] += 1 
                            updates_log.append(f"🔄 強化記憶：{kanji}")
                            found = True
                            is_updated = True
                            break
                    if not found:
                        vocab_data["words"].append({
                            "kanji": kanji, "kana": kana, "meaning": meaning, 
                            "count": 1, "added_date": today_str
                        })
                        updates_log.append(f"✅ 收錄：{kanji}")
                        is_updated = True
                    continue

            # Case C: 翻譯/作業
            if not text.startswith("/"):
                lines_count = len([l for l in text.split('\n') if len(l.strip()) > 1])
                lines_count = max(1, lines_count)
                today_answers_accumulated += lines_count
                
                pending_correction_texts.append(text)
                
                user_data["translation_log"].append(f"{today_str}: {text[:50]}")
                is_updated = True

        # === 迴圈結束後，統一批改 ===
        if pending_correction_texts:
            combined_text = "\n\n".join(pending_correction_texts)
            history_context = user_data["translation_log"][:-len(pending_correction_texts)]
            result = ai_correction(combined_text, history_context)
            
            if len(pending_correction_texts) > 1:
                correction_msgs.append(f"📝 **作業/練習批改 (共 {len(pending_correction_texts)} 則合併)：**\n{result}")
            else:
                correction_msgs.append(f"📝 **作業/練習批改：**\n{result}")

        # 結算數據
        # ✅ 更新 last_update_id，確保下次不會重複處理
        if max_id_in_this_run > user_data["stats"]["last_update_id"]:
            user_data["stats"]["last_update_id"] = max_id_in_this_run
            is_updated = True

        if user_data["stats"]["last_active"] != today_str:
            user_data["stats"]["yesterday_answers_count"] = today_answers_accumulated
            if today_answers_accumulated > 0 or is_updated:
                 yesterday = str((datetime.now() - timedelta(days=1)).date())
                 if user_data["stats"]["last_active"] == yesterday:
                     user_data["stats"]["streak_days"] += 1
                 else:
                     user_data["stats"]["streak_days"] = 1
                 user_data["stats"]["last_active"] = today_str
                 is_updated = True

        if updates_log: send_telegram("\n".join(set(updates_log)))
        for msg in correction_msgs:
            send_telegram(msg)
            time.sleep(1)

        return vocab_data, user_data

    except Exception as e:
        print(f"Error: {e}")
        return load_json(VOCAB_FILE, {}), load_json(USER_DATA_FILE, {})

# ================= 每日特訓生成 (保持不動) =================

def run_daily_quiz(vocab, user):
    if not vocab.get("words"):
        send_telegram("📭 單字庫空的！請傳送單字或匯入 JSON。")
        return user
    
    user["stats"]["execution_count"] += 1
    exec_count = user["stats"]["execution_count"]
    streak_days = user["stats"]["streak_days"]

    # 1. 發送昨天的詳解
    pending_answers = user.get("pending_answers", "")
    if pending_answers:
        send_telegram(f"🗝️ **昨日測驗詳解**\n\n{pending_answers}")
        time.sleep(3)
        user["pending_answers"] = ""
    
    # 2. 判斷情緒 Prompt
    is_first_run = user["stats"]["last_quiz_date"] == "2000-01-01" or exec_count == 1
    questions_given = user["stats"].get("last_quiz_questions_count", 0)
    answers_given = user["stats"].get("yesterday_answers_count", 0)
    
    emotion_prompt = ""
    
    if is_first_run:
        emotion_prompt = """
        這是你第一次與使用者見面 (Day 1)。
        請用充滿活力、專業且期待的語氣打招呼。
        自我介紹你是「N2 斯巴達 AI 教練」，並說明未來的訓練模式：
        「每天中午我會出題，隔天中午我會檢討昨天的作業並出新題目。」
        請給予使用者滿滿的信心！
        """
    else:
        answer_rate = answers_given / questions_given if questions_given > 0 else 0
        if answer_rate >= 0.8:
            emotion_prompt = f"昨日表現：回覆 {answers_given}/{questions_given} 題。狀態：極佳！大力誇獎！"
        elif answer_rate >= 0.3:
            emotion_prompt = f"昨日表現：回覆 {answers_given}/{questions_given} 題。狀態：尚可。給予肯定但要求更多。"
        else:
            emotion_prompt = f"""
            昨日表現：回覆 {answers_given}/{questions_given} 題。
            狀態：偷懶！請開啟【幽默情勒模式 😈】。
            用有點受傷但又好笑的語氣，質問她是不是被被窩綁架了？
            還是覺得 N2 太簡單不屑寫？
            最後要拉回來，要求今天必須補償回來。
            """

    # 3. 準備出題
    weights = [w.get("count", 1) * 5 for w in vocab["words"]]
    k = min(10, len(vocab["words"]))
    selected_words = random.choices(vocab["words"], weights=weights, k=k)
    word_list = "\n".join([f"{w['kanji']} ({w['meaning']})" for w in selected_words])
    
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(MODEL_NAME)

    print("🤖 AI 生成測驗中...")
    
    prompt = f"""
    你是日文 N2 斯巴達教練。
    
    【系統資訊】
    這是第 {exec_count} 次特訓。
    這是連續第 {streak_days} 天的挑戰 (Day {streak_days})。
    
    【情緒與開場】
    {emotion_prompt}
    請在開場白中明確提到：「這是我們的第 {exec_count} 次特訓 (Day {streak_days})！」。
    
    【今日單字庫】
    {word_list}
    
    請製作 **10 題** 翻譯測驗 (7題中翻日，3題日翻中)。
    
    【輸出格式要求】
    1. **Part 1: 題目卷**
       - 包含開場白(含回數與天數)、今日單字預習、10 個題目。
       - **不要**包含答案。
       - 全篇繁體中文 + Emoji。
       - **嚴禁** HTML 標籤 (如 <br>)，請直接換行。
    
    2. **分隔線**
       - 請在題目卷結束後，輸出一行 `|||SEPARATOR|||` 作為切割。
    
    3. **Part 2: 解答卷**
       - 包含這 10 題的參考答案與解析。
       - 這裡的內容將會在「明天」才發送。
    """
    
    try:
        response = model.generate_content(prompt, safety_settings=SAFETY_SETTINGS)
        if response.text:
            full_text = response.text
            if "|||SEPARATOR|||" in full_text:
                parts = full_text.split("|||SEPARATOR|||")
                send_telegram(parts[0].strip())
                user["pending_answers"] = parts[1].strip()
            else:
                send_telegram(full_text)
                user["pending_answers"] = ""

            user["stats"]["last_quiz_questions_count"] = 10
            user["stats"]["last_quiz_date"] = str(datetime.now().date())

    except Exception as e:
        print(f"Gemini Error: {e}")
        send_telegram("⚠️ 測驗生成失敗，請稍後重試。")
    
    return user

if __name__ == "__main__":
    v_data, u_data = process_data()
    u_data_updated = run_daily_quiz(v_data, u_data)
    
    save_json(VOCAB_FILE, v_data)
    if u_data_updated:
        save_json(USER_DATA_FILE, u_data_updated)
    else:
        save_json(USER_DATA_FILE, u_data)