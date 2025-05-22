import telegram
from telegram import (
    ReplyKeyboardMarkup, KeyboardButton, Update,
    BotCommand, InlineKeyboardButton, InlineKeyboardMarkup,
    LabeledPrice
)
from telegram.constants import ParseMode, ChatAction
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, PreCheckoutQueryHandler, CallbackQueryHandler # Добавлен CallbackQueryHandler
)
import google.generativeai as genai
import google.api_core.exceptions
import requests # Оставлен, если используется для других целей, иначе можно удалить
import logging
import traceback
import os
import asyncio
import nest_asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple, List # Улучшены аннотации типов
import uuid

# Firebase
import firebase_admin
from firebase_admin import credentials, firestore, initialize_app
from firebase_admin.exceptions import FirebaseError
from google.cloud.firestore_v1.client import Client as FirestoreClient # Явный импорт для ясности

nest_asyncio.apply()

# --- Глобальная конфигурация логирования ---
# Принцип: Ясность и Стандартизация
# Логирование настраивается один раз и используется во всем приложении.
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- КОНСТАНТЫ ---
# Принцип: DRY (Don't Repeat Yourself) и Читаемость
# Использование констант вместо "магических строк" улучшает читаемость и упрощает изменения.

# Ключи конфигурации
CONFIG_TELEGRAM_TOKEN = "TELEGRAM_TOKEN"
CONFIG_GEMINI_API_KEY = "GOOGLE_GEMINI_API_KEY"
CONFIG_FIREBASE_CRED_PATH = "FIREBASE_CREDENTIALS_PATH"
CONFIG_FIREBASE_DB_URL = "FIREBASE_DATABASE_URL" # Пример, если используется Realtime Database URL
CONFIG_ADMIN_USER_ID = "ADMIN_USER_ID"
CONFIG_FREE_DAILY_LIMIT = "FREE_DAILY_LIMIT"
CONFIG_BONUS_CHANNEL_ID = "BONUS_CHANNEL_ID"
CONFIG_BONUS_CHANNEL_LINK = "BONUS_CHANNEL_LINK"
CONFIG_PAYMENT_PROVIDER_TOKEN = "PAYMENT_PROVIDER_TOKEN"
CONFIG_PRICE_AMOUNT_RUB = "PRICE_AMOUNT_RUB" # Сумма в копейках (e.g., 10000 for 100 RUB)
CONFIG_PRICE_LABEL = "PRICE_LABEL"
CONFIG_PRICE_DESCRIPTION = "PRICE_DESCRIPTION"
CONFIG_CURRENCY = "RUB" # Валюта платежа

# Названия коллекций Firestore
FIRESTORE_USERS_COLLECTION = "users"
FIRESTORE_PAYMENTS_COLLECTION = "payments"

# Тексты для кнопок и сообщений (примеры)
TEXT_MENU_BUTTON = "📋 Открыть меню"
TEXT_USAGE_BUTTON = "📊 Мои лимиты"
TEXT_SUBSCRIBE_BUTTON = "💎 О подписке"
# ... другие тексты

# Callback data префиксы (для Inline кнопок)
CALLBACK_PREFIX_ACTION = "action:"
# ... другие префиксы

