import google.generativeai as genai
import requests
import os
import json
import random
import re
from datetime import datetime, timedelta
import time
import math

# ================= 環境變數 =================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

# 檔案設定
VOCAB_FILE = "vocab.json"
USER_DATA_FILE = "user_data.json"
MODEL_NAME = 'models/gemini-2.5-flash' 

# N2 衝刺設定 (半年 = 180天)
SPRINT_DURATION_DAYS = 180
TARGET_DIFFICULTY = 4.0  # 設定 4.0 為穩拿 N2 (甚至 N1 入門) 的標準
START_DIFFICULTY = 2.0   # N4 起點

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
    # 擴大歷史紀錄保存量以供 AI 評估，保留最近 100 筆
    if filename == USER_DATA_FILE and "translation_log" in data:
        if len(data["translation_log"]) > 100:
            data["translation_log"] = data["translation_log"][-100:]
            
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

# ================= 輔助功能：計算衝刺進度 =================

def get_sprint_status(user_data):
    """計算目前是否落後於 N2 衝刺計畫"""
    stats = user_data["stats"]
    if "sprint_start_date" not in stats:
        # 如果是第一次運行新版，初始化開始日期為今天
        stats["sprint_start_date"] = str(datetime.now().date())
        return 0, 0, "🚀 衝刺計畫今日啟動！目標：半年內攻克 N2！"

    start_date = datetime.strptime(stats["sprint_start_date"], "%Y-%m-%d").date()
    today = datetime.now().date()
    days_passed = (today - start_date).days
    
    if days_passed <= 0: days_passed = 1

    # 計算「今天理論上該有的難度」 (線性成長)
    # 公式：起點 + (經過天數 / 總天數) * (終點 - 起點)
    progress_ratio = min(1.0, days_passed / SPRINT_DURATION_DAYS)
    expected_difficulty = START_DIFFICULTY + progress_ratio * (TARGET_DIFFICULTY - START_DIFFICULTY)
    
    current_difficulty = float(stats.get("current_difficulty", 2.0))
    
    diff = current_difficulty - expected_difficulty
    
    # 計算落後或超前天數
    # 每日平均成長率
    daily_growth = (TARGET_DIFFICULTY - START_DIFFICULTY) / SPRINT_DURATION_DAYS
    days_diff = int(diff / daily_growth)

    status_msg = ""
    if days_diff >= 5:
        status_msg = f"🔥 超前進度：你比預期快了 {days_diff} 天！太強了！"
    elif days_diff <= -5:
        status_msg = f"⚠️ 落後警報：你落後計畫 {abs(days_diff)} 天了！皮繃緊一點！"
    else:
        status_msg = f"✅ 進度正常：穩步邁向 N2 中。"

    return days_passed, expected_difficulty, status_msg

# ================= AI 核心功能 =================

def assess_user_level(history_logs, specific_request=None):
    """
    [CH] 功能：分析歷史紀錄並重新定級
    """
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(MODEL_NAME)
    
    print("🧠 AI 正在進行全盤能力評估...")

    # 如果使用者指定了等級 (例如 [CH] N2)
    manual_level_map = {
        "n5": 1.0, "n4": 2.0, "n3": 3.0, "n2": 4.0, "n1": 5.0
    }
    
    if specific_request:
        req_lower = specific_request.lower().replace(" ", "")
        for key, val in manual_level_map.items():
            if key in req_lower:
                return val, f"收到指令，教練已將難度強制設定為 {key.upper()} (Lv{val})。"
        
        # 嘗試解析純數字
        match = re.search(r"(\d+(\.\d+)?)", specific_request)
        if match:
            val = float(match.group(1))
            return val, f"收到指令，難度設定為 Lv{val}。"

    # AI 自動評估
    history_text = "\n".join(history_logs[-50:]) # 取最近 50 筆
    
    prompt = f"""
    你是日文 N2 斯巴達教練。使用者要求重新評估她的日文等級。
    
    【使用者的歷史翻譯紀錄】
    {history_text}
    
    請根據這些紀錄，客觀且嚴格地判斷她的日文程度。
    目前的難度量表如下：
    - Lv 1.0: N5 (單字為主)
    - Lv 2.0: N4 (簡單句子)
    - Lv 3.0: N3 (日常會話)
    - Lv 4.0: N2 (商業/新聞入門)
    - Lv 5.0: N1 (高階綜合)
    - Lv 6.0+: 母語者/專業領域
    
    請給出一個 **精確的浮點數 (例如 2.4 或 3.8)** 代表她目前的實力。
    
    【輸出格式 (JSON)】
    請只回傳 JSON，不要有 markdown 標記：
    {{
        "new_difficulty": 2.5,
        "reason": "你的單字量不錯，但助詞還是常錯，建議從 N3 前半段開始磨練。"
    }}
    """
    
    try:
        response = model.generate_content(prompt, safety_settings=SAFETY_SETTINGS)
        clean_text = response.text.replace("```json", "").replace("```", "").strip()
        result = json.loads(clean_text)
        return float(result["new_difficulty"]), result["reason"]
    except Exception as e:
        print(f"評估失敗: {e}")
        return None, "無法評估，維持原難度。"

