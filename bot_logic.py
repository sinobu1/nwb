# bot_logic.py
import traceback
import asyncio
import io
import mimetypes
from datetime import datetime, timezone, timedelta
import telegram
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice
from telegram.constants import ParseMode, ChatAction
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, PreCheckoutQueryHandler, filters 
import json
import base64 # Import base64 for decoding


from config import (
    firestore_service, CONFIG, BotConstants, AVAILABLE_TEXT_MODELS,
    AI_MODES, MENU_STRUCTURE, auto_delete_message_decorator,
    get_current_model_key, get_current_mode_details,
    is_menu_button_text, generate_menu_keyboard, _store_and_try_delete_message,
    check_and_log_request_attempt, get_ai_service, smart_truncate,
    increment_request_count, logger, show_menu,
    get_user_gem_balance, update_user_gem_balance, get_daily_usage_for_model,
    get_agent_lifetime_uses_left, decrement_agent_lifetime_uses,
    genai 
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
    
    if 'conversation_history' not in user_data_loc:
        updates_to_user_data['conversation_history'] = []

    for agent_key, agent_config_val in AI_MODES.items():
        if initial_uses := agent_config_val.get('initial_lifetime_free_uses'):
            uses_firestore_key = f"lifetime_uses_{agent_key}"
            if uses_firestore_key not in user_data_loc:
                updates_to_user_data[uses_firestore_key] = initial_uses
    
    if 'claimed_news_bonus' not in user_data_loc:
        updates_to_user_data['claimed_news_bonus'] = False
        for bonus_model_key in CONFIG.NEWS_CHANNEL_BONUS_CONFIG.keys():
            bonus_uses_left_firestore_key = f"news_bonus_uses_left_{bonus_model_key}"
            if bonus_uses_left_firestore_key not in user_data_loc:
                 updates_to_user_data[bonus_uses_left_firestore_key] = 0
    
    if 'purchased_one_time_packs' not in user_data_loc:
        updates_to_user_data['purchased_one_time_packs'] = []


    if updates_to_user_data:
        await firestore_service.set_user_data(user_id, updates_to_user_data)
        user_data_loc.update(updates_to_user_data)

    current_model_key_val = await get_current_model_key(user_id, user_data_loc)
    mode_details_res = await get_current_mode_details(user_id, user_data_loc)

    model_name_display = "Не выбрана"
    active_agent_cfg_for_start = mode_details_res

    if active_agent_cfg_for_start and active_agent_cfg_for_start.get("forced_model_key"):
        forced_model_details = AVAILABLE_TEXT_MODELS.get(active_agent_cfg_for_start.get("forced_model_key"))
        if forced_model_details:
            model_name_display = forced_model_details.get("name", "N/A")
    elif current_model_key_val:
        model_details_for_display = AVAILABLE_TEXT_MODELS.get(current_model_key_val)
        if model_details_for_display:
            model_name_display = model_details_for_display.get("name", "N/A")

    mode_name = active_agent_cfg_for_start.get('name', 'N/A') if active_agent_cfg_for_start else "N/A"

    greeting_message = (
        f"👋 Привет, {user_first_name}!\n\n"
        f"🤖 Текущий агент: <b>{mode_name}</b>\n"
        f"⚙️ Активная модель: <b>{model_name_display}</b>\n\n"
        "Я готов к вашим запросам! Используйте текстовые сообщения для общения с ИИ "
        "или кнопки меню для навигации и настроек.\n"
        "Чтобы начать новый диалог (очистить контекст), используйте команду /new."
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
async def new_topic_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сбрасывает историю диалога для пользователя."""
    user_id = update.effective_user.id
    await firestore_service.set_user_data(user_id, {'conversation_history': []})
    logger.info(f"Conversation history cleared for user {user_id}.")
    current_menu = (await firestore_service.get_user_data(user_id)).get('current_menu', BotConstants.MENU_MAIN)
    await update.message.reply_text(
        "Начинаем новую тему. Я не буду помнить наш предыдущий разговор.",
        reply_markup=generate_menu_keyboard(current_menu)
        )

@auto_delete_message_decorator()
async def open_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_menu(update, update.effective_user.id, BotConstants.MENU_MAIN)

@auto_delete_message_decorator()
async def usage_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_limits(update, update.effective_user.id) 

@auto_delete_message_decorator()
async def gems_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_menu(update, update.effective_user.id, BotConstants.MENU_GEMS_SUBMENU)

@auto_delete_message_decorator()
async def get_news_bonus_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await claim_news_bonus_logic(update, update.effective_user.id) 

@auto_delete_message_decorator()
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_help(update, update.effective_user.id) 

async def show_limits(update: Update, user_id: int): 
    user_data_loc = await firestore_service.get_user_data(user_id)
    bot_data_loc = await firestore_service.get_bot_data()
    user_gem_balance = await get_user_gem_balance(user_id, user_data_loc)
    
    parts = [f"<b>💎 Ваш баланс: {user_gem_balance:.1f} гемов</b>"]
    parts.append("") 

    parts.append("<b>🎁 Общие бесплатные попытки для спец. агентов:</b>")
    has_lifetime_agent_limits = False
    for agent_k, agent_c in AI_MODES.items():
        if initial_lt_uses := agent_c.get('initial_lifetime_free_uses'):
            lt_uses_left = await get_agent_lifetime_uses_left(user_id, agent_k, user_data_loc)
            parts.append(f"▫️ {agent_c['name']}: {lt_uses_left}/{initial_lt_uses} попыток")
            has_lifetime_agent_limits = True
    if not has_lifetime_agent_limits: 
        parts.append("▫️ Нет агентов с общим лимитом бесплатных попыток.")
    parts.append("") 

    parts.append("<b>📊 Ваши дневные бесплатные лимиты и стоимость моделей:</b>")
    for model_key, model_config in AVAILABLE_TEXT_MODELS.items():
        current_free_usage = await get_daily_usage_for_model(user_id, model_key, bot_data_loc)
        free_daily_limit = model_config.get('free_daily_limit', 0)
        gem_cost = model_config.get('gem_cost', 0.0)
        
        usage_display = f"Бесплатно сегодня: {current_free_usage}/{free_daily_limit}"
        
        cost_display_parts = []
        if gem_cost > 0:
            cost_display_parts.append(f"Стоимость: {gem_cost:.1f} гемов за 1 генерацию")
        elif free_daily_limit > 0 : 
             cost_display_parts.append("Бесплатно в рамках дневного лимита")

        bonus_notification = ""
        news_bonus_uses_left_key = f"news_bonus_uses_left_{model_key}"
        if model_key in CONFIG.NEWS_CHANNEL_BONUS_CONFIG and \
           user_data_loc.get('claimed_news_bonus', False) and \
           (bonus_left := user_data_loc.get(news_bonus_uses_left_key, 0)) > 0:
            bonus_notification = f" (еще <b>{bonus_left}</b> бонусных)"
            if not cost_display_parts: 
                cost_display_parts.append("Доступно по бонусу")

        cost_display_str = ". ".join(filter(None, cost_display_parts))
        if not cost_display_str and free_daily_limit == 0 and gem_cost == 0 and not bonus_notification:
             cost_display_str = "Модель не настроена для использования."

        parts.append(f"▫️ {model_config['name']}: {usage_display}{bonus_notification}. {cost_display_str}")
        parts.append("") 
        
    if parts and parts[-1] == "":
        parts.pop()
    parts.append("") 

    bonus_models_names = []
    claimed_bonus = user_data_loc.get('claimed_news_bonus', False)

    for bk, b_uses in CONFIG.NEWS_CHANNEL_BONUS_CONFIG.items():
        if bk_cfg := AVAILABLE_TEXT_MODELS.get(bk):
            bonus_models_names.append(f"{bk_cfg['name']} ({b_uses} шт.)")

    if bonus_models_names:
        bonus_models_str = ", ".join(bonus_models_names)
        if not claimed_bonus:
            parts.append(f'🎁 Подпишитесь на <a href="{CONFIG.NEWS_CHANNEL_LINK}">канал новостей</a> (+{bonus_models_str})! «🎁 Бонус» в меню.')
        else:
            active_bonuses_texts = []
            for bk_check, b_uses_check in CONFIG.NEWS_CHANNEL_BONUS_CONFIG.items():
                bonus_uses_left_for_model_key_check = f"news_bonus_uses_left_{bk_check}"
                bonus_left_val_check = user_data_loc.get(bonus_uses_left_for_model_key_check, 0)
                if bonus_left_val_check > 0:
                    model_name_display_check = AVAILABLE_TEXT_MODELS.get(bk_check, {}).get('name', bk_check)
                    active_bonuses_texts.append(f"<b>{bonus_left_val_check}</b> для {model_name_display_check}")
            
            if active_bonuses_texts:
                parts.append(f"✅ У вас бонусных генераций: {'; '.join(active_bonuses_texts)}.")
            else:
                parts.append(f"ℹ️ Бонус с канала новостей ({bonus_models_str}) был использован или не активирован для этих моделей.")
    
    parts.append("\n💎 Пополнить баланс: /gems или через меню «💎 Гемы».")
    current_menu_for_reply = user_data_loc.get('current_menu', BotConstants.MENU_LIMITS_SUBMENU)
    await update.message.reply_text("\n".join(parts), parse_mode=ParseMode.HTML,
                                    reply_markup=generate_menu_keyboard(current_menu_for_reply),
                                    disable_web_page_preview=True)

async def claim_news_bonus_logic(update: Update, user_id: int): 
    user_data_loc = await firestore_service.get_user_data(user_id)
    parent_menu_key = user_data_loc.get('current_menu', BotConstants.MENU_BONUS_SUBMENU)
    current_menu_config = MENU_STRUCTURE.get(parent_menu_key, MENU_STRUCTURE[BotConstants.MENU_MAIN])
    reply_menu_key = current_menu_config.get("parent", BotConstants.MENU_MAIN) if current_menu_config.get("is_submenu") else parent_menu_key

    if not CONFIG.NEWS_CHANNEL_BONUS_CONFIG:
        await update.message.reply_text("Ошибка: Бонусные модели не настроены.", reply_markup=generate_menu_keyboard(reply_menu_key))
        return

    if user_data_loc.get('claimed_news_bonus', False):
        active_bonuses_texts = []
        all_bonuses_used = True
        for bonus_model_key, bonus_amount in CONFIG.NEWS_CHANNEL_BONUS_CONFIG.items():
            bonus_uses_left_firestore_key = f"news_bonus_uses_left_{bonus_model_key}"
            uses_left = user_data_loc.get(bonus_uses_left_firestore_key, 0)
            model_name = AVAILABLE_TEXT_MODELS.get(bonus_model_key, {}).get('name', bonus_model_key)
            if uses_left > 0:
                active_bonuses_texts.append(f"<b>{uses_left}</b> для {model_name}")
                all_bonuses_used = False
        
        reply_text = "Вы уже активировали бонус. "
        if not all_bonuses_used and active_bonuses_texts:
            reply_text += f"У вас осталось: {'; '.join(active_bonuses_texts)}."
        else:
            reply_text += "Все бонусные генерации использованы."
            
        await update.message.reply_text(reply_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(reply_menu_key))
        return

    try:
        member_status = await update.get_bot().get_chat_member(chat_id=CONFIG.NEWS_CHANNEL_USERNAME, user_id=user_id)
        if member_status.status in ['member', 'administrator', 'creator']:
            updates_for_firestore = {'claimed_news_bonus': True}
            awarded_bonuses_texts = []
            for bonus_model_key, bonus_amount in CONFIG.NEWS_CHANNEL_BONUS_CONFIG.items():
                bonus_uses_left_firestore_key = f"news_bonus_uses_left_{bonus_model_key}"
                updates_for_firestore[bonus_uses_left_firestore_key] = bonus_amount
                model_name = AVAILABLE_TEXT_MODELS.get(bonus_model_key, {}).get('name', bonus_model_key)
                awarded_bonuses_texts.append(f"<b>{bonus_amount}</b> для {model_name}")

            await firestore_service.set_user_data(user_id, updates_for_firestore)
            
            success_text = (f'🎉 Спасибо за подписку на <a href="{CONFIG.NEWS_CHANNEL_LINK}">{CONFIG.NEWS_CHANNEL_USERNAME}</a>! '
                            f"Вам начислены бонусы: {'; '.join(awarded_bonuses_texts)}.")
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
        "<b>Как задать вопрос?</b>\n"
        "Просто напишите ваш вопрос или задачу в чат. Бот поддерживает контекст диалога: он помнит ваши последние несколько сообщений. Чтобы начать новый диалог с чистого листа, используйте команду /new.\n\n"
        "<b>Управление ботом</b>\n"
        "Используйте кнопки меню для доступа ко всем функциям:\n"
        "    🤖 <b>Агенты ИИ</b>: Выберите специализацию для ИИ (например, 'Карьерный консультант').\n"
        "    ⚙️ <b>Модели ИИ</b>: Переключайтесь между доступными нейросетями.\n"
        "    📊 <b>Лимиты</b>: Проверьте ваши дневные лимиты, баланс гемов и стоимость моделей.\n"
        "    🎁 <b>Бонус</b>: Получите бесплатные генерации за подписку на новостной канал.\n"
        "    💎 <b>Гемы</b>: Пополните ваш баланс гемов для доступа к продвинутым моделям.\n\n"
        "<b>Основные команды</b>\n"
        "    ▫️ /start - Перезапуск бота и приветственное сообщение.\n"
        "    ▫️ /new - Начать новый диалог (очистить контекст).\n"
        "    ▫️ /menu - Открыть главное меню.\n"
        "    ▫️ /usage - Показать лимиты и баланс.\n"
        "    ▫️ /gems - Открыть магазин гемов.\n"
        "    ▫️ /bonus - Получить бонус за подписку.\n"
        "    ▫️ /help - Показать эту справку."
    )
    current_menu_for_reply = user_data_loc.get('current_menu', BotConstants.MENU_HELP_SUBMENU)
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(current_menu_for_reply), disable_web_page_preview=True)

async def send_gem_purchase_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE, package_key: str):
    user_id = update.effective_user.id
    package_info = CONFIG.GEM_PACKAGES.get(package_key)
    if not package_info:
        logger.error(f"User {user_id} tried to buy non-existent gem package: {package_key}")
        await update.message.reply_text("Ошибка: Выбранный пакет гемов не найден.", reply_markup=generate_menu_keyboard(BotConstants.MENU_GEMS_SUBMENU))
        return

    if package_info.get("is_one_time"):
        user_data = await firestore_service.get_user_data(user_id)
        purchased_one_time_packs = user_data.get('purchased_one_time_packs', [])
        if package_key in purchased_one_time_packs:
            await update.message.reply_text(f"Вы уже приобретали пакет «{package_info['title']}». Эта покупка доступна только один раз.", reply_markup=generate_menu_keyboard(BotConstants.MENU_GEMS_SUBMENU))
            return

    title, description = package_info["title"], package_info["description"]
    # ИСПРАВЛЕНИЕ: Используем ':' как основной разделитель, чтобы избежать конфликта с '_' в названии пакета.
    payload = f"gems:{package_key}:user:{user_id}_{int(datetime.now().timestamp())}"
    currency, price_units = package_info["currency"], package_info["price_units"]
    prices = [LabeledPrice(label=f"{package_info['gems']} Гемов", amount=price_units)]
    if not CONFIG.PAYMENT_PROVIDER_TOKEN or "YOUR_" in CONFIG.PAYMENT_PROVIDER_TOKEN:
        logger.error("Payment provider token is not configured.")
        await update.message.reply_text("Система оплаты временно недоступна.", reply_markup=generate_menu_keyboard(BotConstants.MENU_GEMS_SUBMENU))
        return
    try:
        current_menu = (await firestore_service.get_user_data(user_id)).get('current_menu', BotConstants.MENU_GEMS_SUBMENU)
        await update.message.reply_text(f"Готовлю счет для пакета «{title}»...", reply_markup=generate_menu_keyboard(current_menu))
        await context.bot.send_invoice(chat_id=user_id, title=title, description=description, payload=payload, provider_token=CONFIG.PAYMENT_PROVIDER_TOKEN, currency=currency, prices=prices)
        logger.info(f"Invoice for '{package_key}' sent to user {user_id}.")
    except Exception as e:
        logger.error(f"Failed to send invoice to user {user_id} for package {package_key}: {e}", exc_info=True)
        await update.message.reply_text("Ошибка при формировании счета.", reply_markup=generate_menu_keyboard(BotConstants.MENU_GEMS_SUBMENU))

async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE): 
    if not update.message or not update.message.text: return
    button_text = update.message.text.strip()
    if not is_menu_button_text(button_text): return 
    
    user_id = update.effective_user.id
    logger.info(f"User {user_id} pressed menu button: '{button_text}'")
    
    try: 
        await update.message.delete()
    except telegram.error.TelegramError as e: 
        logger.warning(f"Failed to delete menu button message '{button_text}': {e}")

    user_data_loc = await firestore_service.get_user_data(user_id)
    current_menu_key_from_db = user_data_loc.get('current_menu', BotConstants.MENU_MAIN)

    if button_text == "⬅️ Назад":
        parent_key = MENU_STRUCTURE.get(current_menu_key_from_db, {}).get("parent", BotConstants.MENU_MAIN)
        await show_menu(update, user_id, parent_key)
        return
    elif button_text == "🏠 Главное меню":
        await show_menu(update, user_id, BotConstants.MENU_MAIN)
        return

    action_item_found, effective_menu_key_of_action = None, current_menu_key_from_db
    search_order = [current_menu_key_from_db] + [k for k in MENU_STRUCTURE if k != current_menu_key_from_db]

    for menu_key_search in search_order:
        for item in MENU_STRUCTURE.get(menu_key_search, {}).get("items", []):
            if item["text"] == button_text:
                action_item_found = item
                effective_menu_key_of_action = menu_key_search 
                break
        if action_item_found:
            break
            
    if not action_item_found:
        logger.error(f"Button '{button_text}' no action found. DB current_menu: '{current_menu_key_from_db}'. Showing main menu.")
        await show_menu(update, user_id, BotConstants.MENU_MAIN)
        return

    action_type = action_item_found["action"]
    action_target = action_item_found["target"]
    
    reply_menu_after_action = effective_menu_key_of_action 

    if action_type == BotConstants.CALLBACK_ACTION_SUBMENU:
        await show_menu(update, user_id, action_target)
    elif action_type == BotConstants.CALLBACK_ACTION_SET_AGENT:
        await firestore_service.set_user_data(user_id, {'current_ai_mode': action_target, 'conversation_history': []}) # Clear history on agent change
        agent_name = AI_MODES.get(action_target, {}).get('name', 'N/A')
        await update.message.reply_text(f"🤖 Агент ИИ изменен на: <b>{agent_name}</b>. История диалога сброшена.", parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(reply_menu_after_action))
        await firestore_service.set_user_data(user_id, {'current_menu': reply_menu_after_action}) 
    elif action_type == BotConstants.CALLBACK_ACTION_SET_MODEL:
        model_info = AVAILABLE_TEXT_MODELS.get(action_target, {})
        update_payload = {'selected_model_id': model_info.get("id"), 'selected_api_type': model_info.get("api_type"), 'conversation_history': []} # Clear history on model change
        
        current_agent_key_local = user_data_loc.get('current_ai_mode')
        current_agent_config_local = AI_MODES.get(current_agent_key_local)
        if current_agent_config_local and current_agent_config_local.get("forced_model_key") and \
           current_agent_config_local.get("forced_model_key") != action_target :
            update_payload['current_ai_mode'] = CONFIG.DEFAULT_AI_MODE_KEY 
            logger.info(f"Agent '{current_agent_key_local}' was reset to default due to model change to '{action_target}'.")
            await update.message.reply_text(f"Агент сброшен на '{AI_MODES[CONFIG.DEFAULT_AI_MODE_KEY]['name']}', т.к. он несовместим с новой моделью.", parse_mode=ParseMode.HTML)

        await firestore_service.set_user_data(user_id, update_payload)
        user_data_loc.update(update_payload) 
        
        bot_data = await firestore_service.get_bot_data() 
        free_uses = await get_daily_usage_for_model(user_id, action_target, bot_data)
        free_limit = model_info.get('free_daily_limit',0)
        gem_cost = model_info.get('gem_cost',0.0)
        
        response_text_parts = [f"⚙️ Модель изменена на: <b>{model_info.get('name', 'N/A')}</b>. История диалога сброшена."]
        response_text_parts.append(f"Бесплатно сегодня: {free_uses}/{free_limit}.")
        if gem_cost > 0:
            response_text_parts.append(f"Стоимость: {gem_cost:.1f} гемов за 1 генерацию.")
        elif free_limit > 0: 
             response_text_parts.append("Бесплатно в рамках дневного лимита.")
        
        news_bonus_uses_left_key = f"news_bonus_uses_left_{action_target}"
        if action_target in CONFIG.NEWS_CHANNEL_BONUS_CONFIG and \
           user_data_loc.get('claimed_news_bonus', False) and \
           (bonus_left := user_data_loc.get(news_bonus_uses_left_key, 0)) > 0:
            response_text_parts.append(f"(Еще <b>{bonus_left}</b> бонусных генераций для этой модели!)")
            
        await update.message.reply_text("\n".join(response_text_parts), parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(reply_menu_after_action))
        await firestore_service.set_user_data(user_id, {'current_menu': reply_menu_after_action}) 
    elif action_type == BotConstants.CALLBACK_ACTION_SHOW_LIMITS:
        await show_limits(update, user_id)
    elif action_type == BotConstants.CALLBACK_ACTION_CHECK_BONUS:
        await claim_news_bonus_logic(update, user_id)
    elif action_type == BotConstants.CALLBACK_ACTION_SHOW_GEMS_STORE:
        await show_menu(update, user_id, BotConstants.MENU_GEMS_SUBMENU) 
    elif action_type == BotConstants.CALLBACK_ACTION_BUY_GEM_PACKAGE:
        await send_gem_purchase_invoice(update, context, action_target)
    elif action_type == BotConstants.CALLBACK_ACTION_SHOW_HELP:
        await show_help(update, user_id)
    else:
        logger.warning(f"Unknown action_type '{action_type}' for button '{button_text}'. Showing main menu.")
        await show_menu(update, user_id, BotConstants.MENU_MAIN)

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE): 
    user_id = update.effective_user.id
    user_data = await firestore_service.get_user_data(user_id)
    current_ai_mode_key = user_data.get('current_ai_mode')
    active_agent_config = AI_MODES.get(current_ai_mode_key)

    if active_agent_config and current_ai_mode_key == "photo_dietitian_analyzer":
        billing_model_key = active_agent_config.get("forced_model_key")
        if not billing_model_key or billing_model_key not in AVAILABLE_TEXT_MODELS:
            logger.error(f"Agent {current_ai_mode_key} invalid forced_model_key: {billing_model_key}")
            await update.message.reply_text("Ошибка конфигурации модели для этого агента."); return
        
        bot_data_cache = await firestore_service.get_bot_data()
        can_proceed, check_message, _, _ = await check_and_log_request_attempt(
            user_id, billing_model_key, user_data, bot_data_cache, current_ai_mode_key
        )
        if not can_proceed: 
            await update.message.reply_text(check_message, parse_mode=ParseMode.HTML); return
        
        photo_file = update.message.photo[-1]
        context.user_data['dietitian_pending_photo_id'] = photo_file.file_id 
        context.user_data['dietitian_state'] = 'awaiting_weight' 
        logger.info(f"User {user_id} (agent {current_ai_mode_key}) sent photo {photo_file.file_id} directly to bot. Awaiting weight.")
        await update.message.reply_text("Отличное фото! Теперь, пожалуйста, укажите примерный вес этой порции в граммах для расчета КБЖУ.")
    else:
        if update.message: 
            await update.message.reply_text("Для анализа фото еды, пожалуйста, выберите агента '🥑 Диетолог (анализ фото)' в меню (/menu) и отправьте фото снова, или воспользуйтесь Mini App.")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text or is_menu_button_text(update.message.text.strip()):
        return

    user_id = update.effective_user.id
    user_message_text = update.message.text.strip()
    user_data_cache = await firestore_service.get_user_data(user_id)
    current_ai_mode_key = user_data_cache.get('current_ai_mode', CONFIG.DEFAULT_AI_MODE_KEY)
    active_agent_config = AI_MODES.get(current_ai_mode_key)
    conversation_history = user_data_cache.get('conversation_history', [])

    if current_ai_mode_key == "photo_dietitian_analyzer" and context.user_data.get('dietitian_state') == 'awaiting_weight':
        photo_file_id = context.user_data.get('dietitian_pending_photo_id')
        if not photo_file_id:
            logger.warning(f"Dietitian awaiting weight for user {user_id}, but no pending photo ID found.")
            context.user_data.pop('dietitian_state', None) 
        else:
            billing_model_key = active_agent_config.get("forced_model_key")
            native_vision_model_id = active_agent_config.get("native_vision_model_id") 
            
            if not (billing_model_key and billing_model_key in AVAILABLE_TEXT_MODELS and native_vision_model_id):
                logger.error(f"Photo Dietitian (direct bot) config error for agent '{current_ai_mode_key}'. Billing: {billing_model_key}, Vision: {native_vision_model_id}")
                await update.message.reply_text("Ошибка конфигурации Диетолога. Сообщите администратору.")
                context.user_data.pop('dietitian_state', None); context.user_data.pop('dietitian_pending_photo_id', None)
                return

            bot_data_cache = await firestore_service.get_bot_data()
            can_proceed, limit_or_gem_message, usage_type, gem_cost_for_request = await check_and_log_request_attempt(
                user_id, billing_model_key, user_data_cache, bot_data_cache, current_ai_mode_key
            )
            if not can_proceed:
                await update.message.reply_text(limit_or_gem_message, parse_mode=ParseMode.HTML)
                return

            logger.info(f"User {user_id} (agent {current_ai_mode_key}, direct bot) provided weight/comment: '{user_message_text}' for photo {photo_file_id}.")
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
            
            ai_response_text = "Ошибка при обработке изображения."
            try:
                if not CONFIG.GOOGLE_GEMINI_API_KEY or "YOUR_" in CONFIG.GOOGLE_GEMINI_API_KEY:
                    raise ValueError("API ключ для Google Gemini (Vision) не настроен.")
                
                actual_photo_file = await context.bot.get_file(photo_file_id)
                file_bytes = await actual_photo_file.download_as_bytearray()
                
                mime_type, _ = mimetypes.guess_type(actual_photo_file.file_path or "image.jpg")
                if not mime_type or not mime_type.startswith("image/"):
                    mime_type = "image/jpeg" 
                
                image_part_direct = {"mime_type": mime_type, "data": bytes(file_bytes)}
                
                vision_system_instruction = active_agent_config["prompt"]
                text_prompt_with_weight = f"Проанализируй предоставленное ФОТО. Пользователь указал вес порции или комментарий: {user_message_text}."
                
                # Для диетолога история не используется при анализе фото, т.к. каждый анализ - новая транзакция
                model_vision = genai.GenerativeModel(native_vision_model_id) 
                response_vision = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: model_vision.generate_content([vision_system_instruction, image_part_direct, text_prompt_with_weight])
                )
                ai_response_text = response_vision.text
                logger.info(f"Successfully received response from Google Vision API (direct bot) for user {user_id}")
            except ValueError as ve:
                logger.error(f"Configuration error for Google Gemini Vision (direct bot) for user {user_id}: {ve}")
                ai_response_text = str(ve)
            except Exception as e:
                logger.error(f"Error with Google Gemini Vision API (direct bot) for user {user_id}: {e}", exc_info=True)
                ai_response_text = "К сожалению, не удалось проанализировать изображение. Попробуйте позже."
            
            await increment_request_count(user_id, billing_model_key, usage_type, current_ai_mode_key, gem_cost_for_request)
            final_reply_text, _ = smart_truncate(ai_response_text, CONFIG.MAX_MESSAGE_LENGTH_TELEGRAM)
            current_menu_reply = user_data_cache.get('current_menu', BotConstants.MENU_AI_MODES_SUBMENU) 
            await update.message.reply_text(final_reply_text, reply_markup=generate_menu_keyboard(current_menu_reply))
            
            context.user_data.pop('dietitian_state', None)
            context.user_data.pop('dietitian_pending_photo_id', None)
            return 

    final_model_key_for_request = ""
    if active_agent_config and active_agent_config.get("forced_model_key"):
        final_model_key_for_request = active_agent_config.get("forced_model_key")
    else:
        final_model_key_for_request = await get_current_model_key(user_id, user_data_cache)

    bot_data_cache_for_check = await firestore_service.get_bot_data()
    can_proceed, limit_or_gem_message, usage_type, gem_cost_for_request = await check_and_log_request_attempt(
        user_id, final_model_key_for_request, user_data_cache, bot_data_cache_for_check, current_ai_mode_key
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

    logger.info(f"User {user_id} (agent: {current_ai_mode_key}, model: {final_model_key_for_request}) sent AI request: '{user_message_text[:100]}...' with history length {len(conversation_history)}")

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
        ai_response_text = await ai_service.generate_response(
            system_prompt_to_use, 
            user_message_text, 
            history=conversation_history # Передаем историю
            )
    except Exception as e:
        model_name_for_error = AVAILABLE_TEXT_MODELS.get(final_model_key_for_request, {}).get('name', final_model_key_for_request)
        logger.error(f"Unhandled exception in AI service for model {model_name_for_error}: {e}", exc_info=True)
        ai_response_text = f"Произошла внутренняя ошибка при обработке вашего запроса моделью {model_name_for_error}."

    await increment_request_count(user_id, final_model_key_for_request, usage_type, current_ai_mode_key, gem_cost_for_request)

    # Обновляем историю диалога
    new_history = list(conversation_history) # Создаем копию, чтобы не изменять оригинальный список напрямую, если он передается по ссылке
    new_history.append({"role": "user", "parts": [{"text": user_message_text}]}) # Gemini ожидает parts как список словарей
    new_history.append({"role": "model", "parts": [{"text": ai_response_text}]})
    
    if len(new_history) > CONFIG.MAX_CONVERSATION_HISTORY * 2: # *2 потому что храним пары
        new_history = new_history[-(CONFIG.MAX_CONVERSATION_HISTORY * 2):]
        
    await firestore_service.set_user_data(user_id, {'conversation_history': new_history})


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
    # ИСПРАВЛЕНИЕ: Логика разбора payload изменена для поддержки нового формата с ':'
    if query.invoice_payload and query.invoice_payload.startswith("gems:"):
        payload_parts = query.invoice_payload.split(':')
        # Ожидаемый формат: ['gems', package_key, 'user', 'user_id_timestamp'] -> 4 части
        if len(payload_parts) == 4 and payload_parts[2] == "user":
            package_key_from_payload = payload_parts[1]
            user_info_part = payload_parts[3]
            package_info_check = CONFIG.GEM_PACKAGES.get(package_key_from_payload)

            if package_info_check:
                try:
                    user_id_in_payload = int(user_info_part.split('_')[0])
                    if query.from_user.id == user_id_in_payload:
                        if package_info_check.get("is_one_time"):
                            user_data_check = await firestore_service.get_user_data(query.from_user.id)
                            purchased_one_time_packs_check = user_data_check.get('purchased_one_time_packs', [])
                            if package_key_from_payload in purchased_one_time_packs_check:
                                await query.answer(ok=False, error_message=f"Вы уже приобретали пакет «{package_info_check['title']}».")
                                logger.warning(f"PreCheckout FAILED for one-time package {package_key_from_payload} by user {query.from_user.id} (already purchased).")
                                return
                        await query.answer(ok=True)
                        logger.info(f"PreCheckout OK: {query.invoice_payload}")
                        return
                    else:
                        logger.error(f"PreCheckout User ID mismatch: Payload {user_id_in_payload}, Query {query.from_user.id}")
                except (ValueError, IndexError):
                    logger.error(f"PreCheckout Error parsing user_id from payload: {query.invoice_payload}")
            else:
                logger.warning(f"PreCheckout Unknown gem package in payload: {query.invoice_payload}")
        else:
            logger.warning(f"PreCheckout Invalid payload structure: {query.invoice_payload}")
    else:
        logger.warning(f"PreCheckout Invalid payload type or prefix: {query.invoice_payload}")

    await query.answer(ok=False, error_message="Ошибка проверки платежа. Попробуйте еще раз или выберите другой пакет.")

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    payment_info = update.message.successful_payment
    invoice_payload = payment_info.invoice_payload
    logger.info(f"Successful payment from {user_id}. Amount: {payment_info.total_amount} {payment_info.currency}. Payload: {invoice_payload}")

    # ИСПРАВЛЕНИЕ: Логика разбора payload изменена для поддержки нового формата с ':'
    if invoice_payload and invoice_payload.startswith("gems:"):
        try:
            payload_parts = invoice_payload.split(':')
            # Ожидаемый формат: ['gems', package_key, 'user', 'user_id_timestamp']
            if len(payload_parts) != 4 or payload_parts[0] != 'gems' or payload_parts[2] != 'user':
                raise ValueError("Invalid payload structure")

            package_key = payload_parts[1]
            user_id_from_payload = int(payload_parts[3].split('_')[0])

            if user_id != user_id_from_payload:
                logger.error(f"Security: Payload UID {user_id_from_payload} != message UID {user_id}")
                raise ValueError("User ID mismatch")

            package_info = CONFIG.GEM_PACKAGES.get(package_key)
            if not package_info:
                logger.error(f"Payment for UNKNOWN package '{package_key}' by {user_id}")
                raise ValueError("Unknown package")

            if package_info.get("is_one_time"):
                user_data_for_pack = await firestore_service.get_user_data(user_id)
                purchased_packs = user_data_for_pack.get('purchased_one_time_packs', [])
                if package_key not in purchased_packs:
                    purchased_packs.append(package_key)
                    await firestore_service.set_user_data(user_id, {'purchased_one_time_packs': purchased_packs})
                else:
                    logger.warning(f"User {user_id} somehow managed to pay for one-time package '{package_key}' again. Gems not added.")
                    await update.message.reply_text(f"Похоже, вы уже приобретали пакет «{package_info['title']}». Гемы не были начислены повторно.")
                    return

            gems_to_add = float(package_info["gems"])
            current_balance = await get_user_gem_balance(user_id)
            new_gem_balance = current_balance + gems_to_add
            await update_user_gem_balance(user_id, new_gem_balance)

            confirmation_msg = (f"🎉 Оплата успешна! Начислено <b>{gems_to_add:.1f} гемов</b>.\n"
                               f"Новый баланс: <b>{new_gem_balance:.1f} гемов</b>.")
            user_data = await firestore_service.get_user_data(user_id)
            await update.message.reply_text(confirmation_msg, parse_mode=ParseMode.HTML,
                                            reply_markup=generate_menu_keyboard(user_data.get('current_menu', BotConstants.MENU_GEMS_SUBMENU)))
            if CONFIG.ADMIN_ID:
                admin_msg = (f"💎 Покупка гемов!\nUser: {user_id} ({update.effective_user.full_name or 'N/A'})\n"
                             f"Пакет: {package_info['title']} ({gems_to_add:.1f} гемов)\nСумма: {payment_info.total_amount / 100.0:.2f} {payment_info.currency}\n"
                             f"Баланс: {new_gem_balance:.1f}\nPayload: {invoice_payload}")
                await context.bot.send_message(CONFIG.ADMIN_ID, admin_msg)
        except Exception as e:
            logger.error(f"Error processing gem payment for user {user_id}, payload {invoice_payload}: {e}", exc_info=True)
            await update.message.reply_text("Ошибка начисления гемов. Свяжитесь с поддержкой.")
    else:
        logger.warning(f"Successful payment with unknown payload from {user_id}: {invoice_payload}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None: 
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    tb_string = "".join(traceback.format_exception(None, context.error, context.error.__traceback__))
    if isinstance(update, Update) and update.effective_chat:
        user_data = {}
        if update.effective_user: user_data = await firestore_service.get_user_data(update.effective_user.id)
        try:
            current_menu_err = user_data.get('current_menu', BotConstants.MENU_MAIN)
            await context.bot.send_message(chat_id=update.effective_chat.id,
                                           text="Произошла внутренняя ошибка. Разработчики уведомлены. Попробуйте начать с команды /start или выберите опцию из меню.",
                                           reply_markup=generate_menu_keyboard(current_menu_err))
        except Exception as e: logger.error(f"Failed to send error message to user {update.effective_chat.id}: {e}")
    
    if CONFIG.ADMIN_ID and isinstance(update, Update) and update.effective_user:
        msg_text_for_admin = "N/A"
        if update.message and update.message.text:
            msg_text_for_admin = update.message.text
        elif update.callback_query and update.callback_query.data:
            msg_text_for_admin = f"Callback: {update.callback_query.data}"

        error_details = (f"🤖 Ошибка в боте:\nUser: {update.effective_user.id} (@{update.effective_user.username or 'N/A'})\n"
                         f"Msg/Callback: {msg_text_for_admin}\n"
                         f"Error: {context.error}\n\nTraceback (short):\n```\n{tb_string[-1500:]}\n```")
        try: await context.bot.send_message(CONFIG.ADMIN_ID, error_details, parse_mode=ParseMode.MARKDOWN_V2)
        except telegram.error.TelegramError as e_md:
            logger.error(f"Failed to send error to admin (MarkdownV2): {e_md}. Fallback.")
            try: await context.bot.send_message(CONFIG.ADMIN_ID, f"PLAIN TEXT FALLBACK:\n{error_details.replace('```', '')}")
            except Exception as e_plain: logger.error(f"Failed to send plain text error to admin: {e_plain}")

def escape_markdown_v2_custom(text: str) -> str:
    """Более простое экранирование для MarkdownV2, фокусируясь на основных проблемах."""
    if not isinstance(text, str):
        text = str(text)
    # Экранируем только те символы, которые часто вызывают проблемы в автоматических сообщениях
    # Не экранируем `*`, `_`, `~` чтобы разрешить базовое форматирование от ИИ, если оно корректно
    escape_chars = r'.!#+-={}[]()>' # Убраны `*_~`
    return ''.join(f'\\{char}' if char in escape_chars else char for char in text)

async def web_app_data_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.web_app_data:
        return

    user_id = update.effective_user.id
    data_str = update.message.web_app_data.data
    logger.info(f"Raw WebApp data for user {user_id}: {data_str}")
    
    try:
        data = json.loads(data_str)
    except json.JSONDecodeError:
        logger.error(f"JSONDecodeError for WebApp data: {data_str}")
        return

    action = data.get("action")
    logger.info(f"WebApp action '{action}' for user {user_id}")

    if update.message.web_app_data: 
        try:
            await context.bot.delete_message(chat_id=user_id, message_id=update.message.message_id)
        except Exception as e:
            logger.warning(f"Could not delete web_app_data message: {e}")

    if action == "set_agent" or action == "set_model":
        target = data.get("target")
        if action == "set_agent" and target in AI_MODES:
            await firestore_service.set_user_data(user_id, {'current_ai_mode': target, 'conversation_history': []}) # Clear history
            logger.info(f"User {user_id} set agent to '{target}' via Mini App. History cleared.")
        elif action == "set_model" and target in AVAILABLE_TEXT_MODELS:
            model_info = AVAILABLE_TEXT_MODELS[target]
            await firestore_service.set_user_data(user_id, {
                'selected_model_id': model_info.get("id"), 
                'selected_api_type': model_info.get("api_type"),
                'conversation_history': [] # Clear history
            })
            logger.info(f"User {user_id} set model to '{target}' via Mini App. History cleared.")
    
    elif action == "save_chat_to_telegram":
        payload = data.get("payload", {})
        user_query_raw = payload.get("user_query", "N/A")
        ai_response_raw = payload.get("ai_response", "N/A")
        
        logger.info(f"User {user_id} requested to save chat. Q: '{user_query_raw[:50]}...', A: '{ai_response_raw[:50]}...'")
        
        # Экранируем текст для MarkdownV2
        user_query_escaped = escape_markdown_v2_custom(user_query_raw)
        ai_response_escaped = escape_markdown_v2_custom(ai_response_raw)

        saved_message_text = (
            f"📌 *Диалог из Mini App сохранен:*\n\n"
            f"👤 *Ваш запрос:*\n`{user_query_escaped}`\n\n"
            f"💡 *Ответ ИИ:*\n`{ai_response_escaped}`"
        )
        try:
            user_data = await firestore_service.get_user_data(user_id)
            current_menu = user_data.get('current_menu', BotConstants.MENU_MAIN)
            await context.bot.send_message(chat_id=user_id, text=saved_message_text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=generate_menu_keyboard(current_menu))
        except telegram.error.BadRequest as e_md:
            logger.error(f"Failed to send saved chat to user {user_id} with MarkdownV2: {e_md}. Falling back to plain text.")
            # Fallback на простой текст, если MarkdownV2 не сработал даже с экранированием
            plain_text_fallback = (
                f"Диалог из Mini App сохранен:\n\n"
                f"Ваш запрос:\n{user_query_raw}\n\n"
                f"Ответ ИИ:\n{ai_response_raw}"
            )
            await context.bot.send_message(chat_id=user_id, text=plain_text_fallback, reply_markup=generate_menu_keyboard(current_menu))
        except Exception as e: # Другие возможные ошибки
            logger.error(f"Failed to send saved chat to user {user_id} (other error): {e}")
            await context.bot.send_message(chat_id=user_id, text="Не удалось сохранить диалог. Попробуйте позже.")
            
    else:
        logger.warning(f"Unknown WebApp action '{action}' for user {user_id}")