# --- ЗАГРУЗКА КОНФИГУРАЦИИ ---
# Принцип: Централизация конфигурации, KISS
# Загрузка конфигурации из переменных окружения или значений по умолчанию.
def load_config() -> Dict[str, Any]:
    """Загружает конфигурацию из переменных окружения."""
    # Путь к файлу Firebase credentials из переменной окружения или по умолчанию
    default_firebase_creds_path = os.path.join(os.path.dirname(__file__), "firebase_credentials.json")

    config = {
        CONFIG_TELEGRAM_TOKEN: os.getenv(CONFIG_TELEGRAM_TOKEN, "YOUR_TELEGRAM_TOKEN"), # Замените на ваш токен
        CONFIG_GEMINI_API_KEY: os.getenv(CONFIG_GEMINI_API_KEY, "YOUR_GEMINI_API_KEY"), # Замените на ваш ключ
        CONFIG_FIREBASE_CRED_PATH: os.getenv(CONFIG_FIREBASE_CRED_PATH, default_firebase_creds_path),
        CONFIG_FIREBASE_DB_URL: os.getenv(CONFIG_FIREBASE_DB_URL, ""), # Если используете Firestore, это может не понадобиться
        CONFIG_ADMIN_USER_ID: int(os.getenv(CONFIG_ADMIN_USER_ID, "0")), # Замените на ваш ID администратора
        CONFIG_FREE_DAILY_LIMIT: int(os.getenv(CONFIG_FREE_DAILY_LIMIT, 5)),
        CONFIG_BONUS_CHANNEL_ID: os.getenv(CONFIG_BONUS_CHANNEL_ID, ""),
        CONFIG_BONUS_CHANNEL_LINK: os.getenv(CONFIG_BONUS_CHANNEL_LINK, ""),
        CONFIG_PAYMENT_PROVIDER_TOKEN: os.getenv(CONFIG_PAYMENT_PROVIDER_TOKEN, "YOUR_PAYMENT_PROVIDER_TOKEN"),
        CONFIG_PRICE_AMOUNT_RUB: int(os.getenv(CONFIG_PRICE_AMOUNT_RUB, 10000)), # Пример: 100 рублей
        CONFIG_PRICE_LABEL: os.getenv(CONFIG_PRICE_LABEL, "Подписка на бота"),
        CONFIG_PRICE_DESCRIPTION: os.getenv(CONFIG_PRICE_DESCRIPTION, "Доступ ко всем функциям на 30 дней"),
    }

    # Валидация критичных конфигурационных параметров
    if "YOUR_" in config[CONFIG_TELEGRAM_TOKEN] or not config[CONFIG_TELEGRAM_TOKEN]:
        logger.critical(f"{CONFIG_TELEGRAM_TOKEN} не настроен должным образом. Завершение работы.")
        raise ValueError(f"{CONFIG_TELEGRAM_TOKEN} не настроен.")
    if "YOUR_" in config[CONFIG_GEMINI_API_KEY] or not config[CONFIG_GEMINI_API_KEY]:
        logger.warning(f"{CONFIG_GEMINI_API_KEY} не настроен или указан неверно.")
    # Добавьте другие важные проверки

    return config

CONFIG = load_config()

# --- ИНИЦИАЛИЗАЦИЯ FIREBASE ---
# Принцип: SRP (Single Responsibility Principle), Обработка ошибок
# Отдельная функция для инициализации Firebase.
db: Optional[FirestoreClient] = None # Глобальная переменная для клиента Firestore

def initialize_firebase_app() -> Optional[FirestoreClient]:
    """Инициализирует Firebase приложение и возвращает клиент Firestore."""
    global db
    try:
        cred_path = CONFIG[CONFIG_FIREBASE_CRED_PATH]
        if not os.path.exists(cred_path):
            logger.error(f"Файл Firebase credentials не найден по пути: {cred_path}")
            return None

        cred = credentials.Certificate(cred_path)
        # Проверяем, не инициализировано ли уже приложение по умолчанию
        if not firebase_admin._apps:
            firebase_options = {'databaseURL': CONFIG[CONFIG_FIREBASE_DB_URL]} if CONFIG[CONFIG_FIREBASE_DB_URL] else {}
            initialize_app(cred, options=firebase_options)
            logger.info("Firebase приложение успешно инициализировано.")
        else:
            logger.info("Firebase приложение уже было инициализировано.")

        db = firestore.client()
        logger.info("Клиент Firestore успешно получен.")
        return db
    except FirebaseError as e:
        logger.error(f"Ошибка инициализации Firebase: {e}")
        logger.error(traceback.format_exc())
    except Exception as e:
        logger.error(f"Непредвиденная ошибка при инициализации Firebase: {e}")
        logger.error(traceback.format_exc())
    return None

# --- ИНИЦИАЛИЗАЦИЯ GOOGLE GEMINI ---
# Принцип: SRP, Обработка ошибок
def configure_gemini_api():
    """Конфигурирует Google Gemini API."""
    api_key = CONFIG[CONFIG_GEMINI_API_KEY]
    if api_key and "YOUR_" not in api_key and api_key.startswith("AIzaSy"):
        try:
            genai.configure(api_key=api_key)
            logger.info("Google Gemini API успешно сконфигурирован.")
        except Exception as e:
            logger.error(f"Ошибка конфигурации Google Gemini API: {e}")
            logger.error(traceback.format_exc())
    else:
        logger.warning(f"{CONFIG_GEMINI_API_KEY} не настроен или указан неверно. Функциональность Gemini будет недоступна.")

