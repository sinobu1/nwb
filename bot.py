import telegram
from telegram import (
    ReplyKeyboardMarkup, KeyboardButton, Update,
    BotCommand, InlineKeyboardButton, InlineKeyboardMarkup,
    LabeledPrice
)
from telegram.constants import ParseMode, ChatAction
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, PreCheckoutQueryHandler, CallbackQueryHandler
)
import google.generativeai as genai
import google.api_core.exceptions
import requests # Может понадобиться для API Grok, GPT
import logging
import traceback
import os
import asyncio
import nest_asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple, List
import uuid

# Firebase
import firebase_admin
from firebase_admin import credentials, firestore, initialize_app
from firebase_admin.exceptions import FirebaseError
from google.cloud.firestore_v1.client import Client as FirestoreClient

nest_asyncio.apply()

# --- Глобальная конфигурация логирования ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- КОНСТАНТЫ ---

# Ключи конфигурации
CONFIG_TELEGRAM_TOKEN = "TELEGRAM_TOKEN"
CONFIG_GEMINI_API_KEY = "GOOGLE_GEMINI_API_KEY" # Уже используется
CONFIG_GROK_API_KEY = "CUSTOM_GROK_3_API_KEY" # Новый ключ для Grok
CONFIG_GPT_API_KEY = "CUSTOM_GPT4O_MINI_API_KEY" # Новый ключ для GPT (например, GPT-4o mini)
# Добавьте другие API ключи по мере необходимости

CONFIG_FIREBASE_CRED_PATH = "FIREBASE_CREDENTIALS_PATH"
CONFIG_FIREBASE_DB_URL = "FIREBASE_DATABASE_URL"
CONFIG_ADMIN_USER_ID = "ADMIN_USER_ID"
CONFIG_FREE_DAILY_LIMIT = "FREE_DAILY_LIMIT"
CONFIG_BONUS_CHANNEL_ID = "BONUS_CHANNEL_ID"
CONFIG_BONUS_CHANNEL_LINK = "BONUS_CHANNEL_LINK"
CONFIG_PAYMENT_PROVIDER_TOKEN = "PAYMENT_PROVIDER_TOKEN"
CONFIG_PRICE_AMOUNT_RUB = "PRICE_AMOUNT_RUB"
CONFIG_PRICE_LABEL = "PRICE_LABEL"
CONFIG_PRICE_DESCRIPTION = "PRICE_DESCRIPTION"
CONFIG_CURRENCY = "RUB"

# Названия коллекций Firestore
FIRESTORE_USERS_COLLECTION = "users"
FIRESTORE_PAYMENTS_COLLECTION = "payments"

# Идентификаторы моделей (для хранения в БД и callback_data)
MODEL_GEMINI = "gemini"
MODEL_GROK = "grok"
MODEL_GPT = "gpt"
# Добавьте другие модели

# Тексты для кнопок и сообщений
TEXT_MENU_BUTTON = "📋 Открыть меню"
TEXT_USAGE_BUTTON = "📊 Мои лимиты"
TEXT_SUBSCRIBE_BUTTON = "💎 О подписке"
TEXT_SELECT_AI_BUTTON = "🧠 Выбрать ИИ" # Новая кнопка

# Callback data префиксы
CALLBACK_PREFIX_ACTION = "action:"
CALLBACK_PREFIX_MODEL = "model:" # Новый префикс для выбора модели

