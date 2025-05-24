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
            await update.message.reply_text(success_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(BotConstants.MENU_MAIN))
            await firestore_service.set_user_data(user_id, {'current_menu': BotConstants.MENU_MAIN})
        else:
            fail_text = (f'Сначала подпишитесь на <a href="{CONFIG.NEWS_CHANNEL_LINK}">{CONFIG.NEWS_CHANNEL_USERNAME}</a>, '
                         f'а затем вернитесь и нажмите кнопку еще раз.')
            await update.message.reply_text(fail_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(parent_menu_key))
    except telegram.error.TelegramError as e:
        logger.error(f"Bonus claim error for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("Ошибка при проверке подписки. Попробуйте позже.", reply_markup=generate_menu_keyboard(reply_menu_key))

async def show_subscription(update: Update, user_id: int):
    # ... (аналогично предыдущим версиям, но с импортами из config) ...
    user_data_loc = await firestore_service.get_user_data(user_id)
    bot_data_loc = await firestore_service.get_bot_data()
    user_subscriptions = bot_data_loc.get(BotConstants.FS_USER_SUBSCRIPTIONS_KEY, {}).get(str(user_id), {})
    is_active_profi = is_user_profi_subscriber(user_subscriptions)

    parts = ["<b>💎 Информация о подписке Profi</b>"]
    if is_active_profi:
        valid_until_str = user_subscriptions.get('valid_until', 'N/A')
        try:
            valid_until_dt = datetime.fromisoformat(valid_until_str).strftime('%d.%m.%Y')
            parts.append(f"\n✅ Ваша подписка Profi <b>активна</b> до <b>{valid_until_dt}</b>.")
        except ValueError:
            parts.append("\n⚠️ Обнаружена активная подписка, но проблема с отображением даты.")
    else:
        # ... (логика для не-подписчиков) ...
        parts.append("\nПодписка <b>Profi</b> предоставляет расширенные лимиты и доступ ко всем моделям.")
    
    current_menu = user_data_loc.get('current_menu', BotConstants.MENU_MAIN)
    await update.message.reply_text("\n".join(parts), parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(current_menu), disable_web_page_preview=True)


async def show_help(update: Update, user_id: int):
    # ... (аналогично предыдущим версиям, но с импортами из config) ...
    user_data_loc = await firestore_service.get_user_data(user_id)
    help_text = "<b>❓ Справка по боту</b>\n\n1. <b>Запросы:</b> Просто пишите в чат.\n2. <b>Меню:</b> Используйте кнопки для навигации и настроек." # Упрощено для примера
    current_menu = user_data_loc.get('current_menu', BotConstants.MENU_MAIN)
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(current_menu), disable_web_page_preview=True)

