# -*- coding: utf-8 -*-

import asyncio
import logging
import traceback
import os
import json
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple, List, Union
from functools import partial

# --- Библиотеки ---
# Стараемся импортировать все внешние зависимости вверху
import telegram
from telegram import (
    Update, BotCommand, LabeledPrice,
    ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, PreCheckoutQueryHandler
)
from telegram.constants import ParseMode, ChatAction

import google.generativeai as genai
import google.api_core.exceptions
import requests
import firebase_admin
from firebase_admin import credentials, firestore
from pydantic import BaseModel, Field
from google.cloud.firestore_v1.client import Client as FirestoreClient

# --- Настройка логирования ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


# #############################################################################
# --- 1. КОНФИГУРАЦИЯ И КОНСТАНТЫ ---
# Все "магические" строки и числа собраны в одном месте для удобства управления.
# #############################################################################

class AppConfig:
    """Централизованная конфигурация для всего приложения."""
    TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_TOKEN", "8185454402:AAEgJLaBSaUSyP9Z_zv76Fn0PtEwltAqga0")
    PAYMENT_PROVIDER_TOKEN: str = os.getenv("PAYMENT_PROVIDER_TOKEN", "390540012:LIVE:70602")
    ADMIN_ID: int = int(os.getenv("ADMIN_ID", "1222"))

    # Ключи API
    GOOGLE_GEMINI_API_KEY: str = os.getenv("GOOGLE_GEMINI_API_KEY", "AIzaSyCdDMpgLJyz6aYdwT9q4sbBk7sHVID4BTI")
    CUSTOM_GEMINI_PRO_API_KEY: str = os.getenv("CUSTOM_GEMINI_PRO_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P")
    CUSTOM_GROK_3_API_KEY: str = os.getenv("CUSTOM_GROK_3_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P")
    CUSTOM_GPT4O_MINI_API_KEY: str = os.getenv("CUSTOM_GPT4O_MINI_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P")
    
    # Эндпоинты
    CUSTOM_GEMINI_PRO_ENDPOINT: str = "https://api.gen-api.ru/api/v1/networks/gemini-2-5-pro"
    CUSTOM_GROK_3_ENDPOINT: str = "https://api.gen-api.ru/api/v1/networks/grok-3"
    CUSTOM_GPT4O_MINI_ENDPOINT: str = "https://api.gen-api.ru/api/v1/networks/gpt-4o-mini"

    # Firebase
    FIREBASE_CERT_PATH: str = "gemioracle-firebase-adminsdk-fbsvc-8f89d5b941.json"
    FIREBASE_CREDENTIALS_JSON_STR: str | None = os.getenv("FIREBASE_CREDENTIALS")

    # Технические параметры
    MAX_OUTPUT_TOKENS: int = 2048
    MAX_MESSAGE_LENGTH_TELEGRAM: int = 4000
    MIN_AI_REQUEST_LENGTH: int = 4

    # Настройки подписки и бонусов
    PRO_SUBSCRIPTION_LEVEL_KEY: str = "profi_access_v1"
    NEWS_CHANNEL_USERNAME: str = "@timextech"
    NEWS_CHANNEL_LINK: str = "https://t.me/timextech"
    NEWS_CHANNEL_BONUS_MODEL_KEY: str = "custom_api_gemini_2_5_pro"
    NEWS_CHANNEL_BONUS_GENERATIONS: int = 1

    # Значения по умолчанию
    DEFAULT_AI_MODE_KEY: str = "universal_ai_basic"
    DEFAULT_MODEL_KEY: str = "google_gemini_2_0_flash"

CONFIG = AppConfig()

# Ключи API собраны в словарь для удобной передачи в сервисы
API_KEYS_PROVIDER = {
    "CUSTOM_GEMINI_PRO_API_KEY": CONFIG.CUSTOM_GEMINI_PRO_API_KEY,
    "CUSTOM_GROK_3_API_KEY": CONFIG.CUSTOM_GROK_3_API_KEY,
    "CUSTOM_GPT4O_MINI_API_KEY": CONFIG.CUSTOM_GPT4O_MINI_API_KEY,
}

