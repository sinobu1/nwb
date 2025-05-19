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
YANDEX_API_KEY = os.getenv("YANDEX_API_KEY", "YOUR_YANDEX_API_KEY") # Опционально, для функционала карт

# --- КОНФИГУРАЦИЯ БОТА ---
MAX_OUTPUT_TOKENS_GEMINI = 1500 # Как вы и настроили
MAX_MESSAGE_LENGTH_TELEGRAM = 2000 # Немного увеличил, можно настроить (Telegram лимит 4096)

# --- РЕЖИМЫ РАБОТЫ (бывшие "личности") ---
AI_MODES = {
    "universal_ai": {
        "name": "🤖 Универсальный ИИ",
        "prompt": (
            "Ты — Gemini, продвинутый мультимодальный ИИ-ассистент от Google. "
            "Твоя задача — помогать пользователю с разнообразными запросами: отвечать на вопросы, генерировать текст, "
            "давать объяснения, выполнять анализ и предоставлять информацию по широкому кругу тем. "
            "Будь вежлив, объективен, точен и полезен. Если твои знания ограничены по времени, предупреждай об этом. "
            "Избегай личных мнений, если тебя об этом не просят."
        ),
        "welcome": "Активирован режим 'Универсальный ИИ'. Какой у вас запрос?"
    },
    "creative_helper": {
        "name": "✍️ Творческий Помощник",
        "prompt": (
            "Ты — Gemini, креативный ИИ-партнёр и писатель. "
            "Помогай пользователю генерировать идеи, писать тексты (рассказы, стихи, сценарии, маркетинговые материалы), "
            "придумывать слоганы, разрабатывать концепции и решать другие творческие задачи. "
            "Будь вдохновляющим, оригинальным и предлагай нестандартные подходы."
        ),
        "welcome": "Режим 'Творческий Помощник' к вашим услугам! Над какой творческой задачей поработаем?"
    },
    # Можно добавить другие режимы, например, для анализа, программирования и т.д.
}
DEFAULT_AI_MODE_KEY = "universal_ai"

# --- ДОСТУПНЫЕ МОДЕЛИ GEMINI ДЛЯ ВЫБОРА ---
AVAILABLE_TEXT_MODELS = {
    "gemini_2_5_flash_preview": {
        "name": "💎 G-2.5 Flash Preview (04-17)", # Более дружелюбное имя для кнопки
        "id": "gemini-2.5-flash-preview-04-17"
    },
    "gemini_2_0_flash": {
        "name": "⚡️ G-2.0 Flash",
        "id": "gemini-2.0-flash"
    }
    # Можно добавить gemini-1.5-pro-latest или gemini-1.5-flash-latest, если они доступны и нужны
}
DEFAULT_MODEL_ID = AVAILABLE_TEXT_MODELS["gemini_2_5_flash_preview"]["id"] # Модель по умолчанию

# --- Инициализация Gemini API (только конфигурация) ---
try:
    genai.configure(api_key=GEMINI_API_KEY)
    logger.info("Gemini API configured successfully.")
except Exception as e:
    logger.error(f"Failed to configure Gemini API: {str(e)}")
    # В этом случае бот не сможет обращаться к Gemini

# --- Функции для получения текущих настроек пользователя ---
def get_current_mode_details(context: ContextTypes.DEFAULT_TYPE) -> dict:
    mode_key = context.user_data.get('current_ai_mode', DEFAULT_AI_MODE_KEY)
    return AI_MODES.get(mode_key, AI_MODES[DEFAULT_AI_MODE_KEY])

def get_current_model_id(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.user_data.get('selected_model_id', DEFAULT_MODEL_ID)

def get_current_model_display_name(context: ContextTypes.DEFAULT_TYPE) -> str:
    selected_id = get_current_model_id(context)
    for model_info in AVAILABLE_TEXT_MODELS.values():
        if model_info["id"] == selected_id:
            return model_info["name"]
    return "Неизвестная модель"


# --- КОМАНДЫ БОТА ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.setdefault('current_ai_mode', DEFAULT_AI_MODE_KEY)
    context.user_data.setdefault('selected_model_id', DEFAULT_MODEL_ID)

    current_mode = get_current_mode_details(context)
    current_model_name = get_current_model_display_name(context)

    await update.message.reply_text(
        f"Привет! Я многофункциональный ИИ-бот.\n\n"
        f"Текущий режим: *{current_mode['name']}*\n"
        f"Текущая модель: *{current_model_name}*\n\n"
        "Вы можете:\n"
        "▫️ Задавать мне вопросы или давать задания.\n"
        "▫️ Сменить режим работы: /mode\n"
        "▫️ Выбрать другую модель ИИ: /model\n\n"
        "Просто напишите ваш запрос!",
        parse_mode=telegram.constants.ParseMode.MARKDOWN
    )
    logger.info(f"Start command processed for user {update.message.from_user.id}")

async def select_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton(details["name"], callback_data=f"set_mode_{key}")]
        for key, details in AI_MODES.items()
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('Выберите режим работы для ИИ:', reply_markup=reply_markup)

