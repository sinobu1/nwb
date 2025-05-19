import telegram
from telegram.ext import Application, CommandHandler, MessageHandler, filters
import google.generativeai as genai
import requests
import logging
import traceback
import os

# Setup logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Telegram Bot Token from BotFather
TOKEN = os.getenv("TELEGRAM_TOKEN", "8185454402:AAEgJLaBSaUSyP9Z_zv76Fn0PtEwltAqga0")
# Gemini API Key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AIzaSyCdDMpgLJyz6aYdwT9q4sbBk7sHVID4BTI")
# Yandex Maps API Key
YANDEX_API_KEY = os.getenv("YANDEX_API_KEY", "YOUR_YANDEX_API_KEY")

# Initialize Gemini client
try:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel("gemini-2.0-flash")
    logger.info("Gemini client initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize Gemini client: {str(e)}")
    gemini_model = None

# Start command
async def start(update, context):
    try:
        await update.message.reply_text(
            "Привет! Я NeuroPal — умный бот для Москвы на Gemini 2.0. Задавай вопросы, проси советы или развлечения! 😄\n"
            "Пример: 'Где поесть на Таганке?' или 'Расскажи шутку'. Хочешь больше? Попробуй /premium!"
        )
        logger.info(f"Start command received from {update.message.from_user.id}")
    except Exception as e:
        logger.error(f"Error in start command: {str(e)}")
        await update.message.reply_text("Произошла ошибка. Попробуй снова.")

# Premium command
async def premium(update, context):
    try:
        await update.message.reply_text(
            "Премиум за 150 ₽/мес.: больше функций, быстрые ответы! Оплати: [ЮKassa URL]"
        )
        logger.info(f"Premium command received from {update.message.from_user.id}")
    except Exception as e:
        logger.error(f"Error in premium command: {str(e)}")
        await update.message.reply_text("Ошибка. Попробуй снова.")

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
    elif "что поесть" in user_message.lower():
        response = "Зависит от настроения! Хочешь быстро — бери шаурму в ларьке (150–200 ₽). Для уюта — 'Кофемания' на Тверской, чек 1000 ₽."
        await update.message.reply_text(response)
        logger.info(f"Sent static response: {response}")
        return
    elif "что делать в москве вечером" in user_message.lower():
        response = "Прогуляйся по Красной площади или загляни в бар 'Time Out' на Тверской — коктейли от 500 ₽!"
        await update.message.reply_text(response)
        logger.info(f"Sent static response: {response}")
        return
    elif "где выпить в москве" in user_message.lower():
        response = "Зайди в 'Noor Bar' на Тверской — коктейли от 600 ₽, крутая атмосфера!"
        await update.message.reply_text(response)
        logger.info(f"Sent static response: {response}")
        return
    
    # Yandex Maps for other "где поесть" queries
    if "где поесть" in user_message.lower():
        try:
            place = user_message.split("на ")[-1] if "на " in user_message else "Москва"
            url = f"https://api-maps.yandex.ru/2.1/?text=кафе+{place}+Москва&ll=37.6173,55.7558&spn=0.1,0.1&lang=ru_RU&apikey={YANDEX_API_KEY}"
            response = requests.get(url).json()
            places = response.get('features', [])
            if places:
                place_name = places[0]['properties']['name']
                response = f"Попробуй {place_name} в районе {place}!"
            else:
                response = "Не нашел кафе, попробуй другое место!"
            await update.message.reply_text(response)
            logger.info(f"Sent Yandex response: {response}")
        except Exception as e:
            logger.error(f"Yandex Maps error: {str(e)}\n{traceback.format_exc()}")
            await update.message.reply_text("Ошибка поиска. Попробуй 'Где поесть на Таганке?'")
        return
    
    # Gemini response
    if not gemini_model:
        await update.message.reply_text("Gemini временно недоступен. Попробуй спросить 'Где поесть на Таганке?' или 'Расскажи шутку'.")
        logger.warning("Gemini client is not initialized")
        return
    
    try:
        response = gemini_model.generate_content(
            [
                {"role": "user", "parts": [
                    "Ты NeuroPal, ИИ-бот для Москвы. Отвечай остроумно, кратко и по-русски. Для локальных вопросов (например, 'где поесть') предлагай места в Москве."
                ]},
                {"role": "user", "parts": [user_message]}
            ],
            generation_config={"max_output_tokens": 100, "temperature": 0.7}
        )
        reply = response.text
        await update.message.reply_text(reply)
        logger.info(f"Sent Gemini response: {reply}")
    except Exception as e:
        logger.error(f"Gemini error: {str(e)}\n{traceback.format_exc()}")
        await update.message.reply_text(f"Ошибка Gemini: {str(e)}. Спроси 'Где поесть на Таганке?'")

async def main():
    try:
        application = Application.builder().token(TOKEN).build()
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("premium", premium))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        logger.info("Starting bot...")
        await application.run_polling()
    except Exception as e:
        logger.error(f"Error in main: {str(e)}\n{traceback.format_exc()}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