# Определения режимов и моделей
AI_MODES = {
    "universal_ai_basic": {"name": "Универсальный", "prompt": "Ты — Gemini...", "welcome": "Активирован агент 'Универсальный'."},
    "gemini_pro_custom_mode": {"name": "Продвинутый", "prompt": "Ты — Gemini 2.5 Pro...", "welcome": "Активирован агент 'Продвинутый'."},
    "creative_helper": {"name": "Творческий", "prompt": "Ты — Gemini, креативный ИИ-партнёр...", "welcome": "Агент 'Творческий' к вашим услугам!"},
    "analyst": {"name": "Аналитик", "prompt": "Ты — ИИ-аналитик на базе Gemini...", "welcome": "Агент 'Аналитик' активирован."},
    "joker": {"name": "Шутник", "prompt": "Ты — ИИ с чувством юмора...", "welcome": "Агент 'Шутник' включен! 😄"},
}

AVAILABLE_TEXT_MODELS = {
    "google_gemini_2_0_flash": {
        "name": "Gemini 2.0", "id": "gemini-2.0-flash", "api_type": "google_genai", "is_limited": True, 
        "limit_if_no_subscription": 72, "subscription_daily_limit": 150
    },
    "custom_api_gemini_2_5_pro": {
        "name": "Gemini Pro", "id": "gemini-2.5-pro-preview-03-25", "api_type": "custom_http",
        "endpoint": CONFIG.CUSTOM_GEMINI_PRO_ENDPOINT, "api_key_var_name": "CUSTOM_GEMINI_PRO_API_KEY", "is_limited": True, 
        "limit_if_no_subscription": 0, "subscription_daily_limit": 25
    },
    "custom_api_grok_3": {
        "name": "Grok 3", "id": "grok-3-beta", "api_type": "custom_http",
        "endpoint": CONFIG.CUSTOM_GROK_3_ENDPOINT, "api_key_var_name": "CUSTOM_GROK_3_API_KEY", "is_limited": True, 
        "limit_if_no_subscription": 3, "subscription_daily_limit": 25
    },
    "custom_api_gpt_4o_mini": {
        "name": "GPT-4o mini", "id": "gpt-4o-mini", "api_type": "custom_http",
        "endpoint": CONFIG.CUSTOM_GPT4O_MINI_ENDPOINT, "api_key_var_name": "CUSTOM_GPT4O_MINI_API_KEY", "is_limited": True, 
        "limit_if_no_subscription": 3, "subscription_daily_limit": 25
    },
}


# #############################################################################
# --- 2. ДОМЕННЫЕ МОДЕЛИ (DATA CLASSES) ---
# Описываем "сущности" нашего приложения. Это чертежи для наших данных.
# Используем Pydantic для валидации и удобства работы.
# #############################################################################

class Subscription(BaseModel):
    """Модель подписки пользователя."""
    level: str
    valid_until: datetime

class User(BaseModel):
    """Модель пользователя со всеми его настройками и данными."""
    id: int
    first_name: str
    username: Optional[str] = None
    
    current_ai_mode_key: str = CONFIG.DEFAULT_AI_MODE_KEY
    selected_model_key: str = CONFIG.DEFAULT_MODEL_KEY
    
    claimed_news_bonus: bool = False
    news_bonus_uses_left: int = 0
    
    subscription: Optional[Subscription] = None
    
    # Ключ: model_key, Значение: количество использований за сегодня (дата неявно подразумевается)
    daily_usage: Dict[str, int] = Field(default_factory=dict)
    
    # Поле для хранения даты последнего сброса лимитов, чтобы не хранить ее для каждой модели
    usage_last_reset_date: str = ""

    def has_active_pro_subscription(self) -> bool:
        """Проверяет, активна ли у пользователя Pro подписка."""
        if not self.subscription:
            return False
        # Убедимся, что сравниваем с aware datetime
        aware_now = datetime.now(self.subscription.valid_until.tzinfo or timezone.utc)
        return self.subscription.valid_until >= aware_now


# #############################################################################
# --- 3. СЕРВИСЫ И РЕПОЗИТОРИИ (INFRASTRUCTURE) ---
# Здесь находится код для взаимодействия с внешним миром: база данных, AI API.
# #############################################################################

# --- Репозиторий для работы с данными ---