def ai_correction(user_text, translation_history, progress_status):
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(MODEL_NAME)
    
    history_str = "\n".join(translation_history[-10:]) if translation_history else "(尚無歷史紀錄)"
    
    prompt = f"""
    使用者正在練習日文，這是她剛剛傳來的內容：
    「{user_text}」
    
    【歷史紀錄】
    {history_str}
    
    【當前答題進度】
    {progress_status}
    
    請扮演日文教授與斯巴達教練，完成以下任務：
    1. **📈 進度評估**：比較歷史紀錄，判斷是否有進步？給予鼓勵或警惕。
    2. **🎯 批改**：請針對上述內容進行批改，修正錯誤 (✅/❌)。
    3. **✨ 三種多樣化表達**：提供 正式/口語/換句話說 三種版本。
    4. **👹 斯巴達即時督促**：
       - **情況 A (必修)**：若進度落後，請用「幽默且帶點嘲諷」語氣催促。
       - **情況 B (Bonus)**：給予高度肯定，稱讚這份額外的努力。
    
    【格式要求】
    - 全程使用繁體中文。
    - 使用 Emoji 區隔。
    - 不使用 Markdown 標題 (#)。
    """
    
    try:
        response = model.generate_content(prompt, safety_settings=SAFETY_SETTINGS)
        return response.text if response.text else "⚠️ AI 批改失敗"
    except Exception as e:
        return f"⚠️ AI 批改錯誤: {e}"

