import telegram
from telegram import (
    Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
)
from telegram.constants import ParseMode, ChatAction
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, PreCheckoutQueryHandler
)
import logging
import traceback
import os
import asyncio
import nest_asyncio
from datetime import datetime, timezone, timedelta # Нужен для _store_and_try_delete_message

# Импорт из локального файла bot_core.py
from bot_core import (
    CONFIG, BotConstants, AI_MODES, AVAILABLE_TEXT_MODELS, MENU_STRUCTURE, DEFAULT_MODEL_ID,
    firestore_service, get_ai_service,
    get_current_model_key, get_current_mode_details, smart_truncate,
    is_user_profi_subscriber, get_user_actual_limit_for_model,
    check_and_log_request_attempt, increment_request_count,
    is_menu_button_text, generate_menu_keyboard
)
import google.generativeai as genai # Для конфигурации в main

nest_asyncio.apply() # Если используется Jupyter или другие среды с существующим циклом
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


# --- УПРАВЛЕНИЕ СООБЩЕНИЯМИ И ДЕКОРАТОРЫ ---
async def _store_and_try_delete_message(update: Update, user_id: int, is_command_to_keep: bool = False):
    if not update.message: return

    message_id_to_process = update.message.message_id
    timestamp_now_iso = datetime.now(timezone.utc).isoformat()
    chat_id = update.effective_chat.id
    
    user_data_for_msg_handling = await firestore_service.get_user_data(user_id)
    prev_command_info = user_data_for_msg_handling.pop('user_command_to_delete', None)

    if prev_command_info and prev_command_info.get('message_id'):
        try:
            prev_msg_time = datetime.fromisoformat(prev_command_info['timestamp'])
            if prev_msg_time.tzinfo is None: prev_msg_time = prev_msg_time.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - prev_msg_time <= timedelta(hours=48):
                await update.get_bot().delete_message(chat_id=chat_id, message_id=prev_command_info['message_id'])
                logger.info(f"Successfully deleted previous user message {prev_command_info['message_id']}")
        except (telegram.error.BadRequest, ValueError) as e:
            logger.warning(f"Failed to delete/process previous user message {prev_command_info.get('message_id')}: {e}")
    
    if not is_command_to_keep:
        user_data_for_msg_handling['user_command_to_delete'] = {
            'message_id': message_id_to_process, 'timestamp': timestamp_now_iso
        }
        try:
            await update.get_bot().delete_message(chat_id=chat_id, message_id=message_id_to_process)
            logger.info(f"Successfully deleted current user message {message_id_to_process} (not kept).")
            user_data_for_msg_handling.pop('user_command_to_delete', None)
        except telegram.error.BadRequest as e:
            logger.warning(f"Failed to delete current user message {message_id_to_process}: {e}. Will try next time if stored.")
    else:
         user_data_for_msg_handling['user_command_message_to_keep'] = {
            'message_id': message_id_to_process, 'timestamp': timestamp_now_iso
        }
    await firestore_service.set_user_data(user_id, user_data_for_msg_handling)

def auto_delete_message_decorator(is_command_to_keep: bool = False):
    def decorator(func):
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if update.effective_user and update.message:
                 await _store_and_try_delete_message(update, update.effective_user.id, is_command_to_keep)
            return await func(update, context)
        return wrapper
    return decorator

# --- ОТОБРАЖЕНИЕ МЕНЮ И ИНФОРМАЦИИ ---
async def show_menu(update: Update, user_id: int, menu_key: str, user_data_param: Optional[Dict[str, Any]] = None):
    menu_cfg = MENU_STRUCTURE.get(menu_key)
    if not menu_cfg:
        logger.error(f"Menu key '{menu_key}' not found. Defaulting to main menu for user {user_id}.")
        await update.message.reply_text(
            "Ошибка: Меню не найдено. Показываю главное меню.",
            reply_markup=generate_menu_keyboard(BotConstants.MENU_MAIN)
        )
        await firestore_service.set_user_data(user_id, {'current_menu': BotConstants.MENU_MAIN})
        return

    await firestore_service.set_user_data(user_id, {'current_menu': menu_key})
    await update.message.reply_text(
        menu_cfg["title"],
        reply_markup=generate_menu_keyboard(menu_key),
        disable_web_page_preview=True
    )
    logger.info(f"User {user_id} shown menu '{menu_key}'.")