# --- УТИЛИТЫ FIREBASE ---
# Принцип: DRY, SRP, Читаемость, Обработка ошибок
# Функции для работы с Firestore, инкапсулирующие логику доступа к данным.

async def get_user_data(user_id: int) -> Optional[Dict[str, Any]]:
    """Получает данные пользователя из Firestore."""
    if not db:
        logger.error("Клиент Firestore не инициализирован. Невозможно получить данные пользователя.")
        return None
    try:
        user_ref = db.collection(FIRESTORE_USERS_COLLECTION).document(str(user_id))
        doc = await asyncio.to_thread(user_ref.get) # Используем asyncio.to_thread для синхронных вызовов
        if doc.exists:
            return doc.to_dict()
        return None
    except FirebaseError as e:
        logger.error(f"Firebase ошибка при получении данных пользователя {user_id}: {e}")
    except Exception as e:
        logger.error(f"Непредвиденная ошибка при получении данных пользователя {user_id}: {e}")
    return None

async def update_user_data(user_id: int, data: Dict[str, Any], merge: bool = True) -> bool:
    """Обновляет или создает данные пользователя в Firestore."""
    if not db:
        logger.error("Клиент Firestore не инициализирован. Невозможно обновить данные пользователя.")
        return False
    try:
        user_ref = db.collection(FIRESTORE_USERS_COLLECTION).document(str(user_id))
        await asyncio.to_thread(user_ref.set, data, merge=merge)
        logger.info(f"Данные пользователя {user_id} обновлены: {data if not merge else '(merged)'}")
        return True
    except FirebaseError as e:
        logger.error(f"Firebase ошибка при обновлении данных пользователя {user_id}: {e}")
    except Exception as e:
        logger.error(f"Непредвиденная ошибка при обновлении данных пользователя {user_id}: {e}")
    return False

async def check_or_create_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[Dict[str, Any]]:
    """Проверяет наличие пользователя в БД, создает запись если отсутствует."""
    if not update.effective_user:
        return None

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
            "subscription_until": None, # Дата окончания подписки
            "is_bonus_claimed": False
        }
        if await update_user_data(user_id, new_user_data, merge=False):
            logger.info(f"Создан новый пользователь: {user_id}")
            return new_user_data
        else:
            logger.error(f"Не удалось создать запись для нового пользователя: {user_id}")
            return None
    else:
        # Обновляем дату последней активности
        await update_user_data(user_id, {"last_activity_date": firestore.SERVER_TIMESTAMP})
        return user_data
    return user_data # Возвращаем данные пользователя

# --- УТИЛИТЫ GEMINI API ---
# Принцип: SRP, Обработка ошибок
async def generate_text_with_gemini(prompt: str) -> Optional[str]:
    """Генерирует текст с помощью Google Gemini API."""
    if not genai._configured: # Проверяем, сконфигурирован ли API
        logger.warning("Gemini API не сконфигурирован. Генерация текста невозможна.")
        return None
    try:
        # Убедитесь, что используете модель, подходящую для ваших задач
        # Например, 'gemini-pro' для текстовых задач
        model = genai.GenerativeModel('gemini-1.5-flash-latest') # или другая актуальная модель
        response = await asyncio.to_thread(model.generate_content, prompt)
        return response.text
    except google.api_core.exceptions.GoogleAPIError as e:
        logger.error(f"Ошибка Google Gemini API: {e}")
    except Exception as e:
        logger.error(f"Непредвиденная ошибка при генерации текста Gemini: {e}")
    return None

# --- УТИЛИТЫ TELEGRAM (КЛАВИАТУРЫ, СООБЩЕНИЯ) ---
# Принцип: DRY, Читаемость
def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Возвращает клавиатуру главного меню."""
    keyboard = [
        [InlineKeyboardButton(TEXT_USAGE_BUTTON, callback_data=f"{CALLBACK_PREFIX_ACTION}usage")],
        [InlineKeyboardButton(TEXT_SUBSCRIBE_BUTTON, callback_data=f"{CALLBACK_PREFIX_ACTION}subscribe_info")],
        # Добавьте другие кнопки по необходимости
    ]
    return InlineKeyboardMarkup(keyboard)

async def send_typing_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет действие 'печатает...'."""
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

