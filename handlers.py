# handlers.py
import traceback
from datetime import datetime, timezone, timedelta
import telegram
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode, ChatAction
from telegram.ext import ContextTypes

# Импортируем всё необходимое из общего файла config.py
from config import (
    firestore_service, CONFIG, BotConstants, AVAILABLE_TEXT_MODELS,
    AI_MODES, MENU_STRUCTURE, auto_delete_message_decorator,
    get_current_model_key, get_current_mode_details, get_user_actual_limit_for_model,
    is_menu_button_text, generate_menu_keyboard, _store_and_try_delete_message,
    check_and_log_request_attempt, get_ai_service, smart_truncate,
    increment_request_count, is_user_profi_subscriber, logger, show_menu
)

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

    mode_name = mode_details_res.get('name', 'N/A')
    model_name = model_details_res.get('name', 'N/A')

    greeting_message = (
        f"👋 Привет, {user_first_name}!\n\n"
        f"🤖 Текущий агент: <b>{mode_name}</b>\n"
        f"⚙️ Активная модель: <b>{model_name}</b>\n\n"
        "Я готов к вашим запросам! Используйте текстовые сообщения для общения с ИИ "
        "или кнопки меню для навигации и настроек."
    )
    await update.message.reply_text(
        greeting_message,
        parse_mode=ParseMode.HTML,
        reply_markup=generate_menu_keyboard(BotConstants.MENU_MAIN),
        disable_web_page_preview=True
    )
    await firestore_service.set_user_data(user_id, {'current_menu': BotConstants.MENU_MAIN})
    logger.info(f"User {user_id} ({user_first_name}) started the bot.")

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

# --- ЛОГИКА ОТОБРАЖЕНИЯ ИНФОРМАЦИИ ---

async def show_limits(update: Update, user_id: int):
    user_data_loc = await firestore_service.get_user_data(user_id)
    bot_data_loc = await firestore_service.get_bot_data()
    
    user_subscriptions = bot_data_loc.get(BotConstants.FS_USER_SUBSCRIPTIONS_KEY, {}).get(str(user_id), {})
    is_profi = is_user_profi_subscriber(user_subscriptions)
    
    subscription_status_display = "Бесплатный"
    if is_profi:
        try:
            valid_until_dt = datetime.fromisoformat(user_subscriptions['valid_until']).astimezone(timezone.utc)
            subscription_status_display = f"Профи (активна до {valid_until_dt.strftime('%d.%m.%Y')})"
        except (ValueError, KeyError):
            subscription_status_display = "Профи (ошибка в дате)"
    elif user_subscriptions.get('level') == CONFIG.PRO_SUBSCRIPTION_LEVEL_KEY:
        try:
            expired_dt = datetime.fromisoformat(user_subscriptions['valid_until']).astimezone(timezone.utc)
            subscription_status_display = f"Профи (истекла {expired_dt.strftime('%d.%m.%Y')})"
        except (ValueError, KeyError):
             subscription_status_display = "Профи (истекла, ошибка в дате)"

    parts = [f"<b>📊 Ваши текущие лимиты</b> (Статус: <b>{subscription_status_display}</b>)\n"]
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    user_counts_today = bot_data_loc.get(BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY, {}).get(str(user_id), {})

    for model_key, model_config in AVAILABLE_TEXT_MODELS.items():
        if model_config.get("is_limited"):
            usage_info = user_counts_today.get(model_key, {'date': '', 'count': 0})
            current_day_usage = usage_info['count'] if usage_info.get('date') == today_str else 0
            actual_limit = await get_user_actual_limit_for_model(user_id, model_key, user_data_loc, bot_data_loc)
            
            bonus_notification = ""
            if model_key == CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY and not is_profi and user_data_loc.get('claimed_news_bonus', False):
                bonus_left = user_data_loc.get('news_bonus_uses_left', 0)
                if bonus_left > 0:
                    bonus_notification = f" (включая <b>{bonus_left}</b> бонусных)"
            
            limit_display = '∞' if actual_limit == float('inf') else str(int(actual_limit))
            parts.append(f"▫️ {model_config['name']}: <b>{current_day_usage} / {limit_display}</b>{bonus_notification}")

    parts.append("")
    bonus_model_name_display = AVAILABLE_TEXT_MODELS.get(CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY, {}).get('name', 'бонусной модели')

    if not user_data_loc.get('claimed_news_bonus', False):
        parts.append(f'🎁 Подпишитесь на <a href="{CONFIG.NEWS_CHANNEL_LINK}">канал новостей</a>, чтобы получить бонусные генерации ({CONFIG.NEWS_CHANNEL_BONUS_GENERATIONS} для {bonus_model_name_display})! Нажмите «🎁 Бонус» в меню.')
    elif (bonus_left_val := user_data_loc.get('news_bonus_uses_left', 0)) > 0:
        parts.append(f"✅ У вас есть <b>{bonus_left_val}</b> бонусных генераций для модели {bonus_model_name_display}.")
    else:
        parts.append(f"ℹ️ Бонус с канала новостей для модели {bonus_model_name_display} был использован.")
        
    if not is_profi:
        parts.append("\n💎 Хотите больше лимитов? Оформите подписку Profi через команду /subscribe или меню.")
        
    current_menu_for_reply = user_data_loc.get('current_menu', BotConstants.MENU_MAIN)
    await update.message.reply_text(
        "\n".join(parts), parse_mode=ParseMode.HTML, 
        reply_markup=generate_menu_keyboard(current_menu_for_reply),
        disable_web_page_preview=True
    )

