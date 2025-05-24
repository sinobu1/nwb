import telegram
from telegram import (
    ReplyKeyboardMarkup, KeyboardButton, Update,
    BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
)
from telegram.constants import ParseMode, ChatAction
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, PreCheckoutQueryHandler
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

# --- ИМПОРТЫ ---
import firebase_admin
from firebase_admin import credentials, firestore, initialize_app
from abc import ABC, abstractmethod
# ---------------------------------

nest_asyncio.apply()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- КОНФИГУРАЦИЯ (с вашими значениями по умолчанию из bot (48).py) ---
class AppConfig:
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8185454402:AAEgJLaBSaUSyP9Z_zv76Fn0PtEwltAqga0")
    GOOGLE_GEMINI_API_KEY = os.getenv("GOOGLE_GEMINI_API_KEY", "AIzaSyCdDMpgLJyz6aYdwT9q4sbBk7sHVID4BTI")
    
    # Ключи gen-api.ru из вашего исходного файла как значения по умолчанию
    CUSTOM_GEMINI_PRO_API_KEY = os.getenv("CUSTOM_GEMINI_PRO_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P")
    CUSTOM_GEMINI_PRO_ENDPOINT = os.getenv("CUSTOM_GEMINI_PRO_ENDPOINT", "https://api.gen-api.ru/api/v1/networks/gemini-2-5-pro")
    CUSTOM_GROK_3_API_KEY = os.getenv("CUSTOM_GROK_3_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P")
    CUSTOM_GPT4O_MINI_API_KEY = os.getenv("CUSTOM_GPT4O_MINI_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P")
    
    PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "390540012:LIVE:70602")
    ADMIN_ID = int(os.getenv("ADMIN_ID", "489230152")) # Ваш исходный ADMIN_ID
    
    FIREBASE_CREDENTIALS_JSON_STR = os.getenv("FIREBASE_CREDENTIALS")
    FIREBASE_CERT_PATH = "gemioracle-firebase-adminsdk-fbsvc-8f89d5b941.json" # Убедитесь, что этот файл существует или настройте JSON_STR

    MAX_OUTPUT_TOKENS_GEMINI_LIB = 2048
    MAX_MESSAGE_LENGTH_TELEGRAM = 4000
    MIN_AI_REQUEST_LENGTH = 4

    # Лимиты для системы гемов (старые лимиты подписки больше не используются)
    DEFAULT_FREE_REQUESTS_GOOGLE_FLASH_DAILY = 72 # Для Gemini 2.0 Flash
    DEFAULT_FREE_REQUESTS_GEMINI_2_5_FLASH_PREVIEW_DAILY = 48 # Для Gemini 2.5 Flash

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