# --- ЗАГРУЗКА КОНФИГУРАЦИИ ---
def load_config() -> Dict[str, Any]:
    """Загружает конфигурацию из переменных окружения."""
    default_firebase_creds_path = os.path.join(os.path.dirname(__file__), "firebase_credentials.json")

    config = {
        CONFIG_TELEGRAM_TOKEN: os.getenv(CONFIG_TELEGRAM_TOKEN, "8185454402:AAEgJLaBSaUSyP9Z_zv76Fn0PtEwltAqga0"),
        CONFIG_GEMINI_API_KEY: os.getenv(CONFIG_GEMINI_API_KEY, "AIzaSyCdDMpgLJyz6aYdwT9q4sbBk7sHVID4BTI"),
        CONFIG_GROK_API_KEY: os.getenv(CONFIG_GROK_API_KEY, "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P"), # Загрузка ключа Grok
        CONFIG_GPT_API_KEY: os.getenv(CONFIG_GPT_API_KEY, "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P"),   # Загрузка ключа GPT

        CONFIG_FIREBASE_CRED_PATH: os.getenv(CONFIG_FIREBASE_CRED_PATH, default_firebase_creds_path),
        CONFIG_FIREBASE_DB_URL: os.getenv(CONFIG_FIREBASE_DB_URL, ""),
        CONFIG_ADMIN_USER_ID: int(os.getenv(CONFIG_ADMIN_USER_ID, "0")),
        CONFIG_FREE_DAILY_LIMIT: int(os.getenv(CONFIG_FREE_DAILY_LIMIT, 5)),
        CONFIG_BONUS_CHANNEL_ID: os.getenv(CONFIG_BONUS_CHANNEL_ID, ""),
        CONFIG_BONUS_CHANNEL_LINK: os.getenv(CONFIG_BONUS_CHANNEL_LINK, ""),
        CONFIG_PAYMENT_PROVIDER_TOKEN: os.getenv(CONFIG_PAYMENT_PROVIDER_TOKEN, "390540012:LIVE:70602"),
        CONFIG_PRICE_AMOUNT_RUB: int(os.getenv(CONFIG_PRICE_AMOUNT_RUB, 10000)),
        CONFIG_PRICE_LABEL: os.getenv(CONFIG_PRICE_LABEL, "Подписка на бота"),
        CONFIG_PRICE_DESCRIPTION: os.getenv(CONFIG_PRICE_DESCRIPTION, "Доступ ко всем функциям на 30 дней"),
    }

    if "YOUR_" in config[CONFIG_TELEGRAM_TOKEN] or not config[CONFIG_TELEGRAM_TOKEN]:
        logger.critical(f"{CONFIG_TELEGRAM_TOKEN} не настроен. Завершение работы.")
        raise ValueError(f"{CONFIG_TELEGRAM_TOKEN} не настроен.")
    if "YOUR_" in config[CONFIG_GEMINI_API_KEY] or not config[CONFIG_GEMINI_API_KEY]:
        logger.warning(f"{CONFIG_GEMINI_API_KEY} (Gemini) не настроен или указан неверно.")
    if "YOUR_" in config[CONFIG_GROK_API_KEY] or not config[CONFIG_GROK_API_KEY]:
        logger.warning(f"{CONFIG_GROK_API_KEY} (Grok) не настроен или указан неверно.")
    if "YOUR_" in config[CONFIG_GPT_API_KEY] or not config[CONFIG_GPT_API_KEY]:
        logger.warning(f"{CONFIG_GPT_API_KEY} (GPT) не настроен или указан неверно.")
    return config

CONFIG = load_config()

# --- ИНИЦИАЛИЗАЦИЯ FIREBASE ---
db: Optional[FirestoreClient] = None
def initialize_firebase_app() -> Optional[FirestoreClient]:
    global db
    try:
        cred_path = CONFIG[CONFIG_FIREBASE_CRED_PATH]
        if not os.path.exists(cred_path):
            logger.error(f"Файл Firebase credentials не найден: {cred_path}")
            return None
        cred = credentials.Certificate(cred_path)
        if not firebase_admin._apps:
            firebase_options = {'databaseURL': CONFIG[CONFIG_FIREBASE_DB_URL]} if CONFIG[CONFIG_FIREBASE_DB_URL] else {}
            initialize_app(cred, options=firebase_options)
            logger.info("Firebase приложение инициализировано.")
        else:
            logger.info("Firebase приложение уже было инициализировано.")
        db = firestore.client()
        logger.info("Клиент Firestore получен.")
        return db
    except Exception as e:
        logger.error(f"Ошибка инициализации Firebase: {e}", exc_info=True)
    return None