async def claim_news_bonus_logic(update: Update, user_id: int):
    user_data_loc = await firestore_service.get_user_data(user_id)
    parent_menu_key = user_data_loc.get('current_menu', BotConstants.MENU_MAIN)
    reply_menu_key = MENU_STRUCTURE.get(parent_menu_key, {}).get("parent", BotConstants.MENU_MAIN)

    bonus_model_config = AVAILABLE_TEXT_MODELS.get(CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY)
    if not bonus_model_config:
        await update.message.reply_text("Ошибка: Бонусная модель не настроена.", reply_markup=generate_menu_keyboard(reply_menu_key))
        return
        
    bonus_model_name = bonus_model_config['name']

    if user_data_loc.get('claimed_news_bonus', False):
        uses_left = user_data_loc.get('news_bonus_uses_left', 0)
        reply_text = f"Вы уже активировали бонус. " + (f"У вас осталось: <b>{uses_left}</b> бонусных генераций для {bonus_model_name}." if uses_left > 0 else f"Бонусные генерации для {bonus_model_name} использованы.")
        await update.message.reply_text(reply_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(reply_menu_key))
        return

    try:
        member_status = await update.get_bot().get_chat_member(chat_id=CONFIG.NEWS_CHANNEL_USERNAME, user_id=user_id)
        if member_status.status in ['member', 'administrator', 'creator']:
            await firestore_service.set_user_data(user_id, {
                'claimed_news_bonus': True, 
                'news_bonus_uses_left': CONFIG.NEWS_CHANNEL_BONUS_GENERATIONS
            })
            success_text = (f'🎉 Спасибо за подписку на <a href="{CONFIG.NEWS_CHANNEL_LINK}">{CONFIG.NEWS_CHANNEL_USERNAME}</a>! '
                            f"Вам начислен бонус: <b>{CONFIG.NEWS_CHANNEL_BONUS_GENERATIONS}</b> генераций для модели {bonus_model_name}.")
            await update.message.reply_text(success_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(BotConstants.MENU_MAIN), disable_web_page_preview=True)
            await firestore_service.set_user_data(user_id, {'current_menu': BotConstants.MENU_MAIN})
        else:
            fail_text = (f'Сначала подпишитесь на <a href="{CONFIG.NEWS_CHANNEL_LINK}">{CONFIG.NEWS_CHANNEL_USERNAME}</a>, '
                         f'а затем вернитесь и нажмите кнопку еще раз.')
            await update.message.reply_text(fail_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(parent_menu_key), disable_web_page_preview=True)
    except telegram.error.TelegramError as e:
        logger.error(f"Bonus claim error for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("Ошибка при проверке подписки. Попробуйте позже.", reply_markup=generate_menu_keyboard(reply_menu_key))

async def show_subscription(update: Update, user_id: int):
    user_data_loc = await firestore_service.get_user_data(user_id)
    bot_data_loc = await firestore_service.get_bot_data()
    user_subscriptions = bot_data_loc.get(BotConstants.FS_USER_SUBSCRIPTIONS_KEY, {}).get(str(user_id), {})
    is_active_profi = is_user_profi_subscriber(user_subscriptions)

    parts = ["<b>💎 Информация о подписке Profi</b>"]

    if is_active_profi:
        try:
            valid_until_dt = datetime.fromisoformat(user_subscriptions['valid_until']).astimezone(timezone.utc)
            parts.append(f"\n✅ Ваша подписка Profi <b>активна</b> до <b>{valid_until_dt.strftime('%d.%m.%Y')}</b>.")
            parts.append("Вам доступны расширенные лимиты и все модели ИИ.")
        except (ValueError, KeyError):
            parts.append("\n⚠️ Обнаружена активная подписка Profi, но есть проблема с отображением даты окончания.")
    else:
        if user_subscriptions.get('level') == CONFIG.PRO_SUBSCRIPTION_LEVEL_KEY:
            try:
                expired_dt = datetime.fromisoformat(user_subscriptions['valid_until']).astimezone(timezone.utc)
                parts.append(f"\n⚠️ Ваша подписка Profi истекла <b>{expired_dt.strftime('%d.%m.%Y')}</b>.")
            except (ValueError, KeyError):
                parts.append("\n⚠️ Ваша подписка Profi истекла (ошибка в дате).")

        parts.append("\nПодписка <b>Profi</b> предоставляет следующие преимущества:")
        parts.append("▫️ Значительно увеличенные дневные лимиты.")
        
        pro_models = [m_cfg["name"] for m_key, m_cfg in AVAILABLE_TEXT_MODELS.items() if m_cfg.get("limit_type") == "subscription_custom_pro" and m_cfg.get("limit_if_no_subscription", 0) == 0]
        if pro_models:
            parts.append(f"▫️ Эксклюзивный доступ к моделям: {', '.join(pro_models)}.")
        
        parts.append("\nДля оформления подписки используйте команду /subscribe.")

    current_menu_for_reply = user_data_loc.get('current_menu', BotConstants.MENU_MAIN)
    await update.message.reply_text("\n".join(parts), parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(current_menu_for_reply), disable_web_page_preview=True)


async def show_help(update: Update, user_id: int):
    user_data_loc = await firestore_service.get_user_data(user_id)
    help_text = (
        "<b>❓ Справка по использованию бота</b>\n\n"
        "1.  <b>Запросы к ИИ</b>: Просто напишите ваш вопрос или задачу в чат.\n"
        "2.  <b>Меню</b>: Используйте кнопки для доступа ко всем функциям.\n"
        "    ▫️ «🤖 Агенты ИИ»: Выберите роль для ИИ.\n"
        "    ▫️ «⚙️ Модели ИИ»: Переключайтесь между моделями.\n"
        "    ▫️ «📊 Лимиты»: Проверьте дневные лимиты.\n"
        "    ▫️ «🎁 Бонус»: Получите бонусные генерации.\n"
        "    ▫️ «💎 Подписка»: Информация о Profi подписке.\n"
        "    ▫️ «❓ Помощь»: Этот раздел справки.\n\n"
        "3.  <b>Основные команды</b>:\n"
        "    /start, /menu, /usage, /subscribe, /bonus, /help."
    )
    current_menu_for_reply = user_data_loc.get('current_menu', BotConstants.MENU_MAIN)
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(current_menu_for_reply), disable_web_page_preview=True)