AI_MODES = {
    "universal_ai_basic": {"name": "Универсальный", "prompt": "Ты — Gemini...", "welcome": "..."},
    "gemini_pro_custom_mode": {"name": "Продвинутый", "prompt": "Ты — Gemini 2.5 Pro...", "welcome": "..."},
    "creative_helper": {"name": "Творческий", "prompt": "Ты — Gemini, креативный...", "welcome": "..."},
    "analyst": {"name": "Аналитик", "prompt": "Ты — ИИ-аналитик...", "welcome": "..."},
    "joker": {"name": "Шутник", "prompt": "Ты — ИИ с чувством юмора...", "welcome": "..."}
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
    BotConstants.MENU_MAIN: {"title": "📋 Главное меню", "items": [{"text": "🤖 Агенты ИИ", "action": BotConstants.CALLBACK_ACTION_SUBMENU, "target": BotConstants.MENU_AI_MODES_SUBMENU}, {"text": "⚙️ Модели ИИ", "action": BotConstants.CALLBACK_ACTION_SUBMENU, "target": BotConstants.MENU_MODELS_SUBMENU}, {"text": "📊 Лимиты", "action": BotConstants.CALLBACK_ACTION_SUBMENU, "target": BotConstants.MENU_LIMITS_SUBMENU}, {"text": "🎁 Бонус", "action": BotConstants.CALLBACK_ACTION_SUBMENU, "target": BotConstants.MENU_BONUS_SUBMENU}, {"text": "💎 Гемы", "action": BotConstants.CALLBACK_ACTION_SUBMENU, "target": BotConstants.MENU_GEMS_SUBMENU}, {"text": "❓ Помощь", "action": BotConstants.CALLBACK_ACTION_SUBMENU, "target": BotConstants.MENU_HELP_SUBMENU}], "parent": None, "is_submenu": False},
    BotConstants.MENU_AI_MODES_SUBMENU: {"title": "Выберите агент ИИ", "items": [{"text": mode["name"], "action": BotConstants.CALLBACK_ACTION_SET_AGENT, "target": key} for key, mode in AI_MODES.items() if key != "gemini_pro_custom_mode"], "parent": BotConstants.MENU_MAIN, "is_submenu": True},
    BotConstants.MENU_MODELS_SUBMENU: {"title": "Выберите модель ИИ", "items": [{"text": model["name"], "action": BotConstants.CALLBACK_ACTION_SET_MODEL, "target": key} for key, model in AVAILABLE_TEXT_MODELS.items()], "parent": BotConstants.MENU_MAIN, "is_submenu": True},
    BotConstants.MENU_LIMITS_SUBMENU: {"title": "Ваши лимиты", "items": [{"text": "📊 Показать", "action": BotConstants.CALLBACK_ACTION_SHOW_LIMITS, "target": "usage"}], "parent": BotConstants.MENU_MAIN, "is_submenu": True},
    BotConstants.MENU_BONUS_SUBMENU: {"title": "Бонус за подписку", "items": [{"text": "🎁 Получить", "action": BotConstants.CALLBACK_ACTION_CHECK_BONUS, "target": "news_bonus"}], "parent": BotConstants.MENU_MAIN, "is_submenu": True},
    BotConstants.MENU_GEMS_SUBMENU: {"title": "💎 Покупка Гемов", "items": [{"text": "🛒 100 💎 (150 RUB)", "action": BotConstants.CALLBACK_ACTION_BUY_GEMS, "target": "100_150"}, {"text": "🛒 250 💎 (350 RUB)", "action": BotConstants.CALLBACK_ACTION_BUY_GEMS, "target": "250_350"}, {"text": "🛒 500 💎 (600 RUB)", "action": BotConstants.CALLBACK_ACTION_BUY_GEMS, "target": "500_600"}], "parent": BotConstants.MENU_MAIN, "is_submenu": True},
    BotConstants.MENU_HELP_SUBMENU: {"title": "Помощь", "items": [{"text": "❓ Справка", "action": BotConstants.CALLBACK_ACTION_SHOW_HELP, "target": "help"}], "parent": BotConstants.MENU_MAIN, "is_submenu": True}
}

class FirestoreService:
    def __init__(self, cert_path: str, creds_json_str: Optional[str] = None):
        self._db: Optional[Any] = None
        try:
            cred_obj = None
            if creds_json_str and creds_json_str.strip():
                try:
                    cred_dict = json.loads(creds_json_str)
                    cred_obj = credentials.Certificate(cred_dict)
                except json.JSONDecodeError as e:
                    logger.error(f"Error decoding FIREBASE_CREDENTIALS_JSON_STR: {e}. Using file path if available.")
                    cred_obj = None
            if not cred_obj and os.path.exists(cert_path):
                cred_obj = credentials.Certificate(cert_path)
                logger.info(f"Using Firebase credentials from file: {cert_path}")
            elif not cred_obj:
                raise FileNotFoundError("Firebase credentials not found (JSON string invalid/missing and file path invalid/missing).")
            if not firebase_admin._apps: # type: ignore
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

