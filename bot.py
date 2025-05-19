import telegram
from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup, Update,
    ReplyKeyboardMarkup, KeyboardButton, BotCommand
)
from telegram.constants import ParseMode, ChatAction # ChatAction все еще полезен для "печатает..."
from telegram.helpers import escape_markdown
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, CallbackQueryHandler
)
import google.generativeai as genai
import google.api_core.exceptions # Оставим на случай специфических ошибок API
import requests
import logging
import traceback
import os
import asyncio
import nest_asyncio
# import io # Больше не нужен, если нет генерации изображений

nest_asyncio.apply()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO) # Вернем INFO, DEBUG был для imagine
logger = logging.getLogger(__name__)

# --- КЛЮЧИ API И ТОКЕНЫ ---
TOKEN = os.getenv("TELEGRAM_TOKEN", "8185454402:AAEgJLaBSaUSyP9Z_zv76Fn0PtEwltAqga0") # ЗАМЕНИТЕ!!
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AIzaSyCdDMpgLJyz6aYdwT9q4sbBk7sHVID4BTI") # ЗАМЕНИТЕ!!
YANDEX_API_KEY = os.getenv("YANDEX_API_KEY", "YOUR_YANDEX_API_KEY") # Опционально

# --- КОНФИГУРАЦИЯ БОТА ---
MAX_OUTPUT_TOKENS_GEMINI = 1500
MAX_MESSAGE_LENGTH_TELEGRAM = 2500

# --- РЕЖИМЫ РАБОТЫ ИИ (остаются как есть, с промтами для простого структурированного текста) ---
AI_MODES = {
    "universal_ai": {
        "name": "🤖 Универсальный ИИ",
        "prompt": (
            "Ты — Gemini, продвинутый ИИ-ассистент от Google. "
            "Твоя задача — помогать пользователю с разнообразными запросами: отвечать на вопросы, генерировать текст, "
            "давать объяснения, выполнять анализ и предоставлять информацию по широкому кругу тем. "
            "Будь вежлив, объективен, точен и полезен. Если твои знания ограничены по времени, предупреждай об этом.\n\n"
            "**Оформление ответа (простой структурированный текст):**\n"
            "1.  **Абзацы:** Четко разделяй смысловые блоки текста абзацами. Используй одну или две пустые строки между абзацами для лучшей читаемости.\n"
            "2.  **Списки:** Если информация предполагает перечисление, используй нумерованные списки (например, `1. Первый пункт`, `2. Второй пункт`) или маркированные списки (например, `- Элемент списка` или `* Другой элемент`). Используй стандартные символы для списков.\n"
            "3.  **Секции/Заголовки (если нужно):** Для разделения крупных смысловых блоков можешь использовать короткую поясняющую фразу или заголовок на отдельной строке. Если хочешь выделить заголовок, можешь написать его ЗАГЛАВНЫМИ БУКВАМИ. Например:\n"
            "    ОСНОВНЫЕ ХАРАКТЕРИСТИКИ:\n"
            "    - Характеристика один...\n"
            "    - Характеристика два...\n"
            "4.  **Без специального форматирования:** Пожалуйста, НЕ используй Markdown-разметку (звездочки для жирного текста или курсива, обратные апострофы для кода, символы цитирования и т.д.). Генерируй только ясный, чистый текст.\n"
            "5.  **Логическая Завершённость:** Старайся, чтобы твои ответы были полными. Если ответ содержит списки, убедись, что последний пункт завершен. Лучше не начинать новый пункт, если не уверен, что успеешь его закончить в рамках разумной длины ответа.\n"
            "6.  **Читаемость:** Главное — чтобы ответ был понятным, хорошо структурированным и легким для восприятия.\n"
            "7. **Без лишних символов:** Не используй в тексте избыточные скобки, дефисы или другие знаки пунктуации, если они не несут смысловой нагрузки или не требуются правилами грамматики."
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
            "**Оформление творческого ответа (простой структурированный текст):**\n"
            "1.  **Структура и Абзацы:** Для прозы используй абзацы, чтобы четко структурировать повествование. Для стихов сохраняй деление на строфы и правильные переносы строк.\n"
            "2.  **Без специального форматирования:** Пожалуйста, НЕ используй Markdown-разметку (звездочки для жирного текста или курсива и т.п.). Основной акцент на содержании и структуре через абзацы и списки, если они нужны (например, для перечисления идей).\n"
            "3.  **Списки Идей/Вариантов:** Если предлагаешь несколько вариантов (например, заголовков, идей), оформляй их как простой маркированный или нумерованный список.\n"
            "4.  **Диалоги:** Прямую речь в рассказах или сценариях оформляй стандартными литературными способами (например, с использованием тире или кавычек), без Markdown.\n"
            "5.  **Читаемость:** Текст должен легко читаться и быть увлекательным. Структура должна помогать этому.\n"
            "6.  **Завершённость:** Старайся доводить творческие произведения до логического конца в рамках одного ответа, если это подразумевается задачей."
        ),
        "welcome": "Режим 'Творческий Помощник' к вашим услугам! Над какой творческой задачей поработаем?"
    },
}
DEFAULT_AI_MODE_KEY = "universal_ai"

