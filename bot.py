import telegram
from telegram import (
    ReplyKeyboardMarkup, KeyboardButton, Update,
    BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
)
from telegram.constants import ParseMode, ChatAction
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, PreCheckoutQueryHandler, CallbackQueryHandler
)
import google.generativeai as genai
import google.api_core.exceptions
import requests
import logging
import traceback
import os
import asyncio
import nest_asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple, List

nest_asyncio.apply()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- КОНФИГУРАЦИЯ ---
class AppConfig:
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8185454402:AAEgJLaBSaUSyP9Z_zv76Fn0PtEwltAqga0")
    GOOGLE_GEMINI_API_KEY = os.getenv("GOOGLE_GEMINI_API_KEY", "AIzaSyCdDMpgLJyz6aYdwT9q4sbBk7sHVID4BTI")
    CUSTOM_GEMINI_PRO_API_KEY = os.getenv("CUSTOM_GEMINI_PRO_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P")
    CUSTOM_GEMINI_PRO_ENDPOINT = os.getenv("CUSTOM_GEMINI_PRO_ENDPOINT", "https://api.gen-api.ru/api/v1/networks/gemini-2-5-pro")
    CUSTOM_GROK_3_API_KEY = os.getenv("CUSTOM_GROK_3_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P")
    CUSTOM_GPT4O_MINI_API_KEY = os.getenv("CUSTOM_GPT4O_MINI_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P")
    PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "390540012:LIVE:70602")
    ADMIN_ID = int(os.getenv("ADMIN_ID", "489230152"))
    FIREBASE_CREDENTIALS_JSON_STR = os.getenv("FIREBASE_CREDENTIALS")
    FIREBASE_CERT_PATH = "gemioracle-firebase-adminsdk-fbsvc-8f89d5b941.json"

    MAX_OUTPUT_TOKENS_GEMINI_LIB = 2048
    MAX_MESSAGE_LENGTH_TELEGRAM = 4000
    MIN_AI_REQUEST_LENGTH = 4

    DEFAULT_FREE_REQUESTS_GOOGLE_FLASH_DAILY = 72
    DEFAULT_FREE_REQUESTS_GEMINI_2_5_FLASH_PREVIEW_DAILY = 48

    NEWS_CHANNEL_USERNAME = "@timextech"
    NEWS_CHANNEL_LINK = "https://t.me/timextech"
    NEWS_CHANNEL_BONUS_MODEL_KEY = "custom_api_gemini_2_5_pro"
    NEWS_CHANNEL_BONUS_GENERATIONS = 1

    DEFAULT_AI_MODE_KEY = "universal_ai_basic"
    DEFAULT_MODEL_KEY = "google_gemini_2_0_flash"

CONFIG = AppConfig()

_API_KEYS_PROVIDER = {
    "CUSTOM_GEMINI_PRO_API_KEY": CONFIG.CUSTOM_GEMINI_PRO_API_KEY,
    "CUSTOM_GROK_3_API_KEY": CONFIG.CUSTOM_GROK_3_API_KEY,
    "CUSTOM_GPT4O_MINI_API_KEY": CONFIG.CUSTOM_GPT4O_MINI_API_KEY,
}

# --- КОНСТАНТЫ ПРИЛОЖЕНИЯ ---
class BotConstants:
    FS_USERS_COLLECTION = "users"
    FS_BOT_DATA_COLLECTION = "bot_data"
    FS_BOT_DATA_DOCUMENT = "data"
    FS_ALL_USER_DAILY_COUNTS_KEY = "all_user_daily_counts"

    MENU_MAIN = "main_menu"
    MENU_AI_MODES_SUBMENU = "ai_modes_submenu"
    MENU_MODELS_SUBMENU = "models_submenu"
    MENU_LIMITS_SUBMENU = "limits_submenu"
    MENU_BONUS_SUBMENU = "bonus_submenu"
    MENU_GEMS_SUBMENU = "gems_submenu"
    MENU_HELP_SUBMENU = "help_submenu"

    CALLBACK_ACTION_SUBMENU = "submenu"
    CALLBACK_ACTION_SET_AGENT = "set_agent"
    CALLBACK_ACTION_SET_MODEL = "set_model"
    CALLBACK_ACTION_SHOW_LIMITS = "show_limits"
    CALLBACK_ACTION_CHECK_BONUS = "check_bonus"
    CALLBACK_ACTION_BUY_GEMS = "buy_gems"
    CALLBACK_ACTION_SHOW_HELP = "show_help"

    API_TYPE_GOOGLE_GENAI = "google_genai"
    API_TYPE_CUSTOM_HTTP = "custom_http_api"