class BaseAIService(ABC):
    def __init__(self, model_config: Dict[str, Any]):
        self.model_config = model_config
        self.model_id = model_config["id"]
    @abstractmethod
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
        
        # Проверка ключа (не должна содержать "ЗАГЛУШКА_", если вы заменили дефолты на реальные ключи)
        if not actual_key or ("ЗАГЛУШКА_" in actual_key and actual_key == CONFIG.CUSTOM_GPT4O_MINI_API_KEY): # Уточненная проверка для случая, если дефолт - заглушка
            logger.error(f"API key for {self.model_id} is a placeholder or missing: {actual_key}")
            return f"Ошибка конфигурации ключа API для «{self.model_config.get('name', self.model_id)}»."
        
        headers = {"Authorization": f"Bearer {actual_key}", "Accept": "application/json"}
        messages_payload = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
        payload = {"messages": messages_payload, "model": self.model_id, "is_sync": True, "max_tokens": CONFIG.MAX_OUTPUT_TOKENS_GEMINI_LIB}
        endpoint = self.model_config["endpoint"]

        try:
            response = await asyncio.to_thread(requests.post, endpoint, headers=headers, json=payload, timeout=45)
            response.raise_for_status()
            
            try:
                json_resp = response.json()
            except json.JSONDecodeError:
                logger.error(f"Failed to decode JSON from API for {self.model_id}. Status: {response.status_code}. Response text: {response.text[:500]}")
                return f"Ошибка API: не удалось обработать ответ от сервера (не является JSON). Текст ответа: {response.text[:200]}"
            
            extracted_text = None

            if self.model_id == "gpt-4o-mini":
                try:
                    if isinstance(json_resp.get("response"), list) and json_resp["response"]:
                        message_obj = json_resp["response"][0].get("message", {})
                        extracted_text = message_obj.get("content", "").strip()
                    
                    if not extracted_text: # Если текст не извлечен
                        # Проверяем, был ли это ожидаемый формат ошибки от gen-api (с полем status)
                        if "status" in json_resp and json_resp.get("status") != "success":
                             logger.warning(
                                f"API for gpt-4o-mini returned explicit error. "
                                f"Status: '{json_resp.get('status')}'. Error: '{json_resp.get('error_message', 'N/A')}'. "
                                f"Full JSON: {json.dumps(json_resp, ensure_ascii=False, indent=2)}"
                            )
                             error_msg = json_resp.get("error_message", "Статус не 'success', но нет сообщения об ошибке.")
                             extracted_text = f"Ошибка API для {self.model_config['name']}: {error_msg}"
                        elif not ("response" in json_resp and json_resp["response"] and "message" in json_resp["response"][0]): # Если и не ошибка, и не успешный формат
                             logger.warning(
                                f"API for gpt-4o-mini returned unexpected JSON structure (no content). "
                                f"Full JSON: {json.dumps(json_resp, ensure_ascii=False, indent=2)}"
                            )
                             extracted_text = f"Ответ API {self.model_config['name']} не содержит текста в ожидаемом формате."

                except (TypeError, IndexError, AttributeError) as e_parse:
                    logger.error(
                        f"Error parsing gpt-4o-mini response structure for {self.model_id}. Error: {e_parse}. "
                        f"Full JSON: {json.dumps(json_resp, ensure_ascii=False, indent=2)}",
                        exc_info=True
                    )
                    extracted_text = f"Ошибка обработки ответа от {self.model_config['name']} (структура)."

            elif self.model_id == "grok-3-beta":
                if "response" in json_resp and isinstance(json_resp.get("response"), list) and json_resp["response"]:
                    extracted_text = json_resp["response"][0].get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            
            elif self.model_id == "gemini-2.5-pro-preview-03-25": # Этот парсинг для старого формата gen-api
                 output_val = json_resp.get("output") # gen-api для gemini pro часто использует 'output' или 'text'
                 if isinstance(output_val, str): extracted_text = output_val.strip()
                 elif isinstance(output_val, dict): extracted_text = output_val.get("text", output_val.get("content", "")).strip()
                 if not extracted_text: extracted_text = json_resp.get("text", "").strip()
                 
                 if json_resp.get("status") != "success" and not extracted_text:
                     logger.warning(
                         f"API for {self.model_id} returned status '{json_resp.get('status')}' "
                         f"with no parsable text and no 'error_message'. Full JSON response: {json.dumps(json_resp, ensure_ascii=False, indent=2)}"
                     )
                     error_msg = json_resp.get("error_message", "Неизвестная ошибка API")
                     extracted_text = f"Ошибка API для {self.model_config['name']}: {error_msg}"
            
            if not extracted_text: 
                for key_check in ["text", "content", "output"]: # Общий fallback для других возможных полей
                    if isinstance(json_resp.get(key_check), str) and (check_val := json_resp[key_check].strip()):
                        extracted_text = check_val
                        logger.info(f"Used fallback text extraction on key '{key_check}' for model {self.model_id}")
                        break
            
            return extracted_text if extracted_text else f"Ответ API {self.model_config['name']} не содержит ожидаемого текста."

        except requests.exceptions.HTTPError as e:
            logger.error(f"Custom API HTTPError for {self.model_id}: {e.response.status_code} - {e.response.text}")
            try:
                error_json = e.response.json()
                error_message = error_json.get("error", e.response.text)
                return f"Ошибка API ({e.response.status_code}) для {self.model_config['name']}: {error_message}"
            except json.JSONDecodeError:
                return f"Ошибка сети API ({e.response.status_code}) для {self.model_config['name']}: {e.response.text[:100]}"
        except Exception as e: 
            logger.error(f"Unexpected Custom API error for {self.model_id}: {e}", exc_info=True)
            return f"Неожиданная ошибка API ({type(e).__name__}) для {self.model_config['name']}."

def get_ai_service(model_key: str) -> Optional[BaseAIService]:
    model_cfg = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_cfg: 
        logger.error(f"Model config for key '{model_key}' not found.")
        return None
    api_type = model_cfg.get("api_type")
    if api_type == BotConstants.API_TYPE_GOOGLE_GENAI: return GoogleGenAIService(model_cfg)
    if api_type == BotConstants.API_TYPE_CUSTOM_HTTP: return CustomHttpAIService(model_cfg)
    logger.error(f"Unknown API type '{api_type}' for model_key '{model_key}'.")
    return None