AVAILABLE_TEXT_MODELS = {
    "gemini_2_5_flash_preview": {"name": "💎 G-2.5 Flash Preview", "id": "gemini-2.5-flash-preview-04-17"},
    "gemini_2_0_flash": {"name": "⚡️ G-2.0 Flash", "id": "gemini-2.0-flash"}
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

def smart_truncate(text: str, max_length: int) -> tuple[str, bool]:
    if len(text) <= max_length:
        return text, False
    suffix = "\n\n(...ответ был сокращен)" # Простой текстовый суффикс
    adjusted_max_length = max_length - len(suffix)
    if adjusted_max_length <= 0: return text[:max_length-len("...")] + "...", True
    truncated_text = text[:adjusted_max_length]
    possible_cut_points = []
    for sep in ['\n\n', '. ', '! ', '? ', '\n']:
        pos = truncated_text.rfind(sep)
        if pos != -1:
            actual_pos = pos + (len(sep) -1 if sep.endswith(' ') and len(sep) > 1 else len(sep))
            if actual_pos > 0 : possible_cut_points.append(actual_pos)
    if possible_cut_points:
        cut_at = max(possible_cut_points)
        if cut_at > adjusted_max_length * 0.5:
             return text[:cut_at].strip() + suffix, True
    last_space = truncated_text.rfind(' ')
    if last_space != -1 and last_space > adjusted_max_length * 0.5:
        return text[:last_space].strip() + suffix, True
    return text[:adjusted_max_length].strip() + suffix, True

def get_main_reply_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton("🤖 Режим ИИ"), KeyboardButton("⚙️ Модель ИИ")],
        [KeyboardButton("❓ Помощь")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.setdefault('current_ai_mode', DEFAULT_AI_MODE_KEY)
    context.user_data.setdefault('selected_model_id', DEFAULT_MODEL_ID)
    current_mode_details = get_current_mode_details(context)
    current_model_display_name_text = get_current_model_display_name(context)
    greeting = escape_markdown("Привет! Я многофункциональный ИИ-бот.", version=2)
    mode_name_content = escape_markdown(current_mode_details['name'], version=2)
    mode_line = f"{escape_markdown('Текущий режим: ', version=2)}*{mode_name_content}*"
    model_name_content = escape_markdown(current_model_display_name_text, version=2)
    model_line = f"{escape_markdown('Текущая текстовая модель: ', version=2)}*{model_name_content}*" # Уточнили, что модель текстовая
    you_can = escape_markdown("Вы можете:", version=2)
    action1 = escape_markdown("▫️ Задавать мне вопросы или давать задания.", version=2)
    action2 = "▫️ Сменить режим работы (кнопка или `/mode`)" 
    action3 = "▫️ Выбрать другую текстовую модель ИИ (кнопка или `/model`)" # Уточнили
    action4 = "▫️ Получить помощь (кнопка или `/help`)" # Убрали /imagine
    invitation = escape_markdown("Просто напишите ваш запрос!", version=2)
    text_to_send = (
        f"{greeting}\n\n"
        f"{mode_line}\n"
        f"{model_line}\n\n"
        f"{you_can}\n"
        f"{action1}\n"
        f"{action2}\n"
        f"{action3}\n"
        f"{action4}\n\n" # Убрали action5, так как action4 стал последним перед приглашением
        f"{invitation}"
    )
    try:
        await update.message.reply_text(
            text_to_send, 
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=get_main_reply_keyboard()
        )
        logger.info(f"Start command processed for user {update.message.from_user.id if update.effective_user else 'Unknown'}.")
    except telegram.error.BadRequest as e:
        logger.error(f"Error sending /start message with MarkdownV2: {e}\nText was: {text_to_send}\n{traceback.format_exc()}")
        plain_text_version = ( # Упрощенная версия без /imagine
            f"Привет! Я многофункциональный ИИ-бот.\n\n"
            f"Текущий режим: {current_mode_details['name']}\n"
            f"Текущая текстовая модель: {current_model_display_name_text}\n\n"
            "Вы можете:\n"
            "▫️ Задавать мне вопросы или давать задания.\n"
            "▫️ Сменить режим работы (кнопка или /mode)\n"
            "▫️ Выбрать другую текстовую модель ИИ (кнопка или /model)\n"
            "▫️ Получить помощь (кнопка или /help)\n\n"
            "Просто напишите ваш запрос!"
        )
        await update.message.reply_text(plain_text_version, reply_markup=get_main_reply_keyboard())
        logger.info("Sent /start message as plain text after MarkdownV2 failure, with reply keyboard.")

async def select_mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton(details["name"], callback_data=f"set_mode_{key}")] for key, details in AI_MODES.items()]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('Выберите режим работы для ИИ:', reply_markup=reply_markup)

