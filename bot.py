import telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode # Используем ParseMode
from telegram.helpers import escape_markdown # Импортируем escape_markdown
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

# --- Обновленные РЕЖИМЫ РАБОТЫ с фокусом на "документный" стиль ---
AI_MODES = {
    "universal_ai": {
        "name": "🤖 Универсальный ИИ",
        "prompt": (
            "Ты — Gemini, продвинутый мультимодальный ИИ-ассистент от Google. "
            "Твоя задача — помогать пользователю с разнообразными запросами: отвечать на вопросы, генерировать текст, "
            "давать объяснения, выполнять анализ и предоставлять информацию по широкому кругу тем. "
            "Будь вежлив, объективен, точен и полезен. Если твои знания ограничены по времени, предупреждай об этом. "
            "Избегай личных мнений, если тебя об этом не просят.\n\n"
            "**Оформление ответа (стиль документа):**\n"
            "1.  **Структура и Абзацы:** Представляй информацию в хорошо структурированном виде. Четко разделяй мысли на абзацы. Если тема объемная, разбивай ответ на логические секции. Для обозначения таких секций можешь использовать выделение ключевой фразы жирным шрифтом в начале секции (например, вынеся её на отдельную строку).\n"
            "2.  **Выделение (умеренно):** Используй выделение жирным шрифтом для акцентирования только самых ключевых терминов или очень важных моментов. Курсив можно применять для примеров или для придания легкого акцента. Пожалуйста, избегай избыточного выделения — текст должен оставаться легким для чтения.\n"
            "3.  **Списки:** Если информация предполагает перечисление, используй нумерованные или маркированные списки (маркеры можно начинать с дефиса `-` или звездочки `*`). Следи за правильным форматированием и отступами в списках для наглядности.\n"
            "4.  **Ясность и Читаемость:** Твой ответ должен быть предельно ясным, аккуратным и легко читаемым, как хорошо подготовленный документ. Избегай сложного или избыточного форматирования, которое может мешать восприятию. Главное — донести смысл.\n"
            "5.  **Логическая Завершённость:** Старайся, чтобы твои ответы были полными и все пункты (если это список) были завершены. Лучше дать на один пункт меньше, но полностью, чем оборвать мысль на середине.\n"
            "6.  **Без лишних символов:** Не используй в тексте избыточные скобки, дефисы или другие знаки пунктуации, если они не несут смысловой нагрузки или не требуются правилами грамматики."

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
            "**Оформление творческого ответа (акцент на читаемость):**\n"
            "1.  **Структура и Абзацы:** Для прозы используй абзацы, чтобы четко структурировать повествование. Для стихов сохраняй деление на строфы и правильные переносы строк.\n"
            "2.  **Выделение (для смысла):** Используй выделение жирным шрифтом или курсивом только для осмысленного акцентирования важных образов, эмоций или ключевых фраз. Форматирование должно усиливать восприятие, а не быть самоцелью.\n"
            "3.  **Списки Идей/Вариантов:** Если предлагаешь несколько вариантов (например, заголовков, идей), оформляй их как простой маркированный или нумерованный список.\n"
            "4.  **Диалоги:** Прямую речь в рассказах или сценариях оформляй стандартными литературными способами (например, с использованием тире или кавычек).\n"
            "5.  **Ясность и Увлекательность:** Текст должен легко читаться и быть увлекательным. Избегай сложного форматирования, которое может отвлекать от содержания.\n"
            "6.  **Завершённость:** Старайся доводить творческие произведения до логического конца в рамках одного ответа, если это подразумевается задачей."
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
    
    current_mode_details = get_current_mode_details(context)
    current_model_display_name_text = get_current_model_display_name(context)

    # Экранируем ВСЕ части, которые будут вставлены в f-string, КРОМЕ самих Markdown символов типа '*'
    greeting = escape_markdown("Привет! Я многофункциональный ИИ-бот.", version=2)
    
    # Для частей, которые мы хотим сделать жирными, сначала экранируем их содержимое, ПОТОМ обрамляем звездочками
    mode_name_content = escape_markdown(current_mode_details['name'], version=2)
    mode_line = f"{escape_markdown('Текущий режим: ', version=2)}*{mode_name_content}*"

    model_name_content = escape_markdown(current_model_display_name_text, version=2)
    model_line = f"{escape_markdown('Текущая модель: ', version=2)}*{model_name_content}*"

    you_can = escape_markdown("Вы можете:", version=2)
    # Для строк списка, если они не содержат Markdown который мы хотим применить, экранируем целиком
    # Символ ▫️ не является спецсимволом Markdown. Команды /mode /model тоже не являются активной разметкой здесь.
    action1 = escape_markdown("▫️ Задавать мне вопросы или давать задания.", version=2)
    # Оставляем команды как есть, escape_markdown превратит / в \/ , что не всегда желательно для отображения команд
    action2 = "▫️ Сменить режим работы: /mode" 
    action3 = "▫️ Выбрать другую модель ИИ: /model" 
    invitation = escape_markdown("Просто напишите ваш запрос!", version=2)

    text_to_send = (
        f"{greeting}\n\n"
        f"{mode_line}\n"
        f"{model_line}\n\n"
        f"{you_can}\n"
        f"{action1}\n"
        f"{action2}\n"
        f"{action3}\n\n"
        f"{invitation}"
    )
    
    try:
        await update.message.reply_text(text_to_send, parse_mode=ParseMode.MARKDOWN_V2)
        logger.info(f"Start command processed for user {update.message.from_user.id} with new escaping.")
    except telegram.error.BadRequest as e:
        logger.error(f"Error sending /start message with MarkdownV2: {e}\nText was: {text_to_send}\n{traceback.format_exc()}")
        # Отправляем как обычный текст в случае ошибки Markdown
        plain_text_version = ( # Создаем версию без Markdown символов форматирования
            f"Привет! Я многофункциональный ИИ-бот.\n\n"
            f"Текущий режим: {current_mode_details['name']}\n"
            f"Текущая модель: {current_model_display_name_text}\n\n"
            "Вы можете:\n"
            "▫️ Задавать мне вопросы или давать задания.\n"
            "▫️ Сменить режим работы: /mode\n"
            "▫️ Выбрать другую модель ИИ: /model\n\n"
            "Просто напишите ваш запрос!"
        )
        await update.message.reply_text(plain_text_version)
        logger.info("Sent /start message as plain text after MarkdownV2 failure.")


async def select_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Имена режимов в кнопках (details["name"]) УЖЕ содержат эмодзи, которые не надо экранировать для отображения
    # Но если бы они содержали Markdown символы, которые мы ХОТИМ отобразить как Markdown, пришлось бы сложнее.
    # Здесь мы просто отображаем текст "как есть" в кнопке.
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
            
            # Экранируем динамические части текста перед вставкой в Markdown строку
            escaped_mode_name = escape_markdown(mode_details['name'], version=2)
            escaped_welcome_message = escape_markdown(mode_details['welcome'], version=2)
            
            text_to_send = f"Режим изменен на: *{escaped_mode_name}*\\.\n{escaped_welcome_message}"
            await query.edit_message_text(
                text=text_to_send,
                parse_mode=ParseMode.MARKDOWN_V2
            )
            logger.info(f"User {query.from_user.id} changed AI mode to {mode_key}")
        else:
            await query.edit_message_text(text="Ошибка: Такой режим не найден\\.") # Тоже экранируем точку

    elif data.startswith("set_model_"):
        model_key_in_dict = data.split("set_model_")[1]
        if model_key_in_dict in AVAILABLE_TEXT_MODELS:
            selected_model_info = AVAILABLE_TEXT_MODELS[model_key_in_dict]
            context.user_data['selected_model_id'] = selected_model_info["id"]
            
            escaped_model_name = escape_markdown(selected_model_info['name'], version=2)
            text_to_send = f"Модель изменена на: *{escaped_model_name}*\\." # Экранируем точку
            
            await query.edit_message_text(
                text=text_to_send,
                parse_mode=ParseMode.MARKDOWN_V2
            )
            logger.info(f"User {query.from_user.id} changed AI model to {selected_model_info['id']}")
        else:
            await query.edit_message_text(text="Ошибка: Такая модель не найдена\\.") # Экранируем точку

# --- handle_message остается таким же, как в предыдущем варианте ---
# (с умной обрезкой и попыткой отправки MarkdownV2, а затем plain text)
# ... (остальной код функции handle_message) ...

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    user_id = update.message.from_user.id
    logger.info(f"Received message from {user_id}: '{user_message}'")

    current_mode_details = get_current_mode_details(context)
    system_prompt = current_mode_details["prompt"]
    selected_model_id = get_current_model_id(context)

    # Пример: если нужно обработать команду /help или подобное статически
    if user_message.lower() == "/help":
        help_text = (
            "Это бот для взаимодействия с ИИ Gemini\\.\n\n"
            "Доступные команды:\n"
            "`/start` \\- начало работы, информация о текущих настройках\n"
            "`/mode` \\- выбрать режим работы ИИ\n"
            "`/model` \\- выбрать модель ИИ\n\n"
            "Просто напишите ваш вопрос или задание после выбора режима и модели\\."
        )
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN_V2)
        return

    if context.user_data.get('current_ai_mode', DEFAULT_AI_MODE_KEY) == "universal_ai":
        # Убрана логика Яндекс.Карт и статических ответов для краткости,
        # но ее можно вернуть, если нужно, и также адаптировать под Markdown
        pass

    if "расскажи шутку" in user_message.lower():
        # Для примера, если шутка содержит Markdown символы
        response_text = "Почему компьютеры не любят ходить на пляж? Боятся, что у них сядет *батарейка* или попадет *песок* в порты\\! 😄"
        # Обратите внимание на экранированный '!' в конце шутки
        try:
            await update.message.reply_text(response_text, parse_mode=ParseMode.MARKDOWN_V2)
        except telegram.error.BadRequest:
            # Если Markdown не удался, отправляем текст как есть (но без Markdown символов, которые могли вызвать ошибку)
            # Лучше всего использовать escape_markdown для всего текста, если он не должен содержать разметку
            safe_text = escape_markdown(response_text, version=2) # Это удалит наши * и \!
            # Поэтому для таких случаев, где мы сами контролируем Markdown, лучше иметь plain-text версию
            plain_joke = "Почему компьютеры не любят ходить на пляж? Боятся, что у них сядет батарейка или попадет песок в порты! 😄"
            await update.message.reply_text(plain_joke)
        return

    try:
        active_gemini_model = genai.GenerativeModel(selected_model_id)
        logger.info(f"Using Gemini model: {selected_model_id} for user {user_id}")
        
        generation_config = genai.types.GenerationConfig(
            max_output_tokens=MAX_OUTPUT_TOKENS_GEMINI,
            temperature=0.75
        )
        # Приветственное сообщение для истории чата НЕ ДОЛЖНО содержать Markdown, который сломает API Gemini.
        # Оно для модели, а не для пользователя. Поэтому убираем escape_markdown отсюда.
        # Если welcome сообщение из AI_MODES содержит Markdown, его нужно очистить или использовать версию без Markdown.
        # Для простоты, пусть welcome для модели будет простым.
        model_welcome_text = "Я готов помочь." # Простой текст для истории модели
        # Или если хотите использовать из AI_MODES, но без Markdown:
        # model_welcome_text = AI_MODES[context.user_data.get('current_ai_mode', DEFAULT_AI_MODE_KEY)]['welcome'].split('\n')[0] # Берем первую строку как пример

        chat_history = [
            {"role": "user", "parts": [system_prompt]},
            {"role": "model", "parts": [model_welcome_text]} 
        ]
        chat = active_gemini_model.start_chat(history=chat_history)
        response_gen = await chat.send_message_async(user_message, generation_config=generation_config)

        # logger.debug(f"Raw Gemini response object: {response_gen}")
        # ... (детальное логирование, если нужно)

        reply_text = response_gen.text
        
        if not reply_text or not reply_text.strip():
            logger.warning(f"Gemini returned empty text. Model: {selected_model_id}, User msg: '{user_message}'. Finish_reason: {response_gen.candidates[0].finish_reason if response_gen.candidates else 'N/A'}")
            reply_text = "ИИ не смог сформировать ответ или он был отфильтрован. Попробуйте переформулировать запрос."
        
        reply_text_for_sending, was_truncated = smart_truncate(reply_text, MAX_MESSAGE_LENGTH_TELEGRAM)
        if was_truncated:
            logger.info(f"Gemini response was smartly truncated. Original length: {len(reply_text)}, Truncated length: {len(reply_text_for_sending)}")

        try:
            await update.message.reply_text(reply_text_for_sending, parse_mode=ParseMode.MARKDOWN_V2)
            logger.info(f"Sent Gemini response with MarkdownV2 (model: {selected_model_id}, length: {len(reply_text_for_sending)})")
        except telegram.error.BadRequest as e_markdown:
            logger.warning(f"Failed to send message with MarkdownV2: {e_markdown}. Sending as plain text. Reply was: {reply_text_for_sending}")
            # Если модель должна была генерировать Markdown, но он оказался невалидным,
            # то отправка reply_text_for_sending без parse_mode покажет пользователю "сырой" Markdown.
            # Это может быть полезно для отладки промпта модели.
            await update.message.reply_text(reply_text_for_sending)
            logger.info(f"Sent Gemini response as plain text after Markdown failure (model: {selected_model_id}, length: {len(reply_text_for_sending)})")

    except Exception as e:
        logger.error(f"Error during Gemini interaction or message handling: {str(e)}\n{traceback.format_exc()}")
        # Экранируем имя модели на случай, если оно содержит Markdown-опасные символы
        escaped_display_name = escape_markdown(get_current_model_display_name(context), version=2)
        await update.message.reply_text(
            f"К сожалению, произошла ошибка при обработке вашего запроса с моделью {escaped_display_name}\\. Пожалуйста, попробуйте позже или смените модель/режим\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

# ... (main и if __name__ == "__main__": остаются такими же) ...
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

    logger.info("Starting bot with enhanced formatting, truncation, and Markdown V2 escaping...")
    await application.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
