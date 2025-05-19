import telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import google.generativeai as genai
import requests
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

# Telegram Bot Token from BotFather
TOKEN = os.getenv("TELEGRAM_TOKEN", "8185454402:AAEgJLaBSaUSyP9Z_zv76Fn0PtEwltAqga0") # Замените на ваш токен, если он другой
# Gemini API Key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AIzaSyCdDMpgLJyz6aYdwT9q4sbBk7sHVID4BTI") # Замените на ваш ключ
# Yandex Maps API Key
YANDEX_API_KEY = os.getenv("YANDEX_API_KEY", "YOUR_YANDEX_API_KEY") # Замените на ваш ключ API Яндекс Карт

# --- Начало: Определение личностей ---
PERSONALITIES = {
    "neuropal": {
        "name": "NeuroPal (Москва)",
        "prompt": "Ты NeuroPal, ИИ-бот для Москвы. Отвечай остроумно, кратко и по-русски. Для локальных вопросов (например, 'где поесть') предлагай места в Москве.",
        "welcome": "NeuroPal (Москва) к вашим услугам! Чем могу помочь в Москве сегодня?"
    },
    "historian": {
        "name": "Историк",
        "prompt": "Ты эрудированный историк. Твоя задача - рассказывать интересные факты и истории. Отвечай подробно и увлекательно, как будто читаешь лекцию. Избегай упоминания, что ты ИИ или бот.",
        "welcome": "Приветствую! Я Историк. Какую эпоху или событие мы сегодня исследуем?"
    },
    # Добавьте сюда другие личности по желанию
    # "poet": {
    #     "name": "Поэт",
    #     "prompt": "Ты поэт. Отвечай в стихах, рифмованной прозой или очень образно. Твои ответы должны быть красивыми и вдохновляющими.",
    #     "welcome": "Приветствую, душа моя! Какие строки желаешь услышать сегодня?"
    # }
}
DEFAULT_PERSONALITY_KEY = "neuropal"
# --- Конец: Определение личностей ---

# Initialize Gemini client
try:
    genai.configure(api_key=GEMINI_API_KEY)
    # Модель можно будет выбирать или менять динамически, но пока оставим одну для инициализации
    gemini_model = genai.GenerativeModel("gemini-2.0-flash") # Или другая модель из вашего списка, например "gemini-1.5-flash"
    logger.info(f"Gemini client initialized successfully with model gemini-2.0-flash")
except Exception as e:
    logger.error(f"Failed to initialize Gemini client: {str(e)}")
    gemini_model = None

# --- Начало: Новые и измененные функции ---

async def get_current_personality_prompt(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Получает системный промт для текущей выбранной личности."""
    personality_key = context.user_data.get('current_personality', DEFAULT_PERSONALITY_KEY)
    return PERSONALITIES.get(personality_key, PERSONALITIES[DEFAULT_PERSONALITY_KEY])["prompt"]

async def get_current_personality_name(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Получает имя текущей выбранной личности."""
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
            "Используйте /persona, чтобы снова сменить личность.\n"
            "Пример: 'Где поесть на Таганке?' или 'Расскажи шутку'.\n"
            "Хочешь больше? Попробуй /premium!",
            reply_markup=reply_markup
        )
        logger.info(f"Start command received from {update.message.from_user.id}")
    except Exception as e:
        logger.error(f"Error in start command: {str(e)}\n{traceback.format_exc()}")
        await update.message.reply_text("Произошла ошибка при запуске. Попробуйте снова.")