# --- ОБРАБОТЧИК КНОПОК МЕНЮ ---
async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатывает ТОЛЬКО нажатия на кнопки ReplyKeyboardMarkup.
    Имеет более высокий приоритет, чем handle_text.
    """
    if not update.message or not update.message.text:
        return

    button_text = update.message.text.strip()

    # Если это не текст кнопки из нашего меню, то этот обработчик ничего не делает,
    # и управление переходит к следующему обработчику (handle_text).
    if not is_menu_button_text(button_text):
        return

    user_id = update.effective_user.id
    logger.info(f"User {user_id} pressed menu button: '{button_text}'")
    
    # Кнопка обработана, удаляем сообщение с ней
    try:
        await update.message.delete()
    except telegram.error.TelegramError as e:
        logger.warning(f"Failed to delete menu button message '{button_text}': {e}")

    user_data_loc = await firestore_service.get_user_data(user_id)
    current_menu_key = user_data_loc.get('current_menu', BotConstants.MENU_MAIN)

    # Обработка универсальных навигационных кнопок
    if button_text == "⬅️ Назад":
        parent_key = MENU_STRUCTURE.get(current_menu_key, {}).get("parent", BotConstants.MENU_MAIN)
        await show_menu(update, user_id, parent_key)
        return
    elif button_text == "🏠 Главное меню":
        await show_menu(update, user_id, BotConstants.MENU_MAIN)
        return

    # Поиск действия для нажатой кнопки по всем меню (для надежности)
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
        await show_menu(update, user_id, BotConstants.MENU_MAIN) # Возвращаем в главное меню при ошибке
        return

    # Выполнение действия
    action_type = action_item_found["action"]
    action_target = action_item_found["target"]

    if action_type == BotConstants.CALLBACK_ACTION_SUBMENU:
        await show_menu(update, user_id, action_target)
    
    elif action_type == BotConstants.CALLBACK_ACTION_SET_AGENT:
        await firestore_service.set_user_data(user_id, {'current_ai_mode': action_target})
        agent_name = AI_MODES.get(action_target, {}).get('name', 'N/A')
        response_text = f"🤖 Агент ИИ изменен на: <b>{agent_name}</b>."
        # После смены агента, возвращаемся в главное меню для ясности
        await update.message.reply_text(response_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(BotConstants.MENU_MAIN))
        await firestore_service.set_user_data(user_id, {'current_menu': BotConstants.MENU_MAIN})

    elif action_type == BotConstants.CALLBACK_ACTION_SET_MODEL:
        model_info = AVAILABLE_TEXT_MODELS.get(action_target, {})
        await firestore_service.set_user_data(user_id, {'selected_model_id': model_info.get("id"), 'selected_api_type': model_info.get("api_type")})
        response_text = f"⚙️ Модель ИИ изменена на: <b>{model_info.get('name', 'N/A')}</b>."
        # После смены модели, возвращаемся в главное меню
        await update.message.reply_text(response_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(BotConstants.MENU_MAIN))
        await firestore_service.set_user_data(user_id, {'current_menu': BotConstants.MENU_MAIN})

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


# --- ОБРАБОТЧИК ТЕКСТОВЫХ СООБЩЕНИЙ (ЗАПРОСЫ К AI) ---
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатывает обычные текстовые сообщения, которые НЕ являются кнопками меню.
    """
    # Этот обработчик не должен срабатывать на кнопки меню.
    # Это проверка на всякий случай, если что-то пойдет не так с приоритетами обработчиков.
    if not update.message or not update.message.text or is_menu_button_text(update.message.text.strip()):
        return
        
    user_id = update.effective_user.id
    user_message_text = update.message.text.strip()

    # Удаляем сообщение пользователя, чтобы не засорять чат
    await _store_and_try_delete_message(update, user_id, is_command_to_keep=False)

    if len(user_message_text) < CONFIG.MIN_AI_REQUEST_LENGTH:
        user_data_cache = await firestore_service.get_user_data(user_id)
        current_menu = user_data_cache.get('current_menu', BotConstants.MENU_MAIN)
        await update.message.reply_text(
            "Ваш запрос слишком короткий. Пожалуйста, сформулируйте его более подробно.",
            reply_markup=generate_menu_keyboard(current_menu)
        )
        return

    logger.info(f"User {user_id} sent AI request: '{user_message_text[:100]}...'")
    
    user_data_cache = await firestore_service.get_user_data(user_id) 
    current_model_key = await get_current_model_key(user_id, user_data_cache)
    
    can_proceed, limit_message, _ = await check_and_log_request_attempt(user_id, current_model_key)
    
    if not can_proceed:
        # Если лимит исчерпан, check_and_log_request_attempt уже мог сменить модель на дефолтную
        # Поэтому обновляем user_data_cache, чтобы показать правильное меню
        user_data_cache_after_reset = await firestore_service.get_user_data(user_id)
        current_menu_after_reset = user_data_cache_after_reset.get('current_menu', BotConstants.MENU_MAIN)
        await update.message.reply_text(
            limit_message, 
            parse_mode=ParseMode.HTML, 
            reply_markup=generate_menu_keyboard(current_menu_after_reset), 
            disable_web_page_preview=True
        )
        return

    # Получаем ключ модели еще раз на случай, если check_and_log_request_attempt сменил его
    current_model_key = await get_current_model_key(user_id, user_data_cache)
    ai_service = get_ai_service(current_model_key)

    if not ai_service:
        logger.critical(f"Could not get AI service for model key '{current_model_key}'")
        current_menu = user_data_cache.get('current_menu', BotConstants.MENU_MAIN)
        await update.message.reply_text(
            "Произошла критическая ошибка при выборе AI модели. Сообщите администратору.",
            reply_markup=generate_menu_keyboard(current_menu)
        )
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    
    mode_details = await get_current_mode_details(user_id, user_data_cache)
    system_prompt = mode_details["prompt"]
    
    try:
        ai_response_text = await ai_service.generate_response(system_prompt, user_message_text)
    except Exception as e:
        logger.error(f"Unhandled exception in AI service for model {current_model_key}: {e}", exc_info=True)
        ai_response_text = f"Произошла внутренняя ошибка при обработке вашего запроса. Попробуйте позже."

    final_reply_text, _ = smart_truncate(ai_response_text, CONFIG.MAX_MESSAGE_LENGTH_TELEGRAM)
    await increment_request_count(user_id, current_model_key)
    
    current_menu = user_data_cache.get('current_menu', BotConstants.MENU_MAIN)
    await update.message.reply_text(
        final_reply_text, 
        reply_markup=generate_menu_keyboard(current_menu), 
        disable_web_page_preview=True
    )
    

# --- ОБРАБОТЧИК ОШИБОК ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (код без изменений, он будет работать с импортами из config) ...
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    # ... (логика отправки сообщения пользователю и администратору) ...
