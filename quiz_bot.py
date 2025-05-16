# === ИМПОРТЫ ===
import json, os, random, pytz
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler,
    filters
)
from apscheduler.schedulers.background import BackgroundScheduler

# === НАСТРОЙКИ ===
TOKEN = "8143738268:AAEE4CRYn8mtmNDpTU2okqhvPsIrFFKANFI"
TIMEZONE = pytz.timezone("Europe/Moscow")
QUIZ_TIME = {"hour": 9, "minute": 0}
REMINDER_TIME = {"hour": 8, "minute": 50}
HINT_DELAY_MINUTES = 30
ADMIN_ID = 1768526947
MAX_POINTS = 10
BONUS_FRIDAY = 3

# === ФАЙЛЫ ===
riddle_file = "riddles.json"
data_file = "data.json"
history_file = "history.json"
friday_file = "friday_riddles.json"

# === ГЛОБАЛЬНЫЕ СОСТОЯНИЯ ===
current_question = {}
friday_question = {}
answered_users = []
chat_ids = []
user_hints_shown = {}
sent_chats_today = []
start_sent_today = set()

# === Системная переменная для защиты от повторного /start
last_handled_update_id = None

# === МОТИВАЦИЯ ===
MOTIVATION = [
    "Не сдавайся! Даже КитиНИТИ иногда ошибается 🐳",
    "Мимо... но ты почти у цели! 🤏",
    "Попробуй подумать иначе 🧠",
    "Ошибки — путь к истине! 🧘",
    "КитиНИТИ верит в тебя! 💪",
    "Неправильно, но смешно 🤭",
    "Ой, а ведь почти! Ещё разок! 🌀"
]

# === ЗАГРУЗКА / СОХРАНЕНИЕ ДАННЫХ ===
def load_data():
    global answered_users
    try:
        with open(data_file, "r") as f:
            data = json.load(f)
            answered_users.clear()
            answered_users.extend([entry["id"] for entry in data.get("answered_today", [])])
            return data
    except:
        answered_users.clear()
        return {"scores": {}, "last_sent_date": "", "answered_today": [], "streaks": {}, "users": {}}

