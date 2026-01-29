import google.generativeai as genai
import requests
import os
import json
import random
import re
from datetime import datetime, timedelta, timezone
import time
import math

# ================= 環境變數 =================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

# 檔案設定
VOCAB_FILE = "vocab.json"
USER_DATA_FILE = "user_data.json"
LOG_FILE = "TG_MSG.log"
MODEL_NAME = 'models/gemini-2.5-flash' 

# N2 衝刺設定 (半年 = 180天)
SPRINT_DURATION_DAYS = 180
TARGET_DIFFICULTY = 4.0
START_DIFFICULTY = 1.0 # 設定 N5 為起點

# 全局日誌緩衝區
LOG_BUFFER = []
TW_TZ = timezone(timedelta(hours=8))

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
                # 確保舊有 vocab 格式相容
                if filename == VOCAB_FILE and "words" in data:
                    for w in data["words"]:
                        if "type" not in w: w["type"] = "word"
                        if "count" not in w: w["count"] = 1
                
                if isinstance(data, dict) and isinstance(default_content, dict):
                    for k, v in default_content.items():
                        if k not in data: data[k] = v
                return data
        except: return default_content
    return default_content

def save_json(filename, data):
    if filename == USER_DATA_FILE and "translation_log" in data:
        if len(data["translation_log"]) > 100:
            data["translation_log"] = data["translation_log"][-100:]
            
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def log_to_buffer(role, message):
    timestamp = datetime.now(TW_TZ).strftime('%H:%M:%S')
    LOG_BUFFER.append(f"[{timestamp}] {role}: {message}")

def send_telegram(message):
    if not message: return
    
    # 記錄到 Log Buffer (完整記錄)
    log_to_buffer("🤖 Bot", message)

    if not TG_BOT_TOKEN: print(f"[模擬發送] {message[:50]}..."); return

    clean_msg = message.replace("**", "").replace("##", "").replace("__", "")
    clean_msg = re.sub(r'<br\s*/?>', '\n', clean_msg)
    
    try:
        # 🔥 修復：移除 Markdown 語法，恢復正常 URL
        requests.post(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage", json={"chat_id": TG_CHAT_ID, "text": clean_msg
        })
    except Exception as e: print(f"TG 發送失敗: {e}")

def normalize_text(text):
    if not text: return ""
    return text.strip().replace("　", " ").lower()

# ================= Log 寫入功能 =================

def write_log_file(user_data):
    stats = user_data["stats"]
    current_difficulty = float(stats.get("current_difficulty", 2.0))
    days_passed, _, sprint_msg = get_sprint_status(user_data)
    
    diff_cn_jp = float(stats.get("difficulty_cn_jp", current_difficulty))
    diff_jp_cn = float(stats.get("difficulty_jp_cn", current_difficulty))
    
    header = f"""# 📊 N2 衝刺計畫 - 學習狀態儀表板
Last Updated: {datetime.now(TW_TZ).strftime('%Y-%m-%d %H:%M:%S')}

## 📈 目前能力值 (雙軌制)
- **中翻日等級 (輸出)**: Lv {diff_cn_jp:.2f}
- **日翻中等級 (輸入)**: Lv {diff_jp_cn:.2f}
- **衝刺進度**: Day {days_passed} / {SPRINT_DURATION_DAYS}
- **狀態評語**: {sprint_msg}
- **連續登入**: {stats.get('streak_days', 0)} 天

## ⚔️ 訓練數據
- **執行回數**: {stats.get('execution_count', 0)} 回
- **累積答題**: {stats.get('daily_answers_count', 0) + stats.get('bonus_answers_count', 0)} (今日計數)
- **上次更新 ID**: {stats.get('last_update_id', 0)}

---
> 以下為對話紀錄 (由新到舊排序)

"""
    old_logs = ""
    separator = "=== 📜 HISTORY LOGS START ===\n"
    
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                content = f.read()
                if separator in content:
                    old_logs = content.split(separator)[1]
                else:
                    old_logs = content
        except: pass

    new_log_entry = ""
    if LOG_BUFFER:
        new_log_entry = f"\n### 🗓️ {datetime.now(TW_TZ).strftime('%Y-%m-%d Execution')}\n"
        new_log_entry += "\n".join(LOG_BUFFER) + "\n"
        new_log_entry += "\n----------------------------------------\n"

    full_content = header + separator + new_log_entry + old_logs

    try:
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            f.write(full_content)
        print("✅ Log file updated successfully.")
    except Exception as e:
        print(f"⚠️ Failed to write log file: {e}")

# ================= 輔助功能 =================