# --- ОПРЕДЕЛЕНИЯ РЕЖИМОВ И МОДЕЛЕЙ ---
AI_MODES = {
    "universal_ai_basic": {"name": "Универсальный", "prompt": "Ты — Gemini...", "welcome": "Активирован агент 'Универсальный'. Какой у вас запрос?"},
    "gemini_pro_custom_mode": {"name": "Продвинутый", "prompt": "Ты — Gemini 2.5 Pro...", "welcome": "Активирован агент 'Продвинутый'. Какой у вас запрос?"},
    "creative_helper": {"name": "Творческий", "prompt": "Ты — Gemini, креативный ИИ-партнёр...", "welcome": "Агент 'Творческий' к вашим услугам! Над какой задачей поработаем?"},
    "analyst": {"name": "Аналитик", "prompt": "Ты — ИИ-аналитик на базе Gemini...", "welcome": "Агент 'Аналитик' активирован. Какую задачу проанализировать?"},
    "joker": {"name": "Шутник", "prompt": "Ты — ИИ с чувством юмора...", "welcome": "Агент 'Шутник' включен! 😄 Готов ответить с улыбкой!"}
}

AVAILABLE_TEXT_MODELS = {
    "google_gemini_2_0_flash": {
        "name": "Gemini 2.0", "id": "gemini-2.0-flash", "api_type": BotConstants.API_TYPE_GOOGLE_GENAI,
        "is_limited": True, "limit_type": "daily_free", "limit": CONFIG.DEFAULT_FREE_REQUESTS_GOOGLE_FLASH_DAILY,
    },
    "google_gemini_2_5_flash_preview": {
        "name": "Gemini 2.5", "id": "gemini-2.5-flash-preview-04-17", "api_type": BotConstants.API_TYPE_GOOGLE_GENAI,
        "is_limited": True, "limit_type": "daily_free",
        "limit": CONFIG.DEFAULT_FREE_REQUESTS_GEMINI_2_5_FLASH_PREVIEW_DAILY,
    },
    "custom_api_gemini_2_5_pro": {
        "name": "Gemini Pro", "id": "gemini-2.5-pro-preview-03-25", "api_type": BotConstants.API_TYPE_CUSTOM_HTTP,
        "endpoint": CONFIG.CUSTOM_GEMINI_PRO_ENDPOINT, "api_key_var_name": "CUSTOM_GEMINI_PRO_API_KEY",
        "is_limited": True, "limit_type": "gems_based", "gem_cost": 2.5,
    },
    "custom_api_grok_3": {
        "name": "Grok 3", "id": "grok-3-beta", "api_type": BotConstants.API_TYPE_CUSTOM_HTTP,
        "endpoint": "https://api.gen-api.ru/api/v1/networks/grok-3", "api_key_var_name": "CUSTOM_GROK_3_API_KEY",
        "is_limited": True, "limit_type": "gems_based", "gem_cost": 2.5,
    },
    "custom_api_gpt_4o_mini": {
        "name": "GPT-4o mini", "id": "gpt-4o-mini", "api_type": BotConstants.API_TYPE_CUSTOM_HTTP,
        "endpoint": "https://api.gen-api.ru/api/v1/networks/gpt-4o-mini", "api_key_var_name": "CUSTOM_GPT4O_MINI_API_KEY",
        "is_limited": True, "limit_type": "daily_free_or_gems",
        "limit": 25, "gem_cost": 0.5,
    }
}
DEFAULT_MODEL_ID = AVAILABLE_TEXT_MODELS[CONFIG.DEFAULT_MODEL_KEY]["id"]