# --- ИНИЦИАЛИЗАЦИЯ AI СЕРВИСОВ ---
def initialize_ai_services():
    """Конфигурирует API ключи для AI сервисов."""
    # Gemini
    gemini_api_key = CONFIG[CONFIG_GEMINI_API_KEY]
    if gemini_api_key and "YOUR_" not in gemini_api_key and gemini_api_key.startswith("AIzaSy"):
        try:
            genai.configure(api_key=gemini_api_key)
            logger.info("Google Gemini API сконфигурирован.")
        except Exception as e:
            logger.error(f"Ошибка конфигурации Google Gemini API: {e}", exc_info=True)
    else:
        logger.warning(f"{CONFIG_GEMINI_API_KEY} (Gemini) не настроен. Функциональность Gemini будет недоступна.")

    # Grok - здесь может потребоваться инициализация клиента, если есть SDK
    grok_api_key = CONFIG[CONFIG_GROK_API_KEY]
    if grok_api_key and "YOUR_" not in grok_api_key:
        logger.info(f"{CONFIG_GROK_API_KEY} (Grok) ключ найден.")
        # Пример: grok_client = GrokLibrary.Client(api_key=grok_api_key)
    else:
        logger.warning(f"{CONFIG_GROK_API_KEY} (Grok) не настроен. Функциональность Grok будет недоступна.")

    # GPT - здесь может потребоваться инициализация клиента, если есть SDK (например, от OpenAI)
    gpt_api_key = CONFIG[CONFIG_GPT_API_KEY]
    if gpt_api_key and "YOUR_" not in gpt_api_key:
        logger.info(f"{CONFIG_GPT_API_KEY} (GPT) ключ найден.")
        # Пример: from openai import OpenAI; client = OpenAI(api_key=gpt_api_key)
    else:
        logger.warning(f"{CONFIG_GPT_API_KEY} (GPT) не настроен. Функциональность GPT будет недоступна.")


# --- УТИЛИТЫ FIREBASE ---
async def get_user_data(user_id: int) -> Optional[Dict[str, Any]]:
    if not db: return None
    try:
        doc = await asyncio.to_thread(db.collection(FIRESTORE_USERS_COLLECTION).document(str(user_id)).get)
        return doc.to_dict() if doc.exists else None
    except Exception as e:
        logger.error(f"Ошибка получения данных пользователя {user_id}: {e}", exc_info=True)
    return None

async def update_user_data(user_id: int, data: Dict[str, Any], merge: bool = True) -> bool:
    if not db: return False
    try:
        await asyncio.to_thread(db.collection(FIRESTORE_USERS_COLLECTION).document(str(user_id)).set, data, merge=merge)
        # logger.info(f"Данные пользователя {user_id} обновлены: {'(merged)' if merge else data}")
        return True
    except Exception as e:
        logger.error(f"Ошибка обновления данных пользователя {user_id}: {e}", exc_info=True)
    return False

async def check_or_create_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[Dict[str, Any]]:
    if not update.effective_user: return None
    user_id = update.effective_user.id
    user_data = await get_user_data(user_id)

    if not user_data:
        new_user_data = {
            "user_id": user_id,
            "username": update.effective_user.username or "",
            "first_name": update.effective_user.first_name or "",
            "last_name": update.effective_user.last_name or "",
            "registration_date": firestore.SERVER_TIMESTAMP,
            "last_activity_date": firestore.SERVER_TIMESTAMP,
            "requests_today": 0,
            "subscription_until": None,
            "is_bonus_claimed": False,
            "current_model": MODEL_GEMINI # Модель по умолчанию
        }
        if await update_user_data(user_id, new_user_data, merge=False):
            logger.info(f"Создан новый пользователь: {user_id} с моделью по умолчанию {MODEL_GEMINI}")
            return new_user_data
        return None
    else:
        # Обновляем дату последней активности и проверяем наличие current_model
        update_payload = {"last_activity_date": firestore.SERVER_TIMESTAMP}
        if "current_model" not in user_data:
            user_data["current_model"] = MODEL_GEMINI # Устанавливаем модель по умолчанию, если отсутствует
            update_payload["current_model"] = MODEL_GEMINI
        await update_user_data(user_id, update_payload)
        return user_data
    return user_data