# --- ОБРАБОТЧИКИ КОМАНД ---
# Принцип: SRP, Читаемость, KISS
# Каждый обработчик отвечает за свою команду. Сложная логика выносится в утилиты.

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start. Приветствует пользователя и показывает меню."""
    user = update.effective_user
    if not user: return

    await check_or_create_user(update, context) # Проверка и создание пользователя

    logger.info(f"Пользователь {user.id} ({user.username}) запустил команду /start.")
    reply_text = f"👋 Привет, {user.first_name}!\nЯ твой бот-помощник. Чем могу помочь?"
    await update.message.reply_html(reply_text, reply_markup=get_main_menu_keyboard())

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /menu. Показывает главное меню."""
    user = update.effective_user
    if not user: return

    await check_or_create_user(update, context)

    logger.info(f"Пользователь {user.id} ({user.username}) запросил меню.")
    await update.message.reply_html("📋 **Главное меню:**", reply_markup=get_main_menu_keyboard())

async def usage_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /usage. Показывает лимиты пользователя."""
    user = update.effective_user
    if not user: return

    user_data = await check_or_create_user(update, context)
    if not user_data:
        await update.message.reply_text("Не удалось получить ваши данные. Попробуйте позже.")
        return

    requests_today = user_data.get("requests_today", 0)
    daily_limit = CONFIG[CONFIG_FREE_DAILY_LIMIT]
    subscription_until_ts = user_data.get("subscription_until")
    subscription_status = "не активна"

    if subscription_until_ts:
        # Преобразуем Timestamp Firebase в datetime
        if isinstance(subscription_until_ts, datetime):
            subscription_until_dt = subscription_until_ts.replace(tzinfo=timezone.utc)
        else: # Предполагаем, что это google.cloud.firestore_v1.base_document.SERVER_TIMESTAMP или уже datetime
             # Для простоты, если это не datetime, считаем, что подписка неактивна или требует конвертации
            try:
                # Попытка конвертации, если это стандартный timestamp Firestore
                subscription_until_dt = datetime.fromtimestamp(subscription_until_ts.seconds, tz=timezone.utc)
            except AttributeError: # Если это не Timestamp объект
                 subscription_until_dt = None


        if subscription_until_dt and subscription_until_dt > datetime.now(timezone.utc):
            subscription_status = f"активна до {subscription_until_dt.strftime('%d.%m.%Y %H:%M')} UTC"
            # Если подписка активна, лимиты могут быть другими или отсутствовать
            # Это нужно реализовать в логике проверки лимитов
            # Для примера, пока оставим так:
            limit_text = f"У вас активная подписка! Лимиты не действуют."
        else:
            limit_text = f"Использовано сегодня: {requests_today} из {daily_limit} (бесплатных)."
    else:
        limit_text = f"Использовано сегодня: {requests_today} из {daily_limit} (бесплатных)."


    reply_text = (
        f"📊 **Ваши лимиты:**\n\n"
        f"{limit_text}\n"
        f"Подписка: {subscription_status}"
    )
    await update.message.reply_html(reply_text)


async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /subscribe. Информация о подписке и кнопка оплаты."""
    user = update.effective_user
    if not user: return

    await check_or_create_user(update, context)

    price_label = CONFIG[CONFIG_PRICE_LABEL]
    price_description = CONFIG[CONFIG_PRICE_DESCRIPTION]
    price_amount = CONFIG[CONFIG_PRICE_AMOUNT_RUB] # в копейках
    currency = CONFIG[CONFIG_CURRENCY]

    reply_text = (
        f"💎 **Информация о подписке:**\n\n"
        f"Получите неограниченный доступ ко всем функциям бота!\n"
        f"Стоимость: {price_amount / 100:.2f} {currency} на 30 дней.\n\n"
        f"Нажмите кнопку ниже, чтобы оформить подписку."
    )

    # Создаем инвойс
    payload = f"subscribe_payload_{user.id}_{uuid.uuid4()}" # Уникальный payload для отслеживания
    
    # Кнопка оплаты
    keyboard = [[InlineKeyboardButton("💳 Оплатить подписку", pay=True)]] # pay=True не работает так для инвойсов
                                                                        # Вместо этого, мы отправим инвойс отдельной командой
    
    # Правильный способ - отправить инвойс
    # await context.bot.send_invoice(...)
    # Для простоты примера, покажем информацию и предложим команду для оплаты
    # или кнопку, которая вызовет send_invoice
    
    payment_button = InlineKeyboardButton(
        f"💳 Оплатить {price_amount / 100:.2f} {currency}",
        callback_data=f"{CALLBACK_PREFIX_ACTION}pay_subscription"
    )
    reply_markup = InlineKeyboardMarkup([[payment_button]])

    await update.message.reply_html(reply_text, reply_markup=reply_markup)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /help."""
    user = update.effective_user
    if not user: return
    await check_or_create_user(update, context)
    
    help_text = (
        "❓ **Справка по боту:**\n\n"
        "/start - Перезапуск и главное меню\n"
        "/menu - Открыть главное меню\n"
        "/usage - Узнать текущие лимиты\n"
        "/subscribe - Информация о подписке\n"
        "/help - Эта справка\n\n"
        # Добавьте описание других функций
        "Если у вас возникли проблемы, обратитесь к администратору." # (укажите контакт, если нужно)
    )
    await update.message.reply_html(help_text)

# --- ОБРАБОТЧИК ТЕКСТОВЫХ СООБЩЕНИЙ ---
async def message_handler_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает текстовые сообщения от пользователя."""
    user = update.effective_user
    if not user or not update.message or not update.message.text:
        return

    user_input = update.message.text
    logger.info(f"Пользователь {user.id} ({user.username}) отправил текст: '{user_input}'")

    user_data = await check_or_create_user(update, context)
    if not user_data:
        await update.message.reply_text("Произошла ошибка при обработке вашего профиля. Попробуйте позже.")
        return

    # Проверка лимитов
    requests_today = user_data.get("requests_today", 0)
    daily_limit = CONFIG[CONFIG_FREE_DAILY_LIMIT]
    subscription_until_ts = user_data.get("subscription_until")
    is_subscribed = False

    if subscription_until_ts:
        if isinstance(subscription_until_ts, datetime):
            subscription_until_dt = subscription_until_ts.replace(tzinfo=timezone.utc)
        else:
            try:
                subscription_until_dt = datetime.fromtimestamp(subscription_until_ts.seconds, tz=timezone.utc)
            except AttributeError:
                subscription_until_dt = None
        
        if subscription_until_dt and subscription_until_dt > datetime.now(timezone.utc):
            is_subscribed = True

    if not is_subscribed and requests_today >= daily_limit:
        await update.message.reply_text(
            "Вы достигли дневного лимита бесплатных запросов. "
            "Чтобы продолжить, оформите подписку (/subscribe) или попробуйте завтра."
        )
        return

    await send_typing_action(update, context) # Показываем, что бот "думает"

    # Генерация ответа с помощью Gemini
    # Пример простого промпта. Адаптируйте под свои нужды.
    prompt = f"Ответь на следующий вопрос пользователя: {user_input}"
    bot_response = await generate_text_with_gemini(prompt)

    if bot_response:
        await update.message.reply_text(bot_response)
        if not is_subscribed: # Увеличиваем счетчик только для бесплатных пользователей
            await update_user_data(user.id, {"requests_today": requests_today + 1})
    else:
        await update.message.reply_text("К сожалению, не удалось сгенерировать ответ. Попробуйте позже.")


