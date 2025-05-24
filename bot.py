# -*- coding: utf-8 -*-

import asyncio
import logging
import traceback
import os
import json
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Callable
from functools import partial

# --- Библиотеки ---
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
# #############################################################################

class AppConfig:
    """Централизованная конфигурация для всего приложения."""
    TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_TOKEN", "8185454402:AAEgJLaBSaUSyP9Z_zv76Fn0PtEwltAqga0")
    PAYMENT_PROVIDER_TOKEN: str = os.getenv("PAYMENT_PROVIDER_TOKEN", "390540012:LIVE:70602")
    ADMIN_ID: int = int(os.getenv("ADMIN_ID", "489230152"))

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

API_KEYS_PROVIDER = {
    "CUSTOM_GEMINI_PRO_API_KEY": CONFIG.CUSTOM_GEMINI_PRO_API_KEY,
    "CUSTOM_GROK_3_API_KEY": CONFIG.CUSTOM_GROK_3_API_KEY,
    "CUSTOM_GPT4O_MINI_API_KEY": CONFIG.CUSTOM_GPT4O_MINI_API_KEY,
}

AI_MODES = {
    "universal_ai_basic": {"name": "Универсальный", "prompt": "Ты — Gemini...", "welcome": "Активирован агент 'Универсальный'."},
    "gemini_pro_custom_mode": {"name": "Продвинутый", "prompt": "Ты — Gemini 2.5 Pro...", "welcome": "Активирован агент 'Продвинутый'."},
    "creative_helper": {"name": "Творческий", "prompt": "Ты — Gemini, креативный ИИ-партнёр...", "welcome": "Агент 'Творческий' к вашим услугам!"},
    "analyst": {"name": "Аналитик", "prompt": "Ты — ИИ-аналитик на базе Gemini...", "welcome": "Агент 'Аналитик' активирован."},
    "joker": {"name": "Шутник", "prompt": "Ты — ИИ с чувством юмора...", "welcome": "Агент 'Шутник' включен! 😄"},
}

AVAILABLE_TEXT_MODELS = {
    "google_gemini_2_0_flash": {"name": "Gemini 2.0", "id": "gemini-2.0-flash", "api_type": "google_genai", "is_limited": True, "limit_if_no_subscription": 72, "subscription_daily_limit": 150},
    "custom_api_gemini_2_5_pro": {"name": "Gemini Pro", "id": "gemini-2.5-pro-preview-03-25", "api_type": "custom_http", "endpoint": CONFIG.CUSTOM_GEMINI_PRO_ENDPOINT, "api_key_var_name": "CUSTOM_GEMINI_PRO_API_KEY", "is_limited": True, "limit_if_no_subscription": 0, "subscription_daily_limit": 25},
    "custom_api_grok_3": {"name": "Grok 3", "id": "grok-3-beta", "api_type": "custom_http", "endpoint": CONFIG.CUSTOM_GROK_3_ENDPOINT, "api_key_var_name": "CUSTOM_GROK_3_API_KEY", "is_limited": True, "limit_if_no_subscription": 3, "subscription_daily_limit": 25},
    "custom_api_gpt_4o_mini": {"name": "GPT-4o mini", "id": "gpt-4o-mini", "api_type": "custom_http", "endpoint": CONFIG.CUSTOM_GPT4O_MINI_ENDPOINT, "api_key_var_name": "CUSTOM_GPT4O_MINI_API_KEY", "is_limited": True, "limit_if_no_subscription": 3, "subscription_daily_limit": 25},
}


# #############################################################################
# --- 2. ДОМЕННЫЕ МОДЕЛИ (DATA CLASSES) ---
# #############################################################################

class Subscription(BaseModel):
    level: str
    valid_until: datetime

class User(BaseModel):
    id: int
    first_name: str
    username: Optional[str] = None
    current_ai_mode_key: str = CONFIG.DEFAULT_AI_MODE_KEY
    selected_model_key: str = CONFIG.DEFAULT_MODEL_KEY
    claimed_news_bonus: bool = False
    news_bonus_uses_left: int = 0
    subscription: Optional[Subscription] = None
    daily_usage: Dict[str, int] = Field(default_factory=dict)
    usage_last_reset_date: str = ""
    current_menu: str = "main" # Новое поле для отслеживания меню

    def has_active_pro_subscription(self) -> bool:
        if not self.subscription: return False
        aware_now = datetime.now(self.subscription.valid_until.tzinfo or timezone.utc)
        return self.subscription.valid_until >= aware_now


# #############################################################################
# --- 3. СЕРВИСЫ И РЕПОЗИТОРИИ (INFRASTRUCTURE) ---
# #############################################################################