# --- ОБРАБОТЧИК КНОПОК МЕНЮ ---
async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    button_text = update.message.text.strip()
    if not is_menu_button_text(button_text):
        return

    user_id = update.effective_user.id
    logger.info(f"User {user_id} pressed menu button: '{button_text}'")
    
    try:
        await update.message.delete()
    except telegram.error.TelegramError as e:
        logger.warning(f"Failed to delete menu button message '{button_text}': {e}")

    user_data_loc = await firestore_service.get_user_data(user_id)
    current_menu_key = user_data_loc.get('current_menu', BotConstants.MENU_MAIN)

    if button_text == "⬅️ Назад":
        parent_key = MENU_STRUCTURE.get(current_menu_key, {}).get("parent", BotConstants.MENU_MAIN)
        await show_menu(update, user_id, parent_key)
        return
    elif button_text == "🏠 Главное меню":
        await show_menu(update, user_id, BotConstants.MENU_MAIN)
        return

    action_item_found = None
    search_order = [current_menu_key] + [key for key in MENU_STRUCTURE if key != current_menu_key]
    
    for menu_key in search_order:
        for item in MENU_STRUCTURE.get(menu_key, {}).get("items", []):
            if item["text"] == button_text:
                action_item_found = item
                break
        if action_item_found:
            break
    
    if not action_item_found:
        logger.error(f"Button '{button_text}' was identified as a menu button, but no action was found.")
        await show_menu(update, user_id, BotConstants.MENU_MAIN)
        return

    action_type = action_item_found["action"]
    action_target = action_item_found["target"]

     if action_type == BotConstants.CALLBACK_ACTION_SUBMENU:
        # Код для этого условия с правильным отступом
        await show_menu(update, user_id, action_target)
    
    elif action_type == BotConstants.CALLBACK_ACTION_SET_AGENT: # <--- Убедитесь, что эта строка на одном уровне с if выше
        # Весь код ниже должен быть с ОДИНАКОВЫМ отступом (на 4 пробела больше, чем elif)
        await firestore_service.set_user_data(user_id, {'current_ai_mode': action_target})
        agent_name = AI_MODES.get(action_target, {}).get('name', 'N/A')
        response_text = f"🤖 Агент ИИ изменен на: <b>{agent_name}</b>."
        
        # user_data_loc уже был получен выше в menu_button_handler
        # current_menu_key также уже был получен выше
        reply_menu_after_set_agent = current_menu_key 
        
        await update.message.reply_text(response_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(reply_menu_after_set_agent))
        await firestore_service.set_user_data(user_id, {'current_menu': reply_menu_after_set_agent})

    elif action_type == BotConstants.CALLBACK_ACTION_SET_MODEL: # <--- Эта строка на том же уровне, что и elif выше
        # Код для этого условия с правильным отступом (на 4 пробела больше, чем этот elif)
        model_info = AVAILABLE_TEXT_MODELS.get(action_target, {})
        update_payload = {
            'selected_model_id': model_info.get("id"), 
            'selected_api_type': model_info.get("api_type")
        }
        # user_data_loc уже был получен выше
        if action_target in ["custom_api_grok_3", "custom_api_gpt_4o_mini"] and \
           user_data_loc.get('current_ai_mode') == "gemini_pro_custom_mode":
            update_payload['current_ai_mode'] = CONFIG.DEFAULT_AI_MODE_KEY
            logger.info(f"User {user_id} selected model {action_target}, AI mode reset from gemini_pro_custom_mode to default.")
        
        await firestore_service.set_user_data(user_id, update_payload)
        user_data_loc.update(update_payload) 
        
        bot_data_cache = await firestore_service.get_bot_data()
        today_string_val = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        user_model_counts = bot_data_cache.get(BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY, {}).get(str(user_id), {})
        model_daily_usage = user_model_counts.get(action_target, {'date': '', 'count': 0})
        current_usage_string = str(model_daily_usage['count']) if model_daily_usage.get('date') == today_string_val else "0"
        
        actual_limit_string = await get_user_actual_limit_for_model(user_id, action_target, user_data_loc, bot_data_cache)
        limit_display_string = '∞' if actual_limit_string == float('inf') else str(int(actual_limit_string))
        
        response_text = (f"⚙️ Модель ИИ изменена на: <b>{model_info.get('name', 'N/A')}</b>.\n"
                         f"Дневной лимит: {current_usage_string} / {limit_display_string}.")
        
        # current_menu_key также уже был получен выше
        reply_menu_after_set_model = current_menu_key

        await update.message.reply_text(response_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(reply_menu_after_set_model))
        await firestore_service.set_user_data(user_id, {'current_menu': reply_menu_after_set_model})

    elif action_type == BotConstants.CALLBACK_ACTION_SHOW_LIMITS:
        await show_limits(update, user_id)
    elif action_type == BotConstants.CALLBACK_ACTION_CHECK_BONUS:
        await claim_news_bonus_logic(update, user_id)
    elif action_type == BotConstants.CALLBACK_ACTION_SHOW_SUBSCRIPTION:
        await show_subscription(update, user_id)
    elif action_type == BotConstants.CALLBACK_ACTION_SHOW_HELP:
        await show_help(update, user_id)
    else:
        logger.warning(f"Unknown action type '{action_type}' for button '{button_text}'")
        await show_menu(update, user_id, BotConstants.MENU_MAIN)

