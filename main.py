# main.py
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response, status, Form, File, UploadFile
from typing import Optional, Dict, List, Any
from telegram import Update
from telegram.ext import (
    Application,
)
from fastapi.middleware.cors import CORSMiddleware


from config import CONFIG, logger, BotConstants, firestore_service, genai, AI_MODES, AVAILABLE_TEXT_MODELS

try:
    import bot_logic
except ImportError:
    logger.error("Не удалось импортировать bot_logic.py. Убедитесь, что вы переименовали handlers.py в bot_logic.py")
    import handlers as bot_logic

from pydantic import BaseModel
from datetime import datetime, timezone


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Application startup...")
    if CONFIG.GOOGLE_GEMINI_API_KEY and "YOUR_" not in CONFIG.GOOGLE_GEMINI_API_KEY:
        try:
            genai.configure(api_key=CONFIG.GOOGLE_GEMINI_API_KEY)
            logger.info("Google Gemini API successfully configured.")
        except Exception as e:
            logger.error(f"Failed to configure Google Gemini API: {e}", exc_info=True)
    else:
        logger.warning("Google Gemini API key is not configured or is missing.")

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

    logger.info("Application shutdown...")
    await ptb_app.shutdown()

class AppChatMessageRequest(BaseModel):
    text: Optional[str] = None
    agentKey: str
    modelKey: str
    image_base64: Optional[str] = None
    image_mime_type: Optional[str] = None
    history: Optional[List[Dict[str, Any]]] = None

# Pydantic Models for Profile Data API
class DailyLimitInfo(BaseModel):
    used: int
    limit: int
    gem_cost: float
    model_name: str
    bonus_uses_left: int = 0 # Поле для бонусов

class AgentLifetimeUseInfo(BaseModel):
    left: int
    initial: int
    agent_name: str

class UserProfileDataResponse(BaseModel):
    status: str
    user_id: int
    gem_balance: float
    daily_limits: Dict[str, DailyLimitInfo]
    agent_lifetime_uses: Dict[str, AgentLifetimeUseInfo]


app = FastAPI(title="Telegram Bot API Server", version="1.5.2", lifespan=lifespan) # Incremented version