async def get_current_model_key(user_id: int, user_data: Optional[Dict[str, Any]] = None) -> str:
    user_data_loc = user_data if user_data is not None else await firestore_service.get_user_data(user_id)
    selected_id = user_data_loc.get('selected_model_id', DEFAULT_MODEL_ID)
    for key, info in AVAILABLE_TEXT_MODELS.items():
        if info["id"] == selected_id: return key
    logger.warning(f"Selected model_id '{selected_id}' for user {user_id} not found. Reverting to default.")
    default_key = CONFIG.DEFAULT_MODEL_KEY
    default_cfg = AVAILABLE_TEXT_MODELS[default_key]
    await firestore_service.set_user_data(user_id, {'selected_model_id': default_cfg["id"]})
    return default_key

async def get_current_mode_details(user_id: int, user_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    user_data_loc = user_data if user_data is not None else await firestore_service.get_user_data(user_id)
    current_model_k_loc = await get_current_model_key(user_id, user_data_loc)
    mode_k_loc = user_data_loc.get('current_ai_mode', CONFIG.DEFAULT_AI_MODE_KEY)
    if current_model_k_loc == "custom_api_gemini_2_5_pro": return AI_MODES["gemini_pro_custom_mode"]
    return AI_MODES.get(mode_k_loc, AI_MODES[CONFIG.DEFAULT_AI_MODE_KEY])

def smart_truncate(text: str, max_length: int) -> Tuple[str, bool]:
    if not isinstance(text, str) or len(text) <= max_length: return str(text), False
    suffix = "\n\n(...ответ был сокращен)"
    adjusted_max_length = max(0, max_length - len(suffix))
    if adjusted_max_length == 0:
        return text[:max_length - 3] + "..." if max_length > 3 else text[:max_length], True
    truncated_text = text[:adjusted_max_length]
    for separator in ['\n\n', '. ', '! ', '? ', '\n', ' ']: 
        position = truncated_text.rfind(separator)
        if position != -1:
            actual_cut_position = position + (len(separator) if separator != ' ' else 0) 
            if actual_cut_position > 0 and actual_cut_position > adjusted_max_length * 0.3:
                 return text[:actual_cut_position].strip() + suffix, True
    return text[:adjusted_max_length].strip() + suffix, True

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
        return True, "daily_free_use"
    if limit_type == "gems_based":
        cost = model_cfg.get("gem_cost", 0.0)
        balance = user_data.get("gem_balance", 0.0)
        if balance < cost:
            return False, f"Недостаточно гемов для «{model_cfg['name']}». Требуется: {cost:.1f}💎, у вас: {balance:.1f}💎."
        return True, "use_gems"
    if limit_type == "daily_free_or_gems":
        if current_usage < model_cfg.get("limit", 0):
            return True, "daily_free_use"
        cost = model_cfg.get("gem_cost", 0.0)
        balance = user_data.get("gem_balance", 0.0)
        if balance < cost:
            return False, f"Бесплатные попытки для «{model_cfg['name']}» закончились ({current_usage}/{model_cfg.get('limit', 0)}). Требуется: {cost:.1f}💎, у вас: {balance:.1f}💎."
        return True, "use_gems"
    return True, ""

async def increment_request_count(user_id: int, model_key: str, flag: str):
    model_cfg = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_cfg or not model_cfg.get("is_limited"): return
    if flag == "bonus_use":
        user_data = await firestore_service.get_user_data(user_id)
        bonus_left = user_data.get('news_bonus_uses_left', 0)
        if bonus_left > 0:
            await firestore_service.set_user_data(user_id, {'news_bonus_uses_left': bonus_left - 1})
            logger.info(f"User {user_id} consumed bonus use for {model_key}. Left: {bonus_left - 1}")
        return
    if flag == "use_gems":
        cost = model_cfg.get("gem_cost", 0.0)
        user_data = await firestore_service.get_user_data(user_id)
        balance = user_data.get("gem_balance", 0.0)
        new_balance = balance - cost
        await firestore_service.set_user_data(user_id, {'gem_balance': new_balance})
        logger.info(f"Deducted {cost} gems from user {user_id} for {model_key}. New balance: {new_balance:.1f}")
        return
    if flag == "daily_free_use":
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
        logger.info(f"Incremented daily count for user {user_id}, model {model_key} to {model_usage['count']}.")

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
    keyboard_rows = [[KeyboardButton(items[j]["text"]) for j in range(i, min(i + group_size, len(items)))]
                     for i in range(0, len(items), group_size)]
    if menu_config.get("is_submenu"):
        nav_row = [KeyboardButton("🏠 Главное меню")]
        if menu_config.get("parent"): nav_row.insert(0, KeyboardButton("⬅️ Назад"))
        keyboard_rows.append(nav_row)
    return ReplyKeyboardMarkup(keyboard_rows, resize_keyboard=True)

async def show_menu(update: Update, user_id: int, menu_key: str): 
    menu_cfg = MENU_STRUCTURE.get(menu_key)
    if not menu_cfg: 
        logger.error(f"Menu key '{menu_key}' not found. Defaulting to main for user {user_id}.")
        menu_key = BotConstants.MENU_MAIN
    await firestore_service.set_user_data(user_id, {'current_menu': menu_key})
    message_to_reply = update.effective_message if update.effective_message else update.message
    if not message_to_reply: 
        await update.get_bot().send_message(chat_id=user_id, text=MENU_STRUCTURE[menu_key]["title"], reply_markup=generate_menu_keyboard(menu_key), disable_web_page_preview=True)
        return
    await message_to_reply.reply_text(MENU_STRUCTURE[menu_key]["title"], reply_markup=generate_menu_keyboard(menu_key), disable_web_page_preview=True)

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
            parts.append(f"▫️ {cfg['name']}: <b>{cfg['gem_cost']:.1f} 💎</b> за запрос")
        elif limit_type == "daily_free_or_gems":
            usage = user_counts.get(key, {'count': 0, 'date': ''})
            count = usage['count'] if usage['date'] == today_str else 0
            parts.append(f"▫️ {cfg['name']}: <b>{count} / {cfg['limit']}</b> бесплатных, затем <b>{cfg['gem_cost']:.1f} 💎</b>")
    if (bonus_left := user_data.get('news_bonus_uses_left', 0)) > 0:
        bonus_model_name = AVAILABLE_TEXT_MODELS[CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY]['name']
        parts.append(f"\n✅ У вас есть <b>{bonus_left}</b> бонусных генераций для {bonus_model_name}.")
    await update.effective_message.reply_text("\n".join(parts), parse_mode=ParseMode.HTML, disable_web_page_preview=True, reply_markup=generate_menu_keyboard(user_data.get('current_menu', BotConstants.MENU_LIMITS_SUBMENU)))

async def claim_news_bonus_logic(update: Update, user_id: int):
    user_data = await firestore_service.get_user_data(user_id)
    reply_menu_key = user_data.get('current_menu', BotConstants.MENU_BONUS_SUBMENU)
    if MENU_STRUCTURE.get(reply_menu_key, {}).get("parent"): reply_menu_key = MENU_STRUCTURE[reply_menu_key]["parent"]
    else: reply_menu_key = BotConstants.MENU_MAIN
    bonus_model_config = AVAILABLE_TEXT_MODELS.get(CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY)
    if not bonus_model_config:
        await update.effective_message.reply_text("Настройка бонусной модели неисправна.", reply_markup=generate_menu_keyboard(reply_menu_key))
        return
    bonus_model_name = bonus_model_config['name']
    if user_data.get('claimed_news_bonus', False):
        uses_left = user_data.get('news_bonus_uses_left', 0)
        msg = f"Вы уже активировали бонус. " + (f"Осталось: <b>{uses_left}</b> для {bonus_model_name}." if uses_left > 0 else f"Бонус для {bonus_model_name} использован.")
        await update.effective_message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(reply_menu_key), disable_web_page_preview=True)
        return
    try:
        member_status = await update.get_bot().get_chat_member(chat_id=CONFIG.NEWS_CHANNEL_USERNAME, user_id=user_id)
        if member_status.status in ['member', 'administrator', 'creator']:
            await firestore_service.set_user_data(user_id, {'claimed_news_bonus': True, 'news_bonus_uses_left': CONFIG.NEWS_CHANNEL_BONUS_GENERATIONS})
            msg = f'🎉 Спасибо за подписку! Вам начислен бонус: <b>{CONFIG.NEWS_CHANNEL_BONUS_GENERATIONS}</b> генераций для {bonus_model_name}.'
            await update.effective_message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(BotConstants.MENU_MAIN), disable_web_page_preview=True)
            await firestore_service.set_user_data(user_id, {'current_menu': BotConstants.MENU_MAIN})
        else:
            msg = f'Для бонуса подпишитесь на <a href="{CONFIG.NEWS_CHANNEL_LINK}">{CONFIG.NEWS_CHANNEL_USERNAME}</a> и попробуйте снова.'
            inline_kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"📢 Перейти на {CONFIG.NEWS_CHANNEL_USERNAME}", url=CONFIG.NEWS_CHANNEL_LINK)]])
            await update.effective_message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=inline_kb, disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"News bonus claim error for user {user_id}: {e}")
        await update.effective_message.reply_text("Ошибка при проверке подписки. Попробуйте позже.", reply_markup=generate_menu_keyboard(reply_menu_key))