# --- ОБРАБОТЧИК ТЕКСТА (ЗАПРОСЫ К AI) ---
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text or is_menu_button_text(update.message.text.strip()):
        return
        
    user_id = update.effective_user.id
    user_message_text = update.message.text.strip()

    if len(user_message_text) < CONFIG.MIN_AI_REQUEST_LENGTH:
        user_data_cache = await firestore_service.get_user_data(user_id)
        current_menu = user_data_cache.get('current_menu', BotConstants.MENU_MAIN)
        await update.message.reply_text("Ваш запрос слишком короткий.", reply_markup=generate_menu_keyboard(current_menu))
        return

    logger.info(f"User {user_id} sent AI request: '{user_message_text[:100]}...'")
    
    user_data_cache = await firestore_service.get_user_data(user_id) 
    current_model_key = await get_current_model_key(user_id, user_data_cache)
    can_proceed, limit_message, _ = await check_and_log_request_attempt(user_id, current_model_key)
    
    if not can_proceed:
        user_data_cache_after_reset = await firestore_service.get_user_data(user_id)
        current_menu_after_reset = user_data_cache_after_reset.get('current_menu', BotConstants.MENU_MAIN)
        await update.message.reply_text(limit_message, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(current_menu_after_reset), disable_web_page_preview=True)
        return

    current_model_key = await get_current_model_key(user_id, user_data_cache)
    ai_service = get_ai_service(current_model_key)

    if not ai_service:
        logger.critical(f"Could not get AI service for model key '{current_model_key}'")
        current_menu = user_data_cache.get('current_menu', BotConstants.MENU_MAIN)
        await update.message.reply_text("Критическая ошибка при выборе AI модели.", reply_markup=generate_menu_keyboard(current_menu))
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    
    mode_details = await get_current_mode_details(user_id, user_data_cache)
    system_prompt = mode_details["prompt"]
    
    try:
        ai_response_text = await ai_service.generate_response(system_prompt, user_message_text)
    except Exception as e:
        logger.error(f"Unhandled exception in AI service for model {current_model_key}: {e}", exc_info=True)
        ai_response_text = f"Произошла внутренняя ошибка при обработке вашего запроса."

    final_reply_text, _ = smart_truncate(ai_response_text, CONFIG.MAX_MESSAGE_LENGTH_TELEGRAM)
    await increment_request_count(user_id, current_model_key)
    
    current_menu = user_data_cache.get('current_menu', BotConstants.MENU_MAIN)
    await update.message.reply_text(final_reply_text, reply_markup=generate_menu_keyboard(current_menu), disable_web_page_preview=True)