# ================= 邏輯核心 =================

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
            "daily_answers_count": 0,
            "bonus_answers_count": 0,
            "yesterday_main_score": 0,
            "yesterday_bonus_score": 0,
            "last_update_id": 0,
            "current_difficulty": 1.0, # 預設從 N5 開始
            "sprint_start_date": str(datetime.now().date()) # 衝刺開始日
        },
        "pending_answers": "",
        "translation_log": []
    })
    
    stats = user_data["stats"]
    stats["current_difficulty"] = float(stats.get("current_difficulty", 1.0))

    # 初始化補全
    for key in ["daily_answers_count", "bonus_answers_count", "yesterday_main_score", 
                "yesterday_bonus_score", "execution_count", "streak_days", "last_update_id"]:
        if key not in stats: stats[key] = 0

    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/getUpdates"
    
    try:
        response = requests.get(url).json()
        if "result" not in response: return vocab_data, user_data
        
        is_updated = False
        updates_log = []
        correction_msgs = []
        
        today_str = str(datetime.now().date())
        today_answers_detected = 0
        pending_correction_texts = []
        
        last_processed_id = user_data["stats"]["last_update_id"]
        is_fresh_start = (last_processed_id == 0)
        max_id_in_this_run = last_processed_id

        for item in response["result"]:
            current_update_id = item["update_id"]
            if current_update_id <= last_processed_id: continue
            if current_update_id > max_id_in_this_run: max_id_in_this_run = current_update_id

            if str(item["message"]["chat"]["id"]) != str(TG_CHAT_ID): continue
            
            text = item["message"].get("text", "").strip()
            if not text: continue

            # === Case Special: [CH] 指令 ===
            if text.upper().startswith("[CH]"):
                if is_fresh_start: continue
                # 提取指令參數 (例如 [CH] N3)
                specific_req = text[4:].strip()
                new_diff, reason = assess_user_level(user_data["translation_log"], specific_req)
                
                if new_diff is not None:
                    user_data["stats"]["current_difficulty"] = new_diff
                    updates_log.append(f"🧠 AI 評級完成：調整至 Lv{new_diff}。\n💬 理由：{reason}")
                    is_updated = True
                else:
                    updates_log.append(f"⚠️ 評級失敗：{reason}")
                continue

            # Case A: JSON
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
                if is_fresh_start: continue
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
                if is_fresh_start: continue
                lines_count = len([l for l in text.split('\n') if len(l.strip()) > 1])
                lines_count = max(1, lines_count)
                today_answers_detected += lines_count
                
                pending_correction_texts.append(text)
                user_data["translation_log"].append(f"{today_str}: {text[:100]}") # 增加紀錄長度
                is_updated = True

        # === 計算計分 ===
        if today_answers_detected > 0:
            current_main = user_data["stats"]["daily_answers_count"]
            main_quota = 10 
            remaining_quota = max(0, main_quota - current_main)
            
            fill_main = min(today_answers_detected, remaining_quota)
            user_data["stats"]["daily_answers_count"] += fill_main
            
            spill_to_bonus = today_answers_detected - fill_main
            if spill_to_bonus > 0:
                user_data["stats"]["bonus_answers_count"] += spill_to_bonus
            is_updated = True

        # === 批改處理 ===
        if not is_fresh_start and pending_correction_texts:
            combined_text = "\n\n".join(pending_correction_texts)
            history_context = user_data["translation_log"][:-len(pending_correction_texts)]
            
            main_count = user_data["stats"]["daily_answers_count"]
            bonus_count = user_data["stats"]["bonus_answers_count"]
            
            if bonus_count > 0:
                progress_str = f"狀態：Bonus 挑戰中 (已完成 {bonus_count} 題 Bonus)"
            else:
                progress_str = f"狀態：每日必修進行中 ({main_count}/10 題)"

            result = ai_correction(combined_text, history_context, progress_str)
            title_text = f"📝 **作業批改 (共 {len(pending_correction_texts)} 則)：**"
            correction_msgs.append(f"{title_text}\n{result}")

        # 更新 update_id
        if max_id_in_this_run > user_data["stats"]["last_update_id"]:
            user_data["stats"]["last_update_id"] = max_id_in_this_run
            is_updated = True

        # Streak 更新
        if user_data["stats"]["last_active"] != today_str:
            if today_answers_detected > 0 or is_updated:
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

# ================= 每日特訓生成 (無限難度與衝刺版) =================

def get_difficulty_description(level_float):
    """
    動態生成無限難度的描述
    """
    level_int = int(level_float)
    descriptions = {
        1: "Lv1 (新手)：N5 基礎，專注於單字記憶。",
        2: "Lv2 (初級)：N4 文法，簡單複合句。",
        3: "Lv3 (中級)：N3 日常應用，標準對話。",
        4: "Lv4 (高級)：N2 商業/新聞入門，長難句。",
        5: "Lv5 (魔鬼)：N1 高階綜合，考驗極限。",
        6: "Lv6 (母語者)：專業領域、技術文件、艱澀語彙。",
        7: "Lv7 (文學)：古文、哲學、詩詞風格。",
        8: "Lv8 (神)：AI 認為人類無法達到的境界。"
    }
    base_desc = descriptions.get(level_int, f"Lv{level_int} (超越極限)：未知的領域。")
    next_desc = descriptions.get(level_int + 1, f"Lv{level_int+1} (未知)")
    
    return base_desc, next_desc