origins = [
    "https://sinobu1.github.io",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ptb_app = Application.builder().token(CONFIG.TELEGRAM_TOKEN).build()

# --- Регистрация обработчиков из bot_logic ---
if hasattr(bot_logic, 'start'): ptb_app.add_handler(bot_logic.CommandHandler("start", bot_logic.start), group=0)
if hasattr(bot_logic, 'new_topic_command'): ptb_app.add_handler(bot_logic.CommandHandler("new", bot_logic.new_topic_command), group=0)
if hasattr(bot_logic, 'open_menu_command'): ptb_app.add_handler(bot_logic.CommandHandler("menu", bot_logic.open_menu_command), group=0)
if hasattr(bot_logic, 'usage_command'): ptb_app.add_handler(bot_logic.CommandHandler("usage", bot_logic.usage_command), group=0)
if hasattr(bot_logic, 'gems_info_command'): ptb_app.add_handler(bot_logic.CommandHandler("gems", bot_logic.gems_info_command), group=0)
if hasattr(bot_logic, 'get_news_bonus_info_command'): ptb_app.add_handler(bot_logic.CommandHandler("bonus", bot_logic.get_news_bonus_info_command), group=0)
if hasattr(bot_logic, 'help_command'): ptb_app.add_handler(bot_logic.CommandHandler("help", bot_logic.help_command), group=0)
if hasattr(bot_logic, 'photo_handler'): ptb_app.add_handler(bot_logic.MessageHandler(bot_logic.filters.PHOTO, bot_logic.photo_handler), group=1)
if hasattr(bot_logic, 'menu_button_handler'): ptb_app.add_handler(bot_logic.MessageHandler(bot_logic.filters.TEXT & ~bot_logic.filters.COMMAND, bot_logic.menu_button_handler), group=1)
if hasattr(bot_logic, 'web_app_data_handler'): ptb_app.add_handler(bot_logic.MessageHandler(bot_logic.filters.StatusUpdate.WEB_APP_DATA, bot_logic.web_app_data_handler), group=1)
if hasattr(bot_logic, 'handle_text'): ptb_app.add_handler(bot_logic.MessageHandler(bot_logic.filters.TEXT & ~bot_logic.filters.COMMAND, bot_logic.handle_text), group=2)
if hasattr(bot_logic, 'precheckout_callback'): ptb_app.add_handler(bot_logic.PreCheckoutQueryHandler(bot_logic.precheckout_callback))
if hasattr(bot_logic, 'successful_payment_callback'): ptb_app.add_handler(bot_logic.MessageHandler(bot_logic.filters.SUCCESSFUL_PAYMENT, bot_logic.successful_payment_callback))
if hasattr(bot_logic, 'error_handler'): ptb_app.add_error_handler(bot_logic.error_handler)
# --- Конец регистрации обработчиков ---


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

@app.post("/api/process_app_message/{user_id_unsafe}")
async def process_app_message(user_id_unsafe: int, request_data: AppChatMessageRequest):
    user_id = user_id_unsafe
    logger.info(f"Received message from MiniApp for user {user_id}. Agent: {request_data.agentKey}, Model: {request_data.modelKey}, Text: '{request_data.text}', HasImage: {bool(request_data.image_base64)}, History: {len(request_data.history or [])} items")

    image_data_for_logic = None
    if request_data.image_base64 and request_data.image_mime_type:
        try:
            image_data_for_logic = {
                "base64": request_data.image_base64,
                "mime_type": request_data.image_mime_type
            }
        except Exception as e:
            logger.error(f"Error processing base64 image for user {user_id}: {e}")
            image_data_for_logic = None

    try:
        message_to_log_in_chat = f"(Из MiniApp - {request_data.agentKey}): {request_data.text or '[Фото отправлено]'}"
        await ptb_app.bot.send_message(chat_id=user_id, text=message_to_log_in_chat)
    except Exception as e:
        logger.error(f"Failed to send user message copy to main chat for {user_id}: {e}")

    user_data_cache = await firestore_service.get_user_data(user_id)
    bot_data_cache = await firestore_service.get_bot_data()

    can_proceed, limit_message, usage_type, gem_cost = await bot_logic.check_and_log_request_attempt(
        user_id, request_data.modelKey, user_data_cache, bot_data_cache, request_data.agentKey
    )

    ai_response_text = "Ошибка обработки вашего запроса."
    if not can_proceed:
        ai_response_text = limit_message
    else:
        try:
            ai_service = bot_logic.get_ai_service(request_data.modelKey)
            active_agent_config = AI_MODES.get(request_data.agentKey)

            if not active_agent_config:
                 logger.error(f"Agent config not found for key: {request_data.agentKey} in /api/process_app_message. Falling back to default.")
                 active_agent_config = AI_MODES[CONFIG.DEFAULT_AI_MODE_KEY]
            
            system_prompt = active_agent_config["prompt"]

            history_from_app = request_data.history or []
            
            if len(history_from_app) > CONFIG.MAX_CONVERSATION_HISTORY * 2:
                history_from_app = history_from_app[-(CONFIG.MAX_CONVERSATION_HISTORY * 2):]
                logger.info(f"History from Mini App for user {user_id} was truncated to {len(history_from_app)} messages.")

            raw_ai_response = await ai_service.generate_response(
                system_prompt,
                request_data.text or ("Анализ изображения" if image_data_for_logic else "Пустой запрос"),
                history=history_from_app,
                image_data=image_data_for_logic
            )
            ai_response_text, _ = bot_logic.smart_truncate(raw_ai_response, CONFIG.MAX_MESSAGE_LENGTH_TELEGRAM)
            await bot_logic.increment_request_count(user_id, request_data.modelKey, usage_type, request_data.agentKey, gem_cost)
        except Exception as e:
            logger.error(f"AI service error in /api/process_app_message for user {user_id}: {e}", exc_info=True)
            ai_response_text = f"Произошла внутренняя ошибка при обращении к ИИ ({type(e).__name__})."

    try:
        await ptb_app.bot.send_message(chat_id=user_id, text=ai_response_text, disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Failed to send AI response to main chat for {user_id}: {e}")

    bot_message_for_app = [{"sender": "bot", "text": ai_response_text, "timestamp": datetime.now(timezone.utc).isoformat()}]
    messages_ref = firestore_service._db.collection(BotConstants.FS_APP_MESSAGES_COLLECTION).document(str(user_id))
    try:
        await firestore_service._execute_firestore_op(messages_ref.set, {"messages": bot_message_for_app})
    except Exception as e:
        logger.error(f"Failed to save AI response to app_messages for user {user_id}: {e}")
        return {"status": "error", "message": "Failed to queue response for app"}

    return {"status": "ok", "message": "Message received and is being processed."}


@app.get("/api/get_user_profile_data/{user_id}", response_model=UserProfileDataResponse)
async def get_user_profile_data_endpoint(user_id: int):
    try:
        user_data = await firestore_service.get_user_data(user_id)
        bot_data = await firestore_service.get_bot_data()

        gem_balance = await bot_logic.get_user_gem_balance(user_id, user_data)

        daily_limits_data: Dict[str, DailyLimitInfo] = {}
        for model_key, model_config in AVAILABLE_TEXT_MODELS.items():
            used = await bot_logic.get_daily_usage_for_model(user_id, model_key, bot_data)
            
            bonus_uses_left = 0
            if user_data.get('claimed_news_bonus', False) and model_key in CONFIG.NEWS_CHANNEL_BONUS_CONFIG:
                bonus_key = f"news_bonus_uses_left_{model_key}"
                bonus_uses_left = user_data.get(bonus_key, 0)
            
            daily_limits_data[model_key] = DailyLimitInfo(
                used=used,
                limit=model_config.get('free_daily_limit', 0),
                gem_cost=model_config.get('gem_cost', 0.0),
                model_name=model_config.get('name', model_key),
                bonus_uses_left=bonus_uses_left
            )

        agent_lifetime_uses_data: Dict[str, AgentLifetimeUseInfo] = {}
        for agent_key, agent_config in AI_MODES.items():
            initial_uses = agent_config.get('initial_lifetime_free_uses')
            if initial_uses is not None:
                uses_left = await bot_logic.get_agent_lifetime_uses_left(user_id, agent_key, user_data)
                agent_lifetime_uses_data[agent_key] = AgentLifetimeUseInfo(
                    left=uses_left,
                    initial=initial_uses,
                    agent_name=agent_config.get('name', agent_key)
                )
        
        return UserProfileDataResponse(
            status="ok",
            user_id=user_id,
            gem_balance=gem_balance,
            daily_limits=daily_limits_data,
            agent_lifetime_uses=agent_lifetime_uses_data
        )
    except Exception as e:
        logger.error(f"Error in /api/get_user_profile_data for user {user_id}: {e}", exc_info=True)
        return UserProfileDataResponse(
            status="error",
            user_id=user_id,
            gem_balance=0.0,
            daily_limits={},
            agent_lifetime_uses={},
        )


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=CONFIG.WEB_SERVER_PORT if hasattr(CONFIG, 'WEB_SERVER_PORT') else 8000, reload=True)