async def select_model_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton(details["name"], callback_data=f"set_model_{key}")] for key, details in AVAILABLE_TEXT_MODELS.items()]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('Выберите текстовую модель ИИ для использования:', reply_markup=reply_markup) # Уточнили

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    current_mode_details = get_current_mode_details(context)
    current_model_display_name_text = get_current_model_display_name(context)
    mode_name_content = escape_markdown(current_mode_details['name'], version=2)
    model_name_content = escape_markdown(current_model_display_name_text, version=2)
    help_text = (
        f"{escape_markdown('🤖 Это многофункциональный ИИ-бот на базе Gemini от Google для текстовых задач.', version=2)}\n\n" # Уточнили
        f"{escape_markdown('Текущие настройки для текста:', version=2)}\n"
        f"  » {escape_markdown('Режим ИИ: ', version=2)}*{mode_name_content}*\n"
        f"  » {escape_markdown('Текстовая модель ИИ: ', version=2)}*{model_name_content}*\n\n"
        f"{escape_markdown('Основные команды и кнопки:', version=2)}\n"
        f"`/start` {escape_markdown('- это сообщение и основные настройки.', version=2)}\n"
        f"`/mode` {escape_markdown(' или кнопка ', version=2)}`🤖 Режим ИИ` {escape_markdown('- позволяет сменить текущий режим (специализацию) ИИ для текстовых ответов.', version=2)}\n"
        f"`/model` {escape_markdown(' или кнопка ', version=2)}`⚙️ Модель ИИ` {escape_markdown('- позволяет выбрать одну из доступных текстовых моделей Gemini.', version=2)}\n"
        # Убрали /imagine
        f"`/help` {escape_markdown(' или кнопка ', version=2)}`❓ Помощь` {escape_markdown('- это сообщение помощи.', version=2)}\n\n"
        f"{escape_markdown('После выбора режима и модели просто отправьте свой вопрос или задание боту.', version=2)}\n\n"
        f"{escape_markdown('Подсказка: вы можете скрыть/показать клавиатуру с кнопками с помощью иконки клавиатуры в вашем клиенте Telegram.', version=2)}"
    )
    try:
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=get_main_reply_keyboard())
    except telegram.error.BadRequest as e:
        logger.error(f"Error sending /help message with MarkdownV2: {e}\nText was: {help_text}\n{traceback.format_exc()}")
        plain_help_text = ( # Упрощенная версия без /imagine
             "Это ИИ-бот для текстовых задач.\n"
             f"Режим: {current_mode_details['name']}, Текстовая модель: {current_model_display_name_text}\n"
             "Команды: /start, /mode, /model, /help. Используйте кнопки ниже."
        )
        await update.message.reply_text(plain_help_text, reply_markup=get_main_reply_keyboard())

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    message_to_edit = query.message 
    new_text = ""
    plain_text_fallback = ""
    if data.startswith("set_mode_"):
        mode_key = data.split("set_mode_")[1]
        if mode_key in AI_MODES:
            context.user_data['current_ai_mode'] = mode_key
            mode_details = AI_MODES[mode_key]
            escaped_mode_name = escape_markdown(mode_details['name'], version=2)
            escaped_welcome_message = escape_markdown(mode_details['welcome'], version=2)
            new_text = f"Режим изменен на: *{escaped_mode_name}*.\n{escaped_welcome_message}"
            plain_text_fallback = f"Режим изменен на: {mode_details['name']}.\n{mode_details['welcome']}"
            logger.info(f"User {query.from_user.id} changed AI mode to {mode_key}")
        else:
            new_text = escape_markdown("Ошибка: Такой режим не найден.", version=2)
            plain_text_fallback = "Ошибка: Такой режим не найден."
    elif data.startswith("set_model_"):
        model_key_in_dict = data.split("set_model_")[1]
        if model_key_in_dict in AVAILABLE_TEXT_MODELS:
            selected_model_info = AVAILABLE_TEXT_MODELS[model_key_in_dict]
            context.user_data['selected_model_id'] = selected_model_info["id"]
            escaped_model_name = escape_markdown(selected_model_info['name'], version=2)
            new_text = f"Модель изменена на: *{escaped_model_name}*."
            plain_text_fallback = f"Модель изменена на: {selected_model_info['name']}."
            logger.info(f"User {query.from_user.id} changed AI model to {selected_model_info['id']}")
        else:
            new_text = escape_markdown("Ошибка: Такая модель не найдена.", version=2)
            plain_text_fallback = "Ошибка: Такая модель не найдена."
    if new_text:
        try:
            await message_to_edit.edit_text(text=new_text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=message_to_edit.reply_markup)
        except telegram.error.BadRequest as e:
            logger.warning(f"Failed to edit message with MarkdownV2 in button_callback: {e}. Sending plain text. Text was: {new_text}")
            await message_to_edit.edit_text(text=plain_text_fallback, reply_markup=message_to_edit.reply_markup)

