# main.py
import asyncio
import uvicorn
from fastapi import FastAPI, Request, Response, status
from telegram import Update
from telegram.ext import Application

# Импортируем конфигурацию, логгер и сервисы
from config import CONFIG, logger, BotConstants, firestore_service

# Импортируем всю логику и обработчики из нового файла bot_logic.py
# (Предполагается, что вы перенесли содержимое handlers.py в bot_logic.py)
try:
    import bot_logic
except ImportError:
    # Фоллбэк, если пользователь еще не переименовал файл
    import handlers as bot_logic

# 1. Инициализация FastAPI
# Мы добавляем документацию для наших новых API эндпоинтов
app = FastAPI(
    title="Telegram Bot API Server",
    description="Сервер для обработки вебхуков Telegram и API для Mini App.",
    version="1.0.0"
)

# 2. Инициализация Telegram-бота
# Убираем таймауты, т.к. вебхуки работают иначе
ptb_app = Application.builder().token(CONFIG.TELEGRAM_TOKEN).build()


# 3. Регистрация всех ваших обработчиков из bot_logic.py
# Убедитесь, что все ваши хендлеры перечислены здесь.
# Группа 0: Команды
ptb_app.add_handler(bot_logic.CommandHandler("start", bot_logic.start), group=0)
ptb_app.add_handler(bot_logic.CommandHandler("menu", bot_logic.open_menu_command), group=0)
ptb_app.add_handler(bot_logic.CommandHandler("usage", bot_logic.usage_command), group=0)
ptb_app.add_handler(bot_logic.CommandHandler("gems", bot_logic.gems_info_command), group=0)
ptb_app.add_handler(bot_logic.CommandHandler("bonus", bot_logic.get_news_bonus_info_command), group=0)
ptb_app.add_handler(bot_logic.CommandHandler("help", bot_logic.help_command), group=0)

# Группа 1: Обработчики кнопок, фото и данных от Mini App
ptb_app.add_handler(bot_logic.MessageHandler(bot_logic.filters.PHOTO, bot_logic.photo_handler), group=1)
# Важно: menu_button_handler должен идти перед web_app_data_handler, если вы используете текстовые кнопки
ptb_app.add_handler(bot_logic.MessageHandler(bot_logic.filters.TEXT & ~bot_logic.filters.COMMAND, bot_logic.menu_button_handler), group=1)
ptb_app.add_handler(bot_logic.MessageHandler(bot_logic.filters.StatusUpdate.WEB_APP_DATA, bot_logic.web_app_data_handler), group=1)

# Группа 2: Общий обработчик текстовых сообщений (запросы к ИИ)
ptb_app.add_handler(bot_logic.MessageHandler(bot_logic.filters.TEXT & ~bot_logic.filters.COMMAND, bot_logic.handle_text), group=2)

# Обработчики платежей
ptb_app.add_handler(bot_logic.PreCheckoutQueryHandler(bot_logic.precheckout_callback))
ptb_app.add_handler(bot_logic.MessageHandler(bot_logic.filters.SUCCESSFUL_PAYMENT, bot_logic.successful_payment_callback))

# Глобальный обработчик ошибок
ptb_app.add_error_handler(bot_logic.error_handler)


@app.on_event("startup")
async def on_startup():
    """Действия при старте сервера: установка вебхука."""
    # Проверка Firestore
    if not firestore_service._db:
        logger.critical("Firestore (db) was NOT initialized successfully! Server will not work correctly.")
        return
        
    webhook_url = f"{CONFIG.WEBHOOK_URL}/telegram"
    try:
        await ptb_app.bot.set_webhook(
            url=webhook_url,
            allowed_updates=Update.ALL_TYPES,
            secret_token=CONFIG.TELEGRAM_TOKEN.split(":")[-1] # Используем часть токена как простой секрет
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
    # Проверяем секретный заголовок для безопасности
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != CONFIG.TELEGRAM_TOKEN.split(":")[-1]:
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
                # Сразу удаляем, чтобы не отправить повторно
                await firestore_service._execute_firestore_op(messages_ref.delete)
                return {"status": "ok", "messages": pending_messages}
        
        return {"status": "ok", "messages": []}
    except Exception as e:
        logger.error(f"API /get_updates error for user {user_id}: {e}", exc_info=True)
        return {"status": "error", "messages": [], "error": str(e)}


if __name__ == "__main__":
    # Запускаем веб-сервер uvicorn
    # Он будет слушать на порту 8000 и принимать внешние подключения
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000
    )