MENU_STRUCTURE = {
    BotConstants.MENU_MAIN: {
        "title": "📋 Главное меню", "items": [
            {"text": "🤖 Агенты ИИ", "action": BotConstants.CALLBACK_ACTION_SUBMENU, "target": BotConstants.MENU_AI_MODES_SUBMENU},
            {"text": "⚙️ Модели ИИ", "action": BotConstants.CALLBACK_ACTION_SUBMENU, "target": BotConstants.MENU_MODELS_SUBMENU},
            {"text": "📊 Лимиты", "action": BotConstants.CALLBACK_ACTION_SUBMENU, "target": BotConstants.MENU_LIMITS_SUBMENU},
            {"text": "🎁 Бонус", "action": BotConstants.CALLBACK_ACTION_SUBMENU, "target": BotConstants.MENU_BONUS_SUBMENU},
            {"text": "💎 Гемы", "action": BotConstants.CALLBACK_ACTION_SUBMENU, "target": BotConstants.MENU_GEMS_SUBMENU},
            {"text": "❓ Помощь", "action": BotConstants.CALLBACK_ACTION_SUBMENU, "target": BotConstants.MENU_HELP_SUBMENU}
        ], "parent": None, "is_submenu": False
    },
    BotConstants.MENU_AI_MODES_SUBMENU: {
        "title": "Выберите агент ИИ", "items": [
            {"text": mode["name"], "action": BotConstants.CALLBACK_ACTION_SET_AGENT, "target": key}
            for key, mode in AI_MODES.items() if key != "gemini_pro_custom_mode"
        ], "parent": BotConstants.MENU_MAIN, "is_submenu": True
    },
    BotConstants.MENU_MODELS_SUBMENU: {
        "title": "Выберите модель ИИ", "items": [
            {"text": model["name"], "action": BotConstants.CALLBACK_ACTION_SET_MODEL, "target": key}
            for key, model in AVAILABLE_TEXT_MODELS.items()
        ], "parent": BotConstants.MENU_MAIN, "is_submenu": True
    },
    BotConstants.MENU_LIMITS_SUBMENU: {"title": "Ваши лимиты", "items": [{"text": "📊 Показать", "action": BotConstants.CALLBACK_ACTION_SHOW_LIMITS, "target": "usage"}], "parent": BotConstants.MENU_MAIN, "is_submenu": True},
    BotConstants.MENU_BONUS_SUBMENU: {"title": "Бонус за подписку", "items": [{"text": "🎁 Получить", "action": BotConstants.CALLBACK_ACTION_CHECK_BONUS, "target": "news_bonus"}], "parent": BotConstants.MENU_MAIN, "is_submenu": True},
    BotConstants.MENU_GEMS_SUBMENU: {
        "title": "💎 Покупка Гемов", "items": [
            {"text": "🛒 100 💎 (150 RUB)", "action": BotConstants.CALLBACK_ACTION_BUY_GEMS, "target": "100_150"},
            {"text": "🛒 250 💎 (350 RUB)", "action": BotConstants.CALLBACK_ACTION_BUY_GEMS, "target": "250_350"},
            {"text": "🛒 500 💎 (600 RUB)", "action": BotConstants.CALLBACK_ACTION_BUY_GEMS, "target": "500_600"},
        ], "parent": BotConstants.MENU_MAIN, "is_submenu": True
    },
    BotConstants.MENU_HELP_SUBMENU: {"title": "Помощь", "items": [{"text": "❓ Справка", "action": BotConstants.CALLBACK_ACTION_SHOW_HELP, "target": "help"}], "parent": BotConstants.MENU_MAIN, "is_submenu": True}
}

# --- СЕРВИС ДЛЯ РАБОТЫ С FIRESTORE ---
class FirestoreService:
    def __init__(self, cert_path: str, creds_json_str: Optional[str] = None):
        self._db: Optional[Any] = None
        try:
            if creds_json_str and creds_json_str.strip():
                cred_obj = credentials.Certificate(json.loads(creds_json_str))
            elif os.path.exists(cert_path):
                cred_obj = credentials.Certificate(cert_path)
            else:
                raise FileNotFoundError("Firebase credentials not found.")
            if not firebase_admin._apps:
                initialize_app(cred_obj)
            self._db = firestore.client()
            logger.info("Firestore client successfully initialized.")
        except Exception as e:
            logger.error(f"Critical error during Firestore initialization: {e}", exc_info=True)
            self._db = None
    
    async def _execute_firestore_op(self, func, *args, **kwargs):
        if not self._db: return None
        return await asyncio.get_event_loop().run_in_executor(None, lambda: func(*args, **kwargs))

    async def get_user_data(self, user_id: int) -> Dict[str, Any]:
        if not self._db: return {}
        doc_ref = self._db.collection(BotConstants.FS_USERS_COLLECTION).document(str(user_id))
        doc = await self._execute_firestore_op(doc_ref.get)
        return doc.to_dict() if doc and doc.exists else {}

    async def set_user_data(self, user_id: int, data: Dict[str, Any]) -> None:
        if not self._db: return
        doc_ref = self._db.collection(BotConstants.FS_USERS_COLLECTION).document(str(user_id))
        await self._execute_firestore_op(doc_ref.set, data, merge=True)

    async def get_bot_data(self) -> Dict[str, Any]:
        if not self._db: return {}
        doc_ref = self._db.collection(BotConstants.FS_BOT_DATA_COLLECTION).document(BotConstants.FS_BOT_DATA_DOCUMENT)
        doc = await self._execute_firestore_op(doc_ref.get)
        return doc.to_dict() if doc and doc.exists else {}

    async def set_bot_data(self, data: Dict[str, Any]) -> None:
        if not self._db: return
        doc_ref = self._db.collection(BotConstants.FS_BOT_DATA_COLLECTION).document(BotConstants.FS_BOT_DATA_DOCUMENT)
        await self._execute_firestore_op(doc_ref.set, data, merge=True)

firestore_service = FirestoreService(CONFIG.FIREBASE_CERT_PATH, CONFIG.FIREBASE_CREDENTIALS_JSON_STR)