# --- ОБРАБОТЧИКИ ПЛАТЕЖЕЙ ---
async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    expected_payload_part = f"subscription_{CONFIG.PRO_SUBSCRIPTION_LEVEL_KEY}"
    if query.invoice_payload and expected_payload_part in query.invoice_payload:
        await query.answer(ok=True)
        logger.info(f"PreCheckoutQuery OK for payload: {query.invoice_payload}")
    else:
        await query.answer(ok=False, error_message="Неверный или устаревший запрос на оплату.")
        logger.warning(f"PreCheckoutQuery FAILED for payload: {query.invoice_payload}")

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
            if previous_valid_until > now_utc:
                subscription_start_date = previous_valid_until
        except (ValueError, KeyError):
            logger.warning(f"Could not parse previous 'valid_until' for user {user_id}.")

    new_valid_until_date = subscription_start_date + timedelta(days=subscription_days)

    user_subscriptions_map[str(user_id)] = {
        'level': CONFIG.PRO_SUBSCRIPTION_LEVEL_KEY,
        'valid_until': new_valid_until_date.isoformat(),
        'last_payment_amount': payment_info.total_amount,
        'currency': payment_info.currency,
        'purchase_date': now_utc.isoformat(),
        'telegram_payment_charge_id': payment_info.telegram_payment_charge_id,
        'provider_payment_charge_id': payment_info.provider_payment_charge_id
    }
    
    await firestore_service.set_bot_data({BotConstants.FS_USER_SUBSCRIPTIONS_KEY: user_subscriptions_map})

    confirmation_message = (
        f"🎉 Оплата прошла успешно! Ваша подписка <b>Profi</b> активна до <b>{new_valid_until_date.strftime('%d.%m.%Y')}</b>."
    )
    
    user_data = await firestore_service.get_user_data(user_id)
    await update.message.reply_text(
        confirmation_message, parse_mode=ParseMode.HTML, 
        reply_markup=generate_menu_keyboard(user_data.get('current_menu', BotConstants.MENU_MAIN))
    )

# --- ОБРАБОТЧИК ОШИБОК ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    
    tb_string = "".join(traceback.format_exception(None, context.error, context.error.__traceback__))

    if isinstance(update, Update) and update.effective_chat:
        user_data = {}
        if update.effective_user:
             user_data = await firestore_service.get_user_data(update.effective_user.id)
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Произошла внутренняя ошибка. Разработчики уже уведомлены.",
                reply_markup=generate_menu_keyboard(user_data.get('current_menu', BotConstants.MENU_MAIN))
            )
        except Exception as e:
            logger.error(f"Failed to send error message to user {update.effective_chat.id}: {e}")

    if CONFIG.ADMIN_ID and isinstance(update, Update) and update.effective_user:
        error_details = (
            f"🤖 Ошибка в боте:\n"
            f"Пользователь: ID {update.effective_user.id} (@{update.effective_user.username})\n"
            f"Сообщение: {update.message.text if update.message else 'N/A'}\n"
            f"Ошибка: {context.error}\n\n"
            f"Traceback:\n```\n{tb_string[:3500]}\n```"
        )
        try:
            await context.bot.send_message(CONFIG.ADMIN_ID, error_details)
        except Exception as e:
            logger.error(f"Failed to send detailed error report to admin: {e}")
