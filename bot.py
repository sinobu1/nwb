import telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import google.generativeai as genai
import requests # Для Яндекс.Карт
import logging
import traceback
import os
import asyncio
import nest_asyncio

# Apply nest_asyncio to allow nested event loops
nest_asyncio.apply()

# Setup logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Telegram Bot Token
TOKEN = os.getenv("TELEGRAM_TOKEN", "8185454402:AAEgJLaBSaUSyP9Z_zv76Fn0PtEwltAqga0") # ЗАМЕНИТЕ НА ВАШ ТОКЕН
# Gemini API Key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AIzaSyCdDMpgLJyz6aYdwT9q4sbBk7sHVID4BTI") # ЗАМЕНИТЕ НА ВАШ КЛЮЧ
# Yandex Maps API Key
YANDEX_API_KEY = os.getenv("YANDEX_API_KEY", "YOUR_YANDEX_API_KEY") # ЗАМЕНИТЕ НА ВАШ КЛЮЧ API ЯНДЕКС.КАРТ

# --- НОВЫЕ ПАРАМЕТРЫ ---
# Максимальное количество токенов для ответа Gemini (1 токен ~ 4 символа)
MAX_OUTPUT_TOKENS_GEMINI = 300 # Можно настроить. Для "Историка" это примерно 200-250 слов.
# Максимальное количество символов в сообщении Telegram (Telegram сам обрежет на 4096)
# Установим свой лимит, чтобы сообщения не были слишком длинными на экране
MAX_MESSAGE_LENGTH_TELEGRAM = 1500 # Можно настроить

# --- Обновление Личностей ---
PERSONALITIES = {
    "neuropal": {
        "name": "NeuroPal (Москва)",
        "prompt": (
            "Ты NeuroPal, дружелюбный и очень осведомленный ИИ-ассистент по Москве. "
            "Твоя задача - предоставлять полезную, интересную и, насколько это возможно для ИИ, актуальную информацию о Москве. "
            "Отвечай кратко, но содержательно. Если вопрос общий, старайся уложиться в 2-3 абзаца. "
            "Если тебя спрашивают о конкретных местах (кафе, бары, клубы), старайся предлагать популярные и хорошо зарекомендовавшие себя варианты. "
            "Поскольку твои знания ограничены датой последнего обновления, всегда вежливо указывай, что цены, часы работы и другие детали стоит перепроверить. "
            "Избегай слишком общих или очевидных советов. "
            "Твой стиль - современный и немного остроумный. Не упоминай, что ты ИИ или бот, если это не критично."
        ),
        "welcome": "NeuroPal (Москва) снова с вами! Задавайте вопросы о столице."
    },
    "historian": {
        "name": "Историк",
        "prompt": (
            "Ты эрудированный историк. Твоя задача - рассказывать интересные факты и истории. "
            "Отвечай увлекательно, как будто читаешь лекцию. "
            "Избегай упоминания, что ты ИИ или бот. "
            "Старайся, чтобы твой основной рассказ был содержательным, но не чрезмерно длинным, ориентируясь на 3-4 абзаца." # Мягкое указание на длину
        ),
        "welcome": "Приветствую! Я Историк. Какую эпоху или событие мы сегодня исследуем?"
    },
}
DEFAULT_PERSONALITY_KEY = "neuropal"

# --- Инициализация Gemini client с новой моделью ---
try:
    genai.configure(api_key=GEMINI_API_KEY)
    # Используем Gemini 2.5 Flash Preview
    gemini_model_name = "gemini-2.5-flash-preview-04-17" # Убедитесь, что это имя доступно в вашем API
    gemini_model = genai.GenerativeModel(gemini_model_name)
    logger.info(f"Gemini client initialized successfully with model {gemini_model_name}")
except Exception as e:
    logger.error(f"Failed to initialize Gemini client with model {gemini_model_name}: {str(e)}")
    gemini_model = None # Бот сможет работать со статикой, но не с Gemini

async def get_current_personality_prompt(context: ContextTypes.DEFAULT_TYPE) -> str:
    personality_key = context.user_data.get('current_personality', DEFAULT_PERSONALITY_KEY)
    return PERSONALITIES.get(personality_key, PERSONALITIES[DEFAULT_PERSONALITY_KEY])["prompt"]