# --- УТИЛИТЫ AI API ---
async def generate_text_with_gemini(prompt: str) -> Optional[str]:
    if not genai._configured:
        logger.warning("Gemini API не сконфигурирован для генерации.")
        return "Сервис Gemini временно недоступен."
    try:
        model = genai.GenerativeModel('gemini-1.5-flash-latest')
        response = await asyncio.to_thread(model.generate_content, prompt)
        return response.text
    except Exception as e:
        logger.error(f"Ошибка Google Gemini API: {e}", exc_info=True)
    return "К сожалению, не удалось получить ответ от Gemini."

async def generate_text_with_grok(prompt: str, api_key: str) -> Optional[str]:
    logger.info(f"Попытка генерации с Grok (ключ {'присутствует' if api_key and 'YOUR_' not in api_key else 'ОТСУТСТВУЕТ/НЕВЕРЕН'})")
    if not api_key or "YOUR_" in api_key:
        return "Сервис Grok не настроен или API ключ не указан."
    # --- НАЧАЛО РЕАЛИЗАЦИИ ДЛЯ GROK API ---
    # Вам нужно будет заменить этот блок на реальный вызов API Grok
    # Пример с использованием requests (если у Grok REST API):
    # headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    # payload = {"prompt": prompt, "model": "grok-model-name"} # Уточните параметры
    # try:
    #     response = await asyncio.to_thread(requests.post, "URL_GROK_API_ENDPOINT", json=payload, headers=headers)
    #     response.raise_for_status() # Проверка на HTTP ошибки
    #     return response.json().get("generated_text") # Адаптируйте под структуру ответа Grok
    # except requests.RequestException as e:
    #     logger.error(f"Ошибка API Grok: {e}", exc_info=True)
    #     return "Ошибка при обращении к Grok."
    # except Exception as e:
    #     logger.error(f"Непредвиденная ошибка с Grok: {e}", exc_info=True)
    #     return "Не удалось получить ответ от Grok."
    await asyncio.sleep(1) # Имитация работы API
    return f"Ответ от Grok на запрос: '{prompt}' (Это заглушка. Реализуйте вызов API!)"
    # --- КОНЕЦ РЕАЛИЗАЦИИ ДЛЯ GROK API ---

async def generate_text_with_gpt(prompt: str, api_key: str) -> Optional[str]:
    logger.info(f"Попытка генерации с GPT (ключ {'присутствует' if api_key and 'YOUR_' not in api_key else 'ОТСУТСТВУЕТ/НЕВЕРЕН'})")
    if not api_key or "YOUR_" in api_key:
        return "Сервис GPT не настроен или API ключ не указан."
    # --- НАЧАЛО РЕАЛИЗАЦИИ ДЛЯ GPT API (например, OpenAI) ---
    # Пример с использованием библиотеки openai:
    # from openai import OpenAI, AsyncOpenAI # AsyncOpenAI для асинхронных вызовов
    # try:
    #     client = AsyncOpenAI(api_key=api_key) # или OpenAI для синхронных + asyncio.to_thread
    #     chat_completion = await client.chat.completions.create(
    #         messages=[{"role": "user", "content": prompt}],
    #         model="gpt-4o-mini", # или другая модель
    #     )
    #     return chat_completion.choices[0].message.content
    # except Exception as e: # Уточните типы исключений OpenAI API
    #     logger.error(f"Ошибка OpenAI API: {e}", exc_info=True)
    #     return "Ошибка при обращении к GPT."
    await asyncio.sleep(1) # Имитация работы API
    return f"Ответ от GPT на запрос: '{prompt}' (Это заглушка. Реализуйте вызов API!)"
    # --- КОНЕЦ РЕАЛИЗАЦИИ ДЛЯ GPT API ---

async def generate_text_with_selected_model(
    model_name: str,
    prompt: str,
    context: ContextTypes.DEFAULT_TYPE
) -> Optional[str]:
    """Диспетчер для вызова соответствующей AI модели."""
    if model_name == MODEL_GEMINI:
        return await generate_text_with_gemini(prompt)
    elif model_name == MODEL_GROK:
        return await generate_text_with_grok(prompt, CONFIG[CONFIG_GROK_API_KEY])
    elif model_name == MODEL_GPT:
        return await generate_text_with_gpt(prompt, CONFIG[CONFIG_GPT_API_KEY])
    # Добавьте другие модели здесь
    else:
        logger.warning(f"Попытка использовать неизвестную модель: {model_name}")
        return "Выбрана неизвестная модель ИИ."