# --- СЕРВИСЫ ДЛЯ РАБОТЫ С AI ---
class BaseAIService(ABC):
    def __init__(self, model_config: Dict[str, Any]):
        self.model_config = model_config
        self.model_id = model_config["id"]
    async def generate_response(self, system_prompt: str, user_prompt: str) -> str: pass

class GoogleGenAIService(BaseAIService):
    async def generate_response(self, system_prompt: str, user_prompt: str) -> str:
        full_prompt = f"{system_prompt}\n\n**Запрос:**\n{user_prompt}"
        try:
            model_genai = genai.GenerativeModel(self.model_id, generation_config={"max_output_tokens": CONFIG.MAX_OUTPUT_TOKENS_GEMINI_LIB})
            response = await asyncio.to_thread(model_genai.generate_content, full_prompt)
            return response.text.strip() if response.text else "Ответ Google GenAI пуст."
        except Exception as e:
            logger.error(f"Google GenAI API error for model {self.model_id}: {e}", exc_info=True)
            return f"Ошибка Google API ({type(e).__name__}) при обращении к {self.model_id}."

class CustomHttpAIService(BaseAIService):
    async def generate_response(self, system_prompt: str, user_prompt: str) -> str:
        api_key_name = self.model_config.get("api_key_var_name")
        actual_key = _API_KEYS_PROVIDER.get(api_key_name)
        if not actual_key or "YOUR_" in actual_key:
            return f"Ошибка конфигурации ключа API для «{self.model_config.get('name', self.model_id)}»."
        headers = {"Authorization": f"Bearer {actual_key}", "Content-Type": "application/json", "Accept": "application/json"}
        messages_payload = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
        payload = {"messages": messages_payload, "model": self.model_id, "is_sync": True, "max_tokens": CONFIG.MAX_OUTPUT_TOKENS_GEMINI_LIB}
        endpoint = self.model_config["endpoint"]
        try:
            response = await asyncio.to_thread(requests.post, endpoint, headers=headers, json=payload, timeout=45)
            response.raise_for_status()
            json_resp = response.json()
            
            extracted_text = None
            if self.model_id == "grok-3-beta":
                if "response" in json_resp and isinstance(json_resp.get("response"), list) and json_resp["response"]:
                    extracted_text = json_resp["response"][0].get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            
            elif self.model_id in ["gemini-2.5-pro-preview-03-25", "gpt-4o-mini"]:
                 output_val = json_resp.get("output")
                 if isinstance(output_val, str): extracted_text = output_val.strip()
                 elif isinstance(output_val, dict): extracted_text = output_val.get("text", output_val.get("content", "")).strip()
                 if not extracted_text: extracted_text = json_resp.get("text", "").strip()
                 if json_resp.get("status") != "success" and not extracted_text:
                     error_msg = json_resp.get("error_message", "Неизвестная ошибка API")
                     extracted_text = f"Ошибка API для {self.model_config['name']}: {error_msg}"
            
            if extracted_text is None:
                for key in ["text", "content", "message", "output", "response"]:
                    if isinstance(json_resp.get(key), str) and (val := json_resp[key].strip()):
                        extracted_text = val
                        break
            
            return extracted_text if extracted_text else f"Ответ API {self.model_config['name']} не содержит текста."
        except requests.exceptions.HTTPError as e:
            return f"Ошибка сети API ({e.response.status_code}) для {self.model_config['name']}."
        except Exception as e:
            return f"Неожиданная ошибка API ({type(e).__name__}) для {self.model_config['name']}."

def get_ai_service(model_key: str) -> Optional[BaseAIService]:
    model_cfg = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_cfg: return None
    api_type = model_cfg.get("api_type")
    if api_type == BotConstants.API_TYPE_GOOGLE_GENAI: return GoogleGenAIService(model_cfg)
    if api_type == BotConstants.API_TYPE_CUSTOM_HTTP: return CustomHttpAIService(model_cfg)
    return None

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
async def get_current_model_key(user_id: int, user_data: Optional[Dict[str, Any]] = None) -> str:
    user_data_loc = user_data if user_data is not None else await firestore_service.get_user_data(user_id)
    selected_id = user_data_loc.get('selected_model_id', DEFAULT_MODEL_ID)
    for key, info in AVAILABLE_TEXT_MODELS.items():
        if info["id"] == selected_id: return key
    return CONFIG.DEFAULT_MODEL_KEY