# --- ОБРАБОТЧИК CALLBACK QUERIES (Inline кнопки) ---
async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает нажатия на inline-кнопки."""
    query = update.callback_query
    await query.answer() # Важно ответить на callback, чтобы кнопка перестала "грузиться"

    user = update.effective_user
    if not user or not query.data: return

    logger.info(f"Пользователь {user.id} нажал кнопку с callback_data: {query.data}")
    
    # Проверка и создание пользователя (на всякий случай, если это первое взаимодействие через кнопку)
    await check_or_create_user(update, context)

    # Разбор callback_data
    if query.data.startswith(CALLBACK_PREFIX_ACTION):
        action = query.data.split(CALLBACK_PREFIX_ACTION, 1)[1]

        if action == "usage":
            # Переиспользуем существующий обработчик команды, если логика идентична
            # Для этого создадим "фиктивное" сообщение для usage_command
            class MockMessage:
                async def reply_html(self, text, reply_markup=None):
                    await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
                async def reply_text(self, text, reply_markup=None): # на случай если usage_command использует reply_text
                    await query.edit_message_text(text=text, reply_markup=reply_markup)


            mock_update = Update(update.update_id, message=MockMessage(), effective_user=user, callback_query=query)
            await usage_command(mock_update, context) # Вызываем как команду

        elif action == "subscribe_info":
            # Аналогично для информации о подписке
            class MockMessageSub:
                async def reply_html(self, text, reply_markup=None):
                    # Если сообщение уже есть, редактируем. Если нет (редко для callback), отправляем новое.
                    try:
                        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
                    except telegram.error.BadRequest as e:
                        if "message is not modified" in str(e).lower():
                            pass # Ничего страшного, сообщение не изменилось
                        elif "message to edit not found" in str(e).lower() or query.message is None:
                             if query.message: # Если есть исходное сообщение от кнопки
                                await query.message.reply_html(text=text, reply_markup=reply_markup)
                             else: # Если нет, отправляем новое в чат (маловероятно для callback)
                                await context.bot.send_message(chat_id=user.id, text=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

                        else:
                            raise e # Другая ошибка BadRequest

            mock_update_sub = Update(update.update_id, message=MockMessageSub(), effective_user=user, callback_query=query)
            await subscribe_command(mock_update_sub, context)

        elif action == "pay_subscription":
            # Логика отправки инвойса
            await send_payment_invoice(update, context)

        # Добавьте другие обработчики действий по callback_data
        else:
            await query.edit_message_text(text=f"Действие '{action}' в разработке.")
    else:
        await query.edit_message_text(text="Неизвестное действие.")


# --- ПЛАТЕЖИ ---
async def send_payment_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет инвойс на оплату."""
    chat_id = update.effective_chat.id if update.effective_chat else update.effective_user.id
    user_id = update.effective_user.id

    title = CONFIG[CONFIG_PRICE_LABEL]
    description = CONFIG[CONFIG_PRICE_DESCRIPTION]
    payload = f"sub_{user_id}_{int(datetime.now().timestamp())}" # Уникальный payload
    provider_token = CONFIG[CONFIG_PAYMENT_PROVIDER_TOKEN]
    currency = CONFIG[CONFIG_CURRENCY]
    price = CONFIG[CONFIG_PRICE_AMOUNT_RUB] # Цена в минимальных единицах валюты (копейки для RUB)

    if not provider_token or "YOUR_" in provider_token:
        logger.error("Токен провайдера платежей не настроен!")
        # Сообщаем пользователю, если это callback от кнопки
        if update.callback_query:
            await update.callback_query.message.reply_text("К сожалению, оплата временно недоступна. Попробуйте позже.")
        elif update.message: # Если это команда
            await update.message.reply_text("К сожалению, оплата временно недоступна. Попробуйте позже.")
        return

    prices = [LabeledPrice(label=title, amount=price)]

    try:
        await context.bot.send_invoice(
            chat_id, title, description, payload, provider_token, currency, prices,
            # photo_url='URL_TO_YOUR_PRODUCT_IMAGE', # Опционально
            # photo_size=128, # Опционально
            # photo_width=128, # Опционально
            # photo_height=128, # Опционально
            # need_name=True, # Опционально, запрашивать ли имя
            # need_phone_number=True, # Опционально
            # need_email=True, # Опционально
            # need_shipping_address=False, # Опционально
            # send_phone_number_to_provider=True, # Опционально
            # send_email_to_provider=True, # Опционально
            # is_flexible=False # Опционально, для динамических цен доставки
        )
        logger.info(f"Инвойс отправлен пользователю {user_id} с payload: {payload}")
    except telegram.error.TelegramError as e:
        logger.error(f"Ошибка отправки инвойса пользователю {user_id}: {e}")
        if update.callback_query:
            await update.callback_query.message.reply_text("Не удалось создать счет на оплату. Пожалуйста, попробуйте позже.")
        elif update.message:
            await update.message.reply_text("Не удалось создать счет на оплату. Пожалуйста, попробуйте позже.")


