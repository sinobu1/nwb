# main.py
import asyncio
import uvicorn
from fastapi import FastAPI, Request, Response, status
from telegram import Update

# --- ИСПРАВЛЕНИЕ: ИМПОРТИРУЕМ ХЕНДЛЕРЫ И FILTERS ЗДЕСЬ ---
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
)
# --- КОНЕЦ ИСПРАВЛЕНИЯ ---

from config import CONFIG, logger, BotConstants, firestore_service

# Импортируем нашу логику из соседнего файла
try:
    import bot_logic
except ImportError:
    logger.error("Не удалось импортировать bot_logic.py. Убедитесь, что вы переименовали handlers.py в bot_logic.py")
    import handlers as bot_logic

# 1. Инициализация FastAPI
app = FastAPI(
    title="Telegram Bot API Server",
    description="Сервер для обработки вебхуков Telegram и API для Mini App.",
    version="1.0.0"
)

# 2. Инициализация Telegram-бота
ptb_app = Application.builder().token(CONFIG.TELEGRAM_TOKEN).build()


# 3. Регистрация всех ваших обработчиков из bot_logic.py
# --- ИСПРАВЛЕНИЕ: УБРАН ПРЕФИКС bot_logic. У КЛАССОВ ХЕНДЛЕРОВ ---
# Группа 0: Команды
ptb_app.add_handler(CommandHandler("start", bot_logic.start), group=0)
ptb_app.add_handler(CommandHandler("menu", bot_logic.open_menu_command), group=0)
ptb_app.add_handler(CommandHandler("usage", bot_logic.usage_command), group=0)
ptb_app.add_handler(CommandHandler("gems", bot_logic.gems_info_command), group=0)
ptb_app.add_handler(CommandHandler("bonus", bot_logic.get_news_bonus_info_command), group=0)
ptb_app.add_handler(CommandHandler("help", bot_logic.help_command), group=0)

# Группа 1: Обработчики кнопок, фото и данных от Mini App
ptb_app.add_handler(MessageHandler(filters.PHOTO, bot_logic.photo_handler), group=1)
ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot_logic.menu_button_handler), group=1)
ptb_app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, bot_logic.web_app_data_handler), group=1)

# Группа 2: Общий обработчик текстовых сообщений (запросы к ИИ)
ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot_logic.handle_text), group=2)

# Обработчики платежей
ptb_app.add_handler(PreCheckoutQueryHandler(bot_logic.precheckout_callback))
ptb_app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, bot_logic.successful_payment_callback))

# Глобальный обработчик ошибок
ptb_app.add_error_handler(bot_logic.error_handler)
# --- КОНЕЦ ИСПРАВЛЕНИЯ ---

@app.on_event("startup")
async def on_startup():
    """Действия при старте сервера: установка вебхука."""
    if not firestore_service._db:
        logger.critical("Firestore (db) was NOT initialized successfully! Server will not work correctly.")
        return
        
    webhook_url = f"{CONFIG.WEBHOOK_URL}/telegram"
    try:
        # Используем простой секрет для дополнительной безопасности
        secret = CONFIG.TELEGRAM_TOKEN.split(":")[-1]
        await ptb_app.bot.set_webhook(
            url=webhook_url,
            allowed_updates=Update.ALL_TYPES,
            secret_token=secret
        )
        logger.info(f"Webhook has been set to {webhook_url}")
    except Exception as e:
        logger.error(f"Failed to set webhook: {e}", exc_info=True)


@app.on_event("shutdown")
async def on_shutdown():
    """Действия при остановке сервера: удаление вебхука."""
    try:
        await ptb_app.bot.delete_webhook()
        logger.info("Webhook has been deleted.")
    except Exception as e:
        logger.error(f"Failed to delete webhook: {e}", exc_info=True)


# Дверь №1: Эндпоинт для Telegram (Webhook)
@app.post("/telegram")
async def telegram_webhook(request: Request):
    """Принимает обновления от Telegram и передает их в обработчик."""
    secret = CONFIG.TELEGRAM_TOKEN.split(":")[-1]
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != secret:
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)
        
    update_data = await request.json()
    update = Update.de_json(update_data, ptb_app.bot)
    await ptb_app.process_update(update)
    return {"status": "ok"}


# Дверь №2: Эндпоинт для Mini App (API для опроса)
@app.get("/api/get_updates/{user_id}")
async def get_app_updates(user_id: int):
    """Отдает новые сообщения для Mini App из Firestore и очищает их."""
    try:
        messages_ref = firestore_service._db.collection(BotConstants.FS_APP_MESSAGES_COLLECTION).document(str(user_id))
        doc = await firestore_service._execute_firestore_op(messages_ref.get)
        
        if doc and doc.exists:
            pending_messages = doc.to_dict().get('messages', [])
            if pending_messages:
                await firestore_service._execute_firestore_op(messages_ref.delete)
                return {"status": "ok", "messages": pending_messages}
        
        return {"status": "ok", "messages": []}
    except Exception as e:
        logger.error(f"API /get_updates error for user {user_id}: {e}", exc_info=True)
        return {"status": "error", "messages": [], "error": str(e)}


if __name__ == "__main__":
    # Запускаем веб-сервер uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True # Добавляем reload для удобства разработки
    )