# --- ОБРАБОТЧИКИ КОМАНД TELEGRAM ---
@auto_delete_message_decorator(is_command_to_keep=True)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_first_name = update.effective_user.first_name
    user_data_loc = await firestore_service.get_user_data(user_id)
    updates_to_user_data = {}

    if 'current_ai_mode' not in user_data_loc:
        updates_to_user_data['current_ai_mode'] = CONFIG.DEFAULT_AI_MODE_KEY
    if 'current_menu' not in user_data_loc:
        updates_to_user_data['current_menu'] = BotConstants.MENU_MAIN
        
    default_model_config = AVAILABLE_TEXT_MODELS[CONFIG.DEFAULT_MODEL_KEY]
    if 'selected_model_id' not in user_data_loc:
        updates_to_user_data['selected_model_id'] = default_model_config["id"]
    if 'selected_api_type' not in user_data_loc:
        updates_to_user_data['selected_api_type'] = default_model_config.get("api_type")

    if updates_to_user_data:
        await firestore_service.set_user_data(user_id, updates_to_user_data)
        user_data_loc.update(updates_to_user_data)

    current_model_key_val = await get_current_model_key(user_id, user_data_loc)
    mode_details_res = await get_current_mode_details(user_id, user_data_loc)
    model_details_res = AVAILABLE_TEXT_MODELS.get(current_model_key_val)
    mode_name = mode_details_res['name'] if mode_details_res else "N/A"
    model_name = model_details_res['name'] if model_details_res else "N/A"

    greeting_message = (
        f"👋 Привет, {user_first_name}!\n\n"
        f"🤖 Текущий агент: <b>{mode_name}</b>\n"
        f"⚙️ Активная модель: <b>{model_name}</b>\n\n"
        "Я готов к вашим запросам! Используйте текстовые сообщения для общения с ИИ "
        "или кнопки меню для навигации и настроек."
    )
    await update.message.reply_text(
        greeting_message, parse_mode=ParseMode.HTML,
        reply_markup=generate_menu_keyboard(BotConstants.MENU_MAIN),
        disable_web_page_preview=True
    )
    await firestore_service.set_user_data(user_id, {'current_menu': BotConstants.MENU_MAIN})
    logger.info(f"User {user_id} ({user_first_name}) started/restarted the bot.")

@auto_delete_message_decorator()
async def open_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_menu(update, update.effective_user.id, BotConstants.MENU_MAIN)

@auto_delete_message_decorator()
async def usage_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_limits(update, update.effective_user.id)

@auto_delete_message_decorator()
async def subscribe_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_subscription(update, update.effective_user.id)

@auto_delete_message_decorator()
async def get_news_bonus_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await claim_news_bonus_logic(update, update.effective_user.id)

@auto_delete_message_decorator()
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_help(update, update.effective_user.id)