class FirestoreRepository:
    """
    Единый класс для всех операций с Firestore.
    Инкапсулирует логику работы с коллекциями users и bot_data.
    """
    _db: FirestoreClient
    _USERS_COLLECTION = "users_v3"  # Новая версия для новой структуры
    _BOT_DATA_COLLECTION = "bot_data_v3"
    _BOT_DATA_DOC = "data"

    def __init__(self, cert_path: str, creds_json_str: Optional[str] = None):
        try:
            if not firebase_admin._apps:
                cred_obj = credentials.Certificate(json.loads(creds_json_str)) if creds_json_str else credentials.Certificate(cert_path)
                firebase_admin.initialize_app(cred_obj)
            self._db = firestore.client()
            logger.info("FirestoreRepository initialized successfully.")
        except Exception as e:
            logger.critical(f"Failed to initialize FirestoreRepository: {e}", exc_info=True)
            raise

    async def get_user(self, user_id: int) -> Optional[User]:
        doc_ref = self._db.collection(self._USERS_COLLECTION).document(str(user_id))
        doc = await asyncio.to_thread(doc_ref.get)
        if not doc.exists:
            return None
        
        data = doc.to_dict()
        # Преобразование данных из Firestore в нашу Pydantic модель
        if data.get('subscription') and isinstance(data['subscription'].get('valid_until'), str):
             data['subscription']['valid_until'] = datetime.fromisoformat(data['subscription']['valid_until'])
        
        return User(id=user_id, **data)

    async def save_user(self, user: User):
        doc_ref = self._db.collection(self._USERS_COLLECTION).document(str(user.id))
        user_dict = user.model_dump(exclude={'id'})  # Используем model_dump
        if user.subscription:
            user_dict["subscription"]["valid_until"] = user.subscription.valid_until.isoformat()
        await asyncio.to_thread(doc_ref.set, user_dict, merge=True)

# --- AI Сервисы ---

class AbstractAIService(BaseModel, arbitrary_types_allowed=True):
    """Абстрактный базовый класс для всех AI сервисов."""
    model_config: Dict[str, Any]
    
    async def generate_response(self, system_prompt: str, user_prompt: str) -> str:
        raise NotImplementedError

class GoogleGenAIService(AbstractAIService):
    """Сервис для работы с Google Gemini через их библиотеку."""
    async def generate_response(self, system_prompt: str, user_prompt: str) -> str:
        try:
            model_id = self.model_config["id"]
            model = genai.GenerativeModel(model_id, generation_config={"max_output_tokens": CONFIG.MAX_OUTPUT_TOKENS})
            response = await asyncio.to_thread(model.generate_content, f"{system_prompt}\n\n{user_prompt}")
            return response.text.strip() or "Ответ пуст."
        except Exception as e:
            logger.error(f"GoogleGenAIService error for model {self.model_config['id']}: {e}", exc_info=True)
            return f"Ошибка API ({type(e).__name__}) при обращении к {self.model_config['name']}."

class CustomHttpAIService(AbstractAIService):
    """Сервис для работы с любым AI через кастомный HTTP-запрос."""
    api_keys: Dict[str, str]
    
    async def generate_response(self, system_prompt: str, user_prompt: str) -> str:
        cfg = self.model_config
        key_name = cfg.get("api_key_var_name")
        api_key = self.api_keys.get(key_name)
        if not api_key:
            return f"Ошибка: ключ API '{key_name}' не найден."

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": cfg["id"],
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            "max_tokens": CONFIG.MAX_OUTPUT_TOKENS,
        }
        
        try:
            async with requests.Session() as session:
                response = await asyncio.to_thread(
                    session.post, cfg["endpoint"], headers=headers, json=payload, timeout=45
                )
                response.raise_for_status()
                data = response.json()
                # Упрощенная логика извлечения ответа
                return data.get("text") or data.get("output", {}).get("text") or str(data)
        except requests.RequestException as e:
            logger.error(f"CustomHttpAIService HTTP error for model {cfg['id']}: {e}", exc_info=True)
            return f"Сетевая ошибка API ({type(e).__name__}) для {cfg['name']}."