async def send_gems_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE, target: str):
    user_id = update.effective_user.id
    try:
        amount_str, price_str = target.split('_')
        amount, price = int(amount_str), int(price_str)
    except (ValueError, IndexError):
        await update.effective_message.reply_text("Ошибка в выборе пакета гемов.")
        return
    title = f"Покупка {amount} 💎"
    description = f"Пакет из {amount} гемов для использования в боте."
    payload = f"buy_gems_{amount}_user_{user_id}"
    await context.bot.send_invoice(chat_id=user_id, title=title, description=description, payload=payload, provider_token=CONFIG.PAYMENT_PROVIDER_TOKEN, currency="RUB", prices=[LabeledPrice(f"{amount} 💎", price * 100)])

async def show_help(update: Update, user_id: int):
    user_data = await firestore_service.get_user_data(user_id)
    help_text = "<b>❓ Справка...</b>" 
    await update.effective_message.reply_text(help_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(user_data.get('current_menu', BotConstants.MENU_HELP_SUBMENU)), disable_web_page_preview=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = await firestore_service.get_user_data(user_id)
    updates_to_db = {}
    if 'current_ai_mode' not in user_data: updates_to_db['current_ai_mode'] = CONFIG.DEFAULT_AI_MODE_KEY
    if 'current_menu' not in user_data: updates_to_db['current_menu'] = BotConstants.MENU_MAIN
    if 'gem_balance' not in user_data: updates_to_db['gem_balance'] = 0.0 
    default_model_cfg = AVAILABLE_TEXT_MODELS[CONFIG.DEFAULT_MODEL_KEY]
    if 'selected_model_id' not in user_data: updates_to_db['selected_model_id'] = default_model_cfg["id"]
    if updates_to_db: await firestore_service.set_user_data(user_id, updates_to_db)
    greeting = f"👋 Привет, {update.effective_user.first_name}!"
    await update.effective_message.reply_text(greeting, reply_markup=generate_menu_keyboard(BotConstants.MENU_MAIN))
    await firestore_service.set_user_data(user_id, {'current_menu': BotConstants.MENU_MAIN})

async def open_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE): await show_menu(update, update.effective_user.id, BotConstants.MENU_MAIN)
async def usage_command(update: Update, context: ContextTypes.DEFAULT_TYPE): await show_limits(update, update.effective_user.id)
async def get_bonus_command(update: Update, context: ContextTypes.DEFAULT_TYPE): await claim_news_bonus_logic(update, update.effective_user.id)
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE): await show_help(update, update.effective_user.id)

