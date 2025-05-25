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

# Импортируем genai, чтобы сконфигурировать его
from config import CONFIG, logger, BotConstants, firestore_service, genai

try:
    import bot_logic
except ImportError:
    logger.error("Не удалось импортировать bot_logic.py. Убедитесь, что вы переименовали handlers.py в bot_logic.py")
    import handlers as bot_logic

from pydantic import BaseModel # Убедитесь, что BaseModel импортирован
from datetime import datetime, timezone # Для timestamp


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Код, который выполнится при старте сервера
    logger.info("Application startup...")
    
    # --- >> ВАЖНОЕ ДОБАВЛЕНИЕ: КОНФИГУРАЦИЯ GOOGLE GEMINI API << ---
    if CONFIG.GOOGLE_GEMINI_API_KEY and "YOUR_" not in CONFIG.GOOGLE_GEMINI_API_KEY:
        try:
            genai.configure(api_key=CONFIG.GOOGLE_GEMINI_API_KEY)
            logger.info("Google Gemini API successfully configured.")
        except Exception as e:
            logger.error(f"Failed to configure Google Gemini API: {e}", exc_info=True)
    else:
        logger.warning("Google Gemini API key is not configured or is missing.")
    # --- КОНЕЦ ДОБАВЛЕНИЯ ---
    
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

# Модель для запроса от MiniApp к нашему новому эндпоинту
class AppChatMessageRequest(BaseModel):
    text: str
    agentKey: str
    modelKey: str
    # В будущем можно добавить userId, если будете передавать и валидировать initData
    # userId: int 

# Инициализация FastAPI и PTB
app = FastAPI(title="Telegram Bot API Server", version="1.4.0", lifespan=lifespan)
ptb_app = Application.builder().token(CONFIG.TELEGRAM_TOKEN).build()

# Полная регистрация всех обработчиков
# (Этот блок кода остается без изменений)
ptb_app.add_handler(CommandHandler("start", bot_logic.start), group=0)
ptb_app.add_handler(CommandHandler("menu", bot_logic.open_menu_command), group=0)
ptb_app.add_handler(CommandHandler("usage", bot_logic.usage_command), group=0)
ptb_app.add_handler(CommandHandler("gems", bot_logic.gems_info_command), group=0)
ptb_app.add_handler(CommandHandler("bonus", bot_logic.get_news_bonus_info_command), group=0)
ptb_app.add_handler(CommandHandler("help", bot_logic.help_command), group=0)
ptb_app.add_handler(MessageHandler(filters.PHOTO, bot_logic.photo_handler), group=1)
ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot_logic.menu_button_handler), group=1)
ptb_app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, bot_logic.web_app_data_handler), group=1)
ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot_logic.handle_text), group=2)
ptb_app.add_handler(PreCheckoutQueryHandler(bot_logic.precheckout_callback))
ptb_app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, bot_logic.successful_payment_callback))
ptb_app.add_error_handler(bot_logic.error_handler)


# Эндпоинты FastAPI
# (Этот блок кода остается без изменений)
@app.post("/telegram")
async def telegram_webhook(request: Request):
    secret = CONFIG.TELEGRAM_TOKEN.split(":")[-1]
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != secret:
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)
    update_data = await request.json()
    update = Update.de_json(update_data, ptb_app.bot)
    await ptb_app.process_update(update)
    return {"status": "ok"}

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

# >>> НОВЫЙ ЭНДПОИНТ ДЛЯ ПРИЕМА СООБЩЕНИЙ ОТ MINI APP <<<
@app.post("/api/process_app_message/{user_id_unsafe}") # user_id_unsafe для демонстрации
async def process_app_message(user_id_unsafe: int, request_data: AppChatMessageRequest):
    """
    Принимает сообщение от Mini App, обрабатывает через ИИ,
    сохраняет ответ в Firestore для опроса и дублирует в основной чат.
    ВАЖНО: user_id_unsafe здесь используется для примера. В продакшене
    нужно получать user_id из валидированных initData, передаваемых Mini App.
    """
    user_id = user_id_unsafe # ИСПОЛЬЗУЕМ ID ИЗ ПУТИ ДЛЯ ПРОСТОТЫ ПРИМЕРА

    logger.info(f"Received message from MiniApp for user {user_id}. Agent: {request_data.agentKey}, Model: {request_data.modelKey}, Text: '{request_data.text}'")

    # 1. Отправляем копию сообщения пользователя в основной чат для истории
    try:
        await ptb_app.bot.send_message(chat_id=user_id, text=f"(Из MiniApp): {request_data.text}")
    except Exception as e:
        logger.error(f"Failed to send user message copy to main chat for {user_id}: {e}")

    # 2. Обработка через ИИ (логика похожа на ту, что была в web_app_data_handler)
    user_data_cache = await firestore_service.get_user_data(user_id)
    bot_data_cache = await firestore_service.get_bot_data()
    
    can_proceed, limit_message, usage_type, gem_cost = await bot_logic.check_and_log_request_attempt(
        user_id, request_data.modelKey, user_data_cache, bot_data_cache, request_data.agentKey
    )

    ai_response_text = "Ошибка обработки вашего запроса." # Ответ по умолчанию

    if not can_proceed:
        ai_response_text = limit_message
        logger.warning(f"Request from MiniApp for user {user_id} denied: {limit_message}")
    else:
        try:
            # Можно временно отправить "печатает" в основной чат, если хотите
            # await ptb_app.bot.send_chat_action(chat_id=user_id, action='typing')
            
            ai_service = bot_logic.get_ai_service(request_data.modelKey)
            system_prompt = bot_logic.AI_MODES.get(request_data.agentKey, {}).get("prompt", bot_logic.AI_MODES[CONFIG.DEFAULT_AI_MODE_KEY]["prompt"])
            
            raw_ai_response = await ai_service.generate_response(system_prompt, request_data.text, image_data=None)
            logger.info(f"Raw AI response (from /api/process_app_message for user {user_id}): '{raw_ai_response}'")
            ai_response_text, _ = bot_logic.smart_truncate(raw_ai_response, CONFIG.MAX_MESSAGE_LENGTH_TELEGRAM)
            
            await bot_logic.increment_request_count(user_id, request_data.modelKey, usage_type, request_data.agentKey, gem_cost)
        except Exception as e:
            logger.error(f"AI service error in /api/process_app_message for user {user_id}: {e}", exc_info=True)
            ai_response_text = "Произошла внутренняя ошибка при обращении к ИИ."
            
    # 3. Отправляем ответ ИИ в основной чат для истории
    try:
        await ptb_app.bot.send_message(chat_id=user_id, text=ai_response_text, disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Failed to send AI response to main chat for {user_id}: {e}")

    # 4. Сохраняем ответ ИИ в Firestore ("почтовый ящик") для Mini App
    bot_message_for_app = [{"sender": "bot", "text": ai_response_text, "timestamp": datetime.now(timezone.utc).isoformat()}]
    messages_ref = firestore_service._db.collection(BotConstants.FS_APP_MESSAGES_COLLECTION).document(str(user_id))
    try:
        await firestore_service._execute_firestore_op(messages_ref.set, {"messages": bot_message_for_app})
        logger.info(f"AI Response for user {user_id} saved to app_messages for polling.")
    except Exception as e:
        logger.error(f"Failed to save AI response to app_messages for user {user_id}: {e}")
        return {"status": "error", "message": "Failed to queue response for app"}
        
    return {"status": "ok", "message": "Message received and is being processed."}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