def get_ai_service(model_key: str, api_keys_provider: Dict[str, str]) -> Optional[AbstractAIService]:
    """Фабрика для создания нужного AI сервиса."""
    model_cfg = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_cfg:
        return None
    
    api_type = model_cfg.get("api_type")
    if api_type == "google_genai":
        return GoogleGenAIService(model_config=model_cfg)
    elif api_type == "custom_http":
        return CustomHttpAIService(model_config=model_cfg, api_keys=api_keys_provider)
    return None


# #############################################################################
# --- 4. ФУНКЦИИ-ПРЕДСТАВЛЕНИЯ (VIEWS) ---
# Эти функции ничего не вычисляют. Они только форматируют данные в красивые
# сообщения для пользователя.
# #############################################################################

def format_welcome_message(user: User) -> str:
    """Форматирует приветственное сообщение."""
    mode_name = AI_MODES.get(user.current_ai_mode_key, {}).get("name")
    model_name = AVAILABLE_TEXT_MODELS.get(user.selected_model_key, {}).get("name")
    return (
        f"👋 Привет, {user.first_name}!\n\n"
        f"🤖 Текущий агент: <b>{mode_name}</b>\n"
        f"⚙️ Активная модель: <b>{model_name}</b>\n\n"
        "Я готов к вашим запросам!"
    )

def format_limit_exceeded_message(model_name: str, new_model_name: str) -> str:
    """Форматирует сообщение о превышении лимита."""
    return (
        f"🚫 Достигнут дневной лимит для модели «{model_name}».\n"
        f"Ваша модель была автоматически изменена на «{new_model_name}».\n\n"
        "Попробуйте снова завтра или рассмотрите возможность оформления Profi подписки для увеличения лимитов."
    )

def format_limits_info(user: User) -> str:
    """Форматирует информацию о лимитах пользователя."""
    is_profi = user.has_active_pro_subscription()
    sub_status = "Профи" if is_profi else "Бесплатный"
    parts = [f"<b>📊 Ваши лимиты</b> (Статус: <b>{sub_status}</b>)\n"]

    for key, cfg in AVAILABLE_TEXT_MODELS.items():
        if cfg.get("is_limited"):
            usage = user.daily_usage.get(key, 0)
            limit = cfg["subscription_daily_limit"] if is_profi else cfg["limit_if_no_subscription"]
            
            bonus_info = ""
            if key == CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY and not is_profi and user.claimed_news_bonus:
                bonus_info = f" (включая <b>{user.news_bonus_uses_left}</b> бонусных)"
            
            parts.append(f"▫️ {cfg['name']}: <b>{usage} / {limit}</b>{bonus_info}")
    
    return "\n".join(parts)


# #############################################################################
# --- 5. ЛОГИКА ПРИЛОЖЕНИЯ (USE CASES) ---
# Чистые функции, которые содержат бизнес-логику. Они не зависят от Telegram.
# #############################################################################

def get_user_or_create(user_id: int, from_user: telegram.User) -> User:
    """Вспомогательная функция для создания нового пользователя."""
    return User(
        id=user_id,
        first_name=from_user.first_name,
        username=from_user.username
    )

def check_and_reset_daily_limits(user: User) -> User:
    """Проверяет, наступил ли новый день, и сбрасывает лимиты, если нужно."""
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if user.usage_last_reset_date != today_str:
        user.daily_usage = {}
        user.usage_last_reset_date = today_str
        logger.info(f"Daily limits have been reset for user {user.id}")
    return user

def can_user_make_request(user: User, model_key: str) -> bool:
    """
    Проверяет, может ли пользователь сделать запрос. Возвращает True или False.
    Не отправляет сообщений и не меняет состояние.
    """
    model_cfg = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_cfg or not model_cfg.get("is_limited"):
        return True

    # Приоритет бонуса
    if (
        model_key == CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY
        and not user.has_active_pro_subscription()
        and user.claimed_news_bonus
        and user.news_bonus_uses_left > 0
    ):
        return True

    # Проверка основного лимита
    current_usage = user.daily_usage.get(model_key, 0)
    limit = model_cfg["subscription_daily_limit"] if user.has_active_pro_subscription() else model_cfg["limit_if_no_subscription"]
    
    return current_usage < limit

