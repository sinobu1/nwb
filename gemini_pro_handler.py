import requests
import logging
import os
from typing import Optional, Tuple

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Конфигурация модели Gemini 2.5 Pro
GEMINI_PRO_CONFIG = {
    "name": "Gemini Pro",
    "id": "gemini-2.5-pro-preview-03-25",
    "api_type": "custom_http_api",
    "endpoint": os.getenv("CUSTOM_GEMINI_PRO_ENDPOINT", "https://api.gen-api.ru/api/v1/networks/gemini-2-5-pro"),
    "api_key_var_name": "CUSTOM_GEMINI_PRO_API_KEY",
    "is_limited": True,
    "limit_type": "subscription_custom_pro",
    "limit_if_no_subscription": 0,  # DEFAULT_FREE_REQUESTS_CUSTOM_PRO_DAILY
    "subscription_daily_limit": 25,  # DEFAULT_SUBSCRIPTION_REQUESTS_CUSTOM_PRO_DAILY
    "cost_category": "custom_api_pro_paid",
    "pricing_info": {}
}

# Ключ API для Gemini 2.5 Pro
CUSTOM_GEMINI_PRO_API_KEY = os.getenv("CUSTOM_GEMINI_PRO_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P")

# Максимальная длина ответа
MAX_OUTPUT_TOKENS = 2048

async def query_gemini_pro(system_prompt: str, user_message: str) -> Tuple[str, bool]:
    """
    Отправляет запрос к модели Gemini 2.5 Pro через custom HTTP API.
    
    Args:
        system_prompt (str): Системный промпт для модели.
        user_message (str): Сообщение пользователя.
    
    Returns:
        Tuple[str, bool]: Текст ответа и флаг, указывающий на успешность запроса.
    """
    if not CUSTOM_GEMINI_PRO_API_KEY or "YOUR_CUSTOM_KEY" in CUSTOM_GEMINI_PRO_API_KEY or not CUSTOM_GEMINI_PRO_API_KEY.startswith("sk-"):
        logger.error("Custom Gemini Pro API key is missing, a placeholder, or incorrectly formatted.")
        return "Ошибка конфигурации: Ключ API для модели Gemini Pro не настроен корректно. Пожалуйста, сообщите администратору.", False

    headers = {
        "Authorization": f"Bearer {CUSTOM_GEMINI_PRO_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ],
        "model": GEMINI_PRO_CONFIG["id"],
        "is_sync": True,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "temperature": 1.0,
        "top_p": 1.0,
        "n": 1,
        "stream": False
    }

    try:
        logger.info(f"Sending request to Gemini 2.5 Pro API: {GEMINI_PRO_CONFIG['endpoint']}")
        response = await asyncio.get_event_loop().run_in_executor(
            None, lambda: requests.post(GEMINI_PRO_CONFIG["endpoint"], headers=headers, json=payload, timeout=45)
        )
        response.raise_for_status()
        response_json = response.json()
        logger.debug(f"Raw JSON response from Gemini 2.5 Pro: {response_json}")

        # Извлечение текста ответа
        extracted_text = response_json.get("text", "").strip()
        if not extracted_text:
            logger.warning(f"No text content in Gemini 2.5 Pro response: {response_json}")
            return "Ответ от API не содержит текстовых данных или не удалось его извлечь.", False

        logger.info(f"Gemini 2.5 Pro response received. Length: {len(extracted_text)}")
        return extracted_text, True

    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTPError for Gemini 2.5 Pro API: {e}. Response: {e.response.text if e.response else 'No response'}", exc_info=True)
        return f"Ошибка сети при обращении к API Gemini Pro ({e.response.status_code}). Попробуйте позже.", False
    except requests.exceptions.RequestException as e:
        logger.error(f"RequestException for Gemini 2.5 Pro API: {e}", exc_info=True)
        return f"Сетевая ошибка при обращении к API Gemini Pro: {type(e).__name__}. Проверьте соединение или попробуйте позже.", False
    except Exception as e:
        logger.error(f"Unexpected error with Gemini 2.5 Pro API: {e}", exc_info=True)
        return f"Неожиданная ошибка при работе с API Gemini Pro: {type(e).__name__}.", False