async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not (update.message and update.message.text): return
    user_id = update.effective_user.id
    button_text = update.message.text.strip()
    if not is_menu_button_text(button_text): return
    try: await update.message.delete()
    except Exception: pass
    user_data = await firestore_service.get_user_data(user_id)
    current_menu_key = user_data.get('current_menu', BotConstants.MENU_MAIN)
    if button_text == "⬅️ Назад":
        parent_key = MENU_STRUCTURE.get(current_menu_key, {}).get("parent", BotConstants.MENU_MAIN)
        await show_menu(update, user_id, parent_key)
        return
    if button_text == "🏠 Главное меню":
        await show_menu(update, user_id, BotConstants.MENU_MAIN)
        return
    action_item = next((item for menu_cfg in MENU_STRUCTURE.values() for item in menu_cfg.get("items", []) if item["text"] == button_text), None)
    if not action_item: return
    action, target = action_item["action"], action_item["target"]
    response_message = None
    # Определяем, в какое меню вернуться после действия
    # Если текущее меню это подменю, из которого было вызвано действие, то родитель - его родитель
    # Иначе - главное меню
    origin_menu_config = MENU_STRUCTURE.get(current_menu_key, MENU_STRUCTURE[BotConstants.MENU_MAIN])
    return_menu_after_action = origin_menu_config.get("parent", BotConstants.MENU_MAIN) if origin_menu_config.get("is_submenu") else BotConstants.MENU_MAIN


    if action == BotConstants.CALLBACK_ACTION_SUBMENU: await show_menu(update, user_id, target)
    elif action == BotConstants.CALLBACK_ACTION_SET_AGENT:
        await firestore_service.set_user_data(user_id, {'current_ai_mode': target})
        response_message = f"🤖 Агент изменен на: <b>{AI_MODES[target]['name']}</b>."
        await context.bot.send_message(chat_id=user_id, text=response_message, parse_mode=ParseMode.HTML)
        await show_menu(update, user_id, return_menu_after_action) # Возврат в предыдущее меню
    elif action == BotConstants.CALLBACK_ACTION_SET_MODEL:
        model_info = AVAILABLE_TEXT_MODELS[target]
        await firestore_service.set_user_data(user_id, {'selected_model_id': model_info["id"]})
        response_message = f"⚙️ Модель изменена на: <b>{model_info['name']}</b>."
        await context.bot.send_message(chat_id=user_id, text=response_message, parse_mode=ParseMode.HTML)
        await show_menu(update, user_id, return_menu_after_action) # Возврат в предыдущее меню
    elif action == BotConstants.CALLBACK_ACTION_SHOW_LIMITS: await show_limits(update, user_id) # show_limits сам управляет меню
    elif action == BotConstants.CALLBACK_ACTION_CHECK_BONUS: await claim_news_bonus_logic(update, user_id) # claim_news_bonus_logic сам управляет меню
    elif action == BotConstants.CALLBACK_ACTION_BUY_GEMS: await send_gems_invoice(update, context, target) # send_gems_invoice не меняет меню
    elif action == BotConstants.CALLBACK_ACTION_SHOW_HELP: await show_help(update, user_id) # show_help сам управляет меню
    

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not (update.message and update.message.text): return
    user_message_text = update.message.text.strip()
    if is_menu_button_text(user_message_text): return
    try: await update.message.delete()
    except Exception: pass
    if len(user_message_text) < CONFIG.MIN_AI_REQUEST_LENGTH:
        await update.message.reply_text("Ваш запрос слишком короткий.")
        return
    user_data = await firestore_service.get_user_data(user_id)
    model_key = await get_current_model_key(user_id, user_data)
    can_proceed, flag_or_msg = await check_and_log_request_attempt(user_id, model_key)
    if not can_proceed:
        await update.message.reply_text(flag_or_msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        return
    ai_service = get_ai_service(model_key)
    if not ai_service:
        await update.message.reply_text("Ошибка при выборе AI модели.")
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    mode_details = await get_current_mode_details(user_id, user_data)
    ai_response = await ai_service.generate_response(mode_details["prompt"], user_message_text)
    is_successful_response = not (
        ai_response.lower().startswith("ошибка") or 
        "не содержит текста" in ai_response.lower() or 
        "ответ google genai пуст" in ai_response.lower() or 
        "не удалось обработать ответ от сервера" in ai_response.lower() or
        ai_response.startswith("Неожиданная ошибка API"))
    final_reply, _ = smart_truncate(ai_response, CONFIG.MAX_MESSAGE_LENGTH_TELEGRAM)
    if is_successful_response:
        await increment_request_count(user_id, model_key, flag_or_msg)
    else:
        logger.warning(f"AI response error for user {user_id}. Usage not incremented. Response: {ai_response}")
    await update.message.reply_text(final_reply, parse_mode=ParseMode.HTML if '<' in final_reply and '>' in final_reply else None, disable_web_page_preview=True)

async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    if query.invoice_payload.startswith("buy_gems_") and query.invoice_payload.count('_') == 3: # buy_gems_{amount}_user_{user_id}
        await query.answer(ok=True)
    else:
        logger.warning(f"Invalid precheckout payload: {query.invoice_payload}")
        await query.answer(ok=False, error_message="Ошибка запроса.")

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    payment = update.message.successful_payment
    payload = payment.invoice_payload
    if payload.startswith("buy_gems_"):
        try:
            parts = payload.split('_')
            gems_to_add = int(parts[1]) # buy_gems_AMOUNT_user_USERID
            user_data = await firestore_service.get_user_data(user_id)
            new_balance = user_data.get('gem_balance', 0.0) + gems_to_add
            await firestore_service.set_user_data(user_id, {'gem_balance': new_balance})
            await update.message.reply_text(
                f"🎉 Оплата прошла! Вам начислено <b>{gems_to_add}💎</b>. Ваш новый баланс: <b>{new_balance:.1f}💎</b>.", 
                parse_mode=ParseMode.HTML)
            if CONFIG.ADMIN_ID and CONFIG.ADMIN_ID != 0 :
                admin_msg = f"🔔 Новая покупка: {gems_to_add}💎 от user {user_id} (@{update.effective_user.username or 'N/A'}). Сумма: {payment.total_amount / 100} {payment.currency}."
                await context.bot.send_message(CONFIG.ADMIN_ID, admin_msg)
        except (IndexError, ValueError) as e:
            logger.error(f"Failed to parse gem payment payload '{payload}': {e}")
            await update.message.reply_text("Ошибка при обработке платежа. Свяжитесь с поддержкой.")
    else:
        logger.warning(f"Unknown successful payment payload: {payload} from user {user_id}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    tb_string = "".join(traceback.format_exception(None, context.error, context.error.__traceback__))
    if isinstance(update, Update) and update.effective_chat:
        try: await context.bot.send_message(chat_id=update.effective_chat.id, text="Произошла внутренняя ошибка. Попробуйте /start.")
        except Exception: pass
    if CONFIG.ADMIN_ID and CONFIG.ADMIN_ID != 0:
        user_info = "N/A"; msg_text = "N/A"
        if isinstance(update, Update) and update.effective_user: user_info = f"ID: {update.effective_user.id} (@{update.effective_user.username or 'N/A'})"
        if isinstance(update, Update) and update.message and hasattr(update.message, 'text'): msg_text = update.message.text
        details = (f"🤖 Ошибка:\nUser: {user_info}\nMsg: {msg_text}\n"
                   f"Err: {context.error.__class__.__name__}: {context.error}\n\nTrace:\n```\n{tb_string[:3000]}\n```")
        try:
            escaped_details = telegram.helpers.escape_markdown(details, version=2)
            await context.bot.send_message(CONFIG.ADMIN_ID, escaped_details[:4096], parse_mode=ParseMode.MARKDOWN_V2)
        except Exception: 
            try: await context.bot.send_message(CONFIG.ADMIN_ID, details[:4096])
            except Exception as e_plain: logger.error(f"Failed to send plain text error report to admin: {e_plain}")

async def main():
    # Используем реальные ключи из CONFIG напрямую, если они там заданы (не "ЗАГЛУШКА_")
    if CONFIG.GOOGLE_GEMINI_API_KEY and not CONFIG.GOOGLE_GEMINI_API_KEY.startswith("ЗАГЛУШКА_") and CONFIG.GOOGLE_GEMINI_API_KEY.startswith("AIzaSy"):
        genai.configure(api_key=CONFIG.GOOGLE_GEMINI_API_KEY); logger.info("Google Gemini API configured.")
    else: logger.warning("Google Gemini API key not configured/invalid (using default or env var).")
    
    # Проверка остальных ключей, которые теперь могут быть реальными значениями по умолчанию в CONFIG
    for key_name_in_config, env_var_name in [
        ("TELEGRAM_TOKEN", "TELEGRAM_TOKEN"),
        ("PAYMENT_PROVIDER_TOKEN", "PAYMENT_PROVIDER_TOKEN"),
        ("CUSTOM_GEMINI_PRO_API_KEY", "CUSTOM_GEMINI_PRO_API_KEY"),
        ("CUSTOM_GROK_3_API_KEY", "CUSTOM_GROK_3_API_KEY"),
        ("CUSTOM_GPT4O_MINI_API_KEY", "CUSTOM_GPT4O_MINI_API_KEY")
    ]:
        key_value = getattr(CONFIG, key_name_in_config)
        if "ЗАГЛУШКА_" in key_value or "YOUR_TOKEN_HERE" in key_value: # Общая проверка на заглушки
             logger.warning(f"{env_var_name} is still a placeholder in AppConfig defaults and not overridden by environment variable.")
    
    if CONFIG.ADMIN_ID == 0: logger.warning("ADMIN_ID is 0 (default or env var). Admin notifications disabled.")
    
    if not firestore_service._db: logger.critical("Firestore not initialized! Bot cannot work."); return
    
    app = Application.builder().token(CONFIG.TELEGRAM_TOKEN).read_timeout(30).connect_timeout(30).build()
    handlers = [
        CommandHandler("start", start), CommandHandler("menu", open_menu_command),
        CommandHandler("usage", usage_command), CommandHandler("bonus", get_bonus_command),
        CommandHandler("help", help_command),
        MessageHandler(filters.TEXT & ~filters.COMMAND, menu_button_handler, block=False), 
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text), 
        PreCheckoutQueryHandler(precheckout_callback),
        MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback)
    ]
    for handler in handlers: app.add_handler(handler)
    app.add_error_handler(error_handler)
    
    bot_commands = [BotCommand("start", "🚀 Меню"), BotCommand("menu", "📋 Меню"),
                    BotCommand("usage", "📊 Лимиты"), BotCommand("bonus", "🎁 Бонус"), BotCommand("help", "❓ Справка")]
    await app.bot.set_my_commands(bot_commands)
    logger.info("Bot is starting...")
    await app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    asyncio.run(main())
