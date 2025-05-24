# handlers.py
import traceback
import asyncio # Добавлен для прямого вызова Google AI SDK
import io # Для работы с байтами изображения
from datetime import datetime, timezone, timedelta
import telegram
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice
from telegram.constants import ParseMode, ChatAction
from telegram.ext import ContextTypes

# Импортируем всё необходимое из общего файла config.py
from config import (
    firestore_service, CONFIG, BotConstants, AVAILABLE_TEXT_MODELS,
    AI_MODES, MENU_STRUCTURE, auto_delete_message_decorator,
    get_current_model_key, get_current_mode_details,
    is_menu_button_text, generate_menu_keyboard, _store_and_try_delete_message,
    check_and_log_request_attempt, get_ai_service, smart_truncate,
    increment_request_count, logger, show_menu,
    get_user_gem_balance, update_user_gem_balance, get_daily_usage_for_model,
    genai # Импортируем genai из config, где он должен быть инициализирован
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

    if 'gem_balance' not in user_data_loc:
        updates_to_user_data['gem_balance'] = CONFIG.GEMS_FOR_NEW_USER 

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
    
    if user_data_loc.get('current_menu') != BotConstants.MENU_MAIN:
         await firestore_service.set_user_data(user_id, {'current_menu': BotConstants.MENU_MAIN})
    
    logger.info(f"User {user_id} ({user_first_name}) started or restarted the bot.")

@auto_delete_message_decorator()
async def open_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_menu(update, update.effective_user.id, BotConstants.MENU_MAIN)

@auto_delete_message_decorator()
async def usage_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_limits(update, update.effective_user.id)

@auto_delete_message_decorator()
async def gems_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отображает меню покупки гемов."""
    await show_menu(update, update.effective_user.id, BotConstants.MENU_GEMS_SUBMENU)

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
    
    user_gem_balance = await get_user_gem_balance(user_id, user_data_loc)

    parts = [f"<b>💎 Ваш баланс: {user_gem_balance:.1f} гемов</b>\n"]
    parts.append("<b>📊 Ваши дневные бесплатные лимиты и стоимость:</b>\n")

    for model_key, model_config in AVAILABLE_TEXT_MODELS.items():
        if model_config.get("is_limited", True):
            current_free_usage = await get_daily_usage_for_model(user_id, model_key, bot_data_loc)
            free_daily_limit = model_config.get('free_daily_limit', 0)
            gem_cost = model_config.get('gem_cost', 0.0)

            usage_display = f"Бесплатно сегодня: {current_free_usage}/{free_daily_limit}"
            cost_display = f"Стоимость: {gem_cost:.1f} гемов" if gem_cost > 0 else "Только бесплатно"
            
            bonus_notification = ""
            if model_key == CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY and \
               user_data_loc.get('claimed_news_bonus', False) and \
               (bonus_left := user_data_loc.get('news_bonus_uses_left', 0)) > 0:
                bonus_notification = f" (еще <b>{bonus_left}</b> бонусных)"
            
            parts.append(f"▫️ {model_config['name']}: {usage_display}{bonus_notification}. {cost_display}")

    parts.append("")
    bonus_model_cfg = AVAILABLE_TEXT_MODELS.get(CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY)
    if bonus_model_cfg:
        bonus_model_name_display = bonus_model_cfg['name']
        if not user_data_loc.get('claimed_news_bonus', False):
            parts.append(f'🎁 Подпишитесь на <a href="{CONFIG.NEWS_CHANNEL_LINK}">канал новостей</a>, чтобы получить {CONFIG.NEWS_CHANNEL_BONUS_GENERATIONS} бонусных генераций для {bonus_model_name_display}! Нажмите «🎁 Бонус» в меню.')
        elif (bonus_left_val := user_data_loc.get('news_bonus_uses_left', 0)) > 0:
            parts.append(f"✅ У вас есть <b>{bonus_left_val}</b> бонусных генераций для {bonus_model_name_display}.")
        else:
            parts.append(f"ℹ️ Бонус с канала новостей для {bonus_model_name_display} был использован.")
    
    parts.append("\n💎 Пополнить баланс гемов можно через меню «💎 Гемы» или команду /gems.")
        
    current_menu_for_reply = user_data_loc.get('current_menu', BotConstants.MENU_LIMITS_SUBMENU)
    await update.message.reply_text(
        "\n".join(parts), 
        parse_mode=ParseMode.HTML, 
        reply_markup=generate_menu_keyboard(current_menu_for_reply),
        disable_web_page_preview=True
    )

async def claim_news_bonus_logic(update: Update, user_id: int):
    user_data_loc = await firestore_service.get_user_data(user_id)
    parent_menu_key = user_data_loc.get('current_menu', BotConstants.MENU_BONUS_SUBMENU)
    current_menu_config = MENU_STRUCTURE.get(parent_menu_key, MENU_STRUCTURE[BotConstants.MENU_MAIN])
    reply_menu_key = current_menu_config.get("parent", BotConstants.MENU_MAIN) if current_menu_config.get("is_submenu") else parent_menu_key

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
            await update.message.reply_text(success_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(reply_menu_key), disable_web_page_preview=True)
            await firestore_service.set_user_data(user_id, {'current_menu': reply_menu_key}) 
        else:
            fail_text = (f'Сначала подпишитесь на <a href="{CONFIG.NEWS_CHANNEL_LINK}">{CONFIG.NEWS_CHANNEL_USERNAME}</a>, '
                         f'а затем вернитесь и нажмите кнопку «🎁 Получить» еще раз.')
            inline_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(f"📢 Перейти на {CONFIG.NEWS_CHANNEL_USERNAME}", url=CONFIG.NEWS_CHANNEL_LINK)]])
            await update.message.reply_text(fail_text, parse_mode=ParseMode.HTML, reply_markup=inline_keyboard, disable_web_page_preview=True)
    except telegram.error.TelegramError as e:
        logger.error(f"Bonus claim TelegramError for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("Ошибка при проверке подписки. Попробуйте позже.", reply_markup=generate_menu_keyboard(reply_menu_key))
    except Exception as e:
        logger.error(f"Unexpected error during news bonus claim for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("Произошла непредвиденная ошибка.", reply_markup=generate_menu_keyboard(reply_menu_key))

async def show_help(update: Update, user_id: int):
    user_data_loc = await firestore_service.get_user_data(user_id)
    help_text = (
        "<b>❓ Справка по использованию бота</b>\n\n"
        "1.  <b>Запросы к ИИ</b>: Просто напишите ваш вопрос или задачу в чат.\n"
        "2.  <b>Меню</b>: Используйте кнопки для доступа ко всем функциям:\n"
        "    ▫️ «🤖 Агенты ИИ»: Выберите роль для ИИ.\n"
        "    ▫️ «⚙️ Модели ИИ»: Переключайтесь между моделями.\n"
        "    ▫️ «📊 Лимиты»: Проверьте дневные бесплатные лимиты, баланс гемов и стоимость моделей.\n"
        "    ▫️ «🎁 Бонус»: Получите бонусные генерации за подписку на новостной канал.\n"
        "    ▫️ «💎 Гемы»: Просмотр и покупка пакетов гемов.\n"
        "    ▫️ «❓ Помощь»: Этот раздел справки.\n\n"
        "3.  <b>Основные команды</b> (дублируют функции меню):\n"
        "    ▫️ /start - Перезапуск бота и отображение приветственного сообщения.\n"
        "    ▫️ /menu - Открыть главное меню.\n"
        "    ▫️ /usage - Показать лимиты и баланс гемов.\n"
        "    ▫️ /gems - Открыть магазин гемов.\n"
        "    ▫️ /bonus - Получить бонус за подписку на канал.\n"
        "    ▫️ /help - Показать эту справку."
    )
    current_menu_for_reply = user_data_loc.get('current_menu', BotConstants.MENU_HELP_SUBMENU)
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(current_menu_for_reply), disable_web_page_preview=True)

async def send_gem_purchase_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE, package_key: str):
    user_id = update.effective_user.id
    package_info = CONFIG.GEM_PACKAGES.get(package_key)

    if not package_info:
        logger.error(f"User {user_id} tried to buy non-existent gem package: {package_key}")
        await update.message.reply_text("Ошибка: Выбранный пакет гемов не найден.",
                                        reply_markup=generate_menu_keyboard(BotConstants.MENU_GEMS_SUBMENU))
        return

    title = package_info["title"]
    description = package_info["description"]
    payload = f"gems_{package_key}_user_{user_id}_{int(datetime.now().timestamp())}"
    currency = package_info["currency"]
    price_units = package_info["price_units"]

    prices = [LabeledPrice(label=f"{package_info['gems']} Гемов", amount=price_units)]

    if not CONFIG.PAYMENT_PROVIDER_TOKEN or "YOUR_" in CONFIG.PAYMENT_PROVIDER_TOKEN: # Проверка токена
        logger.error("Payment provider token is not configured for sending invoice.")
        await update.message.reply_text("К сожалению, система оплаты временно недоступна.",
                                        reply_markup=generate_menu_keyboard(BotConstants.MENU_GEMS_SUBMENU))
        return
        
    try:
        current_menu = (await firestore_service.get_user_data(user_id)).get('current_menu', BotConstants.MENU_GEMS_SUBMENU)
        await update.message.reply_text(
            f"Вы выбрали пакет «{title}». Сейчас я отправлю вам счет для оплаты.",
            reply_markup=generate_menu_keyboard(current_menu) 
        )
        await context.bot.send_invoice(
            chat_id=user_id, title=title, description=description, payload=payload,
            provider_token=CONFIG.PAYMENT_PROVIDER_TOKEN, currency=currency, prices=prices
        )
        logger.info(f"Invoice for package '{package_key}' sent to user {user_id}.")
    except Exception as e:
        logger.error(f"Failed to send invoice to user {user_id} for package {package_key}: {e}", exc_info=True)
        await update.message.reply_text("Ошибка при формировании счета. Попробуйте позже.",
                                        reply_markup=generate_menu_keyboard(BotConstants.MENU_GEMS_SUBMENU))

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
    
    effective_menu_key_of_action = current_menu_key # Меню, в котором фактически была найдена кнопка
    for menu_key_search_loop in search_order:
        for item in MENU_STRUCTURE.get(menu_key_search_loop, {}).get("items", []):
            if item["text"] == button_text:
                action_item_found = item
                effective_menu_key_of_action = menu_key_search_loop
                break
        if action_item_found:
            break
    
    if not action_item_found:
        logger.error(f"Button '{button_text}' was identified as menu button, but no action found. User's current_menu in DB: '{user_data_loc.get('current_menu', 'N/A')}'")
        await show_menu(update, user_id, BotConstants.MENU_MAIN) # Возвращаем в главное меню при ошибке
        return

    action_type = action_item_found["action"]
    action_target = action_item_found["target"]

    if action_type == BotConstants.CALLBACK_ACTION_SUBMENU:
        await show_menu(update, user_id, action_target)
    
    elif action_type == BotConstants.CALLBACK_ACTION_SET_AGENT:
        await firestore_service.set_user_data(user_id, {'current_ai_mode': action_target})
        agent_name = AI_MODES.get(action_target, {}).get('name', 'N/A')
        response_text = f"🤖 Агент ИИ изменен на: <b>{agent_name}</b>."
        # Остаемся в меню выбора агентов (effective_menu_key_of_action должен быть MENU_AI_MODES_SUBMENU)
        await update.message.reply_text(response_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(effective_menu_key_of_action))
        await firestore_service.set_user_data(user_id, {'current_menu': effective_menu_key_of_action})

    elif action_type == BotConstants.CALLBACK_ACTION_SET_MODEL:
        model_info = AVAILABLE_TEXT_MODELS.get(action_target, {})
        update_payload = {
            'selected_model_id': model_info.get("id"), 
            'selected_api_type': model_info.get("api_type")
        }
        if action_target in ["custom_api_grok_3", "custom_api_gpt_4o_mini"] and \
           user_data_loc.get('current_ai_mode') == "gemini_pro_custom_mode":
            update_payload['current_ai_mode'] = CONFIG.DEFAULT_AI_MODE_KEY
            logger.info(f"User {user_id} selected model {action_target}, AI mode reset from gemini_pro_custom_mode to default.")
        
        await firestore_service.set_user_data(user_id, update_payload)
        user_data_loc.update(update_payload) 
        
        bot_data_cache = await firestore_service.get_bot_data()
        current_free_usage_for_selected = await get_daily_usage_for_model(user_id, action_target, bot_data_cache)
        free_daily_limit_for_selected = model_info.get('free_daily_limit',0)
        gem_cost_for_selected = model_info.get('gem_cost',0.0)

        response_text = (f"⚙️ Модель ИИ изменена на: <b>{model_info.get('name', 'N/A')}</b>.\n"
                         f"Бесплатно сегодня: {current_free_usage_for_selected}/{free_daily_limit_for_selected}.\n"
                         f"Стоимость: {gem_cost_for_selected:.1f} гемов.")
        
        # Остаемся в меню выбора моделей (effective_menu_key_of_action должен быть MENU_MODELS_SUBMENU)
        await update.message.reply_text(response_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(effective_menu_key_of_action))
        await firestore_service.set_user_data(user_id, {'current_menu': effective_menu_key_of_action})

    elif action_type == BotConstants.CALLBACK_ACTION_SHOW_LIMITS:
        await show_limits(update, user_id)
    elif action_type == BotConstants.CALLBACK_ACTION_CHECK_BONUS:
        await claim_news_bonus_logic(update, user_id)
    elif action_type == BotConstants.CALLBACK_ACTION_SHOW_GEMS_STORE: # Для кнопки "Магазин Гемов", если она не ведет в SUBMENU
        await show_menu(update, user_id, BotConstants.MENU_GEMS_SUBMENU)
    elif action_type == BotConstants.CALLBACK_ACTION_BUY_GEM_PACKAGE:
        package_key_to_buy = action_target
        await send_gem_purchase_invoice(update, context, package_key_to_buy)
    elif action_type == BotConstants.CALLBACK_ACTION_SHOW_HELP:
        await show_help(update, user_id)
    else:
        logger.warning(f"Unknown action type '{action_type}' for button '{button_text}'")
        await show_menu(update, user_id, BotConstants.MENU_MAIN)

# --- ОБРАБОТЧИК ФОТО ---
async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = await firestore_service.get_user_data(user_id)
    current_ai_mode_key = user_data.get('current_ai_mode')
    active_agent_config = AI_MODES.get(current_ai_mode_key)

    if active_agent_config and active_agent_config.get("multimodal_capable"):
        model_to_use_for_billing = active_agent_config.get("forced_model_key")
        if not model_to_use_for_billing or model_to_use_for_billing not in AVAILABLE_TEXT_MODELS:
            logger.error(f"Agent {current_ai_mode_key} has invalid forced_model_key: {model_to_use_for_billing} for billing.")
            await update.message.reply_text("Ошибка конфигурации модели для этого агента.")
            return

        bot_data_cache = await firestore_service.get_bot_data()
        can_proceed, check_message, _, _ = await check_and_log_request_attempt( # usage_type и gem_cost не нужны здесь
            user_id, model_to_use_for_billing, user_data, bot_data_cache
        )

        if not can_proceed:
            await update.message.reply_text(check_message, parse_mode=ParseMode.HTML)
            return
        
        photo_file = update.message.photo[-1]
        context.user_data['dietitian_pending_photo_id'] = photo_file.file_id
        context.user_data['dietitian_state'] = 'awaiting_weight'
        
        logger.info(f"User {user_id} (agent {current_ai_mode_key}) sent photo {photo_file.file_id}. Awaiting weight. Billing model: {model_to_use_for_billing}. Usage check passed.")
        await update.message.reply_text(
            "Отличное фото! Чтобы я мог точно рассчитать КБЖУ, пожалуйста, укажите примерный вес этой порции в граммах."
        )
    else:
        if update.message:
             await update.message.reply_text(
                "Чтобы анализировать фото еды, пожалуйста, выберите агента '🥑 Диетолог (анализ фото)' в меню '🤖 Агенты ИИ'."
            )

# --- ОБРАБОТЧИК ТЕКСТА (ЗАПРОСЫ К AI) ---
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text or is_menu_button_text(update.message.text.strip()):
        return
        
    user_id = update.effective_user.id
    user_message_text = update.message.text.strip()
    user_data_cache = await firestore_service.get_user_data(user_id)
    current_ai_mode_key = user_data_cache.get('current_ai_mode', CONFIG.DEFAULT_AI_MODE_KEY)
    active_agent_config = AI_MODES.get(current_ai_mode_key)

    # Логика для Диетолога (анализ фото), ожидающего вес
    if active_agent_config and \
       active_agent_config.get("multimodal_capable") and \
       context.user_data.get('dietitian_state') == 'awaiting_weight' and \
       'dietitian_pending_photo_id' in context.user_data:

        photo_file_id = context.user_data['dietitian_pending_photo_id']
        billing_model_key = active_agent_config.get("forced_model_key") # Для списания гемов/лимитов
        native_vision_model_id = active_agent_config.get("native_vision_model_id", "gemini-1.5-flash-latest")

        if not billing_model_key or billing_model_key not in AVAILABLE_TEXT_MODELS:
            logger.error(f"Photo Dietitian agent '{current_ai_mode_key}' has invalid 'forced_model_key': {billing_model_key}")
            await update.message.reply_text("Ошибка конфигурации биллинг-модели для Диетолога. Сообщите администратору.")
            context.user_data.pop('dietitian_state', None); context.user_data.pop('dietitian_pending_photo_id', None)
            return

        bot_data_cache = await firestore_service.get_bot_data()
        can_proceed, limit_or_gem_message, usage_type, gem_cost_for_request = await check_and_log_request_attempt(
            user_id, billing_model_key, user_data_cache, bot_data_cache
        )

        if not can_proceed:
            await update.message.reply_text(limit_or_gem_message, parse_mode=ParseMode.HTML)
            return
        
        logger.info(f"User {user_id} (agent {current_ai_mode_key}) provided weight: '{user_message_text}' for photo {photo_file_id}. Billing Model: {billing_model_key}. Usage: {usage_type}. Vision Model: {native_vision_model_id}")
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        
        ai_response_text = "Ошибка при обработке изображения."
        try:
            if not CONFIG.GOOGLE_GEMINI_API_KEY or "YOUR_" in CONFIG.GOOGLE_GEMINI_API_KEY: # Проверка ключа Google
                raise ValueError("API ключ для Google Gemini (Vision) не настроен в конфигурации бота.")

            actual_photo_file = await context.bot.get_file(photo_file_id)
            file_bytes = await actual_photo_file.download_as_bytearray()
            
            image_part = {"mime_type": actual_photo_file.mime_type or "image/jpeg", "data": bytes(file_bytes)}
            
            # Промпт для Vision модели (может отличаться от основного промпта агента)
            # Основной промпт агента содержит инструкции по диалогу, которые здесь не нужны
            vision_system_prompt = (
                "Проанализируй изображение еды и текст с указанием веса. "
                "Определи блюдо/продукты. Рассчитай примерные КБЖУ (калории, белки, жиры, углеводы) для указанного веса. "
                "Представь результат в структурированном виде, начиная с названия блюда, затем вес, затем КБЖУ."
            )
            text_prompt_with_weight = f"Вес этой порции: {user_message_text}. {vision_system_prompt}"
            
            # Используем genai, импортированный из config, где он уже должен быть сконфигурирован
            model_vision = genai.GenerativeModel(native_vision_model_id)
            logger.debug(f"Sending to Google Vision API. Model: {native_vision_model_id}. Text prompt part: {text_prompt_with_weight[:100]}")
            response_vision = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: model_vision.generate_content([image_part, text_prompt_with_weight])
            )
            ai_response_text = response_vision.text
            logger.info(f"Successfully received response from Google Vision API for user {user_id}")

        except ValueError as ve:
            logger.error(f"Configuration error for Google Gemini Vision: {ve}")
            ai_response_text = str(ve)
        except Exception as e:
            logger.error(f"Error with Google Gemini Vision API for user {user_id}: {e}", exc_info=True)
            ai_response_text = "К сожалению, не удалось проанализировать изображение. Попробуйте позже."
        
        await increment_request_count(user_id, billing_model_key, usage_type, gem_cost_for_request)
        
        final_reply_text, _ = smart_truncate(ai_response_text, CONFIG.MAX_MESSAGE_LENGTH_TELEGRAM)
        current_menu = user_data_cache.get('current_menu', BotConstants.MENU_AI_MODES_SUBMENU) 
        await update.message.reply_text(final_reply_text, reply_markup=generate_menu_keyboard(current_menu))
        
        context.user_data.pop('dietitian_state', None)
        context.user_data.pop('dietitian_pending_photo_id', None)
        return 
    
    # --- Обычная обработка текста ---
    final_model_key_for_request = ""
    # Если текущий агент "photo_dietitian_analyzer", но он не ждет вес (т.е. это обычный текстовый запрос к нему)
    if active_agent_config and active_agent_config.get("multimodal_capable") and not context.user_data.get('dietitian_state') == 'awaiting_weight':
        final_model_key_for_request = active_agent_config.get("forced_model_key")
        logger.info(f"Agent '{current_ai_mode_key}' (multimodal in text mode) forcing model to '{final_model_key_for_request}'.")
    elif active_agent_config and active_agent_config.get("forced_model_key") and not active_agent_config.get("multimodal_capable"):
        final_model_key_for_request = active_agent_config.get("forced_model_key")
        logger.info(f"Agent '{current_ai_mode_key}' forcing model to '{final_model_key_for_request}' for text request.")
    else:
        final_model_key_for_request = await get_current_model_key(user_id, user_data_cache)

    bot_data_cache_for_check = await firestore_service.get_bot_data()
    can_proceed, limit_or_gem_message, usage_type, gem_cost_for_request = await check_and_log_request_attempt(
        user_id, final_model_key_for_request, user_data_cache, bot_data_cache_for_check
    )
        
    if not can_proceed:
        await update.message.reply_text(limit_or_gem_message, parse_mode=ParseMode.HTML, 
                                        reply_markup=generate_menu_keyboard(user_data_cache.get('current_menu', BotConstants.MENU_MAIN)), 
                                        disable_web_page_preview=True)
        return

    if len(user_message_text) < CONFIG.MIN_AI_REQUEST_LENGTH:
        current_menu = user_data_cache.get('current_menu', BotConstants.MENU_MAIN)
        await update.message.reply_text("Ваш запрос слишком короткий.", reply_markup=generate_menu_keyboard(current_menu))
        return

    logger.info(f"User {user_id} (agent: {current_ai_mode_key}, model: {final_model_key_for_request}) sent AI request: '{user_message_text[:100]}...'")

    ai_service = get_ai_service(final_model_key_for_request)
    if not ai_service:
        logger.critical(f"Could not get AI service for model key '{final_model_key_for_request}'.")
        current_menu = user_data_cache.get('current_menu', BotConstants.MENU_MAIN)
        await update.message.reply_text("Критическая ошибка при выборе AI модели.", reply_markup=generate_menu_keyboard(current_menu))
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    
    system_prompt_to_use = active_agent_config["prompt"] if active_agent_config else AI_MODES[CONFIG.DEFAULT_AI_MODE_KEY]["prompt"]
    
    ai_response_text = "К сожалению, не удалось получить ответ от ИИ."
    try:
        # Для текстовых запросов image_data не передается (или None)
        ai_response_text = await ai_service.generate_response(system_prompt_to_use, user_message_text) 
    except Exception as e:
        model_name_for_error = AVAILABLE_TEXT_MODELS.get(final_model_key_for_request, {}).get('name', final_model_key_for_request)
        logger.error(f"Unhandled exception in AI service for model {model_name_for_error}: {e}", exc_info=True)
        ai_response_text = f"Произошла внутренняя ошибка при обработке вашего запроса моделью {model_name_for_error}."
    
    await increment_request_count(user_id, final_model_key_for_request, usage_type, gem_cost_for_request)

    final_reply_text, was_truncated = smart_truncate(ai_response_text, CONFIG.MAX_MESSAGE_LENGTH_TELEGRAM)
    if was_truncated:
        logger.info(f"AI response for user {user_id} was truncated.")
    
    current_menu = user_data_cache.get('current_menu', BotConstants.MENU_MAIN)
    await update.message.reply_text(
        final_reply_text, 
        reply_markup=generate_menu_keyboard(current_menu), 
        disable_web_page_preview=True
    )
    logger.info(f"Successfully sent AI response (model: {final_model_key_for_request}, usage: {usage_type}) to user {user_id}.")

# --- ОБРАБОТЧИКИ ПЛАТЕЖЕЙ ---
async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    if query.invoice_payload and query.invoice_payload.startswith("gems_"):
        payload_parts = query.invoice_payload.split('_')
        user_part_index = -1
        for i, part in enumerate(payload_parts):
            if part == "user": user_part_index = i; break
        
        if user_part_index > 1 and len(payload_parts) > user_part_index + 1 :
            package_key_from_payload = "_".join(payload_parts[1:user_part_index])
            if package_key_from_payload in CONFIG.GEM_PACKAGES:
                try:
                    user_id_in_payload = int(payload_parts[user_part_index + 1])
                    if query.from_user.id == user_id_in_payload:
                        await query.answer(ok=True)
                        logger.info(f"PreCheckoutQuery OK for gems payload: {query.invoice_payload}")
                        return
                    else:
                        logger.error(f"PreCheckoutQuery FAILED. User ID mismatch. Payload User: {user_id_in_payload}, Query User: {query.from_user.id}")
                        await query.answer(ok=False, error_message="Ошибка проверки пользователя.")
                        return
                except (ValueError, IndexError):
                    logger.error(f"PreCheckoutQuery FAILED. Error parsing user_id from payload: {query.invoice_payload}")
                    await query.answer(ok=False, error_message="Ошибка в данных платежа.")
                    return    
            else:
                logger.warning(f"PreCheckoutQuery FAILED. Unknown gem package: {query.invoice_payload}")
                await query.answer(ok=False, error_message="Пакет гемов не найден.")    
                return
        
    logger.warning(f"PreCheckoutQuery FAILED. Invalid payload format/type: {query.invoice_payload}")
    await query.answer(ok=False, error_message="Неверный запрос на оплату.")

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    payment_info = update.message.successful_payment
    invoice_payload = payment_info.invoice_payload

    logger.info(f"Successful payment from {user_id}. Amount: {payment_info.total_amount} {payment_info.currency}. Payload: {invoice_payload}")

    if invoice_payload and invoice_payload.startswith("gems_"):
        try:
            payload_parts = invoice_payload.split('_')
            user_part_index = -1
            for i, part in enumerate(payload_parts):
                if part == "user": user_part_index = i; break
            
            if user_part_index == -1 or user_part_index <= 1 or len(payload_parts) <= user_part_index + 1:
                raise ValueError("Invalid payload: missing user or package info")

            package_key = "_".join(payload_parts[1:user_part_index])
            user_id_from_payload = int(payload_parts[user_part_index + 1])

            if user_id != user_id_from_payload:
                logger.error(f"Security: Payload user ID {user_id_from_payload} != message user ID {user_id}")
                await update.message.reply_text("Ошибка обработки платежа. Свяжитесь с поддержкой.")
                if CONFIG.ADMIN_ID: await context.bot.send_message(CONFIG.ADMIN_ID, f"⚠️ Ошибка User ID в платеже! Payload: {invoice_payload}, User: {user_id}")
                return

            package_info = CONFIG.GEM_PACKAGES.get(package_key)
            if not package_info:
                logger.error(f"Successful payment for UNKNOWN gem package '{package_key}' by user {user_id}")
                await update.message.reply_text("Ошибка: купленный пакет не найден. Свяжитесь с поддержкой.")
                return

            gems_to_add = float(package_info["gems"])
            current_gem_balance = await get_user_gem_balance(user_id)
            new_gem_balance = current_gem_balance + gems_to_add
            await update_user_gem_balance(user_id, new_gem_balance)

            confirmation_message = (
                f"🎉 Оплата прошла успешно! Вам начислено <b>{gems_to_add:.1f} гемов</b>.\n"
                f"Ваш новый баланс: <b>{new_gem_balance:.1f} гемов</b>.\n\nСпасибо за покупку!"
            )
            user_data_for_reply_menu = await firestore_service.get_user_data(user_id)
            await update.message.reply_text(
                confirmation_message, parse_mode=ParseMode.HTML, 
                reply_markup=generate_menu_keyboard(user_data_for_reply_menu.get('current_menu', BotConstants.MENU_GEMS_SUBMENU))
            )

            if CONFIG.ADMIN_ID:
                admin_message = (
                    f"💎 Новая покупка гемов!\n"
                    f"Пользователь: {user_id} ({update.effective_user.full_name if update.effective_user else 'N/A'})\n"
                    f"Пакет: {package_info['title']} ({gems_to_add:.1f} гемов)\n"
                    f"Сумма: {payment_info.total_amount / 100.0:.2f} {payment_info.currency}\n"
                    f"Новый баланс: {new_gem_balance:.1f} гемов\nPayload: {invoice_payload}"
                )
                await context.bot.send_message(CONFIG.ADMIN_ID, admin_message)
        except Exception as e:
            logger.error(f"Error processing successful gem payment for user {user_id}, payload {invoice_payload}: {e}", exc_info=True)
            await update.message.reply_text("Ошибка при начислении гемов. Свяжитесь с поддержкой.")
    else:
        logger.warning(f"Successful payment with unknown payload type from user {user_id}: {invoice_payload}")

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
            f"User: {update.effective_user.id} (@{update.effective_user.username if update.effective_user.username else 'N/A'})\n"
            f"Msg: {update.message.text if update.message and update.message.text else 'N/A'}\n"
            f"Error: {context.error}\n\n"
            f"Traceback (short):\n```\n{tb_string[-1500:]}\n```" # Последние 1500 символов трейсбека
        )
        try:
            await context.bot.send_message(CONFIG.ADMIN_ID, error_details, parse_mode=ParseMode.MARKDOWN_V2)
        except telegram.error.TelegramError as e_md:
            logger.error(f"Failed to send detailed error to admin with MarkdownV2: {e_md}. Plain text fallback.")
            try:
                 plain_error_details = f"PLAIN TEXT FALLBACK:\n{error_details.replace('```', '')}"
                 await context.bot.send_message(CONFIG.ADMIN_ID, plain_error_details)
            except Exception as e_plain:
                 logger.error(f"Failed to send plain text error report to admin: {e_plain}")