async def get_current_mode_details(user_id: int, user_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    user_data_loc = user_data if user_data is not None else await firestore_service.get_user_data(user_id)
    current_model_k_loc = await get_current_model_key(user_id, user_data_loc)
    mode_k_loc = user_data_loc.get('current_ai_mode', CONFIG.DEFAULT_AI_MODE_KEY)
    if current_model_k_loc == "custom_api_gemini_2_5_pro": return AI_MODES["gemini_pro_custom_mode"]
    return AI_MODES.get(mode_k_loc, AI_MODES[CONFIG.DEFAULT_AI_MODE_KEY])

def smart_truncate(text: str, max_length: int) -> Tuple[str, bool]:
    if not isinstance(text, str) or len(text) <= max_length: return str(text), False
    suffix = "\n\n(...ответ был сокращен)"
    truncated_text = text[:max_length - len(suffix)]
    last_p = truncated_text.rfind('\n\n')
    if last_p > len(truncated_text) * 0.5: return text[:last_p].strip() + suffix, True
    last_s = truncated_text.rfind('. ')
    if last_s > len(truncated_text) * 0.5: return text[:last_s+1].strip() + suffix, True
    return truncated_text.strip() + suffix, True

async def check_and_log_request_attempt(user_id: int, model_key: str) -> Tuple[bool, str]:
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    model_cfg = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_cfg or not model_cfg.get("is_limited"): return True, ""

    user_data = await firestore_service.get_user_data(user_id)
    limit_type = model_cfg.get("limit_type")

    if model_key == CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY and user_data.get('news_bonus_uses_left', 0) > 0:
        return True, "bonus_use"

    all_counts = (await firestore_service.get_bot_data()).get(BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY, {})
    user_counts = all_counts.get(str(user_id), {})
    model_usage = user_counts.get(model_key, {'date': '', 'count': 0})
    current_usage = model_usage['count'] if model_usage['date'] == today_str else 0

    if limit_type == "daily_free":
        if current_usage >= model_cfg.get("limit", 0):
            return False, f"Достигнут дневной лимит ({current_usage}/{model_cfg['limit']}) для «{model_cfg['name']}»."
        return True, ""

    if limit_type == "gems_based":
        cost = model_cfg.get("gem_cost", 0)
        balance = user_data.get("gem_balance", 0.0)
        if balance < cost:
            return False, f"Недостаточно гемов для «{model_cfg['name']}». Требуется: {cost}💎, у вас: {balance}💎."
        return True, "use_gems"

    if limit_type == "daily_free_or_gems":
        if current_usage < model_cfg.get("limit", 0): return True, ""
        cost = model_cfg.get("gem_cost", 0)
        balance = user_data.get("gem_balance", 0.0)
        if balance < cost:
            return False, f"Бесплатные попытки для «{model_cfg['name']}» закончились. Требуется: {cost}💎, у вас: {balance}💎."
        return True, "use_gems"
        
    return True, ""

async def increment_request_count(user_id: int, model_key: str, flag: str):
    model_cfg = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_cfg or not model_cfg.get("is_limited"): return

    if flag == "bonus_use":
        user_data = await firestore_service.get_user_data(user_id)
        bonus_left = user_data.get('news_bonus_uses_left', 0)
        if bonus_left > 0: await firestore_service.set_user_data(user_id, {'news_bonus_uses_left': bonus_left - 1})
        return

    if flag == "use_gems":
        cost = model_cfg.get("gem_cost", 0)
        user_data = await firestore_service.get_user_data(user_id)
        balance = user_data.get("gem_balance", 0.0)
        await firestore_service.set_user_data(user_id, {'gem_balance': balance - cost})
        return

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    bot_data = await firestore_service.get_bot_data()
    all_counts = bot_data.get(BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY, {})
    user_counts = all_counts.get(str(user_id), {})
    model_usage = user_counts.get(model_key, {'date': today_str, 'count': 0})
    if model_usage['date'] != today_str: model_usage = {'date': today_str, 'count': 0}
    model_usage['count'] += 1
    user_counts[model_key] = model_usage
    all_counts[str(user_id)] = user_counts
    await firestore_service.set_bot_data({BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY: all_counts})

# --- ФУНКЦИИ МЕНЮ ---
def is_menu_button_text(text: str) -> bool:
    if text in ["⬅️ Назад", "🏠 Главное меню"]: return True
    for menu_data in MENU_STRUCTURE.values():
        for item in menu_data.get("items", []):
            if item["text"] == text: return True
    return False

def generate_menu_keyboard(menu_key: str) -> ReplyKeyboardMarkup:
    menu_config = MENU_STRUCTURE.get(menu_key, MENU_STRUCTURE[BotConstants.MENU_MAIN])
    items = menu_config["items"]
    group_size = 2 if menu_key in [BotConstants.MENU_MAIN, BotConstants.MENU_MODELS_SUBMENU] else 1
    keyboard_rows = [
        [KeyboardButton(items[j]["text"]) for j in range(i, min(i + group_size, len(items)))]
        for i in range(0, len(items), group_size)
    ]
    if menu_config.get("is_submenu"):
        nav_row = [KeyboardButton("🏠 Главное меню")]
        if menu_config.get("parent"): nav_row.insert(0, KeyboardButton("⬅️ Назад"))
        keyboard_rows.append(nav_row)
    return ReplyKeyboardMarkup(keyboard_rows, resize_keyboard=True)

async def show_menu(update: Update, user_id: int, menu_key: str):
    menu_cfg = MENU_STRUCTURE.get(menu_key)
    if not menu_cfg: menu_key = BotConstants.MENU_MAIN
    await firestore_service.set_user_data(user_id, {'current_menu': menu_key})
    await update.message.reply_text(
        MENU_STRUCTURE[menu_key]["title"],
        reply_markup=generate_menu_keyboard(menu_key),
        disable_web_page_preview=True
    )

# --- ЛОГИКА ОТОБРАЖЕНИЯ ИНФОРМАЦИИ ---
async def show_limits(update: Update, user_id: int):
    user_data = await firestore_service.get_user_data(user_id)
    bot_data = await firestore_service.get_bot_data()
    gem_balance = user_data.get('gem_balance', 0.0)
    parts = [f"<b>💎 Ваш баланс: {gem_balance:.1f} гемов</b>\n"]
    
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    all_counts = bot_data.get(BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY, {})
    user_counts = all_counts.get(str(user_id), {})

    for key, cfg in AVAILABLE_TEXT_MODELS.items():
        if not cfg.get("is_limited"): continue
        limit_type = cfg.get("limit_type")
        
        if limit_type == "daily_free":
            usage = user_counts.get(key, {'count': 0, 'date': ''})
            count = usage['count'] if usage['date'] == today_str else 0
            parts.append(f"▫️ {cfg['name']}: <b>{count} / {cfg['limit']}</b> в день")
        
        elif limit_type == "gems_based":
            parts.append(f"▫️ {cfg['name']}: <b>{cfg['gem_cost']} 💎</b> за запрос")

        elif limit_type == "daily_free_or_gems":
            usage = user_counts.get(key, {'count': 0, 'date': ''})
            count = usage['count'] if usage['date'] == today_str else 0
            parts.append(f"▫️ {cfg['name']}: <b>{count} / {cfg['limit']}</b> бесплатных, затем <b>{cfg['gem_cost']} 💎</b>")

    if (bonus_left := user_data.get('news_bonus_uses_left', 0)) > 0:
        bonus_model_name = AVAILABLE_TEXT_MODELS[CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY]['name']
        parts.append(f"\n✅ У вас есть <b>{bonus_left}</b> бонусных генераций для {bonus_model_name}.")

    await update.message.reply_text("\n".join(parts), parse_mode=ParseMode.HTML, disable_web_page_preview=True)

async def claim_news_bonus_logic(update: Update, user_id: int):
    user_data = await firestore_service.get_user_data(user_id)
    if user_data.get('claimed_news_bonus', False):
        await update.message.reply_text("Вы уже получали бонус за подписку на канал.")
        return

    try:
        member_status = await update.get_bot().get_chat_member(chat_id=CONFIG.NEWS_CHANNEL_USERNAME, user_id=user_id)
        if member_status.status in ['member', 'administrator', 'creator']:
            await firestore_service.set_user_data(user_id, {
                'claimed_news_bonus': True, 
                'news_bonus_uses_left': CONFIG.NEWS_CHANNEL_BONUS_GENERATIONS
            })
            model_name = AVAILABLE_TEXT_MODELS[CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY]['name']
            await update.message.reply_text(
                f'🎉 Спасибо за подписку! Вам начислен бонус: <b>{CONFIG.NEWS_CHANNEL_BONUS_GENERATIONS}</b> генераций для {model_name}.',
                parse_mode=ParseMode.HTML, disable_web_page_preview=True
            )
        else:
            inline_kb = InlineKeyboardMarkup([[InlineKeyboardButton("📢 Перейти на канал", url=CONFIG.NEWS_CHANNEL_LINK)]])
            await update.message.reply_text(
                f'Для получения бонуса подпишитесь на канал <a href="{CONFIG.NEWS_CHANNEL_LINK}">{CONFIG.NEWS_CHANNEL_USERNAME}</a> и попробуйте снова.',
                parse_mode=ParseMode.HTML, reply_markup=inline_kb, disable_web_page_preview=True
            )
    except Exception as e:
        logger.error(f"News bonus claim error for user {user_id}: {e}")
        await update.message.reply_text("Произошла ошибка при проверке подписки. Попробуйте позже.")

async def send_gems_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE, target: str):
    user_id = update.effective_user.id
    try:
        amount_str, price_str = target.split('_')
        amount, price = int(amount_str), int(price_str)
    except (ValueError, IndexError):
        await update.message.reply_text("Ошибка в выборе пакета гемов.")
        return

    title = f"Покупка {amount} 💎"
    description = f"Пакет из {amount} гемов для использования в боте."
    payload = f"buy_gems_{amount}_user_{user_id}"
    
    await context.bot.send_invoice(
        chat_id=user_id, title=title, description=description, payload=payload,
        provider_token=CONFIG.PAYMENT_PROVIDER_TOKEN, currency="RUB",
        prices=[LabeledPrice(f"{amount} 💎", price * 100)]
    )

