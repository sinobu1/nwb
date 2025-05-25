# main.py
import asyncio
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


# --- ИСПРАВЛЕНИЕ 2: ИСПОЛЬЗУЕМ СОВРЕМЕННЫЙ LIFESPAN MANAGER ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Код, который выполнится при старте сервера
    logger.info("Application startup...")
    if not firestore_service._db:
        logger.critical("Firestore (db) was NOT initialized successfully! Server will not work correctly.")
    else:
        # --- ИСПРАВЛЕНИЕ 1: УБИРАЕМ ДВОЙНОЙ СЛЕШ ---
        # Убираем слеш в конце URL, если он есть, чтобы избежать //
        webhook_base_url = CONFIG.WEBHOOK_URL.rstrip('/')
        webhook_url = f"{webhook_base_url}/telegram"
        
        try:
            secret = CONFIG.TELEGRAM_TOKEN.split(":")[-1]
            await ptb_app.bot.set_webhook(
                url=webhook_url,
                allowed_updates=Update.ALL_TYPES,
                secret_token=secret
            )
            logger.info(f"Webhook has been set to {webhook_url}")
        except Exception as e:
            logger.error(f"Failed to set webhook: {e}", exc_info=True)
    
    yield  # Сервер работает здесь
    
    # Код, который выполнится при остановке сервера
    logger.info("Application shutdown...")
    try:
        await ptb_app.bot.delete_webhook()
        logger.info("Webhook has been deleted.")
    except Exception as e:
        logger.error(f"Failed to delete webhook: {e}", exc_info=True)


# 1. Инициализация FastAPI с новым lifespan
app = FastAPI(
    title="Telegram Bot API Server",
    description="Сервер для обработки вебхуков Telegram и API для Mini App.",
    version="1.1.0",
    lifespan=lifespan
)

# 2. Инициализация Telegram-бота
ptb_app = Application.builder().token(CONFIG.TELEGRAM_TOKEN).build()

# 3. Регистрация всех обработчиков
# (Этот блок остается без изменений)
ptb_app.add_handler(CommandHandler("start", bot_logic.start), group=0)
ptb_app.add_handler(CommandHandler("menu", bot_logic.open_menu_command), group=0)
# ... и все остальные ваши обработчики ...
ptb_app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, bot_logic.web_app_data_handler), group=1)
ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot_logic.handle_text), group=2)
# ...

# 4. Эндпоинт для Telegram (Webhook)
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


# 5. Эндпоинт для Mini App (API для опроса)
@app.get("/api/get_updates/{user_id}")
async def get_app_updates(user_id: int):
    """Отдает новые сообщения для Mini App из Firestore и очищает их."""
    # (Этот блок остается без изменений)
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
        reload=True
    )
