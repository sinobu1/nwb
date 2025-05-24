# handlers.py
import traceback
from datetime import datetime, timezone, timedelta
import telegram
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode, ChatAction
from telegram.ext import ContextTypes
from telegram import LabeledPrice
# Импортируем всё необходимое из общего файла config.py
from config import (
    firestore_service, CONFIG, BotConstants, AVAILABLE_TEXT_MODELS,
    AI_MODES, MENU_STRUCTURE, auto_delete_message_decorator,
    get_current_model_key, get_current_mode_details, # УДАЛИТЕ get_user_actual_limit_for_model если он тут был
    is_menu_button_text, generate_menu_keyboard, _store_and_try_delete_message,
    check_and_log_request_attempt, get_ai_service, smart_truncate,
    increment_request_count, # УДАЛИТЕ is_user_profi_subscriber если он тут был
    logger, show_menu,
    # НОВЫЕ функции для гемов, которые мы определили в config.py
    get_user_gem_balance, update_user_gem_balance, get_daily_usage_for_model
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
        
    if 'gem_balance' not in user_data_loc: # Инициализация баланса гемов
    updates_to_user_data['gem_balance'] = CONFIG.GEMS_FOR_NEW_USER # Например, 0 или приветственный бонус

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
async def gems_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE): # Было subscribe_info_command
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
    bot_data_loc = await firestore_service.get_bot_data() # Получаем один раз

    user_gem_balance = await get_user_gem_balance(user_id, user_data_loc) # Используем новую функцию

    parts = [f"<b>💎 Ваш баланс: {user_gem_balance:.1f} гемов</b>\n"] # Баланс с 1 знаком после запятой
    parts.append("<b>📊 Ваши дневные бесплатные лимиты и стоимость:</b>\n")

    for model_key, model_config in AVAILABLE_TEXT_MODELS.items():
        if model_config.get("is_limited"):
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
            parts.append(f'🎁 Подпишитесь на <a href="{CONFIG.NEWS_CHANNEL_LINK}">канал новостей</a>, чтобы получить бонусные генерации ({CONFIG.NEWS_CHANNEL_BONUS_GENERATIONS} для {bonus_model_name_display})! Нажмите «🎁 Бонус» в меню.')
        elif (bonus_left_val := user_data_loc.get('news_bonus_uses_left', 0)) > 0:
            parts.append(f"✅ У вас есть <b>{bonus_left_val}</b> бонусных генераций с канала новостей для модели {bonus_model_name_display}.")
        else:
            parts.append(f"ℹ️ Бонус с канала новостей для модели {bonus_model_name_display} был использован.")

    parts.append("\n💎 Пополнить баланс гемов можно через меню «Гемы» (скоро).") # Заглушка

    current_menu_for_reply = user_data_loc.get('current_menu', BotConstants.MENU_MAIN)
    await update.message.reply_text(
        "\n".join(parts), 
        parse_mode=ParseMode.HTML, 
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
        "    /start, /menu, /usage, /subscribe, /bonus, /help." # /start здесь только для информации
    )
    current_menu_for_reply = user_data_loc.get('current_menu', BotConstants.MENU_MAIN)
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(current_menu_for_reply), disable_web_page_preview=True)