# --- УДАЛЯЕМ ФУНКЦИЮ imagine_command ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    user_id = update.effective_user.id if update.effective_user else "UnknownUser"
    logger.info(f"Received message from {user_id}: '{user_message}'")

    current_mode_details = get_current_mode_details(context)
    system_prompt = current_mode_details["prompt"]
    selected_model_id = get_current_model_id(context)

    if user_message.lower() == "/help": # Позволяем /help обрабатываться через CommandHandler
        # Если CommandHandler для /help не сработает первым, этот if может быть нужен.
        # Но лучше полагаться на CommandHandler. Оставим для совместимости или уберем, если CommandHandler всегда первый.
        # await help_command(update, context) 
        return # Если /help, то дальше не идем в этом обработчике

    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        logger.debug(f"Sent 'typing' action to chat {update.effective_chat.id}")
    except Exception as e_typing:
        logger.warning(f"Could not send 'typing' action: {e_typing}")

    try:
        active_gemini_model = genai.GenerativeModel(selected_model_id)
        logger.info(f"Using text model: {selected_model_id} for user {user_id}")
        
        generation_config = genai.types.GenerationConfig(
            max_output_tokens=MAX_OUTPUT_TOKENS_GEMINI,
            temperature=0.75
        )
        model_welcome_text = "Я готов помочь."
        chat_history = [
            {"role": "user", "parts": [system_prompt]},
            {"role": "model", "parts": [model_welcome_text]}
        ]
        chat = active_gemini_model.start_chat(history=chat_history)
        response_gen = await chat.send_message_async(user_message, generation_config=generation_config)

        reply_text = response_gen.text
        
        if not reply_text or not reply_text.strip():
            candidates = getattr(response_gen, 'candidates', [])
            finish_reason = "N/A"
            if candidates and len(candidates) > 0 and hasattr(candidates[0], 'finish_reason'):
                finish_reason_val = candidates[0].finish_reason
                finish_reason = getattr(finish_reason_val, 'name', str(finish_reason_val))
            logger.warning(f"Gemini returned empty text. Model: {selected_model_id}, User msg: '{user_message}'. Finish_reason: {finish_reason}")
            reply_text = "ИИ не смог сформировать ответ или он был отфильтрован. Попробуйте переформулировать запрос."
        
        reply_text_for_sending, was_truncated = smart_truncate(reply_text, MAX_MESSAGE_LENGTH_TELEGRAM)
        
        await update.message.reply_text(reply_text_for_sending) # Отправляем простой текст
        logger.info(f"Sent Gemini response as plain text (model: {selected_model_id}, length: {len(reply_text_for_sending)}). Truncated: {was_truncated}")

    except Exception as e:
        logger.error(f"Error during Gemini text interaction or message handling: {str(e)}\n{traceback.format_exc()}")
        current_model_name_raw = get_current_model_display_name(context)
        escaped_display_name = escape_markdown(current_model_name_raw, version=2)
        error_message_text_md = (
            f"Ой, что-то пошло не так при обращении к ИИ-модели (*{escaped_display_name}*)\\. "
            "Это может быть временный сбой на сервере ИИ\\. \n\n"
            "Пожалуйста, попробуйте **отправить ваш запрос еще раз** через несколько секунд\\. \n\n"
            "Если ошибка не исчезнет, можно также попробовать сменить режим (команда `/mode` или кнопка `🤖 Режим ИИ`) "
            "или модель ИИ (команда `/model` или кнопка `⚙️ Модель ИИ`)\\."
        )
        plain_error_text = (
            f"Ой, что-то пошло не так при обращении к ИИ-модели ({current_model_name_raw}). "
            "Это может быть временный сбой на сервере ИИ.\n\n"
            "Пожалуйста, попробуйте отправить ваш запрос еще раз через несколько секунд.\n\n"
            "Если ошибка не исчезнет, можно также попробовать сменить режим (команда /mode или кнопка 'Режим ИИ') "
            "или модель ИИ (команда /model или кнопка 'Модель ИИ')."
        )
        try:
            await update.message.reply_text(error_message_text_md, parse_mode=ParseMode.MARKDOWN_V2)
        except telegram.error.BadRequest:
            logger.warning("Failed to send MarkdownV2 formatted error message, sending plain text.")
            await update.message.reply_text(plain_error_text)
        except Exception as e_send_error:
            logger.error(f"Failed to send error message to user: {e_send_error}")