async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает pre-checkout запросы от Telegram после того, как пользователь ввел платежные данные."""
    query = update.pre_checkout_query
    if not query: return

    # Здесь вы можете проверить payload, доступность товара и т.д.
    # Например, query.invoice_payload
    logger.info(f"PreCheckoutQuery от пользователя {query.from_user.id} с payload: {query.invoice_payload}")

    # Если все в порядке, подтверждаем платеж
    await query.answer(ok=True)
    # Если есть проблема, отвечаем с ошибкой:
    # await query.answer(ok=False, error_message="Извините, возникла проблема с обработкой вашего заказа.")

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает сообщение об успешном платеже."""
    message = update.message
    if not message or not message.successful_payment: return

    user_id = message.from_user.id
    payment_info = message.successful_payment
    logger.info(
        f"Успешный платеж от пользователя {user_id}: "
        f"Сумма: {payment_info.total_amount / 100} {payment_info.currency}, "
        f"Payload: {payment_info.invoice_payload}, "
        f"Telegram Payment ID: {payment_info.telegram_payment_charge_id}, "
        f"Provider Payment ID: {payment_info.provider_payment_charge_id}"
    )

    # Обновляем данные пользователя в Firestore
    # Предположим, что подписка на 30 дней
    subscription_end_date = datetime.now(timezone.utc) + timedelta(days=30)
    user_update_data = {
        "subscription_until": subscription_end_date,
        "last_payment_date": firestore.SERVER_TIMESTAMP,
        "last_payment_amount": payment_info.total_amount,
        "last_payment_currency": payment_info.currency,
        "requests_today": 0 # Сбрасываем дневной лимит
    }
    if await update_user_data(user_id, user_update_data):
        logger.info(f"Подписка для пользователя {user_id} продлена до {subscription_end_date.isoformat()}")
        await message.reply_text(
            f"🎉 Спасибо за оплату! Ваша подписка активна до {subscription_end_date.strftime('%d.%m.%Y %H:%M')} UTC."
        )
    else:
        logger.error(f"Не удалось обновить данные о подписке для пользователя {user_id} после оплаты.")
        # Важно обработать этот случай: возможно, потребуется ручное вмешательство или повторная попытка
        await message.reply_text(
            "Спасибо за оплату! Возникла проблема с автоматической активацией подписки. "
            "Пожалуйста, свяжитесь с администратором, если подписка не активируется в ближайшее время."
        )

    # Сохраняем информацию о платеже в отдельную коллекцию (опционально, для отчетности)
    if db:
        try:
            payment_record = {
                "user_id": user_id,
                "telegram_user_id": message.from_user.id, # Для связки, если user_id не Telegram ID
                "username": message.from_user.username or "",
                "amount": payment_info.total_amount,
                "currency": payment_info.currency,
                "invoice_payload": payment_info.invoice_payload,
                "telegram_payment_charge_id": payment_info.telegram_payment_charge_id,
                "provider_payment_charge_id": payment_info.provider_payment_charge_id,
                "payment_date": firestore.SERVER_TIMESTAMP,
                "order_info": payment_info.order_info.to_dict() if payment_info.order_info else None
            }
            await asyncio.to_thread(
                db.collection(FIRESTORE_PAYMENTS_COLLECTION).document(payment_info.telegram_payment_charge_id).set,
                payment_record
            )
            logger.info(f"Запись о платеже {payment_info.telegram_payment_charge_id} сохранена в Firestore.")
        except Exception as e:
            logger.error(f"Ошибка сохранения записи о платеже в Firestore: {e}")