# --- УТИЛИТЫ TELEGRAM ---
def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(TEXT_USAGE_BUTTON, callback_data=f"{CALLBACK_PREFIX_ACTION}usage")],
        [InlineKeyboardButton(TEXT_SUBSCRIBE_BUTTON, callback_data=f"{CALLBACK_PREFIX_ACTION}subscribe_info")],
        [InlineKeyboardButton(TEXT_SELECT_AI_BUTTON, callback_data=f"{CALLBACK_PREFIX_ACTION}select_ai")] # Новая кнопка
    ]
    return InlineKeyboardMarkup(keyboard)

def get_model_selection_keyboard(current_model: Optional[str] = None) -> InlineKeyboardMarkup:
    """Возвращает клавиатуру для выбора AI модели."""
    buttons = []
    models_available = {
        MODEL_GEMINI: "🚀 Gemini",
        MODEL_GROK: "👽 Grok",
        MODEL_GPT: "💡 GPT-4o mini" # Пример
        # Добавьте другие модели
    }
    for model_id, model_text in models_available.items():
        text = f"✅ {model_text}" if model_id == current_model else model_text
        buttons.append([InlineKeyboardButton(text, callback_data=f"{CALLBACK_PREFIX_MODEL}{model_id}")])
    
    buttons.append([InlineKeyboardButton("⬅️ Назад в меню", callback_data=f"{CALLBACK_PREFIX_ACTION}main_menu")])
    return InlineKeyboardMarkup(buttons)


async def send_typing_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

# --- ОБРАБОТЧИКИ КОМАНД ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user: return
    await check_or_create_user(update, context)
    logger.info(f"User {user.id} ({user.username}) started.")
    reply_text = f"👋 Привет, {user.first_name}!\nЯ твой бот-помощник с доступом к разным ИИ. Выбери модель в меню."
    await update.message.reply_html(reply_text, reply_markup=get_main_menu_keyboard())

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user: return
    await check_or_create_user(update, context)
    logger.info(f"User {user.id} requested menu.")
    await update.message.reply_html("📋 **Главное меню:**", reply_markup=get_main_menu_keyboard())

async def usage_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user: return
    user_data = await check_or_create_user(update, context)
    if not user_data:
        await update.message.reply_text("Не удалось получить данные. Попробуйте позже.")
        return

    requests_today = user_data.get("requests_today", 0)
    daily_limit = CONFIG[CONFIG_FREE_DAILY_LIMIT]
    subscription_until_ts = user_data.get("subscription_until")
    current_model_display = user_data.get("current_model", "не выбрана").capitalize()
    subscription_status = "не активна"
    limit_text = f"Использовано сегодня: {requests_today} из {daily_limit} (бесплатных)."

    if subscription_until_ts:
        # ... (логика отображения статуса подписки, как и раньше) ...
        if isinstance(subscription_until_ts, datetime):
            subscription_until_dt = subscription_until_ts.replace(tzinfo=timezone.utc)
        else:
            try: subscription_until_dt = datetime.fromtimestamp(subscription_until_ts.seconds, tz=timezone.utc)
            except AttributeError: subscription_until_dt = None

        if subscription_until_dt and subscription_until_dt > datetime.now(timezone.utc):
            subscription_status = f"активна до {subscription_until_dt.strftime('%d.%m.%Y %H:%M')} UTC"
            limit_text = f"У вас активная подписка! Лимиты не действуют."
    
    reply_text = (
        f"📊 **Ваши лимиты и настройки:**\n\n"
        f"Текущая ИИ модель: **{current_model_display}**\n"
        f"{limit_text}\n"
        f"Подписка: {subscription_status}"
    )
    # Если сообщение пришло от callback query, используем edit_message_text
    if update.callback_query:
        await update.callback_query.edit_message_text(reply_text, parse_mode=ParseMode.HTML, reply_markup=get_main_menu_keyboard())
    elif update.message:
        await update.message.reply_html(reply_text)