class FirestoreRepository:
    _db: FirestoreClient
    _USERS_COLLECTION = "users_v3"

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
        if not doc.exists: return None
        data = doc.to_dict()
        if data.get('subscription') and isinstance(data['subscription'].get('valid_until'), str):
             data['subscription']['valid_until'] = datetime.fromisoformat(data['subscription']['valid_until'])
        return User(id=user_id, **data)

    async def save_user(self, user: User):
        doc_ref = self._db.collection(self._USERS_COLLECTION).document(str(user.id))
        user_dict = user.model_dump(exclude={'id'})
        if user.subscription:
            user_dict["subscription"]["valid_until"] = user.subscription.valid_until.isoformat()
        await asyncio.to_thread(doc_ref.set, user_dict, merge=True)

class AbstractAIService(BaseModel, arbitrary_types_allowed=True):
    model_config: Dict[str, Any]
    async def generate_response(self, system_prompt: str, user_prompt: str) -> str: raise NotImplementedError

class GoogleGenAIService(AbstractAIService):
    async def generate_response(self, system_prompt: str, user_prompt: str) -> str:
        try:
            model = genai.GenerativeModel(self.model_config["id"], generation_config={"max_output_tokens": CONFIG.MAX_OUTPUT_TOKENS})
            response = await asyncio.to_thread(model.generate_content, f"{system_prompt}\n\n{user_prompt}")
            return response.text.strip() or "Ответ пуст."
        except Exception as e:
            logger.error(f"GoogleGenAIService error: {e}", exc_info=True)
            return f"Ошибка API ({type(e).__name__}) при обращении к {self.model_config['name']}."