# --- ОБРАБОТЧИК ОШИБОК ---
# Принцип: Четкая обратная связь, Логирование
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Логирует ошибки и отправляет пользователю сообщение о проблеме."""
    logger.error(msg="Исключение при обработке обновления:", exc_info=context.error)

    # Собираем traceback для подробного логирования
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)
    logger.error(f"Traceback:\n{tb_string}")

    # Формируем сообщение для пользователя (без технических деталей)
    user_message = "😕 Ой, что-то пошло не так. Мы уже разбираемся в проблеме. Пожалуйста, попробуйте позже."

    # Если ошибка связана с API Gemini, можно дать более конкретное сообщение
    if isinstance(context.error, google.api_core.exceptions.GoogleAPIError):
        user_message = "Возникла проблема при обращении к нейросети. Попробуйте изменить запрос или повторите попытку позже."
    elif isinstance(context.error, telegram.error.NetworkError):
         user_message = "Проблема с сетевым подключением. Пожалуйста, проверьте ваше интернет-соединение и попробуйте снова."
    # Добавьте другие типы ошибок, если необходимо

    # Отправляем сообщение пользователю, если это возможно
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(user_message)
        except telegram.error.TelegramError as e:
            logger.error(f"Не удалось отправить сообщение об ошибке пользователю: {e}")
    elif isinstance(update, Update) and update.callback_query and update.callback_query.message:
        try:
            await update.callback_query.message.reply_text(user_message)
        except telegram.error.TelegramError as e:
            logger.error(f"Не удалось отправить сообщение об ошибке пользователю (callback): {e}")


    # Уведомление администратора (опционально)
    admin_user_id = CONFIG[CONFIG_ADMIN_USER_ID]
    if admin_user_id and admin_user_id != 0: # Проверяем, что ID администратора задан
        try:
            # Собираем больше контекста для администратора
            error_details_for_admin = f"Ошибка в боте:\n"
            error_details_for_admin += f"Тип: {type(context.error).__name__}\n"
            error_details_for_admin += f"Сообщение: {context.error}\n"
            if isinstance(update, Update):
                if update.effective_user:
                    error_details_for_admin += f"Пользователь: {update.effective_user.id} (@{update.effective_user.username})\n"
                if update.effective_message and update.effective_message.text:
                     error_details_for_admin += f"Сообщение: {update.effective_message.text[:200]}\n" # Первые 200 символов
                elif update.callback_query and update.callback_query.data:
                     error_details_for_admin += f"Callback: {update.callback_query.data}\n"

            # Ограничиваем длину сообщения для Telegram
            max_len = 4000
            if len(tb_string) + len(error_details_for_admin) > max_len:
                available_space_for_tb = max_len - len(error_details_for_admin) - 20 # 20 для запаса
                truncated_tb = tb_string[:available_space_for_tb] + "\n... (traceback truncated)"
                admin_message_text = error_details_for_admin + "\n" + truncated_tb
            else:
                admin_message_text = error_details_for_admin + "\n" + tb_string

            await context.bot.send_message(chat_id=admin_user_id, text=admin_message_text[:4096]) # Telegram лимит
        except Exception as e_admin:
            logger.error(f"Не удалось отправить уведомление об ошибке администратору: {e_admin}")


# --- ОСНОВНАЯ ФУНКЦИЯ ---
async def main() -> None:
    """Запускает бота."""
    global db # Делаем db доступным для main

    # 1. Инициализация Firebase
    db = initialize_firebase_app()
    if not db:
        logger.critical("Не удалось инициализировать Firebase. Бот не может продолжить работу с базой данных.")
        # Можно решить, останавливать ли бота полностью или работать без БД
        # return # Раскомментируйте, если работа без БД невозможна

    # 2. Конфигурация Gemini API
    configure_gemini_api()

    # 3. Создание экземпляра Application
    # Принцип: Ясность
    # Используем context_types для удобства работы с кастомным контекстом (если понадобится)
    # persistence = PicklePersistence(filepath="bot_data_persistence") # Опционально для сохранения данных между перезапусками
    application = (
        Application.builder()
        .token(CONFIG[CONFIG_TELEGRAM_TOKEN])
        # .persistence(persistence) # Раскомментируйте, если используете persistence
        .build()
    )

    # 4. Регистрация обработчиков
    # Принцип: Модульность, SRP
    # Каждый тип обновления обрабатывается своим хендлером.
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CommandHandler("usage", usage_command))
    application.add_handler(CommandHandler("subscribe", subscribe_command))
    application.add_handler(CommandHandler("help", help_command))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler_text))
    application.add_handler(CallbackQueryHandler(button_callback_handler))

    # Обработчики платежей
    application.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))


    # 5. Регистрация обработчика ошибок (должен быть последним)
    application.add_error_handler(error_handler)

    # 6. Установка команд бота
    # Принцип: Удобство пользователя
    bot_commands = [
        BotCommand("start", "🚀 Перезапуск / Главное меню"),
        BotCommand("menu", "📋 Открыть меню"),
        BotCommand("usage", "📊 Мои лимиты"),
        BotCommand("subscribe", "💎 Информация о подписке"),
        BotCommand("help", "❓ Справка по боту"),
    ]
    try:
        await application.bot.set_my_commands(bot_commands)
        logger.info("Команды бота успешно установлены.")
    except Exception as e:
        logger.error(f"Не удалось установить команды бота: {e}")

    # 7. Запуск бота
    logger.info("Запуск бота в режиме опроса (polling)...")
    # allowed_updates можно настроить для получения только нужных типов обновлений
    await application.run_polling(allowed_updates=Update.ALL_TYPES, timeout=30)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except ValueError as e: # Перехватываем ошибку валидации конфигурации
        logger.critical(f"Ошибка запуска бота: {e}")
    except KeyboardInterrupt:
        logger.info("Бот остановлен вручную.")
    except Exception as e:
        logger.critical(f"Непредвиденная критическая ошибка при запуске бота: {e}")
        logger.critical(traceback.format_exc())