async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (код без изменений, как и раньше) ...
    user = update.effective_user
    if not user: return
    await check_or_create_user(update, context)
    price_label = CONFIG[CONFIG_PRICE_LABEL]
    price_description = CONFIG[CONFIG_PRICE_DESCRIPTION]
    price_amount = CONFIG[CONFIG_PRICE_AMOUNT_RUB]
    currency = CONFIG[CONFIG_CURRENCY]
    reply_text = (
        f"💎 **Информация о подписке:**\n\n"
        f"Получите неограниченный доступ ко всем функциям бота!\n"
        f"Стоимость: {price_amount / 100:.2f} {currency} на 30 дней.\n\n"
        f"Нажмите кнопку ниже, чтобы оформить подписку."
    )
    payment_button = InlineKeyboardButton(
        f"💳 Оплатить {price_amount / 100:.2f} {currency}",
        callback_data=f"{CALLBACK_PREFIX_ACTION}pay_subscription"
    )
    reply_markup = InlineKeyboardMarkup([[payment_button]])

    if update.callback_query:
        await update.callback_query.edit_message_text(reply_text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
    elif update.message:
        await update.message.reply_html(reply_text, reply_markup=reply_markup)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (код без изменений, как и раньше) ...
    user = update.effective_user
    if not user: return
    await check_or_create_user(update, context)
    help_text = (
        "❓ **Справка по боту:**\n\n"
        "/start - Перезапуск и главное меню\n"
        "/menu - Открыть главное меню\n"
        "/usage - Узнать текущие лимиты и активную ИИ\n"
        "/subscribe - Информация о подписке\n"
        "/help - Эта справка\n\n"
        "Используйте кнопку '🧠 Выбрать ИИ' в меню для смены активной нейросети.\n"
        "Если у вас возникли проблемы, обратитесь к администратору."
    )
    await update.message.reply_html(help_text)

# --- ОБРАБОТЧИК ТЕКСТОВЫХ СООБЩЕНИЙ ---
async def message_handler_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not update.message or not update.message.text: return

    user_input = update.message.text
    logger.info(f"User {user.id} ({user.username}) sent text: '{user_input}'")

    user_data = await check_or_create_user(update, context)
    if not user_data:
        await update.message.reply_text("Ошибка профиля. Попробуйте позже.")
        return

    # Проверка лимитов (как и раньше)
    requests_today = user_data.get("requests_today", 0)
    daily_limit = CONFIG[CONFIG_FREE_DAILY_LIMIT]
    subscription_until_ts = user_data.get("subscription_until")
    is_subscribed = False
    if subscription_until_ts:
        # ... (логика проверки подписки, как и раньше) ...
        if isinstance(subscription_until_ts, datetime):
            subscription_until_dt = subscription_until_ts.replace(tzinfo=timezone.utc)
        else:
            try: subscription_until_dt = datetime.fromtimestamp(subscription_until_ts.seconds, tz=timezone.utc)
            except AttributeError: subscription_until_dt = None
        if subscription_until_dt and subscription_until_dt > datetime.now(timezone.utc):
            is_subscribed = True

    if not is_subscribed and requests_today >= daily_limit:
        await update.message.reply_text(
            "Достигнут дневной лимит. Оформите подписку (/subscribe) или попробуйте завтра."
        )
        return

    await send_typing_action(update, context)

    current_model = user_data.get("current_model", MODEL_GEMINI) # Получаем текущую модель
    prompt = f"Ответь на следующий вопрос пользователя, используя знания модели {current_model.capitalize()}: {user_input}"
    
    bot_response = await generate_text_with_selected_model(current_model, prompt, context)

    if bot_response:
        await update.message.reply_text(bot_response)
        if not is_subscribed:
            await update_user_data(user.id, {"requests_today": requests_today + 1})
    else:
        await update.message.reply_text("Не удалось сгенерировать ответ. Попробуйте другую модель или позже.")


# --- ОБРАБОТЧИК CALLBACK QUERIES ---
async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    if not user or not query.data: return

    logger.info(f"User {user.id} pressed button: {query.data}")
    user_data = await check_or_create_user(update, context) # Получаем/создаем данные пользователя
    if not user_data:
        await query.edit_message_text("Произошла ошибка с вашим профилем.")
        return

    # Обработка выбора модели
    if query.data.startswith(CALLBACK_PREFIX_MODEL):
        selected_model = query.data.split(CALLBACK_PREFIX_MODEL, 1)[1]
        if selected_model in [MODEL_GEMINI, MODEL_GROK, MODEL_GPT]: # Добавьте сюда другие модели
            if await update_user_data(user.id, {"current_model": selected_model}):
                await query.edit_message_text(
                    f"✅ Выбрана модель: {selected_model.capitalize()}",
                    reply_markup=get_model_selection_keyboard(selected_model) # Обновляем клавиатуру с отметкой
                )
            else:
                await query.edit_message_text("Не удалось сохранить выбор модели.")
        else:
            await query.edit_message_text("Неизвестная модель.")

    # Обработка других действий
    elif query.data.startswith(CALLBACK_PREFIX_ACTION):
        action = query.data.split(CALLBACK_PREFIX_ACTION, 1)[1]

        if action == "usage":
            # Передаем `update` напрямую, т.к. usage_command теперь может обрабатывать callback_query
            await usage_command(update, context)
        elif action == "subscribe_info":
            await subscribe_command(update, context)
        elif action == "pay_subscription":
            await send_payment_invoice(update, context)
        elif action == "select_ai":
            current_model_for_keyboard = user_data.get("current_model")
            await query.edit_message_text(
                "🧠 **Выберите нейросеть для использования:**",
                reply_markup=get_model_selection_keyboard(current_model_for_keyboard)
            )
        elif action == "main_menu":
             await query.edit_message_text("📋 **Главное меню:**", reply_markup=get_main_menu_keyboard())
        else:
            await query.edit_message_text(f"Действие '{action}' в разработке.")
    else:
        await query.edit_message_text("Неизвестное действие.")


# --- ПЛАТЕЖИ ---
async def send_payment_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (код без изменений, как и раньше) ...
    chat_id = update.effective_chat.id if update.effective_chat else update.effective_user.id
    user_id = update.effective_user.id
    title = CONFIG[CONFIG_PRICE_LABEL]
    description = CONFIG[CONFIG_PRICE_DESCRIPTION]
    payload = f"sub_{user_id}_{int(datetime.now().timestamp())}"
    provider_token = CONFIG[CONFIG_PAYMENT_PROVIDER_TOKEN]
    currency = CONFIG[CONFIG_CURRENCY]
    price = CONFIG[CONFIG_PRICE_AMOUNT_RUB]

    if not provider_token or "YOUR_" in provider_token:
        logger.error("Токен провайдера платежей не настроен!")
        msg_target = update.callback_query.message if update.callback_query else update.message
        if msg_target: await msg_target.reply_text("Оплата временно недоступна.")
        return
    prices = [LabeledPrice(label=title, amount=price)]
    try:
        await context.bot.send_invoice(chat_id, title, description, payload, provider_token, currency, prices)
        logger.info(f"Инвойс отправлен {user_id}, payload: {payload}")
    except telegram.error.TelegramError as e:
        logger.error(f"Ошибка отправки инвойса {user_id}: {e}")
        msg_target = update.callback_query.message if update.callback_query else update.message
        if msg_target: await msg_target.reply_text("Не удалось создать счет. Попробуйте позже.")


async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (код без изменений, как и раньше) ...
    query = update.pre_checkout_query
    if not query: return
    logger.info(f"PreCheckoutQuery от {query.from_user.id}, payload: {query.invoice_payload}")
    await query.answer(ok=True)

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (код без изменений, как и раньше) ...
    message = update.message
    if not message or not message.successful_payment: return
    user_id = message.from_user.id
    payment_info = message.successful_payment
    logger.info(f"Успешный платеж от {user_id}: {payment_info.total_amount / 100} {payment_info.currency}")
    subscription_end_date = datetime.now(timezone.utc) + timedelta(days=30)
    user_update_data = {
        "subscription_until": subscription_end_date,
        "last_payment_date": firestore.SERVER_TIMESTAMP,
        "requests_today": 0
    }
    if await update_user_data(user_id, user_update_data):
        await message.reply_text(f"🎉 Спасибо! Подписка активна до {subscription_end_date.strftime('%d.%m.%Y %H:%M')} UTC.")
    else:
        await message.reply_text("Спасибо! Ошибка активации подписки. Свяжитесь с администратором.")
    # Сохранение платежа в коллекцию payments (как и раньше)
    if db:
        try:
            payment_record = { "user_id": user_id, "amount": payment_info.total_amount, "currency": payment_info.currency, "payload": payment_info.invoice_payload, "payment_date": firestore.SERVER_TIMESTAMP, "telegram_payment_charge_id": payment_info.telegram_payment_charge_id, "provider_payment_charge_id": payment_info.provider_payment_charge_id }
            await asyncio.to_thread(db.collection(FIRESTORE_PAYMENTS_COLLECTION).document(payment_info.telegram_payment_charge_id).set, payment_record)
        except Exception as e: logger.error(f"Ошибка сохранения платежа в Firestore: {e}", exc_info=True)


# --- ОБРАБОТЧИК ОШИБОК ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (код без изменений, как и раньше, но можно добавить специфичные сообщения для AI ошибок) ...
    logger.error(msg="Исключение при обработке обновления:", exc_info=context.error)
    tb_string = "".join(traceback.format_exception(None, context.error, context.error.__traceback__))
    logger.error(f"Traceback:\n{tb_string}")

    user_message = "😕 Ой, что-то пошло не так. Пожалуйста, попробуйте позже."
    if isinstance(context.error, google.api_core.exceptions.GoogleAPIError):
        user_message = "Проблема с Gemini. Попробуйте другой запрос или позже."
    # Добавьте обработку ошибок для Grok/GPT API, если у них есть свои классы исключений
    
    # Отправка сообщения пользователю
    effective_message = None
    if isinstance(update, Update):
        if update.effective_message: effective_message = update.effective_message
        elif update.callback_query and update.callback_query.message: effective_message = update.callback_query.message
    
    if effective_message:
        try: await effective_message.reply_text(user_message)
        except Exception as e: logger.error(f"Не удалось отправить сообщение об ошибке пользователю: {e}")

    # Уведомление администратора (как и раньше)
    admin_user_id = CONFIG[CONFIG_ADMIN_USER_ID]
    if admin_user_id and admin_user_id != 0:
        try:
            error_details = f"Ошибка: {type(context.error).__name__}: {context.error}\n"
            if isinstance(update, Update) and update.effective_user:
                error_details += f"User: {update.effective_user.id} (@{update.effective_user.username})\n"
            # ... (остальная часть формирования сообщения для админа)
            await context.bot.send_message(chat_id=admin_user_id, text=(error_details + tb_string)[:4090])
        except Exception as e_admin: logger.error(f"Не удалось отправить уведомление администратору: {e_admin}")


# --- ОСНОВНАЯ ФУНКЦИЯ ---
async def main() -> None:
    global db
    db = initialize_firebase_app()
    # if not db: return # Решите, критична ли БД для работы

    initialize_ai_services() # Инициализация всех AI сервисов

    application = Application.builder().token(CONFIG[CONFIG_TELEGRAM_TOKEN]).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CommandHandler("usage", usage_command))
    application.add_handler(CommandHandler("subscribe", subscribe_command))
    application.add_handler(CommandHandler("help", help_command))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler_text))
    application.add_handler(CallbackQueryHandler(button_callback_handler))

    application.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))

    application.add_error_handler(error_handler)

    bot_commands = [
        BotCommand("start", "🚀 Перезапуск / Главное меню"),
        BotCommand("menu", "📋 Открыть меню"),
        BotCommand("usage", "📊 Лимиты и активная ИИ"),
        BotCommand("subscribe", "💎 Информация о подписке"),
        BotCommand("help", "❓ Справка по боту"),
    ]
    try:
        await application.bot.set_my_commands(bot_commands)
        logger.info("Команды бота установлены.")
    except Exception as e:
        logger.error(f"Не удалось установить команды бота: {e}")

    logger.info("Запуск бота...")
    await application.run_polling(allowed_updates=Update.ALL_TYPES, timeout=30)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except ValueError as e: logger.critical(f"Ошибка запуска (конфигурация): {e}")
    except KeyboardInterrupt: logger.info("Бот остановлен.")
    except Exception as e: logger.critical(f"Критическая ошибка при запуске: {e}", exc_info=True)