# --- ЛОГИКА ОТОБРАЖЕНИЯ ИНФОРМАЦИИ (лимиты, подписка, помощь) ---
async def show_limits(update: Update, user_id: int):
    user_data_loc = await firestore_service.get_user_data(user_id)
    bot_data_loc = await firestore_service.get_bot_data()
    user_subscriptions = bot_data_loc.get(BotConstants.FS_USER_SUBSCRIPTIONS_KEY, {}).get(str(user_id), {})
    is_profi = is_user_profi_subscriber(user_subscriptions)
    subscription_status_display = "Бесплатный"
    if is_profi:
        try:
            valid_until_dt = datetime.fromisoformat(user_subscriptions['valid_until'])
            if valid_until_dt.tzinfo is None: valid_until_dt = valid_until_dt.replace(tzinfo=timezone.utc)
            subscription_status_display = f"Профи (активна до {valid_until_dt.strftime('%d.%m.%Y')})"
        except (ValueError, KeyError): subscription_status_display = "Профи (ошибка в дате)"
    elif user_subscriptions.get('level') == CONFIG.PRO_SUBSCRIPTION_LEVEL_KEY:
        try:
            expired_dt = datetime.fromisoformat(user_subscriptions['valid_until'])
            if expired_dt.tzinfo is None: expired_dt = expired_dt.replace(tzinfo=timezone.utc)
            subscription_status_display = f"Профи (истекла {expired_dt.strftime('%d.%m.%Y')})"
        except (ValueError, KeyError): subscription_status_display = "Профи (истекла, ошибка в дате)"

    parts = [f"<b>📊 Ваши текущие лимиты</b> (Статус: <b>{subscription_status_display}</b>)\n"]
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    all_user_daily_counts = bot_data_loc.get(BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY, {})
    user_counts_today = all_user_daily_counts.get(str(user_id), {})

    for model_key, model_config in AVAILABLE_TEXT_MODELS.items():
        if model_config.get("is_limited"):
            usage_info = user_counts_today.get(model_key, {'date': '', 'count': 0})
            current_day_usage = usage_info['count'] if usage_info['date'] == today_str else 0
            actual_limit = await get_user_actual_limit_for_model(user_id, model_key, user_data_loc, bot_data_loc)
            bonus_notification = ""
            if model_key == CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY and not is_profi and \
               user_data_loc.get('claimed_news_bonus', False) and (bonus_left := user_data_loc.get('news_bonus_uses_left', 0)) > 0:
                bonus_notification = f" (включая <b>{bonus_left}</b> бонусных)"
            limit_display = '∞' if actual_limit == float('inf') else str(actual_limit)
            parts.append(f"▫️ {model_config['name']}: <b>{current_day_usage} / {limit_display}</b>{bonus_notification}")
    parts.append("")
    bonus_model_cfg = AVAILABLE_TEXT_MODELS.get(CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY)
    bonus_model_name_display = bonus_model_cfg['name'] if bonus_model_cfg else "бонусной модели"
    if not user_data_loc.get('claimed_news_bonus', False):
        parts.append(f'🎁 Подпишитесь на <a href="{CONFIG.NEWS_CHANNEL_LINK}">канал новостей</a>, чтобы получить бонусные генерации ({CONFIG.NEWS_CHANNEL_BONUS_GENERATIONS} для {bonus_model_name_display})! Нажмите «🎁 Бонус» в меню для активации.')
    elif (bonus_left_val := user_data_loc.get('news_bonus_uses_left', 0)) > 0:
        parts.append(f"✅ У вас есть <b>{bonus_left_val}</b> бонусных генераций с канала новостей для модели {bonus_model_name_display}.")
    else:
        parts.append(f"ℹ️ Бонус с канала новостей для модели {bonus_model_name_display} был использован.")
    if not is_profi:
        parts.append("\n💎 Хотите больше лимитов и доступ ко всем моделям? Оформите подписку Profi через команду /subscribe или соответствующую кнопку в меню.")
    current_menu_for_reply = user_data_loc.get('current_menu', BotConstants.MENU_LIMITS_SUBMENU)
    await update.message.reply_text(
        "\n".join(parts), parse_mode=ParseMode.HTML, 
        reply_markup=generate_menu_keyboard(current_menu_for_reply),
        disable_web_page_preview=True
    )

