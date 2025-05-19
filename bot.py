import telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update # Добавил ParseMode
from telegram.constants import ParseMode # Явно импортируем ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import google.generativeai as genai
import requests 
import logging
import traceback
import os
import asyncio
import nest_asyncio

nest_asyncio.apply()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_TOKEN", "8185454402:AAEgJLaBSaUSyP9Z_zv76Fn0PtEwltAqga0")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AIzaSyCdDMpgLJyz6aYdwT9q4sbBk7sHVID4BTI")
YANDEX_API_KEY = os.getenv("YANDEX_API_KEY", "YOUR_YANDEX_API_KEY")

MAX_OUTPUT_TOKENS_GEMINI = 1500
MAX_MESSAGE_LENGTH_TELEGRAM = 2500 # Немного увеличим для Markdown, но будем стремиться к меньшему

# --- Обновленные РЕЖИМЫ РАБОТЫ с инструкциями по форматированию и длине ---
AI_MODES = {
    "universal_ai": {
        "name": "🤖 Универсальный ИИ",
        "prompt": (
            "Ты — Gemini, продвинутый мультимодальный ИИ-ассистент от Google. "
            "Твоя задача — помогать пользователю с разнообразными запросами: отвечать на вопросы, генерировать текст, "
            "давать объяснения, выполнять анализ и предоставлять информацию по широкому кругу тем. "
            "Будь вежлив, объективен, точен и полезен. Если твои знания ограничены по времени, предупреждай об этом. "
            "Избегай личных мнений, если тебя об этом не просят.\n\n"
            "**Форматирование:** Используй Markdown для улучшения читаемости: **для выделения** используй двойные звездочки, *для курсива* — одинарные. "
            "Списки оформляй нумерованными пунктами (например, `1. Первый пункт`). "
            "Для терминов или коротких фрагментов кода используй `обратные апострофы`.\n\n"
            "**Длина и завершенность:** Старайся, чтобы твои ответы были полными и логически завершенными. "
            "Если ответ содержит списки или перечисления, убедись, что последний пункт полностью раскрыт. "
            "Если чувствуешь, что ответ получается слишком длинным (больше 4-5 абзацев или 7-10 пунктов списка), "
            "постарайся его сократить, сохранив суть, или предложи пользователю разбить вопрос на части. "
            "Предпочти дать на один пункт меньше, но полностью, чем оборвать последний."
        ),
        "welcome": "Активирован режим 'Универсальный ИИ'. Какой у вас запрос?"
    },
    "creative_helper": {
        "name": "✍️ Творческий Помощник",
        "prompt": (
            "Ты — Gemini, креативный ИИ-партнёр и писатель. "
            "Помогай пользователю генерировать идеи, писать тексты (рассказы, стихи, сценарии, маркетинговые материалы), "
            "придумывать слоганы, разрабатывать концепции и решать другие творческие задачи. "
            "Будь вдохновляющим, оригинальным и предлагай нестандартные подходы.\n\n"
            "**Форматирование:** Используй Markdown для выделения ключевых идей: **для заголовков или акцентов** используй двойные звездочки, *для метафор или цитат* — одинарные. "
            "Если предлагаешь варианты (например, слоганы), оформляй их как список с маркерами (`- Пример`).\n\n"
            "**Длина и завершенность:** Творчество не всегда укладывается в рамки, но старайся, чтобы результат был читаемым. "
            "Если это длинный текст (например, рассказ), убедись, что он имеет логическое завершение. "
            "Если это список идей, пусть он будет полным."
        ),
        "welcome": "Режим 'Творческий Помощник' к вашим услугам! Над какой творческой задачей поработаем?"
    },
}
DEFAULT_AI_MODE_KEY = "universal_ai"

AVAILABLE_TEXT_MODELS = {
    "gemini_2_5_flash_preview": {
        "name": "💎 G-2.5 Flash Preview (04-17)",
        "id": "gemini-2.5-flash-preview-04-17"
    },
    "gemini_2_0_flash": {
        "name": "⚡️ G-2.0 Flash",
        "id": "gemini-2.0-flash"
    }
}
DEFAULT_MODEL_ID = AVAILABLE_TEXT_MODELS["gemini_2_5_flash_preview"]["id"]

try:
    genai.configure(api_key=GEMINI_API_KEY)
    logger.info("Gemini API configured successfully.")
