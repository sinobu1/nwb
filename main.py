# main.py
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response, status
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
)

from config import CONFIG, logger, BotConstants, firestore_service

try:
    import bot_logic
except ImportError:
    logger.error("Не удалось импортировать bot_logic.py. Убедитесь, что вы переименовали handlers.py в bot_logic.py")
    import handlers as bot_logic


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Код при старте сервера
    logger.info("Application startup...")
    await ptb_app.initialize()
    
    webhook_base_url = CONFIG.WEBHOOK_URL.rstrip('/')
    webhook_url = f"{webhook_base_url}/telegram"
    
    try:
        secret = CONFIG.TELEGRAM_TOKEN.split(":")[-1]
        await ptb_app.bot.set_webhook(url=webhook_url, allowed_updates=Update.ALL_TYPES, secret_token=secret)
        logger.info(f"Webhook has been set to {webhook_url}")
    except Exception as e:
        logger.error(f"Failed to set webhook: {e}", exc_info=True)
    
    yield
    
    # Код при остановке сервера
    logger.info("Application shutdown...")
    await ptb_app.shutdown()


# 1. Инициализация FastAPI
app = FastAPI(title="Telegram Bot API Server", version="1.3.0", lifespan=lifespan)

# 2. Инициализация Telegram-бота
ptb_app = Application.builder().token(CONFIG.TELEGRAM_TOKEN).build()


# 3. >>> ВАЖНО: ПОЛНАЯ РЕГИСТРАЦИЯ ВСЕХ ОБРАБОТЧИКОВ <<<
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
# --- КОНЕЦ БЛОКА РЕГИСТРАЦИИ ---


# 4. Эндпоинт для Telegram (Webhook)
@app.post("/telegram")
async def telegram_webhook(request: Request):
    secret = CONFIG.TELEGRAM_TOKEN.split(":")[-1]
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != secret:
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)
        
    update_data = await request.json()
    update = Update.de_json(update_data, ptb_app.bot)
    await ptb_app.process_update(update)
    return {"status": "ok"}


# 5. Эндпоинт для Mini App (API для опроса)
@app.get("/api/get_updates/{user_id}")
async def get_app_updates(user_id: int):
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
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