class CustomHttpAIService(AbstractAIService):
    api_keys: Dict[str, str]
    async def generate_response(self, system_prompt: str, user_prompt: str) -> str:
        cfg = self.model_config
        api_key = self.api_keys.get(cfg.get("api_key_var_name"))
        if not api_key: return f"Ошибка: ключ API '{cfg.get('api_key_var_name')}' не найден."
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {"model": cfg["id"], "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}], "max_tokens": CONFIG.MAX_OUTPUT_TOKENS}
        try:
            response = await asyncio.to_thread(requests.post, cfg["endpoint"], headers=headers, json=payload, timeout=45)
            response.raise_for_status()
            data = response.json()
            return data.get("text") or data.get("output", {}).get("text") or str(data)
        except requests.RequestException as e:
            logger.error(f"CustomHttpAIService HTTP error: {e}", exc_info=True)
            return f"Сетевая ошибка API ({type(e).__name__}) для {cfg['name']}."

def get_ai_service(model_key: str, api_keys_provider: Dict[str, str]) -> Optional[AbstractAIService]:
    model_cfg = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_cfg: return None
    if model_cfg.get("api_type") == "google_genai":
        return GoogleGenAIService(model_config=model_cfg)
    elif model_cfg.get("api_type") == "custom_http":
        return CustomHttpAIService(model_config=model_cfg, api_keys=api_keys_provider)
    return None


# #############################################################################
# --- 4. ФУНКЦИИ-ПРЕДСТАВЛЕНИЯ И КЛАВИАТУРЫ (VIEWS & KEYBOARDS) ---
# #############################################################################

def get_menu_keyboard(user: User) -> ReplyKeyboardMarkup:
    """Генерирует клавиатуру в зависимости от текущего меню пользователя."""
    menu_type = user.current_menu
    # Эта функция может быть расширена для разных меню, пока используем одну
    if menu_type == "agents":
        keyboard = [[KeyboardButton(m["name"])] for m in AI_MODES.values()]
        keyboard.append([KeyboardButton("⬅️ Назад в Главное меню")])
    elif menu_type == "models":
        keyboard = [[KeyboardButton(m["name"])] for m in AVAILABLE_TEXT_MODELS.values()]
        keyboard.append([KeyboardButton("⬅️ Назад в Главное меню")])
    else: # Главное меню по умолчанию
        keyboard = [
            [KeyboardButton("🤖 Агенты ИИ"), KeyboardButton("⚙️ Модели ИИ")],
            [KeyboardButton("📊 Лимиты"), KeyboardButton("💎 Подписка")],
            [KeyboardButton("🎁 Бонус"), KeyboardButton("❓ Помощь")]
        ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def format_welcome_message(user: User) -> str:
    mode_name = AI_MODES.get(user.current_ai_mode_key, {}).get("name")
    model_name = AVAILABLE_TEXT_MODELS.get(user.selected_model_key, {}).get("name")
    return f"👋 Привет, {user.first_name}!\n\n🤖 Текущий агент: <b>{mode_name}</b>\n⚙️ Активная модель: <b>{model_name}</b>"

def format_limit_exceeded_message(model_name: str, new_model_name: str) -> str:
    return f"🚫 Достигнут дневной лимит для модели «{model_name}».\nВаша модель была автоматически изменена на «{new_model_name}»."

def format_limits_info(user: User) -> str:
    is_profi = user.has_active_pro_subscription()
    sub_status = "Профи" if is_profi else "Бесплатный"
    parts = [f"<b>📊 Ваши лимиты</b> (Статус: <b>{sub_status}</b>)\n"]
    for key, cfg in AVAILABLE_TEXT_MODELS.items():
        if cfg.get("is_limited"):
            usage = user.daily_usage.get(key, 0)
            limit = cfg["subscription_daily_limit"] if is_profi else cfg["limit_if_no_subscription"]
            bonus_info = f" (включая <b>{user.news_bonus_uses_left}</b> бонусных)" if key == CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY and not is_profi and user.claimed_news_bonus else ""
            parts.append(f"▫️ {cfg['name']}: <b>{usage} / {limit}</b>{bonus_info}")
    return "\n".join(parts)


# #############################################################################
# --- 5. ЛОГИКА ПРИЛОЖЕНИЯ (USE CASES) ---
# #############################################################################

def get_or_create_user(user_id: int, from_user: telegram.User) -> User:
    return User(id=user_id, first_name=from_user.first_name, username=from_user.username)

def check_and_reset_daily_limits(user: User) -> User:
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if user.usage_last_reset_date != today_str:
        user.daily_usage = {}
        user.usage_last_reset_date = today_str
        logger.info(f"Daily limits have been reset for user {user.id}")
    return user

def can_user_make_request(user: User) -> bool:
    model_key = user.selected_model_key
    model_cfg = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_cfg or not model_cfg.get("is_limited"): return True
    if model_key == CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY and not user.has_active_pro_subscription() and user.claimed_news_bonus and user.news_bonus_uses_left > 0: return True
    current_usage = user.daily_usage.get(model_key, 0)
    limit = model_cfg["subscription_daily_limit"] if user.has_active_pro_subscription() else model_cfg["limit_if_no_subscription"]
    return current_usage < limit

def increment_usage_counter(user: User) -> User:
    model_key = user.selected_model_key
    if model_key == CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY and not user.has_active_pro_subscription() and user.claimed_news_bonus and user.news_bonus_uses_left > 0:
        user.news_bonus_uses_left -= 1
    else:
        user.daily_usage[model_key] = user.daily_usage.get(model_key, 0) + 1
    return user


# #############################################################################
# --- 6. ОБРАБОТЧИКИ TELEGRAM (PRESENTATION/HANDLERS) ---
# #############################################################################

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, repo: FirestoreRepository):
    tg_user = update.effective_user
    user = await repo.get_user(tg_user.id)
    if not user:
        user = get_or_create_user(tg_user.id, tg_user)
    
    user = check_and_reset_daily_limits(user)
    user.current_menu = "main" # Приводим в главное меню
    await repo.save_user(user)

    reply_text = format_welcome_message(user)
    await update.message.reply_text(reply_text, reply_markup=get_menu_keyboard(user), parse_mode=ParseMode.HTML)

async def menu_and_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, repo: FirestoreRepository):
    """Единый обработчик для кнопок меню и текстовых запросов."""
    user_id = update.effective_user.id
    text = update.message.text
    
    user = await repo.get_user(user_id)
    if not user:
        await start_handler(update, context, repo=repo)
        return
    user = check_and_reset_daily_limits(user)

    # --- Диспетчер кнопок меню ---
    # Сопоставляем текст кнопки с функцией-обработчиком
    
    # Сначала проверяем навигационные кнопки
    if text == "⬅️ Назад в Главное меню":
        user.current_menu = "main"
        await repo.save_user(user)
        await update.message.reply_text("📋 Главное меню", reply_markup=get_menu_keyboard(user))
        return

    # Затем проверяем основные кнопки
    if text == "🤖 Агенты ИИ":
        user.current_menu = "agents"
        await repo.save_user(user)
        await update.message.reply_text("Выберите агента:", reply_markup=get_menu_keyboard(user))
        return
        
    if text == "⚙️ Модели ИИ":
        user.current_menu = "models"
        await repo.save_user(user)
        await update.message.reply_text("Выберите модель:", reply_markup=get_menu_keyboard(user))
        return

    if text == "📊 Лимиты":
        reply_text = format_limits_info(user)
        await update.message.reply_text(reply_text, parse_mode=ParseMode.HTML, reply_markup=get_menu_keyboard(user))
        return

    if text == "💎 Подписка":
        is_profi = user.has_active_pro_subscription()
        sub_status = f"активна до {user.subscription.valid_until.strftime('%d.%m.%Y')}" if is_profi else "не активна."
        reply_text = f"Ваша подписка Profi {sub_status}\n\nЗдесь будет информация о преимуществах и кнопка 'Купить'."
        await update.message.reply_text(reply_text, parse_mode=ParseMode.HTML, reply_markup=get_menu_keyboard(user))
        return
        
    if text == "🎁 Бонус":
        if user.claimed_news_bonus:
            reply_text = f"Вы уже получали бонус. Осталось {user.news_bonus_uses_left} использований."
        else:
            # Здесь логика проверки подписки на канал
            reply_text = f'Подпишитесь на <a href="{CONFIG.NEWS_CHANNEL_LINK}">канал</a> и нажмите эту кнопку еще раз для получения бонуса!'
        await update.message.reply_text(reply_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True, reply_markup=get_menu_keyboard(user))
        return

    if text == "❓ Помощь":
        reply_text = "Здесь будет раздел помощи по боту."
        await update.message.reply_text(reply_text, reply_markup=get_menu_keyboard(user))
        return
        
    # Проверка, является ли текст названием агента или модели
    # Это упрощенный вариант, в идеале нужны callback-кнопки
    if user.current_menu == "agents":
        for key, mode in AI_MODES.items():
            if text == mode["name"]:
                user.current_ai_mode_key = key
                user.current_menu = "main"
                await repo.save_user(user)
                await update.message.reply_text(f"✅ Агент изменен на: <b>{mode['name']}</b>", parse_mode=ParseMode.HTML, reply_markup=get_menu_keyboard(user))
                return

    if user.current_menu == "models":
        for key, model in AVAILABLE_TEXT_MODELS.items():
            if text == model["name"]:
                user.selected_model_key = key
                user.current_menu = "main"
                await repo.save_user(user)
                await update.message.reply_text(f"✅ Модель изменена на: <b>{model['name']}</b>", parse_mode=ParseMode.HTML, reply_markup=get_menu_keyboard(user))
                return

    # --- Если это не кнопка меню, то это запрос к ИИ ---
    if not can_user_make_request(user):
        model_name = AVAILABLE_TEXT_MODELS[user.selected_model_key]["name"]
        user.selected_model_key = CONFIG.DEFAULT_MODEL_KEY
        new_model_name = AVAILABLE_TEXT_MODELS[CONFIG.DEFAULT_MODEL_KEY]["name"]
        await repo.save_user(user)
        reply_text = format_limit_exceeded_message(model_name, new_model_name)
        await update.message.reply_text(reply_text, reply_markup=get_menu_keyboard(user))
        return

    await context.bot.send_chat_action(chat_id=user_id, action=ChatAction.TYPING)
    ai_service = get_ai_service(user.selected_model_key, API_KEYS_PROVIDER)
    if not ai_service:
        await update.message.reply_text("Ошибка: не удалось инициализировать AI сервис.", reply_markup=get_menu_keyboard(user))
        return
        
    mode_prompt = AI_MODES[user.current_ai_mode_key]["prompt"]
    ai_response = await ai_service.generate_response(mode_prompt, text)
    
    user = increment_usage_counter(user)
    await repo.save_user(user)

    await update.message.reply_text(ai_response[:CONFIG.MAX_MESSAGE_LENGTH_TELEGRAM], reply_markup=get_menu_keyboard(user))

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception while handling an update:", exc_info=context.error)
    # ... (логика уведомления админа и пользователя)