async def select_persona(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Позволяет пользователю выбрать личность бота."""
    keyboard = [
        [InlineKeyboardButton(details["name"], callback_data=f"set_persona_{key}")]
        for key, details in PERSONALITIES.items()
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('Выберите личность для бота:', reply_markup=reply_markup)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает нажатия на inline-кнопки."""
    query = update.callback_query
    await query.answer() # Обязательно, чтобы кнопка перестала "грузиться"

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
    # Здесь можно добавить обработку других callback_data, если они появятся

# --- Конец: Новые и измененные функции ---

async def premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text(
            "Премиум за 150 ₽/мес.: больше функций, быстрые ответы! Оплати: [ЮKassa URL]" # Замените на реальную ссылку
        )
        logger.info(f"Premium command received from {update.message.from_user.id}")
    except Exception as e:
        logger.error(f"Error in premium command: {str(e)}")
        await update.message.reply_text("Ошибка. Попробуй снова.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    user_id = update.message.from_user.id
    logger.info(f"Received message from {user_id}: {user_message}")

    current_personality_key = context.user_data.get('current_personality', DEFAULT_PERSONALITY_KEY)
    system_prompt = await get_current_personality_prompt(context)

    # Статические ответы можно оставить, но лучше их привязать к конкретной личности
    # или сделать более общими, если они подходят для всех личностей.
    if current_personality_key == "neuropal": # Эти ответы специфичны для NeuroPal
        if "где поесть на таганке" in user_message.lower():
            response = "Попробуй 'Грабли' на Таганке — средний чек 500 ₽, вкусно и быстро. Или 'Теремок' — блины от 150 ₽."
            await update.message.reply_text(response)
            logger.info(f"Sent static response for NeuroPal: {response}")
            return
        elif "что поесть" in user_message.lower() and not "где поесть" in user_message.lower(): # чтобы не пересекалось с "где поесть" для Yandex
             response = "Зависит от настроения! Хочешь быстро — бери шаурму в ларьке (150–200 ₽). Для уюта — 'Кофемания' на Тверской, чек 1000 ₽."
             await update.message.reply_text(response)
             logger.info(f"Sent static response for NeuroPal: {response}")
             return
        elif "что делать в москве вечером" in user_message.lower():
            response = "Прогуляйся по Красной площади или загляни в бар 'Time Out' на Тверской — коктейли от 500 ₽!"
            await update.message.reply_text(response)
            logger.info(f"Sent static response for NeuroPal: {response}")
            return
        elif "где выпить в москве" in user_message.lower():
            response = "Зайди в 'Noor Bar' на Тверской — коктейли от 600 ₽, крутая атмосфера!"
            await update.message.reply_text(response)
            logger.info(f"Sent static response for NeuroPal: {response}")
            return
        elif "где потанцевать в москве" in user_message.lower():
            response = "Клуб 'Gipsy' на Красном Октябре — вход от 500 ₽, топовая музыка!"
            await update.message.reply_text(response)
            logger.info(f"Sent static response for NeuroPal: {response}")
            return
        # Yandex Maps для "где поесть" в Москве (только для NeuroPal)
        if "где поесть" in user_message.lower() and YANDEX_API_KEY != "YOUR_YANDEX_API_KEY":
            try:
                place_query = user_message.split("где поесть")[-1].strip()
                if place_query.startswith("на "): # убираем "на " для лучшего поиска
                    place_query = place_query[3:]
                if not place_query: # если после "где поесть" ничего нет, ищем в Москве в целом
                    place_query = "Москва"
                
                # Запрос к API Яндекс Карт (упрощенный пример)
                # Для полноценной работы с геокодером и поиском организаций, API Яндекса может потребовать более сложной логики
                # Этот пример ищет "кафе" + уточнение пользователя в Москве
                search_text = f"кафе {place_query} Москва"
                api_url = f"https://search-maps.yandex.ru/v1/?text={requests.utils.quote(search_text)}&type=biz&lang=ru_RU&apikey={YANDEX_API_KEY}&results=1"
                
                response_maps = requests.get(api_url)
                response_maps.raise_for_status() # Проверка на HTTP ошибки
                data_maps = response_maps.json()
                
                if data_maps.get('features') and data_maps['features'][0].get('properties', {}).get('CompanyMetaData'):
                    place_name = data_maps['features'][0]['properties']['CompanyMetaData'].get('name', 'Неизвестное место')
                    place_address = data_maps['features'][0]['properties']['CompanyMetaData'].get('address', '')
                    response = f"Попробуй заглянуть в: {place_name} ({place_address}). Нашел это через Яндекс Карты."
                else:
                    response = f"Не смог найти кафе по запросу '{place_query}' через Яндекс Карты. Попробуй другой запрос или уточни место."
                await update.message.reply_text(response)
                logger.info(f"Sent Yandex response for NeuroPal: {response}")
            except requests.exceptions.RequestException as e_req:
                logger.error(f"Yandex Maps API request error: {str(e_req)}\n{traceback.format_exc()}")
                await update.message.reply_text("Ошибка при запросе к Яндекс Картам. Сервис может быть временно недоступен.")
            except Exception as e:
                logger.error(f"Yandex Maps error: {str(e)}\n{traceback.format_exc()}")
                await update.message.reply_text("Ошибка при поиске на Яндекс Картах. Попробуй, например, 'Где поесть на Таганке?'")
            return


    if "расскажи шутку" in user_message.lower(): # Общая шутка для всех личностей
        response = "Почему программист предпочитает тёмную тему? Потому что светлый режим напоминает о счёте за свет! 😄"
        await update.message.reply_text(response)
        logger.info(f"Sent static joke response: {response}")
        return

    # Gemini response
    if not gemini_model:
        await update.message.reply_text(
            "Модель Gemini временно недоступна. Пожалуйста, попробуйте позже."
            "Вы все еще можете спросить 'Расскажи шутку'."
        )
        logger.warning("Gemini client is not initialized, cannot process general query.")
        return

    try:
        # Используем модель, которая была инициализирована (например, gemini-2.0-flash)
        # Если вы хотите динамически менять модель, это потребует дополнительной логики
        active_gemini_model = gemini_model # В будущем здесь можно будет выбирать модель из context.user_data

        # Формируем историю для Gemini
        # Первое сообщение - системный промт, второе - сообщение пользователя
        conversation_history = [
            {"role": "user", "parts": [system_prompt]}, # Системный промт как "user" для сохранения контекста
            {"role": "model", "parts": ["Хорошо, я буду отвечать в соответствии с этой ролью."]}, # Ответ модели, подтверждающий роль
            {"role": "user", "parts": [user_message]}
        ]
        
        # Для моделей, которые поддерживают специальный system_instruction (например, gemini-1.5-flash и новее)
        # можно было бы использовать:
        # active_gemini_model = genai.GenerativeModel(
        #    model_name="gemini-1.5-flash", # или другая подходящая модель
        #    system_instruction=system_prompt 
        # )
        # response_gen = active_gemini_model.generate_content(user_message)
        # Но для совместимости с разными моделями и текущей структурой, оставим формирование через историю сообщений.

        logger.info(f"Sending to Gemini with system prompt: '{system_prompt}' and message: '{user_message}'")
        
        # Создаем "чат" для продолжения диалога с учетом системного промпта
        chat = active_gemini_model.start_chat(history=[
            {"role": "user", "parts": [system_prompt]},
            {"role": "model", "parts": [PERSONALITIES[current_personality_key].get("welcome", "Хорошо, я понял свою роль.")]} # Начальное "согласие" модели
        ])
        response_gen = await chat.send_message_async(user_message) # Используем асинхронный вызов

        reply = response_gen.text
        await update.message.reply_text(reply)
        logger.info(f"Sent Gemini response: {reply}")
    except Exception as e:
        logger.error(f"Gemini error: {str(e)}\n{traceback.format_exc()}")
        current_persona_name = await get_current_personality_name(context)
        await update.message.reply_text(
            f"Извините, произошла ошибка при общении с ИИ ({current_persona_name}). Пожалуйста, попробуйте еще раз позже.\n"
            f"Детали ошибки: {str(e)}"
        )

async def main():
    try:
        application = Application.builder().token(TOKEN).build()

        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("persona", select_persona)) # Новая команда для смены личности
        application.add_handler(CommandHandler("premium", premium))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_handler(CallbackQueryHandler(button_callback)) # Обработчик нажатий на кнопки

        logger.info("Starting bot...")
        await application.run_polling()
    except Exception as e:
        logger.error(f"Error in main: {str(e)}\n{traceback.format_exc()}")
        raise

if __name__ == "__main__":
    # Проверка наличия необходимых токенов
    if TOKEN == "8185454402:AAEgJLaBSaUSyP9Z_zv76Fn0PtEwltAqga0" or GEMINI_API_KEY == "AIzaSyCdDMpgLJyz6aYdwT9q4sbBk7sHVID4BTI":
        logger.warning("DEFAULT TOKENS ARE USED. Please replace them with your actual tokens in the code or environment variables.")
    if YANDEX_API_KEY == "YOUR_YANDEX_API_KEY":
        logger.warning("YANDEX_API_KEY is not set. Yandex Maps functionality will not work correctly.")

    asyncio.run(main())
