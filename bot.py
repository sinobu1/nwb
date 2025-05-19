import telegram
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from openai import OpenAI
import logging
import traceback

# Setup logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Telegram Bot Token from BotFather
TOKEN = "8185454402:AAEgJLaBSaUSyP9Z_zv76Fn0PtEwltAqga0"  # Your token
# xAI API Key
XAI_API_KEY = "xai-NPXckFDHJdFHkhllDynT99kusJx5FOLbXhZjdMbz7jSvCd0k0eWgp0eJutNUDQSLGSNw6f4DUZeO1ucz"  # Your key

# Initialize xAI client
try:
    xai_client = OpenAI(api_key=XAI_API_KEY, base_url="https://api.x.ai/v1")
    logger.info("xAI client initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize xAI client: {str(e)}")
    xai_client = None

# Start command
async def start(update, context):
    try:
        await update.message.reply_text(
            "Привет! Я NeuroPal — умный бот с Grok от xAI. Задавай вопросы, проси советы или развлечения! 😄\n"
            "Пример: 'Где поесть на Таганке?' или 'Расскажи шутку'."
        )
        logger.info(f"Start command received from {update.message.from_user.id}")
    except Exception as e:
        logger.error(f"Error in start command: {str(e)}")
        await update.message.reply_text("Произошла ошибка. Попробуй снова.")

# Handle text messages
async def handle_message(update, context):
    user_message = update.message.text
    logger.info(f"Received message: {user_message}")
    
    # Static responses for Moscow
    if "где поесть на таганке" in user_message.lower():
        response = "Попробуй 'Грабли' на Таганке — средний чек 500 ₽, вкусно и быстро. Или 'Теремок' — блины от 150 ₽."
        await update.message.reply_text(response)
        logger.info(f"Sent static response: {response}")
        return
    elif "расскажи шутку" in user_message.lower():
        response = "Почему программист предпочитает тёмную тему? Потому что светлый режим напоминает о счёте за свет! 😄"
        await update.message.reply_text(response)
        logger.info(f"Sent static response: {response}")
        return
    
    # Try Grok response
    if not xai_client:
        await update.message.reply_text("Grok временно недоступен. Попробуй спросить 'Где поесть на Таганке?' или 'Расскажи шутку'.")
        logger.warning("xAI client is not initialized")
        return
    
    try:
        completion = xai_client.chat.completions.create(
            model="grok-3-latest",  # Try grok-3-latest, fallback to grok-beta if needed
            messages=[
                {"role": "system", "content": "Ты NeuroPal, ИИ-бот для Москвы, созданный на базе Grok от xAI. Отвечай остроумно, кратко и по-русски. Для локальных вопросов (например, 'где поесть') предлагай места в Москве."},
                {"role": "user", "content": user_message}
            ],
            max_tokens=100,
            temperature=0.7
        )
        response = completion.choices[0].message.content
        await update.message.reply_text(response)
        logger.info(f"Sent Grok response: {response}")
    except Exception as e:
        logger.error(f"Error in handle_message: {str(e)}\n{traceback.format_exc()}")
        await update.message.reply_text(f"Ошибка Grok: {str(e)}. Попробуй позже или спроси 'Где поесть на Таганке?'")

def main():
    try:
        application = Application.builder().token(TOKEN).build()
        application.add_handler(CommandHandler("start", start))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        logger.info("Starting bot...")
        application.run_polling()
    except Exception as e:
        logger.error(f"Error in main: {str(e)}\n{traceback.format_exc()}")

if __name__ == "__main__":
    main()