def increment_usage_counter(user: User, model_key: str) -> User:
    """Увеличивает счетчик использования. Мутирует и возвращает объект user."""
    # Обработка бонуса
    if (
        model_key == CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY
        and not user.has_active_pro_subscription()
        and user.claimed_news_bonus
        and user.news_bonus_uses_left > 0
    ):
        user.news_bonus_uses_left -= 1
        logger.info(f"User {user.id} consumed a news bonus. Left: {user.news_bonus_uses_left}")
        return user

    # Инкремент основного счетчика
    user.daily_usage[model_key] = user.daily_usage.get(model_key, 0) + 1
    logger.info(f"Incremented daily count for user {user.id}, model {model_key} to {user.daily_usage[model_key]}.")
    return user


# #############################################################################
# --- 6. ОБРАБОТЧИКИ TELEGRAM (PRESENTATION/HANDLERS) ---
# Функции, которые непосредственно работают с `update` и `context` от Telegram.
# Они "тонкие", их задача - вызвать логику и показать результат.
# #############################################################################

def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Возвращает стандартную клавиатуру главного меню."""
    keyboard = [
        [KeyboardButton("🤖 Агенты ИИ"), KeyboardButton("⚙️ Модели ИИ")],
        [KeyboardButton("📊 Лимиты"), KeyboardButton("💎 Подписка")],
        [KeyboardButton("🎁 Бонус"), KeyboardButton("❓ Помощь")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, repo: FirestoreRepository):
    """Обработчик команды /start."""
    tg_user = update.effective_user
    user = await repo.get_user(tg_user.id)
    if not user:
        user = get_user_or_create(tg_user.id, tg_user)
        logger.info(f"New user created: {user.id} ({user.first_name})")
    
    user = check_and_reset_daily_limits(user) # Проверяем и сбрасываем лимиты при старте
    await repo.save_user(user)

    reply_text = format_welcome_message(user)
    await update.message.reply_text(
        reply_text, 
        reply_markup=get_main_menu_keyboard(), 
        parse_mode=ParseMode.HTML
    )

async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, repo: FirestoreRepository):
    """Основной обработчик текстовых сообщений (запросов к ИИ)."""
    user_id = update.effective_user.id
    user_text = update.message.text
    
    # 1. Получаем и подготавливаем пользователя
    user = await repo.get_user(user_id)
    if not user:
        # Если пользователь как-то "потерялся", отправляем его на /start
        await start_handler(update, context, repo)
        return

    user = check_and_reset_daily_limits(user)
    
    # 2. Проверяем, не кнопка ли это меню
    all_menu_buttons = {item["text"] for menu in AI_MODES.values() for item in menu.get("items", [])} # Упрощено
    if user_text in ["🤖 Агенты ИИ", "⚙️ Модели ИИ", "📊 Лимиты", "💎 Подписка", "🎁 Бонус", "❓ Помощь"]:
        # Здесь должна быть логика обработки кнопок, для простоты пока пропустим
        await update.message.reply_text(f"Вы нажали на кнопку меню: {user_text}. Эта функция в разработке.", reply_markup=get_main_menu_keyboard())
        return

    # 3. Проверяем лимиты
    model_key = user.selected_model_key
    if not can_user_make_request(user, model_key):
        model_name = AVAILABLE_TEXT_MODELS[model_key]["name"]
        user.selected_model_key = CONFIG.DEFAULT_MODEL_KEY
        new_model_name = AVAILABLE_TEXT_MODELS[CONFIG.DEFAULT_MODEL_KEY]["name"]
        
        await repo.save_user(user)
        reply_text = format_limit_exceeded_message(model_name, new_model_name)
        await update.message.reply_text(reply_text, reply_markup=get_main_menu_keyboard())
        return

    # 4. Выполняем запрос к ИИ
    await context.bot.send_chat_action(chat_id=user_id, action=ChatAction.TYPING)
    
    ai_service = get_ai_service(model_key, API_KEYS_PROVIDER)
    if not ai_service:
        await update.message.reply_text("Ошибка: не удалось инициализировать AI сервис.", reply_markup=get_main_menu_keyboard())
        return
        
    mode_prompt = AI_MODES[user.current_ai_mode_key]["prompt"]
    ai_response = await ai_service.generate_response(mode_prompt, user_text)

    # 5. Обновляем счетчики и сохраняем пользователя
    user = increment_usage_counter(user, model_key)
    await repo.save_user(user)

    # 6. Отправляем ответ
    truncated_response, _ = (ai_response[:CONFIG.MAX_MESSAGE_LENGTH_TELEGRAM-30] + '...', True) if len(ai_response) > CONFIG.MAX_MESSAGE_LENGTH_TELEGRAM else (ai_response, False)
    await update.message.reply_text(truncated_response, reply_markup=get_main_menu_keyboard())

async def limits_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, repo: FirestoreRepository):
    """Обработчик команды /limits."""
    user = await repo.get_user(update.effective_user.id)
    if not user:
        await start_handler(update, context, repo)
        return
        
    user = check_and_reset_daily_limits(user) # Обновляем на случай, если это первый запрос за день
    await repo.save_user(user)

    reply_text = format_limits_info(user)
    await update.message.reply_text(reply_text, parse_mode=ParseMode.HTML, reply_markup=get_main_menu_keyboard())

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Логирует ошибки и отправляет сообщение пользователю/админу."""
    logger.error("Exception while handling an update:", exc_info=context.error)
    tb_string = "".join(traceback.format_exception(None, context.error, context.error.__traceback__))

    # Уведомление пользователя
    if isinstance(update, Update) and update.effective_chat:
        error_message = "Произошла внутренняя ошибка. Пожалуйста, попробуйте позже или введите /start."
        await context.bot.send_message(update.effective_chat.id, error_message, reply_markup=get_main_menu_keyboard())

    # Уведомление админа
    admin_message = f"🤖 Ошибка в боте!\n\nUser: {update.effective_user.id if isinstance(update, Update) else 'N/A'}\n\nError: {context.error}\n\nTraceback:\n{tb_string[:3500]}"
    if CONFIG.ADMIN_ID:
        await context.bot.send_message(CONFIG.ADMIN_ID, admin_message)