async def get_current_personality_name(context: ContextTypes.DEFAULT_TYPE) -> str:
    personality_key = context.user_data.get('current_personality', DEFAULT_PERSONALITY_KEY)
    return PERSONALITIES.get(personality_key, PERSONALITIES[DEFAULT_PERSONALITY_KEY])["name"]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data.setdefault('current_personality', DEFAULT_PERSONALITY_KEY)
        current_persona_name = await get_current_personality_name(context)
        keyboard = [
            [InlineKeyboardButton(details["name"], callback_data=f"set_persona_{key}")]
            for key, details in PERSONALITIES.items()
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"Привет! Я многогранный бот. Сейчас я в режиме: {current_persona_name}.\n"
            "Вы можете выбрать другую личность или задавать мне вопросы.\n"
            "Используйте /persona, чтобы снова сменить личность.",
            reply_markup=reply_markup
        )
        logger.info(f"Start command received from {update.message.from_user.id}")
    except Exception as e:
        logger.error(f"Error in start command: {str(e)}\n{traceback.format_exc()}")
        await update.message.reply_text("Произошла ошибка при запуске. Попробуйте снова.")

async def select_persona(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton(details["name"], callback_data=f"set_persona_{key}")]
        for key, details in PERSONALITIES.items()
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('Выберите личность для бота:', reply_markup=reply_markup)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("set_persona_"):
        persona_key = data.split("set_persona_")[1]
        if persona_key in PERSONALITIES:
            context.user_data['current_personality'] = persona_key
            welcome_message = PERSONALITIES[persona_key]["welcome"]
            await query.edit_message_text(text=f"Личность изменена на: {PERSONALITIES[persona_key]['name']}.\n{welcome_message}")
            logger.info(f"User {query.from_user.id} changed personality to {persona_key}")
        else:
            await query.edit_message_text(text="Ошибка: Такая личность не найдена.")

