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

# ================= AI 核心 (Prompt 優化版) =================

def ai_correction(user_text, translation_history, progress_status):
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(MODEL_NAME)
    
    print(f"🤖 AI 正在批改 (進度 {progress_status})...")
    history_str = "\n".join(translation_history[-10:]) if translation_history else "(尚無歷史紀錄)"
    
    # 🔥 批改 Prompt：區分必修與 Bonus 的態度
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
    4. **👹 斯巴達即時督促 (重要)**：
       - 請查看【當前答題進度】。
       - **情況 A：還在寫每日必修 (10題未滿)**：
         - 如果進度嚴重落後，請在結尾加上一句**「幽默且帶點嘲諷的催促」** (例如：「才寫一題？手指抽筋了嗎？快點把剩下的交出來！」)。
         - 如果快完成了，給予鼓勵。
       - **情況 B：正在寫 Bonus (已進入 Bonus 階段)**：
         - **絕對禁止罵人或催促**。
         - Bonus 是額外的努力，無論寫幾題，都請給予高度肯定 (例如：「竟然還願意多寫，這份熱情就是合格的保證！」)。
         - 重點放在「正確率」與「句型運用」的讚美。
    
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
            "current_difficulty": 2
        },
        "pending_answers": "",
        "translation_log": []
    })
    
    stats = user_data["stats"]
    if "current_difficulty" not in stats: stats["current_difficulty"] = 2
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
            
            msg_time = datetime.fromtimestamp(item["message"]["date"])
            if datetime.now() - msg_time > timedelta(hours=24): continue
            
            text = item["message"].get("text", "").strip()
            if not text: continue

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
                user_data["translation_log"].append(f"{today_str}: {text[:50]}")
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

        # === 批改處理 (傳遞進度狀態) ===
        if not is_fresh_start and pending_correction_texts:
            combined_text = "\n\n".join(pending_correction_texts)
            history_context = user_data["translation_log"][:-len(pending_correction_texts)]
            
            main_count = user_data["stats"]["daily_answers_count"]
            bonus_count = user_data["stats"]["bonus_answers_count"]
            
            # 判斷目前是在寫必修還是 Bonus
            if bonus_count > 0:
                progress_str = f"狀態：Bonus 挑戰中 (已完成 {bonus_count} 題 Bonus)"
            else:
                progress_str = f"狀態：每日必修進行中 ({main_count}/10 題)"

            result = ai_correction(combined_text, history_context, progress_str)
            
            title_text = f"📝 **作業/練習批改 (共 {len(pending_correction_texts)} 則合併)：**" if len(pending_correction_texts) > 1 else "📝 **作業/練習批改：**"
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