# #############################################################################
# --- 7. ТОЧКА ВХОДА И СБОРКА ПРИЛОЖЕНИЯ ---
# Здесь мы "собираем" нашего бота: инициализируем сервисы и регистрируем
# обработчики, передавая им все необходимые зависимости.
# #############################################################################

async def main():
    """Основная функция для настройки и запуска бота."""
    
    # --- 1. Инициализация зависимостей ---
    try:
        # Конфигурация Google GenAI
        if CONFIG.GOOGLE_GEMINI_API_KEY and "YOUR_" not in CONFIG.GOOGLE_GEMINI_API_KEY:
            genai.configure(api_key=CONFIG.GOOGLE_GEMINI_API_KEY)
            logger.info("Google GenAI configured.")
        
        # Инициализация репозитория (нашей "базы данных")
        repo = FirestoreRepository(CONFIG.FIREBASE_CERT_PATH, CONFIG.FIREBASE_CREDENTIALS_JSON_STR)
    except Exception as e:
        logger.critical(f"Could not initialize dependencies: {e}. Bot cannot start.")
        return
        
    # --- 2. Сборка приложения Telegram ---
    app = Application.builder().token(CONFIG.TELEGRAM_TOKEN).build()

    # --- 3. Регистрация обработчиков ---
    # Мы "замораживаем" аргумент `repo` для каждого обработчика с помощью `functools.partial`.
    # Теперь каждый вызов, например, `start_handler` будет автоматически получать `repo`.
    
    # Команды
    app.add_handler(CommandHandler("start", partial(start_handler, repo=repo)))
    app.add_handler(CommandHandler("limits", partial(limits_handler, repo=repo)))
    # TODO: Добавить обработчики для остальных команд (/help, /subscribe и т.д.) по аналогии

    # Текстовые сообщения
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, partial(text_message_handler, repo=repo)))

    # Обработчик ошибок
    app.add_error_handler(error_handler)
    
    # Установка команд в меню Telegram
    bot_commands = [
        BotCommand("start", "🚀 Перезапуск / Главное меню"),
        BotCommand("limits", "📊 Показать мои лимиты"),
        # BotCommand("help", "❓ Помощь"), # Добавить, когда будет готов хендлер
    ]
    await app.bot.set_my_commands(bot_commands)

    logger.info("Bot is starting...")
    await app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    # Эта конструкция гарантирует, что `main()` будет вызвана только при прямом запуске файла
    asyncio.run(main())