async def claim_news_bonus_logic(update: Update, user_id: int):
    user_data_loc = await firestore_service.get_user_data(user_id)
    parent_menu_key = user_data_loc.get('current_menu', BotConstants.MENU_BONUS_SUBMENU)
    current_menu_config = MENU_STRUCTURE.get(parent_menu_key, MENU_STRUCTURE[BotConstants.MENU_MAIN])
    reply_menu_key = current_menu_config.get("parent", BotConstants.MENU_MAIN) if current_menu_config.get("is_submenu") else BotConstants.MENU_MAIN

    bonus_model_config = AVAILABLE_TEXT_MODELS.get(CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY)
    if not bonus_model_config:
        await update.message.reply_text("Настройка бонусной модели неисправна.", reply_markup=generate_menu_keyboard(reply_menu_key))
        return
    bonus_model_name_display = bonus_model_config['name']

    if user_data_loc.get('claimed_news_bonus', False):
        uses_left = user_data_loc.get('news_bonus_uses_left', 0)
        reply_text = f"Вы уже активировали бонус. " + (f"Осталось: <b>{uses_left}</b> для {bonus_model_name_display}." if uses_left > 0 else f"Бонус для {bonus_model_name_display} использован.")
        await update.message.reply_text(reply_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(reply_menu_key), disable_web_page_preview=True)
        return
    try:
        member_status = await update.get_bot().get_chat_member(chat_id=CONFIG.NEWS_CHANNEL_USERNAME, user_id=user_id)
        if member_status.status in ['member', 'administrator', 'creator']:
            await firestore_service.set_user_data(user_id, {'claimed_news_bonus': True, 'news_bonus_uses_left': CONFIG.NEWS_CHANNEL_BONUS_GENERATIONS})
            success_text = f'🎉 Спасибо за подписку на <a href="{CONFIG.NEWS_CHANNEL_LINK}">{CONFIG.NEWS_CHANNEL_USERNAME}</a>! Бонус: <b>{CONFIG.NEWS_CHANNEL_BONUS_GENERATIONS}</b> для {bonus_model_name_display}.'
            await update.message.reply_text(success_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(BotConstants.MENU_MAIN), disable_web_page_preview=True)
            await firestore_service.set_user_data(user_id, {'current_menu': BotConstants.MENU_MAIN})
        else:
            fail_text = f'Подпишитесь на <a href="{CONFIG.NEWS_CHANNEL_LINK}">{CONFIG.NEWS_CHANNEL_USERNAME}</a>, затем «🎁 Получить».'
            inline_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(f"📢 В канал {CONFIG.NEWS_CHANNEL_USERNAME}", url=CONFIG.NEWS_CHANNEL_LINK)]])
            await update.message.reply_text(fail_text, parse_mode=ParseMode.HTML, reply_markup=inline_keyboard, disable_web_page_preview=True)
    except telegram.error.TelegramError as e:
        logger.error(f"Telegram API error during news bonus claim for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("Ошибка при проверке подписки. Попробуйте позже.", reply_markup=generate_menu_keyboard(reply_menu_key))
    except Exception as e:
        logger.error(f"Unexpected error during news bonus claim for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("Непредвиденная ошибка. Попробуйте позже.", reply_markup=generate_menu_keyboard(reply_menu_key))

async def show_subscription(update: Update, user_id: int):
    user_data_loc = await firestore_service.get_user_data(user_id)
    bot_data_loc = await firestore_service.get_bot_data()
    user_subscriptions = bot_data_loc.get(BotConstants.FS_USER_SUBSCRIPTIONS_KEY, {}).get(str(user_id), {})
    is_active_profi = is_user_profi_subscriber(user_subscriptions)
    parts = ["<b>💎 Информация о подписке Profi</b>"]
    if is_active_profi:
        try:
            valid_until_dt = datetime.fromisoformat(user_subscriptions['valid_until'])
            if valid_until_dt.tzinfo is None: valid_until_dt = valid_until_dt.replace(tzinfo=timezone.utc)
            parts.append(f"\n✅ Ваша подписка Profi <b>активна</b> до <b>{valid_until_dt.strftime('%d.%m.%Y')}</b>.")
            parts.append("Вам доступны расширенные лимиты и все модели ИИ.")
        except (ValueError, KeyError): parts.append("\n⚠️ Активна подписка Profi, но проблема с датой окончания.")
    else:
        if user_subscriptions.get('level') == CONFIG.PRO_SUBSCRIPTION_LEVEL_KEY:
            try:
                expired_dt = datetime.fromisoformat(user_subscriptions['valid_until'])
                if expired_dt.tzinfo is None: expired_dt = expired_dt.replace(tzinfo=timezone.utc)
                parts.append(f"\n⚠️ Ваша подписка Profi истекла <b>{expired_dt.strftime('%d.%m.%Y')}</b>.")
            except (ValueError, KeyError): parts.append("\n⚠️ Ваша подписка Profi истекла (ошибка в дате).")
        parts.append("\nПодписка <b>Profi</b> предоставляет:")
        parts.append("▫️ Значительно увеличенные дневные лимиты.")
        pro_models = [m_cfg["name"] for m_key, m_cfg in AVAILABLE_TEXT_MODELS.items() if m_cfg.get("limit_type") == "subscription_custom_pro" and m_cfg.get("limit_if_no_subscription", -1) == 0]
        if pro_models: parts.append(f"▫️ Эксклюзивный доступ к моделям: {', '.join(pro_models)}.")
        else: parts.append(f"▫️ Доступ к специальным моделям.")
        parts.append("\nДля оформления: /subscribe или кнопка «💎 Купить».")
    current_menu_for_reply = user_data_loc.get('current_menu', BotConstants.MENU_SUBSCRIPTION_SUBMENU)
    await update.message.reply_text("\n".join(parts), parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(current_menu_for_reply), disable_web_page_preview=True)

async def show_help(update: Update, user_id: int):
    user_data_loc = await firestore_service.get_user_data(user_id)
    help_text = (
        "<b>❓ Справка по использованию бота</b>\n\n"
        "1.  <b>Запросы к ИИ</b>: Пишите вопрос или задачу в чат.\n"
        "2.  <b>Меню</b>:\n"
        "    ▫️ «<b>🤖 Агенты ИИ</b>»: Выбор роли ИИ.\n"
        "    ▫️ «<b>⚙️ Модели ИИ</b>»: Переключение моделей.\n"
        "    ▫️ «<b>📊 Лимиты</b>»: Ваши дневные лимиты.\n"
        "    ▫️ «<b>🎁 Бонус</b>»: Бонус за подписку на канал.\n"
        "    ▫️ «<b>💎 Подписка</b>»: О Profi подписке.\n"
        "    ▫️ «<b>❓ Помощь</b>»: Эта справка.\n\n"
        "3.  <b>Команды</b>: /start, /menu, /usage, /subscribe, /bonus, /help.\n\n"
    )
    current_menu_for_reply = user_data_loc.get('current_menu', BotConstants.MENU_HELP_SUBMENU)
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(current_menu_for_reply), disable_web_page_preview=True)

# --- ОБРАБОТЧИК КНОПОК МЕНЮ ---
async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    user_id = update.effective_user.id
    button_text = update.message.text.strip()
    if not is_menu_button_text(button_text): return 
    try:
        await update.message.delete()
        logger.info(f"Deleted menu button message '{button_text}' from user {user_id}.")
    except telegram.error.TelegramError as e:
        logger.warning(f"Failed to delete menu button message '{button_text}': {e}")

    user_data_loc = await firestore_service.get_user_data(user_id)
    current_menu_key = user_data_loc.get('current_menu', BotConstants.MENU_MAIN)
    logger.info(f"User {user_id} pressed menu button '{button_text}' in menu '{current_menu_key}'.")

    if button_text == "⬅️ Назад":
        parent_key = MENU_STRUCTURE.get(current_menu_key, {}).get("parent", BotConstants.MENU_MAIN)
        await show_menu(update, user_id, parent_key, user_data_loc)
        return 
    elif button_text == "🏠 Главное меню":
        await show_menu(update, user_id, BotConstants.MENU_MAIN, user_data_loc)
        return

    action_item_found = None
    action_origin_menu_key = current_menu_key # Изначально предполагаем, что кнопка из текущего меню
    search_menus_order = [current_menu_key] + [key for key in MENU_STRUCTURE if key != current_menu_key]
    for menu_key_to_search in search_menus_order:
        menu_config_to_search = MENU_STRUCTURE.get(menu_key_to_search, {})
        for item in menu_config_to_search.get("items", []):
            if item["text"] == button_text:
                action_item_found = item
                action_origin_menu_key = menu_key_to_search 
                break
        if action_item_found: break
    
    if not action_item_found:
        logger.warning(f"Button '{button_text}' by user {user_id} not matched. Current menu: '{current_menu_key}'.")
        await update.message.reply_text("Ошибка обработки. Попробуйте /start.", reply_markup=generate_menu_keyboard(current_menu_key))
        return

    action_type, action_target = action_item_found["action"], action_item_found["target"]
    return_menu_key_after_action = MENU_STRUCTURE.get(action_origin_menu_key, {}).get("parent", BotConstants.MENU_MAIN)
    if action_origin_menu_key == BotConstants.MENU_MAIN: return_menu_key_after_action = BotConstants.MENU_MAIN

    if action_type == BotConstants.CALLBACK_ACTION_SUBMENU:
        await show_menu(update, user_id, action_target, user_data_loc)
    elif action_type == BotConstants.CALLBACK_ACTION_SET_AGENT:
        resp_text = "⚠️ Ошибка: Агент не найден."
        if action_target in AI_MODES and action_target != "gemini_pro_custom_mode":
            await firestore_service.set_user_data(user_id, {'current_ai_mode': action_target})
            agent_details = AI_MODES[action_target]
            resp_text = f"🤖 Агент: <b>{agent_details['name']}</b>.\n{agent_details.get('welcome', '')}"
        await update.message.reply_text(resp_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(return_menu_key_after_action), disable_web_page_preview=True)
        await firestore_service.set_user_data(user_id, {'current_menu': return_menu_key_after_action})
    elif action_type == BotConstants.CALLBACK_ACTION_SET_MODEL:
        resp_text = "⚠️ Ошибка: Модель не найдена."
        if action_target in AVAILABLE_TEXT_MODELS:
            model_info = AVAILABLE_TEXT_MODELS[action_target]
            update_payload = {'selected_model_id': model_info["id"], 'selected_api_type': model_info["api_type"]}
            if action_target in ["custom_api_grok_3", "custom_api_gpt_4o_mini"] and user_data_loc.get('current_ai_mode') == "gemini_pro_custom_mode":
                update_payload['current_ai_mode'] = CONFIG.DEFAULT_AI_MODE_KEY
            await firestore_service.set_user_data(user_id, update_payload)
            user_data_loc.update(update_payload)
            bot_data_c = await firestore_service.get_bot_data()
            today_s_val = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            user_model_c = bot_data_c.get(BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY, {}).get(str(user_id), {})
            model_daily_u = user_model_c.get(action_target, {'date': '', 'count': 0})
            current_u_s = str(model_daily_u['count']) if model_daily_u['date'] == today_s_val else "0"
            actual_l_s = await get_user_actual_limit_for_model(user_id, action_target, user_data_loc, bot_data_c)
            limit_s_str = '∞' if actual_l_s == float('inf') else str(actual_l_s)
            resp_text = f"⚙️ Модель: <b>{model_info['name']}</b>.\nЛимит: {current_u_s}/{limit_s_str}."
        await update.message.reply_text(resp_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(return_menu_key_after_action), disable_web_page_preview=True)
        await firestore_service.set_user_data(user_id, {'current_menu': return_menu_key_after_action})
    elif action_type == BotConstants.CALLBACK_ACTION_SHOW_LIMITS: await show_limits(update, user_id)
    elif action_type == BotConstants.CALLBACK_ACTION_CHECK_BONUS: await claim_news_bonus_logic(update, user_id)
    elif action_type == BotConstants.CALLBACK_ACTION_SHOW_SUBSCRIPTION: await show_subscription(update, user_id)
    elif action_type == BotConstants.CALLBACK_ACTION_SHOW_HELP: await show_help(update, user_id)
    else:
        logger.warning(f"Unknown action '{action_type}' for button '{button_text}' user {user_id}.")
        await update.message.reply_text("Неизвестное действие.", reply_markup=generate_menu_keyboard(current_menu_key))
    return

# --- ОБРАБОТЧИК ТЕКСТОВЫХ СООБЩЕНИЙ (ЗАПРОСЫ К AI) ---
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not update.message or not update.message.text: return
    user_message_text = update.message.text.strip()
    await _store_and_try_delete_message(update, user_id, is_command_to_keep=False)
    if is_menu_button_text(user_message_text): 
        logger.debug(f"Menu button text '{user_message_text}' reached handle_text. Ignoring.")
        return

    if len(user_message_text) < CONFIG.MIN_AI_REQUEST_LENGTH:
        user_data_cache = await firestore_service.get_user_data(user_id)
        await update.message.reply_text("Запрос слишком короткий.", reply_markup=generate_menu_keyboard(user_data_cache.get('current_menu', BotConstants.MENU_MAIN)))
        return

    logger.info(f"User {user_id} AI request: '{user_message_text[:100]}...'")
    user_data_cache = await firestore_service.get_user_data(user_id) 
    current_model_key_val = await get_current_model_key(user_id, user_data_cache)
    
    can_proceed, limit_message, _ = await check_and_log_request_attempt(user_id, current_model_key_val)
    if not can_proceed:
        await update.message.reply_text(limit_message, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(user_data_cache.get('current_menu', BotConstants.MENU_MAIN)), disable_web_page_preview=True)
        user_data_cache = await firestore_service.get_user_data(user_id) 
        await update.message.reply_text("Выберите другую модель или попробуйте позже.", reply_markup=generate_menu_keyboard(user_data_cache.get('current_menu', BotConstants.MENU_MAIN)))
        return

    current_model_key_val = await get_current_model_key(user_id, user_data_cache)
    ai_service = get_ai_service(current_model_key_val)
    if not ai_service:
        logger.critical(f"No AI service for model '{current_model_key_val}' user {user_id}.")
        await update.message.reply_text("Ошибка модели. Сообщите администратору.", reply_markup=generate_menu_keyboard(user_data_cache.get('current_menu', BotConstants.MENU_MAIN)))
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    mode_details_val = await get_current_mode_details(user_id, user_data_cache)
    system_prompt_val = mode_details_val["prompt"]
    ai_response_text = "К сожалению, не удалось получить ответ от ИИ."
    try:
        ai_response_text = await ai_service.generate_response(system_prompt_val, user_message_text)
    except Exception as e:
        logger.error(f"Unhandled exception in AI service {type(ai_service).__name__} for model {current_model_key_val}: {e}", exc_info=True)
        ai_response_text = f"Внутренняя ошибка при запросе к {ai_service.model_config['name']}."

    final_reply_text, _ = smart_truncate(ai_response_text, CONFIG.MAX_MESSAGE_LENGTH_TELEGRAM)
    await increment_request_count(user_id, current_model_key_val)
    await update.message.reply_text(final_reply_text, reply_markup=generate_menu_keyboard(user_data_cache.get('current_menu', BotConstants.MENU_MAIN)), disable_web_page_preview=True)
    logger.info(f"Sent AI response (model: {current_model_key_val}) to user {user_id}.")

# --- ОБРАБОТЧИКИ ПЛАТЕЖЕЙ ---
async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    expected_payload_part = f"subscription_{CONFIG.PRO_SUBSCRIPTION_LEVEL_KEY}" 
    if query.invoice_payload and expected_payload_part in query.invoice_payload:
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="Неверный запрос на оплату.")

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    payment_info = update.message.successful_payment
    logger.info(f"Successful payment from {user_id}. Payload: {payment_info.invoice_payload}")
    subscription_days = 30
    bot_data = await firestore_service.get_bot_data()
    user_subscriptions_map = bot_data.get(BotConstants.FS_USER_SUBSCRIPTIONS_KEY, {})
    current_user_subscription = user_subscriptions_map.get(str(user_id), {})
    now_utc = datetime.now(timezone.utc)
    subscription_start_date = now_utc
    if is_user_profi_subscriber(current_user_subscription):
        try:
            previous_valid_until = datetime.fromisoformat(current_user_subscription['valid_until'])
            if previous_valid_until.tzinfo is None: previous_valid_until = previous_valid_until.replace(tzinfo=timezone.utc)
            if previous_valid_until > now_utc: subscription_start_date = previous_valid_until
        except (ValueError, KeyError): logger.warning(f"Could not parse previous 'valid_until' for user {user_id}.")
    new_valid_until_date = subscription_start_date + timedelta(days=subscription_days)
    user_subscriptions_map[str(user_id)] = {
        'level': CONFIG.PRO_SUBSCRIPTION_LEVEL_KEY, 'valid_until': new_valid_until_date.isoformat(),
        'last_payment_amount': payment_info.total_amount, 'currency': payment_info.currency,
        'purchase_date': now_utc.isoformat(),
        'telegram_payment_charge_id': payment_info.telegram_payment_charge_id,
        'provider_payment_charge_id': payment_info.provider_payment_charge_id
    }
    await firestore_service.set_bot_data({BotConstants.FS_USER_SUBSCRIPTIONS_KEY: user_subscriptions_map})
    confirmation_message = f"🎉 Оплата успешна! Подписка <b>Profi</b> активна до <b>{new_valid_until_date.strftime('%d.%m.%Y')}</b>."
    user_data_for_reply_menu = await firestore_service.get_user_data(user_id)
    await update.message.reply_text(confirmation_message, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(user_data_for_reply_menu.get('current_menu', BotConstants.MENU_MAIN)))
    if CONFIG.ADMIN_ID:
        try:
            admin_message = f"🔔 Новая оплата: User {user_id} ({update.effective_user.full_name}), Sub до {new_valid_until_date.strftime('%d.%m.%Y')}"
            await context.bot.send_message(CONFIG.ADMIN_ID, admin_message)
        except Exception as e: logger.error(f"Failed to send payment notification to admin: {e}")

