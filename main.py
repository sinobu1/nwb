# main.py
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response, status, Form, File, UploadFile # Added Form, File, UploadFile
from typing import Optional # Added Optional
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
)
from fastapi.middleware.cors import CORSMiddleware


from config import CONFIG, logger, BotConstants, firestore_service, genai

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

# Updated model to include optional image fields
class AppChatMessageRequest(BaseModel):
    text: Optional[str] = None # Text is now optional if an image is sent
    agentKey: str
    modelKey: str
    image_base64: Optional[str] = None
    image_mime_type: Optional[str] = None


app = FastAPI(title="Telegram Bot API Server", version="1.5.0", lifespan=lifespan) # Incremented version

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
async def process_app_message(user_id_unsafe: int, request_data: AppChatMessageRequest): # Request model updated
    user_id = user_id_unsafe 

    logger.info(f"Received message from MiniApp for user {user_id}. Agent: {request_data.agentKey}, Model: {request_data.modelKey}, Text: '{request_data.text}', HasImage: {bool(request_data.image_base64)}")

    # Prepare image_data if present
    image_data_for_logic = None
    if request_data.image_base64 and request_data.image_mime_type:
        try:
            # No need to decode base64 here if bot_logic expects base64 string directly.
            # If bot_logic expects bytes, then:
            # import base64
            # image_bytes = base64.b64decode(request_data.image_base64)
            # image_data_for_logic = {"mime_type": request_data.image_mime_type, "data": image_bytes}
            # For now, let's assume bot_logic will handle the base64 string if needed, or we adjust it there.
            # The Gemini API client usually takes bytes, so decoding here might be better.
            # Let's assume for now that bot_logic.py's GoogleGenAIService will handle it or we pass bytes.
            # For simplicity, let's pass base64 and mime type and let bot_logic decide.
            image_data_for_logic = {
                "base64": request_data.image_base64, # Sending as base64 string
                "mime_type": request_data.image_mime_type
            }
            logger.info(f"Image data prepared for agent {request_data.agentKey}")
        except Exception as e:
            logger.error(f"Error processing base64 image for user {user_id}: {e}")
            # Continue without image if processing fails
            image_data_for_logic = None


    # 1. Отправляем копию сообщения пользователя/инфо о фото в основной чат для истории
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
        logger.warning(f"Request from MiniApp for user {user_id} denied: {limit_message}")
    else:
        try:
            ai_service = bot_logic.get_ai_service(request_data.modelKey)
            system_prompt_key = request_data.agentKey
            # Handle case where agentKey might not be in AI_MODES directly (e.g. photo_dietitian_analyzer)
            if request_data.agentKey == "photo_dietitian_analyzer" and "photo_dietitian_analyzer" not in bot_logic.AI_MODES:
                 # Use a specific prompt for dietitian if it's handled as a special case
                 # Or ensure "photo_dietitian_analyzer" is in AI_MODES with its prompt in config.py
                 # For now, let's assume it's in AI_MODES or we use a default.
                 # This part depends on how photo_dietitian_analyzer is defined in your config.py's AI_MODES
                system_prompt = bot_logic.AI_MODES.get("photo_dietitian_analyzer", {}).get("prompt", bot_logic.AI_MODES[CONFIG.DEFAULT_AI_MODE_KEY]["prompt"])
            else:
                system_prompt = bot_logic.AI_MODES.get(system_prompt_key, {}).get("prompt", bot_logic.AI_MODES[CONFIG.DEFAULT_AI_MODE_KEY]["prompt"])

            
            # Pass image_data_for_logic to generate_response
            raw_ai_response = await ai_service.generate_response(
                system_prompt, 
                request_data.text or "Анализ изображения", # Provide default text if only image
                image_data=image_data_for_logic # Pass the prepared image data
            )
            logger.info(f"Raw AI response (from /api/process_app_message for user {user_id}): '{raw_ai_response}'")
            ai_response_text, _ = bot_logic.smart_truncate(raw_ai_response, CONFIG.MAX_MESSAGE_LENGTH_TELEGRAM)
            
            await bot_logic.increment_request_count(user_id, request_data.modelKey, usage_type, request_data.agentKey, gem_cost)
        except Exception as e:
            logger.error(f"AI service error in /api/process_app_message for user {user_id}: {e}", exc_info=True)
            ai_response_text = "Произошла внутренняя ошибка при обращении к ИИ."
            
    try:
        await ptb_app.bot.send_message(chat_id=user_id, text=ai_response_text, disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Failed to send AI response to main chat for {user_id}: {e}")

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