except Exception as e:
    logger.error(f"Failed to configure Gemini API: {str(e)}")

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

# --- НОВАЯ ФУНКЦИЯ УМНОЙ ОБРЕЗКИ ---
def smart_truncate(text: str, max_length: int) -> tuple[str, bool]:
    """
    Обрезает текст до max_length, стараясь не рвать слова или предложения.
    Возвращает (обрезанный_текст, была_ли_обрезка).
    """
    if len(text) <= max_length:
        return text, False

    suffix = "\n\n_(...ответ был сокращен)_"
    adjusted_max_length = max_length - len(suffix)
    
    if adjusted_max_length <= 0: # Если даже суффикс не влезает
        return text[:max_length-3] + "...", True 

    truncated_text = text[:adjusted_max_length]

    # Пытаемся найти последний перенос строки или точку с пробелом
    possible_cut_points = []
    last_newline = truncated_text.rfind('\n')
    if last_newline != -1:
        possible_cut_points.append(last_newline)
    
    last_sentence_end_period = truncated_text.rfind('. ')
    if last_sentence_end_period != -1:
        possible_cut_points.append(last_sentence_end_period + 1) # Включаем точку

    last_sentence_end_quest = truncated_text.rfind('? ')
    if last_sentence_end_quest != -1:
        possible_cut_points.append(last_sentence_end_quest + 1)

    last_sentence_end_excl = truncated_text.rfind('! ')
    if last_sentence_end_excl != -1:
        possible_cut_points.append(last_sentence_end_excl + 1)

    if possible_cut_points:
        cut_at = max(possible_cut_points)
        # Убедимся, что мы не обрезаем слишком мало (например, если последний символ - перенос строки)
        if cut_at > adjusted_max_length * 0.7 or len(possible_cut_points) == 1 and possible_cut_points[0] == last_newline: # Обрезаем по переносу строки если он близко к концу или единственный вариант
             return text[:cut_at].strip() + suffix, True

    # Если не нашли хорошей точки, режем по последнему пробелу
    last_space = truncated_text.rfind(' ')
    if last_space != -1 and last_space > adjusted_max_length * 0.7:
        return text[:last_space].strip() + suffix, True
    
    # Самый крайний случай - жесткая обрезка
    return text[:adjusted_max_length].strip() + suffix, True


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
        parse_mode=ParseMode.MARKDOWN_V2 # Используем MarkdownV2
    )

async def select_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton(details["name"], callback_data=f"set_mode_{key}")] for key, details in AI_MODES.items()]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('Выберите режим работы для ИИ:', reply_markup=reply_markup)