# --- >>> НОВАЯ ФУНКЦИЯ для отправки счета за гемы <<< ---
async def send_gem_purchase_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE, package_key: str):
    user_id = update.effective_user.id
    package_info = CONFIG.GEM_PACKAGES.get(package_key)

    if not package_info:
        logger.error(f"User {user_id} tried to buy non-existent gem package: {package_key}")
        await update.message.reply_text("Ошибка: Выбранный пакет гемов не найден. Пожалуйста, попробуйте еще раз.",
                                        reply_markup=generate_menu_keyboard(BotConstants.MENU_GEMS_SUBMENU))
        return

    title = package_info["title"]
    description = package_info["description"]
    # Уникальный payload для этого счета
    payload = f"gems_{package_key}_user_{user_id}_{int(datetime.now().timestamp())}"
    currency = package_info["currency"]
    price_units = package_info["price_units"] # Цена в минимальных единицах валюты

    prices = [LabeledPrice(label=f"{package_info['gems']} Гемов", amount=price_units)]

    if not CONFIG.PAYMENT_PROVIDER_TOKEN or "YOUR_" in CONFIG.PAYMENT_PROVIDER_TOKEN:
        logger.error("Payment provider token is not configured for sending invoice.")
        await update.message.reply_text(
            "К сожалению, система оплаты временно недоступна. Попробуйте позже.",
            reply_markup=generate_menu_keyboard(BotConstants.MENU_GEMS_SUBMENU)
        )
        return
        
    try:
        await context.bot.send_invoice(
            chat_id=user_id,
            title=title,
            description=description,
            payload=payload,
            provider_token=CONFIG.PAYMENT_PROVIDER_TOKEN,
            currency=currency,
            prices=prices,
            # можно добавить start_parameter, need_name, need_phone_number и т.д. по необходимости
        )
        logger.info(f"Invoice for package '{package_key}' sent to user {user_id}.")
        # После отправки счета, можно вернуть пользователя в меню гемов или оставить как есть
        # await show_menu(update, user_id, BotConstants.MENU_GEMS_SUBMENU) # Опционально
    except Exception as e:
        logger.error(f"Failed to send invoice to user {user_id} for package {package_key}: {e}", exc_info=True)
        await update.message.reply_text(
            "Произошла ошибка при формировании счета. Пожалуйста, попробуйте позже.",
            reply_markup=generate_menu_keyboard(BotConstants.MENU_GEMS_SUBMENU)

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
    
    for menu_key_search_loop in search_order: # Изменил имя переменной цикла, чтобы не конфликтовать
        for item in MENU_STRUCTURE.get(menu_key_search_loop, {}).get("items", []):
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
        await show_menu(update, user_id, action_target)
    
    elif action_type == BotConstants.CALLBACK_ACTION_SET_AGENT:
        await firestore_service.set_user_data(user_id, {'current_ai_mode': action_target})
        agent_name = AI_MODES.get(action_target, {}).get('name', 'N/A')
        response_text = f"🤖 Агент ИИ изменен на: <b>{agent_name}</b>."
        # current_menu_key здесь - это меню, из которого была нажата кнопка (т.е. MENU_AI_MODES_SUBMENU)
        reply_menu_after_set_agent = current_menu_key 
        
        await update.message.reply_text(response_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(reply_menu_after_set_agent))
        await firestore_service.set_user_data(user_id, {'current_menu': reply_menu_after_set_agent})

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
        today_string_val = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        user_model_counts = bot_data_cache.get(BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY, {}).get(str(user_id), {})
        model_daily_usage = user_model_counts.get(action_target, {'date': '', 'count': 0})
        current_usage_string = str(model_daily_usage['count']) if model_daily_usage.get('date') == today_string_val else "0"
        
        actual_limit_string = await get_user_actual_limit_for_model(user_id, action_target, user_data_loc, bot_data_cache)
        limit_display_string = '∞' if actual_limit_string == float('inf') else str(int(actual_limit_string))
        
        response_text = (f"⚙️ Модель ИИ изменена на: <b>{model_info.get('name', 'N/A')}</b>.\n"
                         f"Дневной лимит: {current_usage_string} / {limit_display_string}.")
        
        # current_menu_key здесь - это меню, из которого была нажата кнопка (т.е. MENU_MODELS_SUBMENU)
        reply_menu_after_set_model = current_menu_key

        await update.message.reply_text(response_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(reply_menu_after_set_model))
        await firestore_service.set_user_data(user_id, {'current_menu': reply_menu_after_set_model})

    elif action_type == BotConstants.CALLBACK_ACTION_SHOW_LIMITS:
        await show_limits(update, user_id)
    elif action_type == BotConstants.CALLBACK_ACTION_CHECK_BONUS:
        await claim_news_bonus_logic(update, user_id)
    elif action_type == BotConstants.CALLBACK_ACTION_SHOW_GEMS_STORE: # Если вы сделали кнопку для перехода в магазин гемов
        await show_menu(update, user_id, BotConstants.MENU_GEMS_SUBMENU)
    elif action_type == BotConstants.CALLBACK_ACTION_SHOW_HELP:
        await show_help(update, user_id)
    elif action_type == BotConstants.CALLBACK_ACTION_BUY_GEM_PACKAGE:
        package_key_to_buy = action_target # target здесь будет ключом пакета, например "pack_10_gems"
        await send_gem_purchase_invoice(update, context, package_key_to_buy)
    else:
        logger.warning(f"Unknown action type '{action_type}' for button '{button_text}'")
        await show_menu(update, user_id, BotConstants.MENU_MAIN)

# --- ОБРАБОТЧИК ТЕКСТА (ЗАПРОСЫ К AI) ---
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text or is_menu_button_text(update.message.text.strip()):
        return
        
    user_id = update.effective_user.id
    user_message_text = update.message.text.strip()
    # Сообщение пользователя больше не удаляется
    # await _store_and_try_delete_message(update, user_id, is_command_to_keep=False)

    if len(user_message_text) < CONFIG.MIN_AI_REQUEST_LENGTH:
        user_data_cache = await firestore_service.get_user_data(user_id)
        current_menu = user_data_cache.get('current_menu', BotConstants.MENU_MAIN)
        await update.message.reply_text("Ваш запрос слишком короткий.", reply_markup=generate_menu_keyboard(current_menu))
        return

    logger.info(f"User {user_id} sent AI request: '{user_message_text[:100]}...'")

user_data_cache = await firestore_service.get_user_data(user_id) 
bot_data_cache_for_check = await firestore_service.get_bot_data() # Получаем один раз для передачи
current_model_key = await get_current_model_key(user_id, user_data_cache)

# Теперь check_and_log_request_attempt возвращает больше информации
can_proceed, limit_or_gem_message, usage_type, gem_cost_for_request = await check_and_log_request_attempt(
    user_id, current_model_key, user_data_cache, bot_data_cache_for_check
)

if not can_proceed:
    # ... (обработка limit_or_gem_message как раньше) ...
    # limit_or_gem_message уже содержит информацию о нехватке гемов или исчерпании лимита
    await update.message.reply_text(
        limit_or_gem_message, 
        parse_mode=ParseMode.HTML, 
        reply_markup=generate_menu_keyboard(user_data_cache.get('current_menu', BotConstants.MENU_MAIN)), 
        disable_web_page_preview=True
    )
    return

# Если can_proceed, то limit_or_gem_message содержит информационное сообщение (о бонусе, бесплатной попытке или списании гемов)
# Можно его отправить пользователю, если это уместно, или просто продолжить
# Например, если это списание гемов, можно уведомить:
if usage_type == "gem" and gem_cost_for_request:
     # Можно отправить отдельным сообщением или добавить к ответу ИИ
     # await update.message.reply_text(f"🤖 {limit_or_gem_message}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)
     pass # Решите, нужно ли это сообщение

    current_model_key = await get_current_model_key(user_id, user_data_cache) # Перечитываем на случай смены
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
        # После успешного ответа от AI, вызываем increment_request_count
# final_reply_text, _ = smart_truncate(ai_response_text, CONFIG.MAX_MESSAGE_LENGTH_TELEGRAM) # Это уже есть
    await increment_request_count(user_id, current_model_key, usage_type, gem_cost_for_request)

    final_reply_text, _ = smart_truncate(ai_response_text, CONFIG.MAX_MESSAGE_LENGTH_TELEGRAM)
    await increment_request_count(user_id, current_model_key)
    
    current_menu = user_data_cache.get('current_menu', BotConstants.MENU_MAIN)
    await update.message.reply_text(final_reply_text, reply_markup=generate_menu_keyboard(current_menu), disable_web_page_preview=True)

# --- ОБРАБОТЧИКИ ПЛАТЕЖЕЙ (изменяем) ---
async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    # --- >>> ИЗМЕНЯЕМ ПРОВЕРКУ PAYLOAD <<< ---
    # Раньше было: expected_payload_part = f"subscription_{CONFIG.PRO_SUBSCRIPTION_LEVEL_KEY}"
    # Теперь: Проверяем, что payload начинается с "gems_"
    if query.invoice_payload and query.invoice_payload.startswith("gems_"):
        # Здесь можно добавить дополнительную валидацию payload, если нужно
        # Например, проверить, что user_id в payload совпадает с query.from_user.id
        # и что пакет гемов существует.
        payload_parts = query.invoice_payload.split('_')
        if len(payload_parts) >= 3 and payload_parts[0] == "gems":
            package_key = f"{payload_parts[1]}_{payload_parts[2]}" # например, "pack_10_gems"
            if package_key in CONFIG.GEM_PACKAGES:
                await query.answer(ok=True)
                logger.info(f"PreCheckoutQuery OK for gems payload: {query.invoice_payload}")
                return
            else:
                logger.warning(f"PreCheckoutQuery FAILED. Unknown gem package in payload: {query.invoice_payload}")
                await query.answer(ok=False, error_message="Выбранный пакет гемов больше не доступен.")    
                return
        
    logger.warning(f"PreCheckoutQuery FAILED. Invalid payload format: {query.invoice_payload}")
    await query.answer(ok=False, error_message="Неверный или устаревший запрос на оплату.")


async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id # Это user_id того, кто совершил платеж
    payment_info = update.message.successful_payment
    invoice_payload = payment_info.invoice_payload

    logger.info(f"Successful payment received from user {user_id}. Amount: {payment_info.total_amount} {payment_info.currency}. Payload: {invoice_payload}")

    # --- >>> ИЗМЕНЯЕМ ЛОГИКУ: Начисляем гемы вместо подписки <<< ---
    if invoice_payload and invoice_payload.startswith("gems_"):
        try:
            payload_parts = invoice_payload.split('_')
            # Ожидаемый формат: "gems_{pack_key_part1}_{pack_key_part2}_user_{user_id_from_payload}_{timestamp}"
            # Например: "gems_pack_10_gems_user_12345_1678886400"
            # Собираем package_key (может состоять из нескольких частей)
            
            # Найдем "_user_"
            user_part_index = -1
            for i, part in enumerate(payload_parts):
                if part == "user":
                    user_part_index = i
                    break
            
            if user_part_index == -1 or user_part_index == 1: # Не нашли "_user_" или пакет пустой
                raise ValueError("Invalid payload structure: missing user or package info")

            package_key = "_".join(payload_parts[1:user_part_index]) # Собираем ключ пакета
            user_id_from_payload = int(payload_parts[user_part_index + 1])

            if user_id != user_id_from_payload: # Дополнительная проверка безопасности
                logger.error(f"Security alert: Payload user ID {user_id_from_payload} does not match message user ID {user_id} for invoice {invoice_payload}")
                # Не начисляем гемы, но нужно уведомить администратора
                await update.message.reply_text("Произошла ошибка при обработке вашего платежа. Свяжитесь с поддержкой.")
                if CONFIG.ADMIN_ID:
                    await context.bot.send_message(CONFIG.ADMIN_ID, f"⚠️ Ошибка несоответствия User ID в платеже! Payload: {invoice_payload}, User: {user_id}")
                return

            package_info = CONFIG.GEM_PACKAGES.get(package_key)
            if not package_info:
                logger.error(f"Successful payment for UNKNOWN gem package '{package_key}' from payload '{invoice_payload}' by user {user_id}")
                await update.message.reply_text("Ошибка: купленный пакет гемов не найден. Свяжитесь с поддержкой.")
                return

            gems_to_add = package_info["gems"]
            current_gem_balance = await get_user_gem_balance(user_id) # user_id из update.effective_user
            new_gem_balance = current_gem_balance + gems_to_add
            await update_user_gem_balance(user_id, new_gem_balance)

            confirmation_message = (
                f"🎉 Оплата прошла успешно! Вам начислено <b>{gems_to_add} гемов</b>.\n"
                f"Ваш новый баланс: <b>{new_gem_balance:.1f} гемов</b>.\n\n"
                "Спасибо за покупку!"
            )
            user_data_for_reply_menu = await firestore_service.get_user_data(user_id)
            await update.message.reply_text(
                confirmation_message, 
                parse_mode=ParseMode.HTML, 
                reply_markup=generate_menu_keyboard(user_data_for_reply_menu.get('current_menu', BotConstants.MENU_GEMS_SUBMENU)) # Возвращаем в меню гемов
            )

            # Уведомление администратору
            if CONFIG.ADMIN_ID:
                admin_message = (
                    f"💎 Новая покупка гемов!\n"
                    f"Пользователь: {user_id} ({update.effective_user.full_name if update.effective_user else 'N/A'})\n"
                    f"Пакет: {package_info['title']} ({gems_to_add} гемов)\n"
                    f"Сумма: {payment_info.total_amount / 100} {payment_info.currency}\n"
                    f"Новый баланс: {new_gem_balance:.1f} гемов\n"
                    f"Payload: {invoice_payload}"
                )
                await context.bot.send_message(CONFIG.ADMIN_ID, admin_message)

        except Exception as e:
            logger.error(f"Error processing successful gem payment for user {user_id}, payload {invoice_payload}: {e}", exc_info=True)
            await update.message.reply_text("Произошла ошибка при начислении гемов. Пожалуйста, свяжитесь с поддержкой, указав детали вашего платежа.")
    else:
        logger.warning(f"Successful payment received with unknown payload type from user {user_id}: {invoice_payload}")

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
            f"Traceback:\n```\n{tb_string[:3500]}\n```" # Markdown v2 требует экранирования для ```
        )
        # Для MarkdownV2 нужно экранировать некоторые символы внутри ``` блока, если они есть
        # Но для простоты, если есть проблемы, можно отправить без форматирования Markdown
        try:
            await context.bot.send_message(CONFIG.ADMIN_ID, error_details) # Попробуем отправить как есть
        except telegram.error.TelegramError as e_md:
            logger.error(f"Failed to send detailed error report to admin with Markdown: {e_md}. Sending as plain text.")
            try:
                 # Убираем форматирование Markdown, если оно вызывает ошибку
                 plain_error_details = error_details.replace("```", "") 
                 await context.bot.send_message(CONFIG.ADMIN_ID, plain_error_details)
            except Exception as e_plain:
                 logger.error(f"Failed to send plain text detailed error report to admin: {e_plain}")