async def select_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton(details["name"], callback_data=f"set_model_{key}")] # key здесь будет ключ из AVAILABLE_TEXT_MODELS
        for key, details in AVAILABLE_TEXT_MODELS.items()
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('Выберите модель ИИ для использования:', reply_markup=reply_markup)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("set_mode_"):
        mode_key = data.split("set_mode_")[1]
        if mode_key in AI_MODES:
            context.user_data['current_ai_mode'] = mode_key
            mode_details = AI_MODES[mode_key]
            await query.edit_message_text(
                text=f"Режим изменен на: *{mode_details['name']}*.\n{mode_details['welcome']}",
                parse_mode=telegram.constants.ParseMode.MARKDOWN
            )
            logger.info(f"User {query.from_user.id} changed AI mode to {mode_key}")
        else:
            await query.edit_message_text(text="Ошибка: Такой режим не найден.")

    elif data.startswith("set_model_"):
        model_key_in_dict = data.split("set_model_")[1] # Это ключ из словаря AVAILABLE_TEXT_MODELS
        if model_key_in_dict in AVAILABLE_TEXT_MODELS:
            selected_model_info = AVAILABLE_TEXT_MODELS[model_key_in_dict]
            context.user_data['selected_model_id'] = selected_model_info["id"]
            await query.edit_message_text(
                text=f"Модель изменена на: *{selected_model_info['name']}*.",
                parse_mode=telegram.constants.ParseMode.MARKDOWN
            )
            logger.info(f"User {query.from_user.id} changed AI model to {selected_model_info['id']}")
        else:
            await query.edit_message_text(text="Ошибка: Такая модель не найдена.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    user_id = update.message.from_user.id
    logger.info(f"Received message from {user_id}: '{user_message}'")

    current_mode_details = get_current_mode_details(context)
    system_prompt = current_mode_details["prompt"]
    selected_model_id = get_current_model_id(context)

    # Статические ответы и Яндекс.Карты (если активен режим "Универсальный ИИ")
    # и если API ключ Яндекс.Карт предоставлен
    if context.user_data.get('current_ai_mode', DEFAULT_AI_MODE_KEY) == "universal_ai":
        if "где поесть на таганке" in user_message.lower(): # Пример статического ответа
            response = "На Таганке множество кафе! Например, 'Грабли' для бюджетного обеда или 'Теремок'. Для более точной рекомендации уточните, пожалуйста, ваши предпочтения (кухня, ценовой диапазон)."
            await update.message.reply_text(response)
            logger.info(f"Sent static response for universal_ai: {response}")
            return
        # ... (другие статические ответы)

        # Пример интеграции с Яндекс.Картами (оставлен для демонстрации)
        # Эту часть можно дорабатывать или убрать, если не нужна
        if "где поесть" in user_message.lower() and YANDEX_API_KEY != "YOUR_YANDEX_API_KEY":
            try:
                place_query = user_message.split("где поесть")[-1].strip()
                if place_query.startswith("на "): place_query = place_query[3:]
                if not place_query: place_query = "Москва центр"
                
                search_text = f"кафе {place_query}"
                api_url = f"https://search-maps.yandex.ru/v1/?text={requests.utils.quote(search_text)}&type=biz&lang=ru_RU&apikey={YANDEX_API_KEY}&results=1&rspn=1&ll=37.617700,55.755863&spn=0.552069,0.400552"
                
                response_maps = requests.get(api_url)
                response_maps.raise_for_status()
                data_maps = response_maps.json()
                
                if data_maps.get('features') and data_maps['features'][0].get('properties', {}).get('CompanyMetaData'):
                    place_name = data_maps['features'][0]['properties']['CompanyMetaData'].get('name', 'Неизвестное место')
                    place_address = data_maps['features'][0]['properties']['CompanyMetaData'].get('address', '')
                    response = f"Яндекс.Карты предлагают: {place_name} ({place_address}). Рекомендую уточнить детали перед визитом!"
                else:
                    response = f"Не удалось быстро найти '{place_query}' через Яндекс.Карты. Попробуйте другой запрос."
                await update.message.reply_text(response)
                logger.info(f"Sent Yandex response for universal_ai: {response}")
            except Exception as e_maps:
                logger.error(f"Yandex Maps error: {str(e_maps)}\n{traceback.format_exc()}")
                await update.message.reply_text("Возникла проблема при обращении к Яндекс.Картам.")
            return # Завершаем обработку, если сработали Яндекс.Карты

    # Общие команды, не зависящие от режима (можно добавить)
    if "расскажи шутку" in user_message.lower():
        response = "Почему компьютеры так умны? Потому что они слушают свою материнскую плату! 😄"
        await update.message.reply_text(response)
        logger.info(f"Sent static joke response: {response}")
        return

    # --- Взаимодействие с Gemini ---
    try:
        # Динамическое создание экземпляра модели на основе выбора пользователя
        active_gemini_model = genai.GenerativeModel(selected_model_id)
        logger.info(f"Using Gemini model: {selected_model_id} for user {user_id}")
        
        generation_config = genai.types.GenerationConfig(
            max_output_tokens=MAX_OUTPUT_TOKENS_GEMINI,
            temperature=0.75 # Можно сделать настраиваемой
        )

        # Формирование истории для чата
        # Первое сообщение - системный промт, второе - "согласие" модели (улучшает следование промту)
        chat_history = [
            {"role": "user", "parts": [system_prompt]},
            {"role": "model", "parts": [current_mode_details.get("welcome", "Хорошо, я готов.")]}
        ]
        
        chat = active_gemini_model.start_chat(history=chat_history)
        
        # Отправка сообщения пользователя в чат
        response_gen = await chat.send_message_async(
            user_message,
            generation_config=generation_config
        )

        # Логирование ответа от Gemini (оставляем для отладки)
        logger.debug(f"Raw Gemini response object: {response_gen}")
        if hasattr(response_gen, 'prompt_feedback') and response_gen.prompt_feedback:
            logger.debug(f"Gemini prompt feedback: {response_gen.prompt_feedback}")
        if hasattr(response_gen, 'candidates') and response_gen.candidates:
            logger.debug(f"Gemini candidates count: {len(response_gen.candidates)}")
            for i, candidate in enumerate(response_gen.candidates):
                logger.debug(f"Candidate {i} finish reason: {candidate.finish_reason}")
                logger.debug(f"Candidate {i} safety ratings: {candidate.safety_ratings}")

        reply = response_gen.text
        
        if not reply or not reply.strip():
            logger.warning(f"Gemini returned empty text. Model: {selected_model_id}, User msg: '{user_message}'. Finish_reason: {response_gen.candidates[0].finish_reason if response_gen.candidates else 'N/A'}")
            reply = "ИИ не смог сформировать ответ или он был отфильтрован. Попробуйте переформулировать запрос."
        
        if len(reply) > MAX_MESSAGE_LENGTH_TELEGRAM:
            reply = reply[:MAX_MESSAGE_LENGTH_TELEGRAM - 3] + "..."
            logger.info(f"Gemini response truncated to {MAX_MESSAGE_LENGTH_TELEGRAM} chars.")

        await update.message.reply_text(reply)
        logger.info(f"Sent Gemini response to user {user_id} (model: {selected_model_id}, length: {len(reply)})")

    except Exception as e:
        logger.error(f"Error during Gemini interaction or message handling: {str(e)}\n{traceback.format_exc()}")
        await update.message.reply_text(
            f"К сожалению, произошла ошибка при обработке вашего запроса с моделью {get_current_model_display_name(context)}. Пожалуйста, попробуйте позже или смените модель/режим."
        )

async def main():
    # Проверка наличия токенов перед запуском
    if "ВАШ_ТЕЛЕГРАМ_ТОКЕН" in TOKEN or not TOKEN:
        logger.critical("CRITICAL: TELEGRAM_TOKEN is not set or uses a placeholder. Please set your actual token.")
        return
    if "ВАШ_GEMINI_API_КЛЮЧ" in GEMINI_API_KEY or not GEMINI_API_KEY:
        logger.critical("CRITICAL: GEMINI_API_KEY is not set or uses a placeholder. Please set your actual key.")
        # Можно разрешить запуск без Gemini для статических функций, но лучше остановить.
        # return 
        
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler(["mode", "select_mode"], select_mode)) # Команда для смены режима
    application.add_handler(CommandHandler(["model", "select_model"], select_model)) # Команда для смены модели
    # application.add_handler(CommandHandler("premium", premium)) # Если будет премиум
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button_callback))

    logger.info("Starting bot with new concept...")
    try:
        await application.run_polling()
    except telegram.error.NetworkError as ne:
        logger.error(f"Telegram NetworkError: {ne}. Retrying might be necessary or check network.")
    except Exception as e_main:
        logger.error(f"Critical error in main polling loop: {e_main}\n{traceback.format_exc()}")


if __name__ == "__main__":
    asyncio.run(main())