def get_sprint_status(user_data):
    stats = user_data["stats"]
    # 衝刺狀態以「中翻日」難度為主要基準
    current_difficulty = float(stats.get("difficulty_cn_jp", stats.get("current_difficulty", 1.0)))

    if current_difficulty >= TARGET_DIFFICULTY:
        return 0, 0, "infinity"

    if "sprint_start_date" not in stats:
        stats["sprint_start_date"] = str(datetime.now(TW_TZ).date())
        return 0, 0, "start"

    start_date = datetime.strptime(stats["sprint_start_date"], "%Y-%m-%d").date()
    today = datetime.now(TW_TZ).date()
    days_passed = (today - start_date).days
    
    if days_passed <= 0: days_passed = 1

    progress_ratio = min(1.0, days_passed / SPRINT_DURATION_DAYS)
    
    # 簡單計算落後與否
    days_total = SPRINT_DURATION_DAYS
    expected_diff_now = START_DIFFICULTY + (days_passed / days_total) * (TARGET_DIFFICULTY - START_DIFFICULTY)
    
    diff_val = current_difficulty - expected_diff_now
    daily_growth = (TARGET_DIFFICULTY - START_DIFFICULTY) / days_total
    days_gap = int(diff_val / daily_growth)

    # 恢復 v0.0.14 生動的語氣
    status_msg = ""
    if days_gap >= 5:
        status_msg = f"🔥 超前進度：你比預期快了 {days_gap} 天！保持這種神速，N2 根本是囊中之物！"
    elif days_gap <= -5:
        status_msg = f"⚠️ 落後警報：你已經落後計畫 {abs(days_gap)} 天了！距離 N2 越來越遠囉？皮繃緊一點！"
    else:
        status_msg = f"✅ 進度正常：穩步邁向 N2 中，請繼續保持這份節奏。"

    return days_passed, expected_diff_now, status_msg

# ================= AI 核心功能 =================