# --- ОБРАБОТЧИК ОШИБОК ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    tb_string = "".join(traceback.format_exception(None, context.error, context.error.__traceback__))
    if isinstance(update, Update) and update.effective_chat:
        user_data_for_error_reply = {}
        if update.effective_user: user_data_for_error_reply = await firestore_service.get_user_data(update.effective_user.id)
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Произошла внутренняя ошибка. Попробуйте /start.",
                reply_markup=generate_menu_keyboard(user_data_for_error_reply.get('current_menu', BotConstants.MENU_MAIN))
            )
        except Exception as e: logger.error(f"Failed to send error message to user {update.effective_chat.id}: {e}")
    if CONFIG.ADMIN_ID and isinstance(update, Update) and update.effective_user:
        error_details = (
            f"🤖 Ошибка бота:\nТип: {context.error.__class__.__name__}: {context.error}\n"
            f"User: {update.effective_user.id} (@{update.effective_user.username})\n"
            f"Сообщение: {update.message.text if update.message else 'N/A'}\n\n"
            f"Traceback:\n```\n{tb_string[:3500]}\n```"
        )
        try: await context.bot.send_message(CONFIG.ADMIN_ID, error_details, parse_mode=ParseMode.MARKDOWN_V2)
        except Exception: 
            try: await context.bot.send_message(CONFIG.ADMIN_ID, error_details.replace("```","")) # Fallback
            except Exception as e_plain: logger.error(f"Failed to send plain error to admin: {e_plain}")