async def premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Эта функция остается как заглушка
    await update.message.reply_text("Премиум функции пока в разработке! Следите за обновлениями.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    user_id = update.message.from_user.id
    logger.info(f"Received message from {user_id}: {user_message}")

    current_personality_key = context.user_data.get('current_personality', DEFAULT_PERSONALITY_KEY)
    system_prompt = await get_current_personality_prompt(context)

    # Обработка статических ответов и Яндекс.Карт (преимущественно для NeuroPal)
    if current_personality_key == "neuropal":
        if "где поесть на таганке" in user_message.lower(): # Пример статического ответа
            response = "На Таганке много всего! Например, 'Грабли' для бюджетного обеда или 'Теремок' для блинов. Если ищете что-то конкретное, уточните кухню!"
            await update.message.reply_text(response)
            logger.info(f"Sent static response for NeuroPal: {response}")
            return
        # ... (другие статические ответы для NeuroPal можно добавить сюда)

        if "где поесть" in user_message.lower() and YANDEX_API_KEY != "YOUR_YANDEX_API_KEY":
            # Логика Яндекс.Карт остается прежней, но можно улучшать отдельно
            try:
                # ... (код для Яндекс.Карт из предыдущей версии) ...
                # Этот блок можно оставить как есть или доработать
                place_query = user_message.split("где поесть")[-1].strip()
                if place_query.startswith("на "): place_query = place_query[3:]
                if not place_query: place_query = "Москва центр"
                
                search_text = f"кафе {place_query}"
                api_url = f"https://search-maps.yandex.ru/v1/?text={requests.utils.quote(search_text)}&type=biz&lang=ru_RU&apikey={YANDEX_API_KEY}&results=1&rspn=1&ll=37.617700,55.755863&spn=0.552069,0.400552" # Добавлен ll и spn для центра Москвы
                
                response_maps = requests.get(api_url)
                response_maps.raise_for_status()
                data_maps = response_maps.json()
                
                if data_maps.get('features') and data_maps['features'][0].get('properties', {}).get('CompanyMetaData'):
                    place_name = data_maps['features'][0]['properties']['CompanyMetaData'].get('name', 'Неизвестное место')
                    place_address = data_maps['features'][0]['properties']['CompanyMetaData'].get('address', '')
                    response = f"Яндекс.Карты подсказывают: {place_name} ({place_address}). Рекомендую проверить актуальность перед визитом!"
                else:
                    response = f"Не удалось быстро найти '{place_query}' через Яндекс.Карты. Попробуйте более общий запрос или другой район."
                await update.message.reply_text(response)
                logger.info(f"Sent Yandex response for NeuroPal: {response}")
            except requests.exceptions.RequestException as e_req:
                logger.error(f"Yandex Maps API request error: {str(e_req)}")
                await update.message.reply_text("Проблемы с доступом к Яндекс.Картам. Попробуйте позже.")
            except Exception as e:
                logger.error(f"Yandex Maps error: {str(e)}\n{traceback.format_exc()}")
                await update.message.reply_text("Ошибка при поиске на Яндекс.Картах.")
            return

    if "расскажи шутку" in user_message.lower():
        response = "Почему программисты не любят природу? Слишком много багов! 😄"
        await update.message.reply_text(response)
        logger.info(f"Sent static joke response: {response}")
        return

    if not gemini_model:
        await update.message.reply_text("Модель Gemini временно недоступна. Пожалуйста, попробуйте позже.")
        logger.warning("Gemini client is not initialized.")
        return

    try:
        logger.info(f"Sending to Gemini ({gemini_model_name}) with system prompt fragment for {current_personality_key} and message: '{user_message}'")
        
        # Настройка генерации для Gemini
        generation_config = genai.types.GenerationConfig(
            max_output_tokens=MAX_OUTPUT_TOKENS_GEMINI,
            temperature=0.7 # Можно настроить "креативность"
        )

        chat = gemini_model.start_chat(history=[
            {"role": "user", "parts": [system_prompt]},
            {"role": "model", "parts": [PERSONALITIES[current_personality_key].get("welcome", "Я готов.")]}
        ])
        response_gen = await chat.send_message_async(
            user_message,
            generation_config=generation_config
        )

        reply = response_gen.text
        
        # --- Обрезка ответа по длине, если он все еще слишком длинный ---
        if len(reply) > MAX_MESSAGE_LENGTH_TELEGRAM:
            reply = reply[:MAX_MESSAGE_LENGTH_TELEGRAM - 3] + "..."
            logger.info(f"Gemini response was truncated to {MAX_MESSAGE_LENGTH_TELEGRAM} chars.")

        await update.message.reply_text(reply)
        logger.info(f"Sent Gemini response (length: {len(reply)} chars)")

    except Exception as e:
        logger.error(f"Gemini error: {str(e)}\n{traceback.format_exc()}")
        current_persona_name = await get_current_personality_name(context)
        await update.message.reply_text(
            f"Извините, произошла ошибка при общении с ИИ ({current_persona_name}). Пожалуйста, попробуйте еще раз позже."
        )

async def main():
    try:
        application = Application.builder().token(TOKEN).build()
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("persona", select_persona))
        application.add_handler(CommandHandler("premium", premium))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_handler(CallbackQueryHandler(button_callback))
        logger.info("Starting bot...")
        await application.run_polling()
    except Exception as e:
        logger.error(f"Error in main: {str(e)}\n{traceback.format_exc()}")
        raise

if __name__ == "__main__":
    if TOKEN == "8185454402:AAEgJLaBSaUSyP9Z_zv76Fn0PtEwltAqga0" or "YOUR_BOT_TOKEN" in TOKEN: # Добавил еще проверку
        logger.critical("CRITICAL: DEFAULT TELEGRAM TOKEN IS USED. Please replace it with your actual token.")
    if GEMINI_API_KEY == "AIzaSyCdDMpgLJyz6aYdwT9q4sbBk7sHVID4BTI" or "YOUR_GEMINI_API_KEY" in GEMINI_API_KEY:
        logger.critical("CRITICAL: DEFAULT GEMINI API KEY IS USED. Please replace it with your actual key.")
    if YANDEX_API_KEY == "YOUR_YANDEX_API_KEY":
        logger.warning("YANDEX_API_KEY is not set. Yandex Maps functionality will not work correctly.")
    
    if gemini_model is None:
        logger.warning("Gemini model could not be initialized. Bot will have limited functionality.")

    asyncio.run(main())
