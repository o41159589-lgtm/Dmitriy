"""
Telegram Bot — обработчик команды /skill-creator
Использование: /skill-creator <user_id> <amount>
Пример: /skill-creator 123456789 500

Требования: pip install python-telegram-bot
"""

import logging
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes
)

# ── CONFIG ──
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"  # Замените на токен от @BotFather
ADMIN_IDS = [123456789]  # Замените на ваш Telegram ID
WEBAPP_URL = "https://your-domain.com/telegram_mini_app.html"  # URL вашего Mini App

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── В ПРОДАКШНЕ: хранилище балансов (замените на БД — PostgreSQL/Redis/и т.д.) ──
user_balances: dict[int, int] = {}
user_history: dict[int, list] = {}


def get_balance(user_id: int) -> int:
    return user_balances.get(user_id, 100)  # Стартовый баланс 100


def add_balance(user_id: int, amount: int) -> int:
    user_balances[user_id] = get_balance(user_id) + amount
    if user_id not in user_history:
        user_history[user_id] = []
    user_history[user_id].insert(0, {
        "type": "add",
        "amount": amount,
        "ts": __import__("time").time()
    })
    return user_balances[user_id]


# ── КОМАНДА /start ──
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = ctx.args

    # Реферальная система
    if args and args[0].startswith("ref_"):
        ref_id = args[0].split("_")[1]
        logger.info(f"User {user.id} came via ref from {ref_id}")
        # TODO: начислить бонус реферреру

    # Кнопка запуска Mini App
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "🎰 Открыть Казино",
            web_app=WebAppInfo(url=WEBAPP_URL)
        )
    ]])

    await update.message.reply_text(
        f"🎰 Добро пожаловать, {user.first_name}!\n\n"
        f"💰 Ваш баланс: {get_balance(user.id)} монет\n"
        f"Нажмите кнопку ниже, чтобы открыть казино:",
        reply_markup=keyboard
    )


# ── КОМАНДА /skill-creator <id> <amount> ──
async def skill_creator(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Команда только для администраторов.
    Начисляет монеты пользователю с указанным ID.

    Использование: /skill-creator 123456789 500
    """
    caller_id = update.effective_user.id

    # Проверка прав администратора
    if caller_id not in ADMIN_IDS:
        await update.message.reply_text("❌ У вас нет прав для этой команды.")
        return

    # Проверка аргументов
    if len(ctx.args) != 2:
        await update.message.reply_text(
            "❌ Неверный формат команды.\n"
            "Использование: /skill-creator <user_id> <amount>\n"
            "Пример: /skill-creator 123456789 500"
        )
        return

    try:
        target_id = int(ctx.args[0])
        amount = int(ctx.args[1])
    except ValueError:
        await update.message.reply_text("❌ user_id и amount должны быть числами.")
        return

    if amount <= 0:
        await update.message.reply_text("❌ Сумма должна быть больше 0.")
        return

    # Начисляем монеты
    new_balance = add_balance(target_id, amount)

    # Ответ администратору
    await update.message.reply_text(
        f"✅ Успешно!\n"
        f"👤 Пользователь: `{target_id}`\n"
        f"💰 Начислено: +{amount} монет\n"
        f"📊 Новый баланс: {new_balance} монет",
        parse_mode="Markdown"
    )

    # Уведомление пользователю
    try:
        await ctx.bot.send_message(
            chat_id=target_id,
            text=f"🎉 Вам начислено {amount} монет!\n"
                 f"💰 Ваш баланс: {new_balance} монет"
        )
    except Exception as e:
        logger.warning(f"Не удалось отправить уведомление пользователю {target_id}: {e}")
        await update.message.reply_text(
            "⚠️ Монеты начислены, но уведомить пользователя не удалось "
            "(возможно, он не запускал бота)."
        )


# ── КОМАНДА /balance (для пользователей) ──
async def balance(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    bal = get_balance(user.id)
    await update.message.reply_text(
        f"💰 Ваш баланс: {bal} монет"
    )


# ── MAIN ──
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("skill_creator", skill_creator))  # /skill_creator
    app.add_handler(CommandHandler("skillcreator", skill_creator))  # /skillcreator
    app.add_handler(CommandHandler("balance", balance))

    # Примечание: Telegram не поддерживает дефис в командах (/skill-creator),
    # поэтому используется /skill_creator или /skillcreator.
    # Если хотите именно /skill-creator — нужно парсить текст сообщения вручную:
    from telegram.ext import MessageHandler, filters
    async def hyphen_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        text = update.message.text or ""
        if text.startswith("/skill-creator"):
            parts = text.split()
            ctx.args = parts[1:]
            await skill_creator(update, ctx)

    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^/skill-creator"), hyphen_cmd))

    logger.info("Bot started. Commands: /skill-creator <id> <amount>")
    app.run_polling()


if __name__ == "__main__":
    main()