def save_data(data):
    with open(data_file, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_riddles():
    try:
        with open(riddle_file, "r") as f:
            return json.load(f)
    except:
        return {"daily": {}, "friday": {}}
def load_friday_riddles():
    try:
        with open(friday_file, "r") as f:
            return json.load(f)
    except:
        return {}


def update_history(date_key, user_id):
    try:
        with open(history_file, "r") as f:
            history = json.load(f)
    except:
        history = {}

    if date_key not in history:
        history[date_key] = {
            "question": current_question.get("question"),
            "answer": current_question.get("answer"),
            "category": current_question.get("category"),
            "users_correct": []
        }

    if user_id not in history[date_key]["users_correct"]:
        history[date_key]["users_correct"].append(user_id)

    with open(history_file, "w") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

def get_level(score):
    if score >= 100: return "👑 Гений"
    elif score >= 50: return "💡 Мастер"
    elif score >= 20: return "🧠 Знаток"
    return "🐣 Новичок"
    
def format_nitikoins(n: int) -> str:
    if 11 <= n % 100 <= 14:
        return f"{n} НИТИкоинов"
    elif n % 10 == 1:
        return f"{n} НИТИкоин"
    elif 2 <= n % 10 <= 4:
        return f"{n} НИТИкоина"
    else:
        return f"{n} НИТИкоинов"

def update_streak(user_id, data):
    today = datetime.now(TIMEZONE).strftime("%Y-%m-%d")
    streaks = data.get("streaks", {})
    streak = streaks.get(str(user_id), {"count": 0, "last_date": ""})
    last_date = streak["last_date"]

    if last_date == (datetime.now(TIMEZONE) - timedelta(days=1)).strftime("%Y-%m-%d"):
        streak["count"] += 1
    elif last_date != today:
        streak["count"] = 1

    streak["last_date"] = today
    streaks[str(user_id)] = streak
    data["streaks"] = streaks

# === КЛАВИАТУРА ===
def main_menu(user_id):
    rows = [
        ["📩 Повторить загадку", "💡 Подсказка"],
        ["🔥 Пятничная шалость"],
        ["💰 Баланс", "🏆 Рейтинг"],
        ["📘 История"]
    ]
    if user_id == ADMIN_ID:
        rows.append(["🔁 Перезапуск", "🧹 Сброс статистики", "➕ Новая загадка"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

# === СТАРТ ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cid = update.effective_chat.id
    now = datetime.now(TIMEZONE)
    today = now.strftime("%Y-%m-%d")

    if cid not in chat_ids:
        chat_ids.append(cid)

    # ✅ Отправляем приветствие и меню всегда
    await update.message.reply_text(
        "Привет, дорогой друг! 🐳\n"
        "Я — КитиНИТИ, твой загадочный кит!\n\n"
        "🎯 Каждый день в 9:00 я присылаю тебе свежую загадку!\n"
        "💡 Подсказка через 30 минут.\n"
        "🏅 За правильные ответы ты получаешь НИТИкоины и растёшь в уровнях!\n\n"
        "👇 Выбирай действие: ⌘",
        reply_markup=main_menu(uid)
    )

    # ✅ Загружаем данные
    data = load_data()

    # ✅ Отправим загадку, но только если она уже была сегодня и ещё не была показана этому чату
    if now.hour >= 9 and data.get("last_sent_date") == today and current_question:
        if cid not in sent_chats_today:
            await update.message.reply_text(f"🧠 Загадка дня:\n\n{current_question['question']}")
            sent_chats_today.append(cid)

# === ВСЯ ЛОГИКА КНОПОК И ОТВЕТОВ ===
async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not update.message: return
    text = update.message.text.strip()
    data = load_data()
    now = datetime.now(TIMEZONE)
    today = now.strftime("%Y-%m-%d")

    # === Админ: добавление новой загадки ===
    if context.user_data.get("adding_riddle") and uid == ADMIN_ID:
        if text.count("///") == 4:
            try:
                date, q, a, hint, cat = [x.strip() for x in text.split("///")]
                r = {"question": q, "answer": a.lower(), "hint": hint, "category": cat}
                riddles = load_riddles()
                riddles["daily"][date] = r
                with open(riddle_file, "w") as f:
                    json.dump(riddles, f, indent=2, ensure_ascii=False)
                await update.message.reply_text(f"✅ Загадка на {date} добавлена!")
            except Exception as e:
                await update.message.reply_text(f"❗ Ошибка при добавлении: {e}")
            context.user_data["adding_riddle"] = False
        else:
            await update.message.reply_text("❗ Неверный формат. Используй: дата///вопрос///ответ///подсказка///категория")
        return

    # === Новая загадка ===
    if text == "➕ Новая загадка" and uid == ADMIN_ID:
        context.user_data["adding_riddle"] = True
        await update.message.reply_text("✍️ Введи всё одной строкой:\nДата(ГГГГ.ММ.ДД)///Вопрос///Ответ///Подсказка///Категория")
        return

    # === Повторить загадку ===
    if text == "📩 Повторить загадку":
        if not current_question:
            await update.message.reply_text("⏳ Загадка ещё не пришла. Жди 9:00 🕘")
        elif uid in answered_users:
            next_quiz = datetime.combine((now + timedelta(days=1)).date(), datetime.min.time(), tzinfo=TIMEZONE).replace(hour=QUIZ_TIME["hour"])
            diff = next_quiz - now
            h, rem = divmod(int(diff.total_seconds()), 3600)
            m = rem // 60
            await update.message.reply_text(f"🎉 Уже разгадано! Следующая через {h} ч {m} мин.")
        else:
            await update.message.reply_text(f"🧠 Загадка:\n{current_question['question']}")
        return

    # === Подсказка ===
    if text == "💡 Подсказка":
        qt = data.get("quiz_sent_time")
        if not qt: await update.message.reply_text("❌ Нет времени загадки."); return
        quiz_time = datetime.fromisoformat(qt)
        delta = now - quiz_time
        if uid in answered_users:
            await update.message.reply_text("✅ Уже отгадано. Жди следующую завтра в 9:00")
        elif delta.total_seconds() < HINT_DELAY_MINUTES * 60:
            remain = HINT_DELAY_MINUTES - int(delta.total_seconds() // 60)
            await update.message.reply_text(f"⏳ Подсказка будет через {remain} мин.")
        else:
            await update.message.reply_text(f"💡 Подсказка:\n{current_question['hint']}")
        return

    # === Баланс ===
    if text == "💰 Баланс":
        score = data["scores"].get(str(uid), 0)
        streak = data.get("streaks", {}).get(str(uid), {}).get("count", 0)
        level = get_level(score)
        await update.message.reply_text(f"💰 Баланс: {score} НИТИкоинов\n📊 Уровень: {level}\n🔥 Серия: {streak}")
        return

    # === Рейтинг ===
    if text == "🏆 Рейтинг":
        scores = data.get("scores", {})
        sorted_users = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        medals = ["🥇", "🥈", "🥉"]
        result = ["🏆 Топ игроков:"]
        for i, (uid_, score) in enumerate(sorted_users[:10], 1):
            try:
                u = await context.bot.get_chat(int(uid_))
                name = f"@{u.username}" if u.username else u.full_name
            except:
                name = f"User {uid_[-4:]}"
            result.append(f"{medals[i-1] if i<=3 else '🎖'} {i}. {name} — {score}🪙")
        await update.message.reply_text("\n".join(result))
        return

    # === История ===
    if text == "📘 История":
        try:
            with open(history_file, "r") as f:
                history = json.load(f)
        except:
            history = {}
        entries = [f"📅 {d} — [{h['category']}] {h['question']}" for d, h in sorted(history.items()) if uid in h.get("users_correct", [])]
        await update.message.reply_text("\n\n".join(entries[-10:]) if entries else "😿 Пока нет разгаданных загадок.")
        return

    # === Пятничная шалость ===
    if text == "🔥 Пятничная шалость":
        if now.weekday() == 4:
            riddles = load_friday_riddles()
            friday = riddles.get(today)
            if friday:
                friday_question.update(friday)
                await update.message.reply_text(f"🙈 Пятничная шалость:\n{friday['question']}")
            else:
                await update.message.reply_text("❌ Пятничная загадка не найдена.")
        else:
            await update.message.reply_text("🙅‍♂️ Сегодня не пятница!\n"
                "Загляни сюда в пятницу после 9:00 — будет 🔥 особенная загадка от КитиНИТИ 🐳")
        return

    # === Сброс и перезапуск ===
    if text == "🧹 Сброс статистики" and uid == ADMIN_ID:
        save_data({"scores": {}, "last_sent_date": "", "answered_today": [], "streaks": {}, "users": {}})
        with open(history_file, "w") as f: json.dump({}, f)
        answered_users.clear()
        await update.message.reply_text("🧹 Всё сброшено.")
        return

    if text == "🔁 Перезапуск" and uid == ADMIN_ID:
        await send_daily_quiz(context.application, force=True)
        await update.message.reply_text("🔁 Загадка отправлена заново.")
        return

    # === Ответ пользователя ===
    if not current_question:
        await update.message.reply_text("⏳ Жди 9:00 — будет загадка.")
        return

    if uid in answered_users:
        await update.message.reply_text("✅ Ты уже разгадал! Жди следующую.")
        return

    if text.lower() == current_question["answer"].lower():
        place = len(answered_users) + 1
        points = max(MAX_POINTS - (place - 1), 1)
        data["scores"][str(uid)] = data["scores"].get(str(uid), 0) + points
        data["answered_today"].append({"id": uid})
        answered_users.append(uid)
        update_streak(uid, data)
        save_data(data)
        update_history(today, uid)
        await update.message.reply_text(f"🎉 Верно! Ты получаешь {format_nitikoins(points)}.")
    else:
        await update.message.reply_text(random.choice(MOTIVATION))

# === ОТПРАВКА ЗАГАДКИ ===
async def send_daily_quiz(app, force=False):
    global current_question, answered_users, sent_chats_today, user_hints_shown
    today = datetime.now(TIMEZONE).strftime("%Y-%m-%d")
    data = load_data()

    if not force and data.get("last_sent_date") == today:
        return

    r = load_riddles().get("daily", {}).get(today)
    if not r: return

    current_question.clear()
    current_question.update(r)
    answered_users.clear()
    user_hints_shown.clear()
    sent_chats_today.clear()
    data["last_sent_date"] = today
    data["answered_today"] = []
    data["quiz_sent_time"] = datetime.now(TIMEZONE).isoformat()
    save_data(data)

    print(f"📤 Рассылка загадки {today}:")
    for cid in chat_ids:
        try:
            await app.bot.send_message(cid, text=f"🧠 Загадка дня:\n{r['question']}", reply_markup=main_menu(ADMIN_ID))
            sent_chats_today.append(cid)
            print(f"✅ Загадка отправлена в чат {cid}")
        except Exception as e:
            print(f"❌ Ошибка отправки в чат {cid}: {e}")

# === УТРОМ — НАПОМИНАНИЕ ===
async def send_reminder(app):
    for cid in chat_ids:
        try:
            with open("media/start.gif", "rb") as gif:
                await app.bot.send_animation(
                    chat_id=cid,
                    animation=gif,
                    caption="☀️ Доброе утро! Сегодня в 9:00 будет загадка от КитиНИТИ 🐳\nПриготовь мозги!",
                    reply_markup=main_menu(ADMIN_ID)
                )
        except Exception as e:
            print(f"⚠️ Не удалось отправить гифку в чат {cid}: {e}")

# === СТАРТ ПРИЛОЖЕНИЯ ===
async def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.scheduler = BackgroundScheduler(timezone=TIMEZONE)
    app.scheduler.add_job(send_reminder, 'cron', hour=REMINDER_TIME["hour"], minute=REMINDER_TIME["minute"], args=[app])
    app.scheduler.add_job(send_daily_quiz, 'cron', hour=QUIZ_TIME["hour"], minute=QUIZ_TIME["minute"], args=[app])
    app.scheduler.start()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buttons))

    print("🤖 КитиНИТИ запущен. И готов к новым загадкам")
    await app.run_polling()

if __name__ == "__main__":
    import asyncio, nest_asyncio
    nest_asyncio.apply()
    asyncio.run(main())
