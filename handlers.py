# handlers.py
import traceback
import asyncio
import io
import mimetypes
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
    get_agent_lifetime_uses_left, decrement_agent_lifetime_uses, # Новые функции для общих лимитов агента
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

    # Инициализация общих бесплатных попыток для агентов, если они определены
    for agent_key, agent_config_val in AI_MODES.items():
        if initial_uses := agent_config_val.get('initial_lifetime_free_uses'):
            uses_firestore_key = f"lifetime_uses_{agent_key}"
            if uses_firestore_key not in user_data_loc:
                updates_to_user_data[uses_firestore_key] = initial_uses

    if updates_to_user_data:
        await firestore_service.set_user_data(user_id, updates_to_user_data)
        user_data_loc.update(updates_to_user_data)

    current_model_key_val = await get_current_model_key(user_id, user_data_loc)
    mode_details_res = await get_current_mode_details(user_id, user_data_loc)
    model_details_res = AVAILABLE_TEXT_MODELS.get(current_model_key_val)

    mode_name = mode_details_res.get('name', 'N/A') if mode_details_res else AI_MODES.get(user_data_loc.get('current_ai_mode'), {}).get('name', 'N/A')
    model_name_display = model_details_res.get('name', 'N/A') if model_details_res else "Не выбрана"
    
    # Если активен агент с принудительной моделью, отображаем ее
    active_agent_cfg_for_start = AI_MODES.get(user_data_loc.get('current_ai_mode'))
    if active_agent_cfg_for_start and active_agent_cfg_for_start.get("forced_model_key"):
        forced_model_details = AVAILABLE_TEXT_MODELS.get(active_agent_cfg_for_start.get("forced_model_key"))
        if forced_model_details:
            model_name_display = forced_model_details.get("name", model_name_display)


    greeting_message = (
        f"👋 Привет, {user_first_name}!\n\n"
        f"🤖 Текущий агент: <b>{mode_name}</b>\n"
        f"⚙️ Активная модель (глобально/для агента): <b>{model_name_display}</b>\n\n"
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
    
    # Отображение общих бесплатных попыток для агентов
    parts.append("<b>🎁 Общие бесплатные попытки для спец. агентов:</b>")
    has_lifetime_agent_limits = False
    for agent_k, agent_c in AI_MODES.items():
        if initial_lt_uses := agent_c.get('initial_lifetime_free_uses'):
            lt_uses_left = await get_agent_lifetime_uses_left(user_id, agent_k, user_data_loc)
            parts.append(f"▫️ {agent_c['name']}: {lt_uses_left}/{initial_lt_uses} попыток осталось")
            has_lifetime_agent_limits = True
    if not has_lifetime_agent_limits:
        parts.append("▫️ У вас нет агентов с общим лимитом бесплатных попыток.")
    parts.append("") # Пустая строка для разделения

    parts.append("<b>📊 Ваши дневные бесплатные лимиты и стоимость моделей:</b>")
    for model_key, model_config in AVAILABLE_TEXT_MODELS.items():
        # is_limited теперь не используется, ориентируемся на free_daily_limit и gem_cost
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
    # ... (остальная логика для бонуса с канала новостей) ...
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

# ... (claim_news_bonus_logic, show_help, send_gem_purchase_invoice - остаются как в последней полной версии) ...
# ... (menu_button_handler - остается как в последней полной версии) ...
# ... (photo_handler - остается как в последней полной версии) ...

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
        billing_model_key = active_agent_config.get("forced_model_key") # Модель для списания гемов/лимитов
        native_vision_model_id = active_agent_config.get("native_vision_model_id")

        if not billing_model_key or billing_model_key not in AVAILABLE_TEXT_MODELS:
            logger.error(f"Photo Dietitian agent '{current_ai_mode_key}' has invalid 'forced_model_key': {billing_model_key}")
            await update.message.reply_text("Ошибка конфигурации биллинг-модели для Диетолога. Сообщите администратору.")
            context.user_data.pop('dietitian_state', None); context.user_data.pop('dietitian_pending_photo_id', None)
            return
        
        if not native_vision_model_id:
            logger.error(f"Photo Dietitian agent '{current_ai_mode_key}' is missing 'native_vision_model_id'.")
            await update.message.reply_text("Ошибка конфигурации Vision-модели для Диетолога. Сообщите администратору.")
            context.user_data.pop('dietitian_state', None); context.user_data.pop('dietitian_pending_photo_id', None)
            return

        bot_data_cache = await firestore_service.get_bot_data()
        # Передаем current_ai_mode_key для проверки agent_lifetime_free_uses
        can_proceed, limit_or_gem_message, usage_type, gem_cost_for_request = await check_and_log_request_attempt(
            user_id, billing_model_key, user_data_cache, bot_data_cache, current_ai_mode_key
        )

        if not can_proceed:
            await update.message.reply_text(limit_or_gem_message, parse_mode=ParseMode.HTML)
            return
        
        logger.info(f"User {user_id} (agent {current_ai_mode_key}) provided weight: '{user_message_text}' for photo {photo_file_id}. Billing Model: {billing_model_key}. Usage: {usage_type}. Vision Model: {native_vision_model_id}")
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        
        ai_response_text = "Ошибка при обработке изображения."
        try:
            if not CONFIG.GOOGLE_GEMINI_API_KEY or "YOUR_" in CONFIG.GOOGLE_GEMINI_API_KEY:
                raise ValueError("API ключ для Google Gemini (Vision) не настроен в конфигурации бота.")

            actual_photo_file = await context.bot.get_file(photo_file_id)
            file_bytes = await actual_photo_file.download_as_bytearray()
            
            mime_type, _ = mimetypes.guess_type(actual_photo_file.file_path or "image.jpg") # Добавил or "image.jpg" для случая None file_path
            if not mime_type: mime_type = "image/jpeg"
            
            image_part = {"mime_type": mime_type, "data": bytes(file_bytes)}
            logger.info(f"Preparing image for Vision API. Determined/guessed MIME type: {mime_type}")
            
            # Используем основной промпт агента, так как он описывает и диалог, и задачу анализа
            # Модель Vision достаточно умна, чтобы извлечь нужную часть.
            # Либо можно составить более короткий, специфичный для Vision промпт.
            vision_system_instruction = active_agent_config["prompt"] # Берем полный промпт агента
            text_prompt_with_weight = f"Фотография блюда предоставлена. Пользователь указал вес: {user_message_text}."
            
            model_vision = genai.GenerativeModel(native_vision_model_id) # genai уже импортирован и сконфигурирован
            logger.debug(f"Sending to Google Vision API. Model: {native_vision_model_id}. System context (part): {vision_system_instruction[:100]} User text: {text_prompt_with_weight}")
            
            # Для Vision API промпт может быть таким: [system_prompt_text, image_part, user_text_part]
            # или просто [image_part, combined_text_prompt]
            # Попробуем объединить системный промпт и запрос веса в одну текстовую часть
            combined_text_for_vision = f"{vision_system_instruction}\n\nЗАДАЧА ПО ФОТО:\n{text_prompt_with_weight}"

            response_vision = await asyncio.get_event_loop().run_in_executor(
                None,
                # Передаем [image, text] или [text, image, text] и т.д.
                lambda: model_vision.generate_content([image_part, combined_text_for_vision]) 
            )
            ai_response_text = response_vision.text
            logger.info(f"Successfully received response from Google Vision API for user {user_id}")

        except ValueError as ve:
            logger.error(f"Configuration error for Google Gemini Vision for user {user_id}: {ve}")
            ai_response_text = str(ve)
        except Exception as e:
            logger.error(f"Error with Google Gemini Vision API for user {user_id}: {e}", exc_info=True)
            ai_response_text = "К сожалению, не удалось проанализировать изображение. Попробуйте позже."
        
        await increment_request_count(user_id, billing_model_key, usage_type, current_ai_mode_key, gem_cost_for_request)
        
        final_reply_text, _ = smart_truncate(ai_response_text, CONFIG.MAX_MESSAGE_LENGTH_TELEGRAM)
        current_menu = user_data_cache.get('current_menu', BotConstants.MENU_AI_MODES_SUBMENU) 
        await update.message.reply_text(final_reply_text, reply_markup=generate_menu_keyboard(current_menu))
        
        context.user_data.pop('dietitian_state', None)
        context.user_data.pop('dietitian_pending_photo_id', None)
        return 
    
    # --- Обычная обработка текста ---
    final_model_key_for_request = ""
    # Если текущий агент имеет forced_model_key и это не мультимодальный агент в ожидании веса
    if active_agent_config and active_agent_config.get("forced_model_key") and \
       not (active_agent_config.get("multimodal_capable") and context.user_data.get('dietitian_state') == 'awaiting_weight'):
        final_model_key_for_request = active_agent_config.get("forced_model_key")
        logger.info(f"Agent '{current_ai_mode_key}' forcing model to '{final_model_key_for_request}' for text request.")
    else:
        final_model_key_for_request = await get_current_model_key(user_id, user_data_cache)

    bot_data_cache_for_check = await firestore_service.get_bot_data()
    # Передаем current_ai_mode_key для правильной проверки лимитов агента
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
        ai_response_text = await ai_service.generate_response(system_prompt_to_use, user_message_text, image_data=None) 
    except Exception as e:
        model_name_for_error = AVAILABLE_TEXT_MODELS.get(final_model_key_for_request, {}).get('name', final_model_key_for_request)
        logger.error(f"Unhandled exception in AI service for model {model_name_for_error}: {e}", exc_info=True)
        ai_response_text = f"Произошла внутренняя ошибка при обработке вашего запроса моделью {model_name_for_error}."
    
    await increment_request_count(user_id, final_model_key_for_request, usage_type, current_ai_mode_key, gem_cost_for_request)

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
# (precheckout_callback и successful_payment_callback остаются как в предыдущей полной версии handlers.py)
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
# (error_handler остается как в предыдущей полной версии handlers.py)
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
            f"Msg: {update.message.text if update.message and update.message.text else 'N/A (нет текста или не сообщение)'}\n" # Добавил проверку на update.message.text
            f"Error: {context.error}\n\n"
            f"Traceback (short):\n```\n{tb_string[-1500:]}\n```" 
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