async def set_bot_commands(application: Application):
    commands = [
        BotCommand("start", "🚀 Перезапуск / Настройки"),
        BotCommand("mode", "🧠 Сменить режим ИИ"),
        BotCommand("model", "⚙️ Выбрать текстовую модель ИИ"),
        # Убрали /imagine
        BotCommand("help", "ℹ️ Помощь"),
    ]
    try:
        await application.bot.set_my_commands(commands)
        logger.info("Bot commands set successfully.")
    except Exception as e:
        logger.error(f"Failed to set bot commands: {e}")

async def main():
    if "ВАШ_ТЕЛЕГРАМ_ТОКЕН" in TOKEN or not TOKEN or len(TOKEN.split(":")[0]) < 8 : # Более общая проверка формата токена
        logger.critical("CRITICAL: TELEGRAM_TOKEN is not set correctly or uses a placeholder. Please set your actual token.")
        return
    if "ВАШ_GEMINI_API_КЛЮЧ" in GEMINI_API_KEY or not GEMINI_API_KEY or len(GEMINI_API_KEY) < 30:
        logger.critical("CRITICAL: GEMINI_API_KEY is not set correctly or uses a placeholder. Please set your actual key.")
        return
        
    application = Application.builder().token(TOKEN).build()

    try:
        await set_bot_commands(application)
    except Exception as e_set_commands:
        logger.warning(f"Could not set bot commands: {e_set_commands}")

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("mode", select_mode_command))
    application.add_handler(CommandHandler("model", select_model_command))
    # Убрали CommandHandler("imagine", imagine_command)
    application.add_handler(CommandHandler("help", help_command))

    application.add_handler(MessageHandler(filters.Text(["🤖 Режим ИИ"]), select_mode_command))
    application.add_handler(MessageHandler(filters.Text(["⚙️ Модель ИИ"]), select_model_command))
    application.add_handler(MessageHandler(filters.Text(["❓ Помощь"]), help_command))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button_callback))

    logger.info("Starting bot with UI enhancements and plain text AI responses...") # Убрали Image Generation из лога
    await application.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