# --- ОСНОВНАЯ ФУНКЦИЯ ЗАПУСКА БОТА ---
async def main():
    if CONFIG.GOOGLE_GEMINI_API_KEY and "YOUR_" not in CONFIG.GOOGLE_GEMINI_API_KEY and CONFIG.GOOGLE_GEMINI_API_KEY.startswith("AIzaSy"):
        try: genai.configure(api_key=CONFIG.GOOGLE_GEMINI_API_KEY); logger.info("Google Gemini API configured.")
        except Exception as e: logger.error(f"Google Gemini API config error: {e}", exc_info=True)
    else: logger.warning("Google Gemini API key not configured correctly.")
    for key_name in ["CUSTOM_GEMINI_PRO_API_KEY", "CUSTOM_GROK_3_API_KEY", "CUSTOM_GPT4O_MINI_API_KEY"]:
        key_value = getattr(CONFIG, key_name, "")
        if not key_value or "YOUR_" in key_value or not (key_value.startswith("sk-") or key_value.startswith("AIzaSy")):
            logger.warning(f"API key {key_name} incorrect or missing.")
    if not CONFIG.PAYMENT_PROVIDER_TOKEN or "YOUR_" in CONFIG.PAYMENT_PROVIDER_TOKEN:
        logger.warning("Payment Provider Token incorrect.")
    if not firestore_service._db: # pylint: disable=protected-access
        logger.critical("Firestore (db) NOT initialized! Limited functionality.")

    app_builder = Application.builder().token(CONFIG.TELEGRAM_TOKEN)
    app_builder.read_timeout(30).connect_timeout(30)
    app = app_builder.build()

    app.add_handler(CommandHandler("start", start), group=0)
    app.add_handler(CommandHandler("menu", open_menu_command), group=0)
    app.add_handler(CommandHandler("usage", usage_command), group=0)
    app.add_handler(CommandHandler("subscribe", subscribe_info_command), group=0)
    app.add_handler(CommandHandler("bonus", get_news_bonus_info_command), group=0)
    app.add_handler(CommandHandler("help", help_command), group=0)
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_button_handler), group=1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text), group=2)
    
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    app.add_error_handler(error_handler)

    bot_commands = [
        BotCommand("start", "🚀 Перезапуск / Меню"), BotCommand("menu", "📋 Открыть меню"),
        BotCommand("usage", "📊 Мои лимиты"), BotCommand("subscribe", "💎 О подписке"),
        BotCommand("bonus", "🎁 Бонус канала"), BotCommand("help", "❓ Справка")
    ]
    try: await app.bot.set_my_commands(bot_commands); logger.info("Bot commands set.")
    except Exception as e: logger.error(f"Failed to set bot commands: {e}")

    logger.info("Bot polling started...")
    await app.run_polling(allowed_updates=Update.ALL_TYPES, timeout=30)

if __name__ == '__main__':
    asyncio.run(main())