async def show_help(update: Update, user_id: int):
    help_text = (
        "<b>❓ Справка по использованию бота</b>\n\n"
        "1.  <b>Запросы к ИИ</b>: Просто напишите ваш вопрос в чат.\n"
        "2.  <b>Меню</b>: Используйте кнопки для навигации:\n"
        "    ▫️ «<b>🤖 Агенты ИИ</b>»: Выберите роль (стиль) для ответов.\n"
        "    ▫️ «<b>⚙️ Модели ИИ</b>»: Переключайтесь между нейросетями.\n"
        "    ▫️ «<b>📊 Лимиты</b>»: Проверьте баланс гемов и дневные лимиты.\n"
        "    ▫️ «<b>🎁 Бонус</b>»: Получите бонус за подписку на канал.\n"
        "    ▫️ «<b>💎 Гемы</b>»: Пополните ваш баланс гемов.\n"
        "3.  <b>Команды</b>: /start, /menu, /help, /bonus, /usage."
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

# --- ОБРАБОТЧИКИ КОМАНД И КНОПОК ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = await firestore_service.get_user_data(user_id)
    updates_to_db = {}
    if 'current_ai_mode' not in user_data: updates_to_db['current_ai_mode'] = CONFIG.DEFAULT_AI_MODE_KEY
    if 'current_menu' not in user_data: updates_to_db['current_menu'] = BotConstants.MENU_MAIN
    if 'gem_balance' not in user_data: updates_to_db['gem_balance'] = 0.0
    if 'selected_model_id' not in user_data: updates_to_db['selected_model_id'] = DEFAULT_MODEL_ID
    if updates_to_db: await firestore_service.set_user_data(user_id, updates_to_db)
    
    greeting = f"👋 Привет, {update.effective_user.first_name}! Я готов к работе."
    await update.message.reply_text(greeting, reply_markup=generate_menu_keyboard(BotConstants.MENU_MAIN))

async def open_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_menu(update, update.effective_user.id, BotConstants.MENU_MAIN)

async def usage_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_limits(update, update.effective_user.id)

async def get_bonus_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await claim_news_bonus_logic(update, update.effective_user.id)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_help(update, update.effective_user.id)

async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not (update.message and update.message.text): return
    user_id = update.effective_user.id
    button_text = update.message.text.strip()
    if not is_menu_button_text(button_text): return

    try: await update.message.delete()
    except Exception: pass

    user_data = await firestore_service.get_user_data(user_id)
    current_menu = user_data.get('current_menu', BotConstants.MENU_MAIN)

    if button_text == "⬅️ Назад":
        parent = MENU_STRUCTURE.get(current_menu, {}).get("parent", BotConstants.MENU_MAIN)
        await show_menu(update, user_id, parent)
        return
    if button_text == "🏠 Главное меню":
        await show_menu(update, user_id, BotConstants.MENU_MAIN)
        return

    action_item = next((item for menu in MENU_STRUCTURE.values() for item in menu["items"] if item["text"] == button_text), None)
    if not action_item: return

    action, target = action_item["action"], action_item["target"]
    parent_menu = next((k for k, v in MENU_STRUCTURE.items() if v.get("parent") and any(i["text"] == button_text for i in v["items"])), BotConstants.MENU_MAIN)
    return_menu = MENU_STRUCTURE.get(parent_menu, {}).get("parent", BotConstants.MENU_MAIN)

    if action == BotConstants.CALLBACK_ACTION_SUBMENU: await show_menu(update, user_id, target)
    elif action == BotConstants.CALLBACK_ACTION_SET_AGENT:
        await firestore_service.set_user_data(user_id, {'current_ai_mode': target})
        await update.message.reply_text(f"🤖 Агент изменен на: <b>{AI_MODES[target]['name']}</b>.", parse_mode=ParseMode.HTML)
    elif action == BotConstants.CALLBACK_ACTION_SET_MODEL:
        model_info = AVAILABLE_TEXT_MODELS[target]
        await firestore_service.set_user_data(user_id, {'selected_model_id': model_info["id"]})
        await update.message.reply_text(f"⚙️ Модель изменена на: <b>{model_info['name']}</b>.", parse_mode=ParseMode.HTML)
    elif action == BotConstants.CALLBACK_ACTION_SHOW_LIMITS: await show_limits(update, user_id)
    elif action == BotConstants.CALLBACK_ACTION_CHECK_BONUS: await claim_news_bonus_logic(update, user_id)
    elif action == BotConstants.CALLBACK_ACTION_BUY_GEMS: await send_gems_invoice(update, context, target)
    elif action == BotConstants.CALLBACK_ACTION_SHOW_HELP: await show_help(update, user_id)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not (update.message and update.message.text): return
    user_message = update.message.text.strip()
    if is_menu_button_text(user_message): return
    
    try: await update.message.delete()
    except Exception: pass
    
    if len(user_message) < CONFIG.MIN_AI_REQUEST_LENGTH:
        await update.message.reply_text("Запрос слишком короткий.")
        return

    user_data = await firestore_service.get_user_data(user_id)
    model_key = await get_current_model_key(user_id, user_data)
    
    can_proceed, flag_or_msg = await check_and_log_request_attempt(user_id, model_key)
    if not can_proceed:
        await update.message.reply_text(flag_or_msg, parse_mode=ParseMode.HTML)
        return

    ai_service = get_ai_service(model_key)
    if not ai_service:
        await update.message.reply_text("Ошибка при выборе AI модели.")
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    mode_details = await get_current_mode_details(user_id, user_data)
    
    ai_response = await ai_service.generate_response(mode_details["prompt"], user_message)
    final_reply, _ = smart_truncate(ai_response, CONFIG.MAX_MESSAGE_LENGTH_TELEGRAM)
    
    await increment_request_count(user_id, model_key, flag_or_msg)
    await update.message.reply_text(final_reply)

# --- ОБРАБОТЧИКИ ПЛАТЕЖЕЙ ---
async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    if query.invoice_payload.startswith("buy_gems_"):
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="Ошибка запроса на оплату.")

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    payload = update.message.successful_payment.invoice_payload

    if payload.startswith("buy_gems_"):
        try:
            parts = payload.split('_')
            gems_to_add = int(parts[2])
            user_data = await firestore_service.get_user_data(user_id)
            new_balance = user_data.get('gem_balance', 0.0) + gems_to_add
            await firestore_service.set_user_data(user_id, {'gem_balance': new_balance})
            await update.message.reply_text(f"🎉 Оплата прошла! Вам начислено <b>{gems_to_add}💎</b>. Ваш новый баланс: <b>{new_balance:.1f}💎</b>.", parse_mode=ParseMode.HTML)
            if CONFIG.ADMIN_ID:
                await context.bot.send_message(CONFIG.ADMIN_ID, f"🔔 Новая покупка гемов: {gems_to_add}💎 от user {user_id}")
        except Exception as e:
            logger.error(f"Failed to process gem payment payload '{payload}': {e}")