def run_daily_quiz(vocab, user):
    if not vocab.get("words"):
        send_telegram("📭 單字庫空的！請傳送單字或匯入 JSON。")
        return user
    
    pending_answers = user.get("pending_answers", "")
    if pending_answers:
        send_telegram(f"🗝️ **前次測驗詳解**\n\n{pending_answers}")
        time.sleep(3)
        user["pending_answers"] = ""
    
    today_str = str(datetime.now().date())
    is_new_day = (user["stats"]["last_quiz_date"] != today_str)

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(MODEL_NAME)
    
    weights = [w.get("count", 1) * 5 for w in vocab["words"]]
    k = min(10, len(vocab["words"]))
    selected_words = random.choices(vocab["words"], weights=weights, k=k)
    word_list = "\n".join([f"{w['kanji']} ({w['meaning']})" for w in selected_words])

    current_difficulty = float(user["stats"].get("current_difficulty", 1.0))
    
    # 取得衝刺狀態
    days_passed, expected_diff, sprint_msg = get_sprint_status(user)

    # ================= Scenario A: 新的一天 (每日必修) =================
    if is_new_day:
        user["stats"]["yesterday_main_score"] = user["stats"]["daily_answers_count"]
        user["stats"]["yesterday_bonus_score"] = user["stats"]["bonus_answers_count"]
        user["stats"]["daily_answers_count"] = 0
        user["stats"]["bonus_answers_count"] = 0
        
        user["stats"]["execution_count"] += 1
        exec_count = user["stats"]["execution_count"]
        streak_days = user["stats"]["streak_days"]
        
        main_score = user["stats"]["yesterday_main_score"]
        bonus_score = user["stats"]["yesterday_bonus_score"]
        
        emotion_prompt = ""
        difficulty_adjustment_msg = "" 

        # 第一次運行
        if user["stats"]["last_quiz_date"] == "2000-01-01":
            emotion_prompt = f"""
            這是你第一次與使用者見面。
            請熱情地介紹這是一個為期半年的 **「N2 衝刺計畫」**！
            目前的難度是 Lv{current_difficulty}，目標是半年後達到 Lv{TARGET_DIFFICULTY}。
            告訴她：只要每天跟著練，絕對沒問題！
            """
        else:
            # 🎯 難度動態調整核心 (無限等級)
            answer_rate = main_score / 10
            
            if answer_rate >= 0.8: # 表現優異
                increase = 0.2 if answer_rate < 1.0 else 0.3
                # 無上限，取消 min(5.0)
                current_difficulty += increase
                difficulty_adjustment_msg = f"🔥 狀態絕佳！難度升至 Lv{current_difficulty:.1f}！"
                
                # 判斷是否寫了 Bonus
                if bonus_score > 0:
                    emotion_prompt = f"昨日表現：必修 {main_score}/10，Bonus {bonus_score}。狀態：神一般的自律！請用極度崇拜語氣誇獎！並提到「{difficulty_adjustment_msg}」。"
                else:
                    emotion_prompt = f"昨日表現：必修 {main_score}/10。狀態：優秀。提到「{difficulty_adjustment_msg}」。"

            elif answer_rate >= 0.4: # 表現普通
                # 只有普通，但如果「落後進度」，還是要稍微施壓
                if current_difficulty < expected_diff:
                    emotion_prompt = f"昨日表現：普通。雖然沒降級，但我們落後進度了！請稍微嚴肅一點提醒她加快腳步。"
                else:
                    emotion_prompt = f"昨日表現：普通。維持目前難度 Lv{current_difficulty:.1f}。"
                
            else: # 表現差 (0~3題)
                if current_difficulty > 1.0:
                    decrease = 0.3
                    current_difficulty = max(1.0, current_difficulty - decrease)
                    difficulty_adjustment_msg = f"📉 沒關係，我們先降到 Lv{current_difficulty:.1f} 找回手感。"
                else:
                    difficulty_adjustment_msg = "⚠️ 已經是最低難度 Lv1.0 了，不能再退了！"
                
                emotion_prompt = f"""
                昨日表現：必修 {main_score}/10。狀態：偷懶！
                請開啟【幽默情勒模式 😈】。
                並提到「{difficulty_adjustment_msg}」。
                特別注意：請引用「衝刺狀態」來警告她 (例如：我們已經落後 X 天了，沒時間睡覺了！)。
                """
            
            user["stats"]["current_difficulty"] = float(f"{current_difficulty:.1f}")

        print(f"🤖 生成每日必修 (10題) - 難度: {current_difficulty:.1f}...")
        
        base_level = int(current_difficulty)
        next_level = base_level + 1
        decimal_part = current_difficulty - base_level
        base_desc, next_desc = get_difficulty_description(current_difficulty)
        
        prompt = f"""
        你是日文 N2 衝刺班教練。
        
        【衝刺狀態】
        - 目前進度: Day {days_passed} / {SPRINT_DURATION_DAYS}
        - 狀態訊息: {sprint_msg}
        
        **🎯 目標難度等級：{current_difficulty:.1f}**
        請混合出題：
        - **基礎 (Lv{base_level})**：{base_desc} (佔 {(1-decimal_part)*100:.0f}%)
        - **進階 (Lv{next_level})**：{next_desc} (佔 {decimal_part*100:.0f}%)
        
        【情緒與開場】
        {emotion_prompt}
        請在開場白中回報上述的「衝刺狀態訊息」。
        
        【今日單字庫】
        {word_list}
        
        請製作 **10 題** 翻譯測驗 (7題中翻日，3題日翻中)。
        **題型要求：請維持簡短、明確的句子。嚴格遵守難度比例。**
        
        【輸出格式要求】
        1. **語言**：開場白、說明全繁體中文。
        2. **排版**：Emoji 分隔，無 Markdown 標題，無 HTML。
        3. **結構**：
           - Part 1: 題目卷 (含開場、狀態回報、10題)。**不要**給答案。
           - 分隔線: `|||SEPARATOR|||`
           - Part 2: 解答卷 (含參考答案與解析)。
        """
        
        try:
            response = model.generate_content(prompt, safety_settings=SAFETY_SETTINGS)
            if response.text and "|||SEPARATOR|||" in response.text:
                parts = response.text.split("|||SEPARATOR|||")
                send_telegram(parts[0].strip())
                user["pending_answers"] = parts[1].strip()
                
                user["stats"]["last_quiz_date"] = today_str
                user["stats"]["last_quiz_questions_count"] = 10
        except Exception as e:
            print(f"Error: {e}")
            send_telegram("⚠️ 測驗生成失敗")

    # ================= Scenario B: Bonus 無限挑戰 =================
    else:
        bonus_count = user["stats"]["bonus_answers_count"]
        base_diff = float(user["stats"].get("current_difficulty", 1.0))
        bonus_level_increase = (bonus_count // 3) * 0.5 + 0.5 
        bonus_difficulty = base_diff + bonus_level_increase # 無上限
        
        print(f"🤖 生成 Bonus 挑戰 - Lv{bonus_difficulty:.1f}...")
        
        base_level = int(bonus_difficulty)
        next_level = base_level + 1
        decimal_part = bonus_difficulty - base_level
        base_desc, next_desc = get_difficulty_description(bonus_difficulty)

        prompt = f"""
        你是日文 N2 斯巴達教練。使用者主動挑戰 Bonus。
        
        請用「充滿誘惑力與挑戰性」的語氣開場。
        告訴她：既然為了 N2 這麼拼命，那就來點更刺激的！
        
        **🎯 Bonus 難度等級：{bonus_difficulty:.1f}**
        - Lv{base_level}: {base_desc}
        - Lv{next_level}: {next_desc}
        
        並提供 **3 題** 翻譯挑戰 (2中翻日，1日翻中)。
        
        【今日單字庫】
        {word_list}
        
        【格式】
        - 標題：⚔️ **Bonus 無限挑戰 (Lv{bonus_difficulty:.1f})** ⚔️
        - 分隔線: `|||SEPARATOR|||`
        - 全繁體中文解說。
        """

        try:
            response = model.generate_content(prompt, safety_settings=SAFETY_SETTINGS)
            if response.text and "|||SEPARATOR|||" in response.text:
                parts = response.text.split("|||SEPARATOR|||")
                send_telegram(parts[0].strip())
                user["pending_answers"] = parts[1].strip() 
                
        except Exception as e:
            print(f"Error: {e}")
            send_telegram("⚠️ Bonus 生成失敗")

    return user

if __name__ == "__main__":
    v_data, u_data = process_data()
    u_data_updated = run_daily_quiz(v_data, u_data)
    
    save_json(VOCAB_FILE, v_data)
    if u_data_updated:
        save_json(USER_DATA_FILE, u_data_updated)
    else:
        save_json(USER_DATA_FILE, u_data)