def assess_user_level(history_logs, specific_request=None):
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(MODEL_NAME)
    
    print("🧠 AI 正在進行全盤能力評估...")
    log_to_buffer("🧠 AI", "執行能力評估 ([LV])")

    manual_level_map = {"n5": 1.0, "n4": 2.0, "n3": 3.0, "n2": 4.0, "n1": 5.0}
    
    if specific_request:
        req_lower = specific_request.lower().replace(" ", "")
        for key, val in manual_level_map.items():
            if key in req_lower:
                return val, f"收到指令，教練已將難度強制設定為 {key.upper()} (Lv{val})。"
        
        match = re.search(r"(\d+(\.\d+)?)", specific_request)
        if match:
            val = float(match.group(1))
            return val, f"收到指令，難度設定為 Lv{val}。"

    history_text = "\n".join(history_logs[-50:])
    
    # 使用變數替換避免 Markdown 截斷
    json_marker = "```"
    
    # 🔥 強化 Prompt：要求理由也必須有教練語氣
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
    
    請給出一個 **精確的浮點數 (例如 2.4 或 3.8)**。
    **判斷重點：不要只看單字量，請重點評估她的「助詞使用正確率」、「動詞變化的熟練度」以及「句型的豐富度」。**
    
    【輸出格式 (JSON)】
    請只回傳 JSON，不要有 markdown 標記：
    {{ 
      "new_difficulty": 2.5, 
      "reason": "你的單字量不錯，但助詞還是常錯，建議從 N3 前半段開始磨練。(請用教練語氣撰寫此理由，嚴厲但中肯)" 
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

def handle_custom_request(user_text, current_stats):
    """
    [RE] 功能：處理使用者的客製化請求 (調整難度或指定出題方向)
    """
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(MODEL_NAME)
    
    print("🧠 AI 正在處理客製化請求...")
    log_to_buffer("🧠 AI", f"處理請求: {user_text}")

    diff_cn_jp = current_stats.get('difficulty_cn_jp', 1.0)
    diff_jp_cn = current_stats.get('difficulty_jp_cn', 1.0)

    # 使用變數替換避免 Markdown 截斷
    json_marker = "```"

    # 🔥 強化 Prompt：要求創意與多樣性
    prompt = f"""
    你是日文 N2 斯巴達教練。使用者透過 [RE] 指令傳送了客製化請求：
    「{user_text}」

    目前使用者狀態：
    - 中翻日等級: Lv {diff_cn_jp}
    - 日翻中等級: Lv {diff_jp_cn}

    請執行以下任務：
    1. **教練回應**：用斯巴達風格（嚴厲但關心，幽默毒舌）回應使用者。
       - **⚠️ 創意要求**：請不要使用固定的模板（例如不要每次都說「看在你快哭的份上」）。請根據使用者的具體請求內容和語氣，即興發揮。
       - 如果是**求饒**（覺得太難）：可以嘲諷他的意志力，或是用激將法，最後再勉強答應。
       - 如果是**求知**（想學特定文法/單字）：誇獎他的野心，並承諾在下次出題時加入。
       - 如果是**閒聊**：用教練身份回應，提醒他去練習。
    
    2. **系統指令 (JSON)**：在回應最後附上 JSON，告訴系統如何調整。
       格式：
       {json_marker}json
       {{
         "actions": {{
            "adjust_difficulty": -0.2,  
            "quiz_instruction": "出題時請加入'因為、儘管'等轉折詞的練習。" 
         }}
       }}
       {json_marker}
       - **adjust_difficulty**: 浮點數。正數變難，負數變簡單。0 則不變。若使用者覺得太難，建議 -0.2 ~ -0.5。
       - **quiz_instruction**: 字串。給「下一次每日測驗生成」的額外指令。如果使用者要求特定內容，請將其濃縮在此。若無則留空字串。
    
    【格式要求】
    請直接輸出教練的回應文字，JSON 區塊放在最後面。
    """

    try:
        response = model.generate_content(prompt, safety_settings=SAFETY_SETTINGS)
        return response.text if response.text else "⚠️ AI 回應失敗"
    except Exception as e:
        return f"⚠️ AI 處理錯誤: {e}"

def ai_correction(user_text, translation_history, progress_status):
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(MODEL_NAME)
    
    print(f"🤖 AI 正在批改 (進度 {progress_status})...")
    history_str = "\n".join(translation_history[-10:]) if translation_history else "(尚無歷史紀錄)"

    # 使用變數替換避免 Markdown 截斷
    json_marker = "```"
    
    # 🔥 斯巴達教練 Prompt - v0.0.25 (保留語感加分與錯誤懲罰分離) + v0.0.27 (創意鎖定)
    prompt = f"""
    使用者正在回答 N2 翻譯測驗，這是她剛剛傳來的內容（可能包含多句）：
    「{user_text}」
    
    【歷史紀錄】
    {history_str}
    
    【當前答題進度】
    {progress_status}
    
    請扮演日文教授與斯巴達教練，完成以下任務：
    
    1. **🔍 判斷輸入語言 (關鍵)**：
       - **若使用者輸入日文**：這代表她在做「中翻日」。請**極度嚴格**地批改。
         - **重點檢查**：助詞 (てにをは) 是否精準？動詞變化 (活用) 是否正確？時態是否符合語境？有沒有中式日文 (Chinglish) 的問題？
       - **若使用者輸入中文**：這代表她在做「日翻中」。請**不要**把它翻譯回日文！請視為她是對的，並評估她的中文翻譯是否通順、優美 (信達雅)。
    
    2. **🎯 深度批改 (逐句檢討) - 核心價值觀重塑**：
       - 使用者的目標是 **「像日本人一樣說話 (Natural Native Japanese)」**，而不僅是教科書日文。
       - **❌ 錯誤 (Mistake)**：文法錯誤、時態錯誤、用詞意思完全錯誤。 -> **必須列入 JSON 並扣分**。
       - **❕ 語感/風格 (Nuance)**：口語、俚語、非正式用法 (如「コーヒー屋」、「美味い」、「～ちゃった」)。
         - **絕對禁止**把道地的口語視為錯誤！
         - 如果文法正確但風格隨意，請給予 **「❕ 語感提醒」**，解釋：「這是很道地的口語，適合朋友間使用，若在商務場合建議改用...」。
         - **請給予這類道地用法高度評價 (加分)**，因為這代表使用者脫離了死板的教科書。
    
    3. **✨ 三種多樣化表達 (必須包含)**：
       - 針對每一句，展示不同情境的用法：
         1. **👔 正式/書面** (適合報告或長輩)
         2. **🍻 口語/朋友** (道地生活感)
         3. **🔄 換句話說** (使用**完全不同的句型或單字**表達同一個意思，訓練詞彙量與靈活度)
       - 若輸入是中文：提供三種不同風格的中文譯法 (例如：直譯、意譯、文言/成語修飾)。
    
    4. **👹 斯巴達即時督促**：
       - **情況 A (必修)**：進度落後要幽默嘲諷，快完成要鼓勵。
       - **情況 B (Bonus)**：絕對禁止罵人，請給予高度肯定。
         
    5. **🚨 【系統指令：錯誤收錄】(非常重要)**：
       - 請在回應的**最後面**，附上一個 JSON 區塊。
       - **關鍵規則**：只有 **「真正的文法/意思錯誤」** 才能放進 `mistakes`！
       - **語感建議、口語用法、更優雅的說法** -> **絕對不要** 放進 `mistakes`，寫在文字評語裡就好。
       
    6. **📊 【逐句評分與教練短評】(v22 核心升級)**：
       - 你不再只是給總分，請針對使用者的**每一個回答句**，給予獨立的評分與反應。
       - 在文字回應中，請用以下格式列出每句的評價：
         「Q1: 9.5分 - (教練短評: 哇喔！這句助詞用得太神了，簡直是日本人投胎！)」
         「Q2: 4.0分 - (教練短評: 閉著眼睛寫的嗎？時態完全錯了，給我重寫！)」
         「Q3: 0.0分 - (教練短評: 空白？你是被外星人綁架了嗎？這題不予置評！)」
       - **⚠️ 創意要求：以上括號內的短評僅為「語氣範例」，絕對禁止照抄！請根據使用者實際犯的錯誤（如時態、敬語、單字）或是精彩之處，即興創作出「當下最貼切」的毒舌或讚美。請展現你豐富的詞彙量，不要重複。**
       - **評分標準**：
         - **9.0~10.0 (神級)**：文法完美，語感道地 (包含道地口語)，使用了進階語彙/換句話說。
         - **7.0~8.9 (合格)**：正確無誤，中規中矩。
         - **6.0~6.9 (勉強)**：有小錯但不影響理解。
         - **< 6.0 (不及格)**：文法錯誤，語意不清。
         - **0.0 (偷懶)**：空白、亂碼、明顯放棄作答。
    
    7. **JSON 輸出要求 (陣列化)**：
       - 請在回應的**最後面**，附上一個 JSON 區塊，格式如下：
       {json_marker}json
       {{
         "mistakes": [
            {{ "term": "誤用詞", "type": "word", "meaning": "詞意" }}
         ],
         "assessments": [
            {{
                "input": "使用者輸入的第一句",
                "type": "CN_TO_JP" 或 "JP_TO_CN", 
                "score": 9.5,
                "status": "ATTEMPTED" 或 "SKIPPED" 
            }},
            {{
                "input": "使用者輸入的第二句",
                "type": "CN_TO_JP", 
                "score": 0.0,
                "status": "SKIPPED" 
            }}
         ]
       }}
       {json_marker}
       - **status**: 若輸入為空白、"不知道"、"..." 等明顯未作答，標記為 "SKIPPED"。否則為 "ATTEMPTED"。
    
    【格式嚴格要求】
    1. **語言**：解說與評語請全程使用「繁體中文」(Traditional Chinese)。
    2. **排版**：
       - **嚴禁** 使用 Markdown 標題 (如 # 或 ##)。
       - 請使用 Emoji (如 📈, 🎯, ✨, 👹, 👔, 🍻, 🔄) 來區隔。
       - **嚴禁** 使用 HTML 標籤 (如 <br>)，請直接換行。
    """
    
    try:
        response = model.generate_content(prompt, safety_settings=SAFETY_SETTINGS)
        return response.text if response.text else "⚠️ AI 批改失敗"
    except Exception as e:
        return f"⚠️ AI 批改錯誤: {e}"

# ================= 邏輯核心 =================

def process_data():
    print("📥 開始處理資料...")
    log_to_buffer("⚙️ Sys", "Checking for updates...")
    
    # 預設的完整使用者資料結構
    default_user_data = {
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
            "current_difficulty": START_DIFFICULTY, 
            "difficulty_cn_jp": START_DIFFICULTY,
            "difficulty_jp_cn": START_DIFFICULTY,
            "sprint_start_date": str(datetime.now(TW_TZ).date()),
            "next_quiz_instruction": "" 
        },
        "pending_answers": "",
        "translation_log": []
    }
    
    vocab_data = load_json(VOCAB_FILE, {"words": []})
    user_data = load_json(USER_DATA_FILE, default_user_data)
    
    stats = user_data["stats"]
    stats["current_difficulty"] = float(stats.get("current_difficulty", START_DIFFICULTY))
    stats["difficulty_cn_jp"] = float(stats.get("difficulty_cn_jp", stats["current_difficulty"]))
    stats["difficulty_jp_cn"] = float(stats.get("difficulty_jp_cn", stats["current_difficulty"]))
    if "next_quiz_instruction" not in stats: stats["next_quiz_instruction"] = ""

    for key in ["daily_answers_count", "bonus_answers_count", "yesterday_main_score", 
                "yesterday_bonus_score", "execution_count", "streak_days", "last_update_id"]:
        if key not in stats: stats[key] = 0

    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/getUpdates"
    
    try:
        # 🔥 修復：移除 Markdown 語法，恢復正常 URL
        response = requests.get(url).json()
        if "result" not in response: 
            log_to_buffer("⚙️ Sys", "No 'result' in TG response.")
            return vocab_data, user_data
        
        is_updated = False
        updates_log = []
        correction_msgs = []
        
        today_str = str(datetime.now(TW_TZ).date())
        today_answers_detected = 0
        pending_correction_texts = []
        
        last_processed_id = user_data["stats"]["last_update_id"]
        is_fresh_start = (last_processed_id == 0)
        max_id_in_this_run = last_processed_id
        
        found_count = 0
        for item in response["result"]:
            current_update_id = item["update_id"]
            if current_update_id <= last_processed_id: continue
            if current_update_id > max_id_in_this_run: max_id_in_this_run = current_update_id

            message_obj = item.get("message")
            if not message_obj: 
                continue

            if str(message_obj["chat"]["id"]) != str(TG_CHAT_ID): continue
            
            text = message_obj.get("text", "").strip()
            if not text: continue
            
            # 🔥 修正：優先正規化括號，確保全形 ［CH］ 也能被識別
            text = text.replace("［", "[").replace("］", "]")
            
            found_count += 1
            msg_time = datetime.fromtimestamp(message_obj["date"], TW_TZ).strftime('%H:%M:%S')
            log_to_buffer("👤 User", f"{text} (ID: {current_update_id})")

            # [LV] 指令 (更名自 [CH])
            if text.upper().startswith("[LV]"):
                if is_fresh_start: continue
                specific_req = text[4:].strip()
                new_diff, reason = assess_user_level(user_data["translation_log"], specific_req)
                if new_diff is not None:
                    user_data["stats"]["current_difficulty"] = new_diff
                    user_data["stats"]["difficulty_cn_jp"] = new_diff
                    user_data["stats"]["difficulty_jp_cn"] = new_diff
                    updates_log.append(f"🧠 AI 評級完成：調整至 Lv{new_diff}。\n💬 理由：{reason}")
                    is_updated = True
                continue
            
            # [RE] 客製化請求
            if text.upper().startswith("[RE]"):
                if is_fresh_start: continue
                request_content = text[4:].strip()
                
                # 呼叫客製化處理函式
                raw_response = handle_custom_request(request_content, user_data["stats"])
                
                # 解析 AI 回傳的 JSON 指令
                final_reply = raw_response
                try:
                    json_match = re.search(r"```json\s*(\{.*?\})\s*```", raw_response, re.DOTALL)
                    if json_match:
                        json_str = json_match.group(1)
                        action_data = json.loads(json_str)
                        final_reply = raw_response.replace(json_match.group(0), "").strip()
                        
                        if "actions" in action_data:
                            actions = action_data["actions"]
                            # 1. 調整難度
                            adj_val = float(actions.get("adjust_difficulty", 0.0))
                            if adj_val != 0.0:
                                user_data["stats"]["difficulty_cn_jp"] = max(1.0, user_data["stats"]["difficulty_cn_jp"] + adj_val)
                                user_data["stats"]["difficulty_jp_cn"] = max(1.0, user_data["stats"]["difficulty_jp_cn"] + adj_val)
                                log_to_buffer("⚙️ Adjust", f"Difficulty adjusted by {adj_val}")
                            
                            # 2. 設定下次出題指令
                            quiz_instr = actions.get("quiz_instruction", "")
                            if quiz_instr:
                                user_data["stats"]["next_quiz_instruction"] = quiz_instr
                                log_to_buffer("⚙️ Instruct", f"Next quiz instruction set: {quiz_instr}")
                                is_updated = True
                except Exception as e:
                    log_to_buffer("⚠️ Err", f"RE parsing failed: {e}")

                updates_log.append(f"🗣️ 教練回應：\n{final_reply}")
                is_updated = True
                continue

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
                                    "kanji": kanji, 
                                    "kana": word.get("kana", ""),
                                    "meaning": word.get("meaning", ""),
                                    "type": word.get("type", "word"),
                                    "count": 1, "added_date": today_str
                                })
                                added += 1
                                is_updated = True
                        updates_log.append(f"📂 匯入 {added} 個新項目")
                except: pass
                continue

            # Case B: 存單字/文法
            match = re.search(r"^([^/\s]+)(?:[ \u3000]+|/)([^/\s]+)(?:[ \u3000]+|/)(.+)$", text)
            if match:
                if is_fresh_start: continue
                term, kana_or_info, meaning = match.groups()
                if not term.lower().startswith("part") and len(text) < 50: 
                    found = False
                    for word in vocab_data["words"]:
                        if normalize_text(word["kanji"]) == normalize_text(term):
                            word["count"] += 1 
                            updates_log.append(f"🔄 強化記憶：{term}")
                            found = True
                            is_updated = True
                            break
                    if not found:
                        item_type = "grammar" if ("~" in term or "..." in term) else "word"
                        vocab_data["words"].append({
                            "kanji": term, "kana": kana_or_info, "meaning": meaning, 
                            "type": item_type,
                            "count": 1, "added_date": today_str
                        })
                        updates_log.append(f"✅ 收錄 ({item_type})：{term}")
                        is_updated = True
                    continue

            # Case C: 翻譯/作業
            if not text.startswith("/"):
                if is_fresh_start: continue
                lines_count = len([l for l in text.split('\n') if len(l.strip()) > 1])
                lines_count = max(1, lines_count)
                today_answers_detected += lines_count
                
                pending_correction_texts.append(text)
                user_data["translation_log"].append(f"{today_str}: {text[:100]}")
                is_updated = True

        if found_count == 0:
            log_to_buffer("⚙️ Sys", "No new user messages found.")
        else:
             log_to_buffer("⚙️ Sys", f"Processed {found_count} new messages.")

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

            raw_result = ai_correction(combined_text, history_context, progress_str)
            
            final_msg_text = raw_result
            mistaken_terms = []
            
            # 當日/當次平均分數計算
            total_score_sum = 0.0
            total_score_count = 0

            # 解析錯誤與評估 JSON
            try:
                json_match = re.search(r"```json\s*(\{.*?\})\s*```", raw_result, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1)
                    parsed_data = json.loads(json_str)
                    
                    final_msg_text = raw_result.replace(json_match.group(0), "").strip()
                    log_to_buffer("⚙️ AI Feed", f"JSON: {json_str}")
                    
                    # 1. 處理錯誤 (Mistakes)
                    if "mistakes" in parsed_data:
                        mistake_log_list = []
                        for m in parsed_data["mistakes"]:
                            term = m.get("term", "")
                            m_type = m.get("type", "word")
                            meaning = m.get("meaning", "AI 修正")
                            
                            if term:
                                mistakes_found_in_vocab = False
                                for w in vocab_data["words"]:
                                    if normalize_text(w["kanji"]) == normalize_text(term):
                                        w["count"] = w.get("count", 1) + 2 # 答錯懲罰
                                        w["type"] = m_type 
                                        mistaken_terms.append(normalize_text(term))
                                        mistakes_found_in_vocab = True
                                        mistake_log_list.append(f"⚠️ 弱點標記 (權重+2): {term}")
                                        break
                                if not mistakes_found_in_vocab:
                                    vocab_data["words"].append({
                                        "kanji": term, "kana": "", "meaning": meaning,
                                        "type": m_type, "count": 5, "added_date": today_str
                                    })
                                    mistaken_terms.append(normalize_text(term))
                                    mistake_log_list.append(f"🆕 弱點收錄 (權重=5): {term}")
                        if mistake_log_list:
                             updates_log.extend(mistake_log_list)
                             is_updated = True

                    # 2. 逐句評分與雙軌難度調整 (Assessment List)
                    if "assessments" in parsed_data and isinstance(parsed_data["assessments"], list):
                        for item in parsed_data["assessments"]:
                            status = item.get("status", "ATTEMPTED")
                            score = float(item.get("score", 0.0))
                            q_type = item.get("type", "")
                            target_key = "difficulty_cn_jp" if q_type == "CN_TO_JP" else "difficulty_jp_cn"
                            
                            # 🚨 防偷懶核心：只有 ATTEMPTED 才會調整難度與計算總分
                            if status == "ATTEMPTED":
                                total_score_sum += score
                                total_score_count += 1
                                
                                if q_type in ["CN_TO_JP", "JP_TO_CN"]:
                                    # 難度即時調整邏輯
                                    if score >= 9.0: # 神級 (+0.1)
                                        user_data["stats"][target_key] = min(8.0, user_data["stats"][target_key] + 0.1)
                                    elif score >= 7.0: # 合格 (+0.05)
                                        user_data["stats"][target_key] = min(8.0, user_data["stats"][target_key] + 0.05)
                                    elif score < 6.0: # 不及格 (-0.1)
                                        user_data["stats"][target_key] = max(1.0, user_data["stats"][target_key] - 0.1)

            except Exception as e:
                log_to_buffer("⚠️ Err", f"JSON parsing failed: {e}")

            # 3. 權重回調機制 (獎勵答對)
            text_for_search = normalize_text(combined_text)
            for w in vocab_data["words"]:
                if normalize_text(w["kanji"]) in text_for_search:
                    if normalize_text(w["kanji"]) not in mistaken_terms:
                        if w.get("count", 1) > 1:
                            w["count"] = max(1, w["count"] - 2) # 答對獎勵

            # 4. 生成總評分字串
            score_summary = ""
            if total_score_count > 0:
                avg_score = total_score_sum / total_score_count
                rank = "C"
                if avg_score >= 9.0: rank = "SSS"
                elif avg_score >= 8.0: rank = "S"
                elif avg_score >= 7.0: rank = "A"
                elif avg_score >= 6.0: rank = "B"
                score_summary = f"\n\n📊 **本次平均戰力：{avg_score:.1f} / 10.0 (Rank {rank})**"

            title_text = f"📝 **作業批改 (共 {len(pending_correction_texts)} 則)：**"
            correction_msgs.append(f"{title_text}\n{final_msg_text}{score_summary}")

        if max_id_in_this_run > user_data["stats"]["last_update_id"]:
            user_data["stats"]["last_update_id"] = max_id_in_this_run
            is_updated = True

        if user_data["stats"]["last_active"] != today_str:
            if today_answers_detected > 0 or is_updated:
                 yesterday = str((datetime.now(TW_TZ) - timedelta(days=1)).date())
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
        log_to_buffer("⚠️ Critical", f"Process data error: {e}")
        return load_json(VOCAB_FILE, {}), load_json(USER_DATA_FILE, default_user_data)