# ================= 每日特訓生成 =================

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

    current_difficulty = user["stats"].get("current_difficulty", 2)
    difficulty_desc = {
        1: "Lv1 (新手)：短句，無複合句，專注於單字記憶。",
        2: "Lv2 (初級)：簡單複合句，N3/N4 文法。",
        3: "Lv3 (中級)：標準 N2 文法，句子長度適中。",
        4: "Lv4 (高級)：包含易混淆文法，較長的長難句。",
        5: "Lv5 (魔鬼)：新聞日文風格，複雜結構，考驗極限。"
    }

    # ================= Scenario A: 新的一天 (每日必修) =================
    if is_new_day:
        user["stats"]["yesterday_main_score"] = user["stats"]["daily_answers_count"]
        user["stats"]["yesterday_bonus_score"] = user["stats"]["bonus_answers_count"]
        user["stats"]["daily_answers_count"] = 0
        user["stats"]["bonus_answers_count"] = 0
        
        user["stats"]["execution_count"] += 1
        exec_count = user["stats"]["execution_count"]
        streak_days = user["stats"]["streak_days"]
        
        is_first_run = (user["stats"]["last_quiz_date"] == "2000-01-01") or (exec_count == 1)
        main_score = user["stats"]["yesterday_main_score"]
        bonus_score = user["stats"]["yesterday_bonus_score"]
        
        emotion_prompt = ""
        difficulty_adjustment_msg = "" 

        if is_first_run:
            emotion_prompt = """
            這是你第一次與使用者見面 (Day 1)。
            **請注意：請全程使用繁體中文 (Traditional Chinese)。**
            請用充滿活力、專業且期待的語氣打招呼。
            自我介紹你是「N2 斯巴達 AI 教練」，並說明未來的訓練模式：
            「每天中午我會出題，隔天中午我會檢討昨天的作業並出新題目。」
            請給予使用者滿滿的信心！
            """
            current_difficulty = 2 
            user["stats"]["current_difficulty"] = 2
            
        else:
            answer_rate = main_score / 10
            
            if answer_rate >= 0.8: # 表現好
                if current_difficulty < 5:
                    current_difficulty += 1
                    difficulty_adjustment_msg = "🔥 狀態絕佳！教練決定提升難度，別讓我失望！"
                else:
                    difficulty_adjustment_msg = "👑 你已經達到最高難度，請保持這份強大！"
                
                if bonus_score > 0:
                    emotion_prompt = f"昨日表現：必修 {main_score}/10，Bonus {bonus_score}。狀態：神一般的自律！請用極度崇拜語氣誇獎！並提到「{difficulty_adjustment_msg}」。"
                else:
                    emotion_prompt = f"昨日表現：必修 {main_score}/10。狀態：優秀。給予高度肯定。並提到「{difficulty_adjustment_msg}」。"

            elif answer_rate >= 0.3: # 表現普通
                emotion_prompt = f"昨日表現：必修 {main_score}/10。狀態：尚可。維持目前難度，提醒要更努力。"
                
            else: # 表現差
                if current_difficulty > 1:
                    current_difficulty -= 1
                    difficulty_adjustment_msg = "📉 看來你累了，我們先降低一點難度，找回手感吧。"
                else:
                    difficulty_adjustment_msg = "⚠️ 已經是最低難度了，不能再退了！加油啊！"
                
                emotion_prompt = f"""
                昨日表現：必修 {main_score}/10。狀態：偷懶！
                請開啟【幽默情勒模式 😈】。
                用有點受傷但又好笑的語氣，質問她是不是被被窩綁架了？
                並提到「{difficulty_adjustment_msg}」。
                **請全程使用繁體中文。**
                """
            
            user["stats"]["current_difficulty"] = current_difficulty

        print(f"🤖 生成每日必修 (10題) - 難度: {current_difficulty}...")
        
        prompt = f"""
        你是日文 N2 斯巴達教練。
        
        【系統資訊】
        這是第 {exec_count} 次特訓。
        這是連續第 {streak_days} 天的挑戰 (Day {streak_days})。
        **目前難度等級：{difficulty_desc[current_difficulty]}**
        
        【情緒與開場】
        {emotion_prompt}
        請在開場白中明確提到：「這是我們的第 {exec_count} 次特訓 (Day {streak_days})！」。
        
        【今日單字庫】
        {word_list}
        
        請製作 **10 題** 翻譯測驗 (7題中翻日，3題日翻中)。
        **題型要求：請維持簡短、明確的句子，符合上述難度等級。不要出長篇大論的文章翻譯。**
        
        【輸出格式要求 (嚴格遵守)】
        1. **語言**：
           - 開場白、單字預習、題目說明：**全程使用繁體中文**。
           - 題目本身：日文或中文。
        
        2. **排版**：
           - **嚴禁** 使用 Markdown 標題 (如 # 或 ##)。
           - 請使用 Emoji (如 ⚔️, 📚, 📝, 🔹) 來區隔段落與項目。
           - **嚴禁** 使用 HTML 標籤 (如 <br>)，請直接換行。
        
        3. **結構**：
           - Part 1: 題目卷 (含開場、單字、10題)。**不要**給答案。
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

    # ================= Scenario B: Bonus 模式 (誘惑開場 + 難度遞增) =================
    else:
        bonus_count = user["stats"]["bonus_answers_count"]
        base_diff = user["stats"].get("current_difficulty", 2)
        bonus_level_increase = (bonus_count // 3) + 1
        bonus_difficulty = min(5, base_diff + bonus_level_increase)
        
        print(f"🤖 生成 Bonus 挑戰 (3題) - 基礎難度:{base_diff} -> Bonus難度:{bonus_difficulty}...")
        
        # 🔥 Bonus 提示詞優化：誘惑語氣 + 高難度設定
        prompt = f"""
        你是日文 N2 斯巴達教練。
        使用者今天已經完成每日作業，但她**主動**再次回來執行程式。
        
        請用一種**「充滿誘惑力與挑戰性」**的語氣開場。
        不要只是驚訝，而是要像一位魔鬼教練看到學員主動留下來加練時那種「露齒一笑」的感覺。
        這是一種對強者的認可，同時帶有挑釁意味：「喔？還不滿足嗎？看來一般的訓練已經無法滿足你的野心了...😏 那就來試試這個吧！」
        
        **Bonus 難度等級：{difficulty_desc[bonus_difficulty]}**
        (這是一個額外挑戰，請根據此難度出題，可以比每日必修更難一點)
        
        並提供 **3 題** 翻譯挑戰 (Bonus Challenge)。
        **題型要求：2 題中翻日，1 題日翻中。**
        
        【今日單字庫】
        {word_list}
        
        【輸出格式要求 (嚴格遵守)】
        1. **語言**：
           - 開場白、題目說明：**全程使用繁體中文**。
        
        2. **排版**：
           - **嚴禁** 使用 Markdown 標題 (如 # 或 ##)。
           - 請使用 Emoji (如 🔥, 🚀, 💡, 🌟) 來區隔段落。
           - 標題請寫：⚔️ **Bonus 無限挑戰 (Lv{bonus_difficulty})** ⚔️
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
    
    save_json(VOCAB_FILE, v_data)
    if u_data_updated:
        save_json(USER_DATA_FILE, u_data_updated)
    else:
        save_json(USER_DATA_FILE, u_data)