# --- ОБРАБОТЧИК ОШИБОК ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    tb_string = "".join(traceback.format_exception(None, context.error, context.error.__traceback__))
    if isinstance(update, Update) and update.effective_chat:
        try: await context.bot.send_message(chat_id=update.effective_chat.id, text="Произошла внутренняя ошибка. Попробуйте /start.")
        except Exception: pass
    if CONFIG.ADMIN_ID:
        error_details = f"🤖 Ошибка в боте:\n{context.error.__class__.__name__}: {context.error}\n\nTraceback:\n{tb_string[:3500]}"
        try: await context.bot.send_message(CONFIG.ADMIN_ID, error_details)
        except Exception: pass

# --- ОСНОВНАЯ ФУНКЦИЯ ЗАПУСКА БОТА ---
async def main():
    if CONFIG.GOOGLE_GEMINI_API_KEY and CONFIG.GOOGLE_GEMINI_API_KEY.startswith("AIzaSy"):
        genai.configure(api_key=CONFIG.GOOGLE_GEMINI_API_KEY)
    
    if not firestore_service._db:
        logger.critical("Firestore не инициализирован! Бот не может работать.")
        return

    app = Application.builder().token(CONFIG.TELEGRAM_TOKEN).read_timeout(30).connect_timeout(30).build()
    
    app.add_handler(CommandHandler("start", start), group=0)
    app.add_handler(CommandHandler("menu", open_menu_command), group=0)
    app.add_handler(CommandHandler("usage", usage_command), group=0)
    app.add_handler(CommandHandler("bonus", get_bonus_command), group=0)
    app.add_handler(CommandHandler("help", help_command), group=0)
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_button_handler), group=1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text), group=2)
    
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    
    app.add_error_handler(error_handler)

    bot_commands = [
        BotCommand("start", "🚀 Перезапуск / Главное меню"),
        BotCommand("menu", "📋 Открыть меню"),
        BotCommand("usage", "📊 Показать лимиты и баланс"),
        BotCommand("bonus", "🎁 Получить бонус"),
        BotCommand("help", "❓ Справка")
    ]
    await app.bot.set_my_commands(bot_commands)

    logger.info("Bot is starting...")
    await app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    asyncio.run(main())