# #############################################################################
# --- 7. ТОЧКА ВХОДА И СБОРКА ПРИЛОЖЕНИЯ ---
# #############################################################################

async def main():
    try:
        if CONFIG.GOOGLE_GEMINI_API_KEY and "YOUR_" not in CONFIG.GOOGLE_GEMINI_API_KEY:
            genai.configure(api_key=CONFIG.GOOGLE_GEMINI_API_KEY)
        repo = FirestoreRepository(CONFIG.FIREBASE_CERT_PATH, CONFIG.FIREBASE_CREDENTIALS_JSON_STR)
    except Exception as e:
        logger.critical(f"Could not initialize dependencies: {e}. Bot cannot start.")
        return
        
    app = Application.builder().token(CONFIG.TELEGRAM_TOKEN).build()

    # РЕГИСТРИРУЕМ ТОЛЬКО ДВА ОБРАБОТЧИКА
    app.add_handler(CommandHandler("start", partial(start_handler, repo=repo)))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, partial(menu_and_text_handler, repo=repo)))
    app.add_error_handler(error_handler)
    
    bot_commands = [
        BotCommand("start", "🚀 Перезапуск / Главное меню"),
    ]
    await app.bot.set_my_commands(bot_commands)

    logger.info("Bot is starting...")
    await app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    asyncio.run(main())