async def select_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton(details["name"], callback_data=f"set_model_{key}")] for key, details in AVAILABLE_TEXT_MODELS.items()]
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
                text=f"Режим изменен на: *{mode_details['name']}*\n{telegram.helpers.escape_markdown(mode_details['welcome'], version=2)}", # Экранируем Markdown в welcome сообщении
                parse_mode=ParseMode.MARKDOWN_V2
            )
    elif data.startswith("set_model_"):
        model_key_in_dict = data.split("set_model_")[1]
        if model_key_in_dict in AVAILABLE_TEXT_MODELS:
            selected_model_info = AVAILABLE_TEXT_MODELS[model_key_in_dict]
            context.user_data['selected_model_id'] = selected_model_info["id"]
            await query.edit_message_text(
                text=f"Модель изменена на: *{selected_model_info['name']}*",
                parse_mode=ParseMode.MARKDOWN_V2
            )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    user_id = update.message.from_user.id
    logger.info(f"Received message from {user_id}: '{user_message}'")

    current_mode_details = get_current_mode_details(context)
    system_prompt = current_mode_details["prompt"]
    selected_model_id = get_current_model_id(context)

    if context.user_data.get('current_ai_mode', DEFAULT_AI_MODE_KEY) == "universal_ai":
        # ... (логика для Яндекс.Карт и статических ответов, если нужна)
        pass # Убрал для краткости, можно вернуть или доработать

    if "расскажи шутку" in user_message.lower():
        # ... (код для шутки)
        response_text = "Почему компьютеры не любят ходить на пляж? Боятся, что у них сядет *батарейка* или попадет *песок* в порты! 😄"
        try:
            await update.message.reply_text(response_text, parse_mode=ParseMode.MARKDOWN_V2)
        except telegram.error.BadRequest:
            await update.message.reply_text(telegram.helpers.escape_markdown(response_text, version=2)) # Отправляем как обычный текст, если Markdown не удался
        return

    try:
        active_gemini_model = genai.GenerativeModel(selected_model_id)
        logger.info(f"Using Gemini model: {selected_model_id} for user {user_id}")
        
        generation_config = genai.types.GenerationConfig(
            max_output_tokens=MAX_OUTPUT_TOKENS_GEMINI,
            temperature=0.75
        )
        chat_history = [
            {"role": "user", "parts": [system_prompt]},
            {"role": "model", "parts": [telegram.helpers.escape_markdown(current_mode_details.get("welcome", "Хорошо, я готов."), version=2)]} # Экранируем Markdown в "welcome" для истории
        ]
        chat = active_gemini_model.start_chat(history=chat_history)
        response_gen = await chat.send_message_async(user_message, generation_config=generation_config)

        logger.debug(f"Raw Gemini response object: {response_gen}")
        # ... (детальное логирование ответа Gemini, если нужно для отладки)

        reply_text = response_gen.text
        
        if not reply_text or not reply_text.strip():
            logger.warning(f"Gemini returned empty text. Model: {selected_model_id}, User msg: '{user_message}'. Finish_reason: {response_gen.candidates[0].finish_reason if response_gen.candidates else 'N/A'}")
            reply_text = "ИИ не смог сформировать ответ или он был отфильтрован. Попробуйте переформулировать запрос."
        
        # --- ПРИМЕНЕНИЕ УМНОЙ ОБРЕЗКИ ---
        reply_text, was_truncated = smart_truncate(reply_text, MAX_MESSAGE_LENGTH_TELEGRAM)
        if was_truncated:
            logger.info(f"Gemini response was smartly truncated. Original length: {len(response_gen.text)}, Truncated length: {len(reply_text)}")

        # --- ОТПРАВКА С MARKDOWN ---
        try:
            await update.message.reply_text(reply_text, parse_mode=ParseMode.MARKDOWN_V2)
            logger.info(f"Sent Gemini response with MarkdownV2 (model: {selected_model_id}, length: {len(reply_text)})")
        except telegram.error.BadRequest as e_markdown:
            logger.warning(f"Failed to send message with MarkdownV2: {e_markdown}. Sending as plain text.")
            # Попытка отправить как обычный текст, предварительно экранировав потенциально "опасные" для Markdown символы,
            # которые могли быть сгенерированы моделью, но неверно интерпретированы Telegram.
            # Или просто отправить reply_text без parse_mode, если модель НЕ должна была генерировать Markdown.
            # Если модель ДОЛЖНА генерировать Markdown, то экранирование убьет его.
            # Лучше отправить исходный reply_text без parse_mode.
            plain_text_reply = response_gen.text # Берем исходный текст от Gemini
            plain_text_reply, _ = smart_truncate(plain_text_reply, MAX_MESSAGE_LENGTH_TELEGRAM) # Обрезаем его тоже
            await update.message.reply_text(plain_text_reply) # Отправляем без parse_mode
            logger.info(f"Sent Gemini response as plain text after Markdown failure (model: {selected_model_id}, length: {len(plain_text_reply)})")

    except Exception as e:
        logger.error(f"Error during Gemini interaction or message handling: {str(e)}\n{traceback.format_exc()}")
        await update.message.reply_text(
            f"К сожалению, произошла ошибка при обработке вашего запроса с моделью {get_current_model_display_name(context)}. Пожалуйста, попробуйте позже или смените модель/режим."
        )

async def main():
    if "ВАШ_ТЕЛЕГРАМ_ТОКЕН" in TOKEN or not TOKEN: # etc.
        logger.critical("CRITICAL: TELEGRAM_TOKEN is not set or uses a placeholder.")
        return
    if "ВАШ_GEMINI_API_КЛЮЧ" in GEMINI_API_KEY or not GEMINI_API_KEY:
        logger.critical("CRITICAL: GEMINI_API_KEY is not set or uses a placeholder.")
        return
        
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler(["mode", "select_mode"], select_mode))
    application.add_handler(CommandHandler(["model", "select_model"], select_model))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button_callback))

    logger.info("Starting bot with enhanced formatting and truncation...")
    await application.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