# ================= 每日特訓生成 =================

def get_difficulty_description(level_float):
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
    base_desc = descriptions.get(level_int, f"Lv{level_int} (超越極限)")
    next_desc = descriptions.get(level_int + 1, f"Lv{level_int+1} (未知)")
    return base_desc, next_desc

def run_daily_quiz(vocab, user):
    if not vocab.get("words"):
        send_telegram("📭 單字庫空的！請傳送單字或匯入 JSON。")
        return user
    
    # 處理上次詳解
    pending_answers = user.get("pending_answers", "")
    if pending_answers:
        send_telegram(f"🗝️ **前次測驗詳解**\n\n{pending_answers}")
        time.sleep(3)
        user["pending_answers"] = ""
    
    today_str = str(datetime.now(TW_TZ).date())
    is_new_day = (user["stats"]["last_quiz_date"] != today_str)

    # === 選詞邏輯：弱點優先 ===
    all_words = vocab["words"]
    sorted_words = sorted(all_words, key=lambda x: x.get("count", 1), reverse=True)
    
    weak_candidates = sorted_words[:10]
    normal_candidates = sorted_words[10:] if len(sorted_words) > 10 else []
    
    selected_weaks = weak_candidates[:3] if len(weak_candidates) >= 3 else weak_candidates
    needed_normal = 10 - len(selected_weaks)
    
    selected_normals = []
    if normal_candidates:
        weights = [w.get("count", 1) for w in normal_candidates]
        selected_normals = random.choices(normal_candidates, weights=weights, k=needed_normal)
    elif len(selected_weaks) < 10:
         selected_normals = random.choices(weak_candidates, k=10-len(selected_weaks))

    quiz_words = selected_weaks + selected_normals
    random.shuffle(quiz_words) 

    # 🔥 v0.0.28 修正：單字列表回滾為簡潔格式 (日文 + 中文)，避免 AI 混淆
    word_list_str = "\n".join([f"{w['kanji']} ({w['meaning']})" for w in quiz_words])

    must_test_str = ", ".join([w['kanji'] for w in selected_weaks])

    # 讀取雙軌難度
    diff_cn_jp = float(user["stats"].get("difficulty_cn_jp", 1.0))
    diff_jp_cn = float(user["stats"].get("difficulty_jp_cn", 1.0))
    
    days_passed, expected_diff, sprint_msg = get_sprint_status(user)
    is_infinite_mode = (sprint_msg == "infinity")

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(MODEL_NAME)

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

        answer_rate = main_score / 10
        if user["stats"]["last_quiz_date"] == "2000-01-01":
             emotion_prompt = f"""
             這是你第一次與使用者見面 (Day 1)。
             **請注意：請全程使用繁體中文 (Traditional Chinese)。**
             請用充滿活力、專業且期待的語氣打招呼。
             自我介紹你是「N2 斯巴達 AI 教練」，並說明未來的訓練模式：
             「每天中午我會出題，隔天中午我會檢討昨天的作業並出新題目。」
             請給予使用者滿滿的信心！
             """
        else:
            if answer_rate >= 0.8:
                difficulty_adjustment_msg = "🔥 你的表現相當穩定，教練我看在眼裡！"
                if bonus_score > 0:
                    emotion_prompt = f"昨日表現：必修 {main_score}/10，Bonus {bonus_score}。狀態：神一般的自律！請用極度崇拜語氣誇獎！並提到「{difficulty_adjustment_msg}」。"
                else:
                    emotion_prompt = f"昨日表現：必修 {main_score}/10。狀態：優秀。給予高度肯定。並提到「{difficulty_adjustment_msg}」。"
            elif answer_rate >= 0.4:
                if not is_infinite_mode and diff_cn_jp < expected_diff:
                    emotion_prompt = f"昨日表現：普通。雖然沒降級，但我們落後進度了！請稍微嚴肅一點提醒她加快腳步：『現在不是休息的時候，已經落後計畫了！』"
                else:
                    emotion_prompt = f"昨日表現：必修 {main_score}/10。狀態：尚可。繼續保持。"
            else:
                sprint_warn = f"特別注意：請引用「衝刺狀態數據 ({sprint_msg})」來警告她 (例如：我們已經落後 X 天了，這時候睡覺對得起你的 N2 報名費嗎？)。" if not is_infinite_mode else "請提醒她：無限之路不進則退，不要鬆懈了！"
                emotion_prompt = f"""
                昨日表現：必修 {main_score}/10。狀態：偷懶！
                請開啟【幽默情勒模式 😈】。
                {sprint_warn}
                **請全程使用繁體中文。**
                """
        
        print(f"🤖 生成每日必修 - CN->JP Lv{diff_cn_jp:.1f}, JP->CN Lv{diff_jp_cn:.1f}...")
        
        desc_cn_jp, _ = get_difficulty_description(diff_cn_jp)
        desc_jp_cn, _ = get_difficulty_description(diff_jp_cn)
        
        sprint_info = "無限挑戰模式" if is_infinite_mode else f"衝刺 Day {days_passed}/{SPRINT_DURATION_DAYS} ({sprint_msg})"

        # 讀取並重置使用者客製化指令
        custom_instr_text = user["stats"].get("next_quiz_instruction", "")
        custom_block = f"【⚠️ 特別出題指令 (來自使用者請求)】\n{custom_instr_text}\n請務必在出題時融入上述要求。" if custom_instr_text else ""
        if custom_instr_text:
             user["stats"]["next_quiz_instruction"] = "" # 用完即丟

        # 使用變數替換避免 Markdown 截斷
        json_marker = "```"

        prompt = f"""
        你是日文 N2 衝刺班教練。
        {sprint_info}
        
        **🎯 今日雙軌難度目標：**
        - **中翻日 (7題)**: Lv {diff_cn_jp:.1f} ({desc_cn_jp})
        - **日翻中 (3題)**: Lv {diff_jp_cn:.1f} ({desc_jp_cn})
        
        【情緒與開場】
        {emotion_prompt}
        請在開場白中明確提到：「這是我們的第 {exec_count} 次特訓 (Day {streak_days})！」。
        並根據目前的進度狀態 (落後、超前或無限挑戰)展現出對應的教練態度。
        **請不要每次都說一樣的話。請根據今天的日期、天氣（假設）、或是隨機的斯巴達哲學，變化你的開場白。讓使用者覺得你是活生生的教練，而不是錄音機。**
        
        【今日單字庫 (含弱點 🔥)】
        {word_list_str}
        
        {custom_block}
        
        【出題結構要求 (非常重要)】
        請製作 **10 題** 翻譯測驗：
        1. **中翻日 (7題)**：
           - **難度等級：Lv {diff_cn_jp:.1f}** (請依照此難度設計句子結構)
           - **必須包含這 2 個弱點詞/文法**：{must_test_str} (請設計能練習到這些詞的句子)
           - 另外 5 題隨機從單字庫選。
        2. **日翻中 (3題)**：
           - **難度等級：Lv {diff_jp_cn:.1f}** (可以比中翻日更難，使用更進階的閱讀測驗句型)
           - **必須包含 1 個弱點詞/文法** (從上述弱點列表中選一個不同的)。
           - 另外 2 題隨機。
           
        **注意：若是標記 (文法) 的項目，請務必設計出能展現該文法接續與用法的句子。**

        【🚫 品質紅線 (絕對禁止)】
        1. **嚴禁「中式日文 (Chinglish)」**：參考答案的日文必須是**完全道地的日本母語人士用法**。請檢查助詞與搭配詞，不要只是把中文邏輯直接翻成日文。
        2. **嚴禁「日式中文 (翻譯腔)」**：題目的中文必須是**自然流暢的台灣繁體中文**，不要出現生硬的翻譯句型（例如不要寫「關於...這件事」，直接寫「關於...」即可）。
        3. **防止文法題顯示錯誤**：在「今日單字庫」列表或「題目」中，若遇到文法項目（例如 `~てはいけない`），**請務必顯示日文**，絕對不要只寫出中文意思（如 `禁止做...`）。
        
        【輸出格式要求 (嚴格遵守)】
        1. **語言**：
           - 開場白、單字預習、題目說明：**全程使用繁體中文**。
           - 題目本身：日文或中文。
        
        2. **排版**：
           - **嚴禁** 使用 Markdown 標題 (如 # 或 ##)。
           - 請使用 Emoji (如 ⚔️, 📚, 📝, 🔹) 來區隔段落與項目。
           - **嚴禁** 使用 HTML 標籤 (如 <br>)，請直接換行。
        
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
        avg_diff = (diff_cn_jp + diff_jp_cn) / 2
        bonus_difficulty = avg_diff + (bonus_count // 3) * 0.5 + 0.5 
        
        print(f"🤖 生成 Bonus - Lv{bonus_difficulty:.1f}...")
        
        base_level = int(bonus_difficulty)
        next_level = base_level + 1
        decimal_part = bonus_difficulty - base_level
        base_desc, next_desc = get_difficulty_description(bonus_difficulty)

        prompt = f"""
        你是日文 N2 斯巴達教練。使用者今天已經完成每日作業，但她**主動**再次回來執行程式 (挑戰 Bonus)。
        
        請用一種**「充滿誘惑力與挑戰性」**的語氣開場。
        **⚠️ 創意要求**：請不要每次都說一樣的話。請根據今天的日期、天氣（假設）、或是隨機的斯巴達哲學，變化你的開場白。讓使用者覺得你是活生生的教練，而不是錄音機。
        這是一種對強者的認可，同時帶有挑釁意味：「像一位魔鬼教練看到學員主動留下來加練時那種『露齒一笑』的感覺。😏」
        
        **🎯 Bonus 難度等級：{bonus_difficulty:.1f}**
        - Lv{base_level}: {base_desc} (佔 {(1-decimal_part)*100:.0f}%)
        - Lv{next_level}: {next_desc} (佔 {decimal_part*100:.0f}%)
        
        【今日單字庫 (含弱點 🔥)】
        {word_list_str}
        
        提供 **3 題** 翻譯挑戰 (2中翻日，1日翻中)。
        **請盡量優先使用單字庫中標記為 🔥 的弱點項目來出題，折磨使用者！**

        【🚫 品質紅線】
        **生成的日文解答必須是「絕對道地」的日文，嚴禁任何「中式日文」的生硬表達！請用日本人的思維來造句。**
        
        【輸出格式要求 (嚴格遵守)】
        1. **語言**：
           - 開場白、題目說明：**全程使用繁體中文**。
        
        2. **排版**：
           - **嚴禁** 使用 Markdown 標題 (如 # 或 ##)。
           - 請使用 Emoji (如 🔥, 🚀, 💡, 🌟) 來區隔段落。
           - 標題請寫：⚔️ **Bonus 無限挑戰 (Lv{bonus_difficulty:.1f})** ⚔️
           - **嚴禁** 使用 HTML 標籤 (如 <br>)，請直接換行。
        
        3. **結構**：
           - Part 1: Bonus 題目卷 (含開場、3題)。**不要**給答案。
           - 分隔線: `|||SEPARATOR|||`
           - Part 2: 解答卷 (含參考答案與解析)。
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
    
    # 寫入更新後的 JSON 資料
    save_json(VOCAB_FILE, v_data)
    if u_data_updated:
        save_json(USER_DATA_FILE, u_data_updated)
        write_log_file(u_data_updated)
    else:
        save_json(USER_DATA_FILE, u_data)
        write_log_file(u_data)