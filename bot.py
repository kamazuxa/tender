import logging
from config import TELEGRAM_BOT_TOKEN, TENDER_GURU_API_KEY, DAMIA_API_KEY
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import re
from urllib.parse import urlparse, parse_qs
import aiohttp
import os
import tempfile
import shutil
import json
from downloader import download_tender_documents

# Настраиваем подробное логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Создаем отдельный логгер для API
api_logger = logging.getLogger('API_LOGGER')
api_logger.setLevel(logging.INFO)

# Создаем файловый обработчик для API логов
if not os.path.exists('logs'):
    os.makedirs('logs')

# Основной лог-файл для всех API ответов
file_handler = logging.FileHandler('logs/api_responses.log', encoding='utf-8')
file_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
api_logger.addHandler(file_handler)

# Отдельный лог-файл для TenderGuru API
tenderguru_handler = logging.FileHandler('logs/tenderguru_api.log', encoding='utf-8')
tenderguru_handler.setLevel(logging.INFO)
tenderguru_handler.setFormatter(formatter)
api_logger.addHandler(tenderguru_handler)

# Отдельный лог-файл для Damia API
damia_handler = logging.FileHandler('logs/damia_api.log', encoding='utf-8')
damia_handler.setLevel(logging.INFO)
damia_handler.setFormatter(formatter)
api_logger.addHandler(damia_handler)

# Отдельный лог-файл для ошибок API
error_handler = logging.FileHandler('logs/api_errors.log', encoding='utf-8')
error_handler.setLevel(logging.ERROR)
error_handler.setFormatter(formatter)
api_logger.addHandler(error_handler)

TENDERGURU_API_URL = "https://www.tenderguru.ru/api2.3/export"
DAMIA_API_URL = "https://api.damia.ru/zakupki"

platforms_cache = None

async def get_platforms_from_tenderguru():
    """
    Получает справочник площадок (тендерных и торговых) через TenderGuru API.
    Возвращает список словарей с id, name, url.
    Кэширует результат в platforms_cache.
    """
    global platforms_cache
    if platforms_cache is not None:
        return platforms_cache
    platforms = []
    async with aiohttp.ClientSession() as session:
        for mode in ["eauc", "eauc_rgi"]:
            params = {"mode": mode, "dtype": "json", "api_code": TENDER_GURU_API_KEY}
            # Логируем запрос к API
            log_api_request("TenderGuru", TENDERGURU_API_URL, params)
            logging.info(f"Requesting platforms: {params}")
            async with session.get(TENDERGURU_API_URL, params=params) as resp:
                logging.info(f"Response status: {resp.status}")
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    # Логируем полный ответ API
                    log_api_response("TenderGuru", TENDERGURU_API_URL, params, data, resp.status)
                    logging.info(f"Platforms API response: {data}")
                    if isinstance(data, list):
                        for item in data:
                            platforms.append({
                                "id": item.get("ID"),
                                "name": item.get("EtpName") or item.get("Name"),
                                "url": item.get("EtpLink") or item.get("Url", "")
                            })
                    elif isinstance(data, dict):
                        for item in data.get("Items", []):
                            platforms.append({
                                "id": item.get("ID"),
                                "name": item.get("EtpName") or item.get("Name"),
                                "url": item.get("EtpLink") or item.get("Url", "")
                            })
                else:
                    logging.error(f"Failed to get platforms for mode {mode}: {resp.status}")
    if not platforms:
        logging.error("No platforms loaded from TenderGuru API!")
    platforms_cache = platforms
    return platforms

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        keyboard = [
            [InlineKeyboardButton("🔍 TenderGuru", callback_data="wait_for_link_tenderguru")],
            [InlineKeyboardButton("🔍 Damia API", callback_data="wait_for_link_damia")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "Привет! Я TenderBot. Выберите источник для анализа тендеров:",
            reply_markup=reply_markup
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text("Доступные команды:\n/start — начать\n/help — справка")

async def extract_tender_info_from_url(url):
    """
    Определяет площадку и извлекает reg_number (или аналогичный идентификатор) из ссылки на тендер.
    Возвращает (reg_number, platform) или (None, None) если не удалось.
    Теперь использует справочник площадок TenderGuru для определения платформы по домену.
    """
    if not url:
        return None, None
    domain = urlparse(url).netloc.lower()
    platforms = await get_platforms_from_tenderguru()
    matched_platform = None
    for p in platforms:
        if p["url"] and p["url"] in domain:
            matched_platform = p
            break
        if p["url"] and p["url"].replace("www.", "") in domain.replace("www.", ""):
            matched_platform = p
            break
    reg_number = None
    if matched_platform:
        qs = parse_qs(urlparse(url).query)
        for key in ["regNumber", "tenderid", "procedureId", "id", "lot", "purchase", "auction", "number"]:
            if key in qs:
                reg_number = qs[key][0]
                break
        if not reg_number:
            m = re.search(r'(\d{6,})', url)
            if m:
                reg_number = m.group(1)
        logging.info(f"Extracted reg_number={reg_number}, platform={matched_platform['name']} from url={url}")
        return reg_number, matched_platform["name"]
    # Если не нашли — fallback на ручные паттерны (как раньше)
    # zakupki.gov.ru (ЕИС)
    if "zakupki.gov.ru" in domain:
        # Пример: https://zakupki.gov.ru/epz/order/notice/ea44/view/common-info.html?regNumber=0123456789012345678
        qs = parse_qs(urlparse(url).query)
        reg_number = qs.get("regNumber", [None])[0]
        if not reg_number:
            # Иногда номер в пути
            m = re.search(r'/notice/\w+/view/common-info\.html\?regNumber=(\d+)', url)
            if m:
                reg_number = m.group(1)
        return reg_number, "zakupki.gov.ru"
    # sberbank-ast.ru
    if "sberbank-ast.ru" in domain:
        # Пример: https://www.sberbank-ast.ru/procedure/auction/procedure-view/123456789
        m = re.search(r'/procedure-view/(\d+)', url)
        if m:
            return m.group(1), "sberbank-ast.ru"
    # b2b-center.ru
    if "b2b-center.ru" in domain:
        # Пример: https://www.b2b-center.ru/market/?action=show&tenderid=123456789
        qs = parse_qs(urlparse(url).query)
        reg_number = qs.get("tenderid", [None])[0]
        return reg_number, "b2b-center.ru"
    # roseltorg.ru
    if "roseltorg.ru" in domain:
        # Пример: https://www.roseltorg.ru/procedure/auction/view/procedure-cards/123456789
        m = re.search(r'/procedure-cards/(\d+)', url)
        if m:
            return m.group(1), "roseltorg.ru"
    # torgi.gov.ru
    if "torgi.gov.ru" in domain:
        # Пример: https://torgi.gov.ru/new/public/lot/view/123456789
        m = re.search(r'/lot/view/(\d+)', url)
        if m:
            return m.group(1), "torgi.gov.ru"
    # zakazrf.ru
    if "zakazrf.ru" in domain:
        # Пример: https://zakazrf.ru/tender/view/123456789
        m = re.search(r'/tender/view/(\d+)', url)
        if m:
            return m.group(1), "zakazrf.ru"
    # ... можно добавить другие площадки ...
    logging.warning(f"Could not extract reg_number/platform from url={url}")
    return None, None

class TenderGuruAPI:
    @staticmethod
    async def get_tender_by_number(reg_number):
        if not reg_number:
            logging.error("No reg_number provided to get_tender_by_number")
            return None
        params = {
            "regNumber": reg_number,
            "dtype": "json",
            "api_code": TENDER_GURU_API_KEY
        }
        # Логируем запрос к API
        log_api_request("TenderGuru", TENDERGURU_API_URL, params)
        logging.info(f"Requesting tender by number: {params}")
        async with aiohttp.ClientSession() as session:
            async with session.get(TENDERGURU_API_URL, params=params) as resp:
                logging.info(f"Tender API response status: {resp.status}")
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    # Логируем полный ответ API
                    log_api_response("TenderGuru", TENDERGURU_API_URL, params, data, resp.status)
                    logging.info(f"Tender API response: {data}")
                    items = None
                    if isinstance(data, dict):
                        items = data.get("Items")
                    elif isinstance(data, list):
                        # TenderGuru иногда возвращает список, где первый элемент — Total, остальные — тендеры
                        items = [d for d in data if isinstance(d, dict) and (d.get("ID") or d.get("TenderName") or d.get("TenderNumOuter"))]
                    if items and isinstance(items, list) and len(items) > 0:
                        item = items[0]
                        return {
                            "reg_number": reg_number,
                            "customer_name": item.get("Customer", "-"),
                            "purchase_subject": item.get("Name") or item.get("TenderName", "-"),
                            "price": item.get("Price", "-"),
                            "deadline": item.get("DateEnd") or item.get("EndTime", "-"),
                            "location": item.get("RegionName") or item.get("Region", "-")
                        }
                    else:
                        logging.warning(f"No tender found for reg_number {reg_number}")
                else:
                    logging.error(f"Failed to get tender by number {reg_number}: {resp.status}")
        return None

async def analyze_tender_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text:
        link = update.message.text.strip()
        reg_number = extract_tender_number(link)
        if not reg_number:
            await update.message.reply_text("❌ Не удалось извлечь номер закупки из ссылки.")
            return
        # Определяем ФЗ
        fz = None
        if "fz223" in link or "223" in link:
            fz = "fz223"
        card, files = await fetch_tender_card_and_docs(reg_number, fz)
        if not card:
            await update.message.reply_text("❌ Не удалось получить информацию о закупке.")
            return
        # Формируем карточку
        text = f"📄 <b>{card.get('TenderName', 'Без названия')}</b>\n"
        text += f"💰 <b>Цена:</b> {card.get('Price', '—')}\n"
        text += f"🏢 <b>Заказчик:</b> {card.get('Customer', '—')}\n"
        text += f"🌍 <b>Регион:</b> {card.get('Region', '—')}\n"
        text += f"🏛️ <b>Площадка:</b> {card.get('Etp', '—')}\n"
        text += f"⏰ <b>Окончание приёма заявок:</b> {card.get('EndTime', '—')}\n"
        # Кнопки для скачивания файлов
        keyboard = []
        for i, file in enumerate(files):
            keyboard.append([InlineKeyboardButton(f"📥 Скачать {file['name']}", url=file['url'])])
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def get_tender_documents(api_tender_info_url):
    """
    Получает документы тендера по ApiTenderInfo URL.
    """
    if not api_tender_info_url:
        logging.warning("No ApiTenderInfo URL provided")
        return []
    
    logging.info(f"Requesting documents from: {api_tender_info_url}")
    
    # Логируем запрос к API
    log_api_request("TenderGuru", api_tender_info_url, {})
    
    async with aiohttp.ClientSession() as session:
        async with session.get(api_tender_info_url) as resp:
            logging.info(f"Documents API response status: {resp.status}")
            if resp.status == 200:
                data = await resp.json(content_type=None)
                
                # Логируем полный ответ API
                log_api_response("TenderGuru", api_tender_info_url, {}, data, resp.status)
                
                docs = []
                
                # Обрабатываем новый формат ответа API
                if isinstance(data, list) and len(data) > 0:
                    # Берем первый элемент (пропускаем Total)
                    item = data[0]
                    if isinstance(item, dict):
                        # Проверяем поле docsXML
                        if 'docsXML' in item and isinstance(item['docsXML'], dict):
                            docs_data = item['docsXML']
                            if 'document' in docs_data and isinstance(docs_data['document'], list):
                                for doc in docs_data['document']:
                                    if isinstance(doc, dict) and 'link' in doc and 'name' in doc:
                                        docs.append({
                                            'url': doc['link'],
                                            'name': doc['name'],
                                            'size': doc.get('size', 'Неизвестно')
                                        })
                                        logging.info(f"Found document: {doc['name']} -> {doc['link']}")
                
                # Также проверяем старые форматы для совместимости
                for key in ['files', 'attachments', 'docs', 'documents', 'download_links', 'documentation', 'Files', 'Documents']:
                    if key in data and isinstance(data[key], list):
                        docs.extend(data[key])
                        logging.info(f"Found {len(data[key])} documents in key '{key}'")
                
                # Также проверяем, если документы вложены в Items
                if 'Items' in data and isinstance(data['Items'], list) and len(data['Items']) > 0:
                    item = data['Items'][0]
                    for key in ['files', 'attachments', 'docs', 'documents', 'download_links', 'documentation', 'Files', 'Documents']:
                        if key in item and isinstance(item[key], list):
                            docs.extend(item[key])
                            logging.info(f"Found {len(item[key])} documents in Items[0].{key}")
                
                logging.info(f"Total documents found: {len(docs)}")
                return docs
            else:
                logging.error(f"Failed to get documents: {resp.status}")
                return []

def extract_tender_number(url):
    """
    Извлекает regNumber или id из ссылки на zakupki.gov.ru или TenderGuru
    """
    if not url:
        return None
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    for key in ["regNumber", "tend_num", "id", "purchaseNumber"]:
        if key in qs:
            return qs[key][0]
    m = re.search(r'(\d{11,})', url)
    if m:
        return m.group(1)
    return None

async def send_tender_card(update, context, tender_info, tender_number, source=None):
    """
    Отправляет карточку тендера с кнопками.
    """
    # Определяем источник данных
    if source:
        api_source = source
    else:
        api_source = tender_info.get('source', 'unknown')
    
    # Формируем текст карточки
    text = (
        f"📄 **Тендер №{tender_info['id']}**\n\n"
        f"📝 **Предмет:** {tender_info['name']}\n"
        f"📍 **Регион:** {tender_info['region']}\n"
        f"🏗️ **Категория:** {tender_info['category']}\n"
        f"💰 **Начальная цена:** {tender_info['price']}\n"
        f"📅 **Дедлайн подачи заявок:** {tender_info['deadline']}\n"
        f"🗓️ **Дата публикации:** {tender_info['published']}\n"
        f"📎 **Площадка:** {tender_info['etp']}\n"
        f"🏢 **Заказчик:** {tender_info['customer']}\n"
    )
    
    # Добавляем статус для Damia API
    if api_source == "damia" and tender_info.get('status'):
        text += f"📊 **Статус:** {tender_info['status']}\n"
    
    # Добавляем ссылку
    if tender_info.get('url'):
        text += f"🔗 [Открыть тендер]({tender_info['url']})\n"
    
    text += f"\n📊 **Источник:** {api_source.upper()}"
    
    # Создаем кнопки
    keyboard = []
    
    # Кнопка для скачивания документов (если есть документы в docsXML или ApiTenderInfo URL)
    has_documents = False
    
    # Проверяем наличие документов в docsXML
    if tender_info.get('docs_xml') and isinstance(tender_info['docs_xml'], dict):
        docs_data = tender_info['docs_xml']
        if 'document' in docs_data and isinstance(docs_data['document'], list) and len(docs_data['document']) > 0:
            has_documents = True
    
    # Проверяем наличие ApiTenderInfo URL
    if tender_info.get('api_tender_info') and tender_info['api_tender_info'] != "—":
        has_documents = True
    
    if has_documents:
        keyboard.append([InlineKeyboardButton("📥 Скачать документы", callback_data=f"download_docs_{tender_number}")])
    
    # Кнопки для разных API
    if api_source == "tenderguru":
        keyboard.extend([
            [InlineKeyboardButton("🔍 Damia API", callback_data=f"damia_{tender_number}")],
            [InlineKeyboardButton("🔙 Назад к выбору", callback_data=f"back_to_tender_{tender_number}")]
        ])
    elif api_source == "damia":
        keyboard.extend([
            [InlineKeyboardButton("🔍 TenderGuru", callback_data=f"tenderguru_{tender_number}")],
            [InlineKeyboardButton("🔙 Назад к выбору", callback_data=f"back_to_tender_{tender_number}")]
        ])
    else:
        # Если источник не определен, показываем обе кнопки
        keyboard.extend([
            [InlineKeyboardButton("🔍 TenderGuru", callback_data=f"tenderguru_{tender_number}")],
            [InlineKeyboardButton("🔍 Damia API", callback_data=f"damia_{tender_number}")]
        ])
    
    # Добавляем кнопки для проверки поставщика (если есть ИНН)
    if tender_info.get('customers') and len(tender_info['customers']) > 0:
        customer_inn = tender_info['customers'][0].get('inn')
        if customer_inn:
            keyboard.append([InlineKeyboardButton("🔍 Проверить поставщика", callback_data=f"check_supplier_{tender_number}_{customer_inn}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Отправляем сообщение
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, 
            reply_markup=reply_markup, 
            disable_web_page_preview=True, 
            parse_mode='Markdown'
        )
    elif update.message:
        await update.message.reply_text(
            text, 
            reply_markup=reply_markup, 
            disable_web_page_preview=True, 
            parse_mode='Markdown'
        )

async def download_documents_via_api(update, context, tender_id, tender_data=None):
    """
    Скачивает документы тендера используя модуль downloader.py
    """
    query = update.callback_query
    await query.edit_message_text("⏳ Получаю информацию о документах...")
    
    try:
        # Получаем данные тендера, если не переданы
        if not tender_data:
            tender_data = await get_tender_info(tender_id)
        
        if not tender_data:
            await query.edit_message_text("❌ Не удалось получить информацию о тендере.")
            return
        
        # Проверяем, есть ли ApiTenderInfo URL для получения документов
        api_tender_info_url = None
        if isinstance(tender_data, dict):
            api_tender_info_url = tender_data.get('ApiTenderInfo') or tender_data.get('api_tender_info')
        elif isinstance(tender_data, list) and len(tender_data) > 0:
            api_tender_info_url = tender_data[0].get('ApiTenderInfo') or tender_data[0].get('api_tender_info')
        
        # Если есть URL для получения документов, делаем дополнительный запрос
        if api_tender_info_url and api_tender_info_url != "—":
            await query.edit_message_text("⏳ Загружаю документы тендера...")
            
            # Исправляем URL, добавляя API ключ
            if 'api_code=' in api_tender_info_url:
                # Заменяем пустой api_code на реальный ключ
                api_tender_info_url = api_tender_info_url.replace('api_code=', f'api_code={TENDER_GURU_API_KEY}')
            else:
                # Добавляем api_code параметр
                separator = '&' if '?' in api_tender_info_url else '?'
                api_tender_info_url = f"{api_tender_info_url}{separator}api_code={TENDER_GURU_API_KEY}"
            
            logging.info(f"Requesting documents from: {api_tender_info_url}")
            
            # Делаем запрос к API для получения документов
            async with aiohttp.ClientSession() as session:
                async with session.get(api_tender_info_url) as resp:
                    if resp.status == 200:
                        documents_data = await resp.json(content_type=None)
                        logging.info(f"Documents API response: {documents_data}")
                        
                        # Обновляем данные тендера с документами
                        if isinstance(documents_data, list) and len(documents_data) > 0:
                            tender_data = documents_data[0]
                        elif isinstance(documents_data, dict):
                            tender_data = documents_data
                    else:
                        logging.error(f"Failed to get documents: {resp.status}")
        
        await query.edit_message_text("⏳ Скачиваю документацию...")
        
        # Используем модуль downloader для скачивания документов
        result = await download_tender_documents(tender_data, tender_id)
        
        if not result['success']:
            error_msg = "❌ Не удалось скачать документы.\n"
            if result['errors']:
                error_msg += "\n".join(result['errors'][:3])  # Показываем первые 3 ошибки
            await query.edit_message_text(error_msg)
            return
        
        # Отправляем архив пользователю
        if result['archive_path'] and os.path.exists(result['archive_path']):
            with open(result['archive_path'], 'rb') as f:
                await context.bot.send_document(
                    chat_id=query.message.chat_id,
                    document=f,
                    filename=f"tender_{tender_id}_docs.zip"
                )
            
            # Формируем сообщение об успехе
            success_msg = f"✅ Документация успешно скачана!\n"
            success_msg += f"📄 Скачано файлов: {result['downloaded_files']} из {result['total_files']}"
            
            if result['errors']:
                success_msg += f"\n⚠️ Ошибки: {len(result['errors'])} файлов не удалось скачать"
            
            await query.edit_message_text(success_msg)
            
            # Удаляем временный архив
            try:
                os.remove(result['archive_path'])
            except Exception as e:
                logging.error(f"Error removing temporary archive: {e}")
        else:
            await query.edit_message_text("❌ Не удалось создать архив с документами.")
            
    except Exception as e:
        logging.error(f"Error downloading documents via API: {e}")
        await query.edit_message_text("❌ Ошибка при скачивании документации.")

async def download_documents(update, context, tender_id):
    """
    Скачивает документы тендера.
    """
    query = update.callback_query
    await query.edit_message_text("⏳ Скачиваю документацию...")
    
    try:
        # Пытаемся скачать документы
        archive_path = await download_all_files(tender_id)
        
        if archive_path and os.path.exists(archive_path):
            # Отправляем архив
            with open(archive_path, 'rb') as f:
                await context.bot.send_document(
                    chat_id=query.message.chat_id,
                    document=f,
                    filename=f"tender_{tender_id}_docs.zip"
                )
            # Удаляем временный файл
            os.remove(archive_path)
            await query.edit_message_text("✅ Документация успешно скачана!")
        else:
            await query.edit_message_text("❌ Документация не найдена или не удалось скачать файлы.")
    except Exception as e:
        logging.error(f"Error downloading documents: {e}")
        await query.edit_message_text("❌ Ошибка при скачивании документации.")

async def wait_for_link_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик для ожидания ссылки на тендер."""
    if update.message and update.message.text:
        link = update.message.text.strip()
        logging.info(f"Received tender link: {link}")
        await update.message.reply_text("🔍 Анализирую тендер...")
        tender_number = extract_tender_number(link)
        logging.info(f"Extracted tender number: {tender_number}")
        if not tender_number:
            await update.message.reply_text("❌ Не удалось извлечь номер тендера из ссылки. Проверьте формат ссылки.")
            return
        try:
            # Кэшируем результат первого запроса
            cache_key = f"tenderguru_{tender_number}"
            tender_data = context.user_data.get(cache_key)
            if not tender_data:
                logging.info("Trying TenderGuru API first...")
                tender_data = await get_tender_info(tender_number)
                if tender_data:
                    context.user_data[cache_key] = tender_data
            if tender_data:
                logging.info("TenderGuru API returned data, parsing...")
                tender_info = parse_tender_info(tender_data)
                await send_tender_card(update, context, tender_info, tender_number)
            else:
                logging.info("TenderGuru API returned no data, trying Damia API...")
                damia_data = await DamiaAPI.get_tender_by_number(tender_number)
                if damia_data:
                    tender_info = parse_damia_tender_info(damia_data)
                    await send_tender_card(update, context, tender_info, tender_number)
                else:
                    await update.message.reply_text("❌ Не удалось найти информацию о тендере в доступных источниках.")
        except Exception as e:
            logging.error(f"Error in wait_for_link_handler: {e}")
            await update.message.reply_text("❌ Произошла ошибка при анализе тендера. Попробуйте позже.")

async def download_all_files(reg_number):
    """
    Получает список файлов по reg_number через TenderGuruAPI, скачивает их, архивирует в .zip и возвращает путь к архиву.
    """
    params = {
        "regNumber": reg_number,
        "dtype": "json",
        "api_code": TENDER_GURU_API_KEY
    }
    # Логируем запрос к API
    log_api_request("TenderGuru", TENDERGURU_API_URL, params)
    logging.info(f"Requesting files for tender: {params}")
    async with aiohttp.ClientSession() as session:
        async with session.get(TENDERGURU_API_URL, params=params) as resp:
            logging.info(f"Files API response status: {resp.status}")
            if resp.status == 200:
                data = await resp.json(content_type=None)
                # Логируем полный ответ API
                log_api_response("TenderGuru", TENDERGURU_API_URL, params, data, resp.status)
                logging.info(f"Files API response: {data}")
                items = data.get("Items")
                if items and isinstance(items, list) and len(items) > 0:
                    item = items[0]
                    files = item.get("Files") or item.get("Documents") or item.get("Attachments")
                    if not files:
                        logging.warning(f"No files found for tender {reg_number}")
                        return None
                    temp_dir = tempfile.mkdtemp()
                    file_paths = []
                    for f in files:
                        url = f.get("Url") or f.get("url")
                        name = f.get("Name") or f.get("name") or os.path.basename(url)
                        if url:
                            file_path = os.path.join(temp_dir, name)
                            try:
                                async with session.get(url) as file_resp:
                                    logging.info(f"Downloading file: {url}, status: {file_resp.status}")
                                    if file_resp.status == 200:
                                        with open(file_path, "wb") as out_f:
                                            out_f.write(await file_resp.read())
                                        file_paths.append(file_path)
                                    else:
                                        logging.error(f"Failed to download file: {url}, status: {file_resp.status}")
                            except Exception as e:
                                logging.error(f"Exception while downloading file {url}: {e}")
                                continue
                    if not file_paths:
                        shutil.rmtree(temp_dir)
                        return None
                    archive_path = shutil.make_archive(temp_dir, 'zip', temp_dir)
                    shutil.rmtree(temp_dir)
                    logging.info(f"Created archive: {archive_path}")
                    return archive_path
            else:
                logging.error(f"Failed to get files for tender {reg_number}: {resp.status}")
    return None

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий на кнопки."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    data = query.data
    if data is None:
        return
    logging.info(f"Button pressed: {data}")
    if data.startswith("download_docs_"):
        tender_id = data.split("_")[2]
        cache_key = f"tenderguru_{tender_id}"
        tender_data = context.user_data.get(cache_key)
        if not tender_data:
            tender_data = await get_tender_info(tender_id)
            if tender_data:
                context.user_data[cache_key] = tender_data
        await download_documents_via_api(update, context, tender_id, tender_data)
    elif data.startswith("tenderguru_"):
        tender_number = data.split("_", 1)[1]
        cache_key = f"tenderguru_{tender_number}"
        tender_data = context.user_data.get(cache_key)
        if not tender_data:
            tender_data = await get_tender_info(tender_number)
            if tender_data:
                context.user_data[cache_key] = tender_data
        if tender_data:
            tender_info = parse_tender_info(tender_data)
            await send_tender_card(update, context, tender_info, tender_number, source="tenderguru")
        else:
            await query.edit_message_text("❌ Не удалось получить данные через TenderGuru API")
    elif data.startswith("damia_"):
        # Анализ через Damia API
        tender_number = data.split("_", 1)[1]
        logging.info(f"Analyzing tender {tender_number} via Damia API")
        
        await query.edit_message_text("🔍 Анализирую через Damia API...")
        
        damia_data = await DamiaAPI.get_tender_by_number(tender_number)
        if damia_data:
            logging.info("Damia API returned data")
            tender_info = parse_damia_tender_info(damia_data)
            await send_tender_card(update, context, tender_info, tender_number, source="damia")
        else:
            logging.warning("Damia API returned no data")
            await query.edit_message_text("❌ Не удалось получить данные через Damia API")
            
    elif data.startswith("check_supplier_"):
        # Проверка поставщика
        parts = data.split("_")
        if len(parts) >= 4:
            tender_number = parts[2]
            inn = parts[3]
            logging.info(f"Checking supplier with INN: {inn}")
            
            await query.edit_message_text("🔍 Проверяю поставщика в реестрах...")
            
            # Проверяем в разных реестрах
            rnp_result = await DamiaAPI.check_supplier_rnp(inn)
            sro_result = await DamiaAPI.check_supplier_sro(inn)
            eruz_result = await DamiaAPI.check_supplier_eruz(inn)
            
            # Формируем отчет
            report = f"📋 **Результаты проверки ИНН {inn}:**\n\n"
            
            if rnp_result:
                report += "🔴 **РНП (Реестр недобросовестных поставщиков):**\n"
                report += f"Найдено записей: {len(rnp_result) if isinstance(rnp_result, list) else 1}\n\n"
            else:
                report += "✅ **РНП:** Записей не найдено\n\n"
                
            if sro_result:
                report += "🟡 **СРО (Саморегулируемые организации):**\n"
                report += f"Найдено записей: {len(sro_result) if isinstance(sro_result, list) else 1}\n\n"
            else:
                report += "✅ **СРО:** Записей не найдено\n\n"
                
            if eruz_result:
                report += "🟡 **ЕРУЗ (Единый реестр участников закупок):**\n"
                report += f"Найдено записей: {len(eruz_result) if isinstance(eruz_result, list) else 1}\n\n"
            else:
                report += "✅ **ЕРУЗ:** Записей не найдено\n\n"
            
            # Кнопка возврата
            keyboard = [[InlineKeyboardButton("🔙 Назад к тендеру", callback_data=f"back_to_tender_{tender_number}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(report, reply_markup=reply_markup, parse_mode='Markdown')
        
    elif data.startswith("back_to_tender_"):
        # Возврат к карточке тендера
        tender_number = data.split("_", 3)[3]
        logging.info(f"Returning to tender card: {tender_number}")
        
        # Показываем кнопки выбора API
        keyboard = [
            [InlineKeyboardButton("🔍 TenderGuru", callback_data=f"tenderguru_{tender_number}")],
            [InlineKeyboardButton("🔍 Damia API", callback_data=f"damia_{tender_number}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🔍 Выберите источник для анализа тендера:",
            reply_markup=reply_markup
        )
    elif data == "wait_for_link":
        await query.edit_message_text("Отправьте ссылку на тендер сообщением.")
    elif data == "wait_for_link_tenderguru":
        await query.edit_message_text("🔍 **TenderGuru**\n\nОтправьте ссылку на тендер для анализа через TenderGuru API.")
    elif data == "wait_for_link_damia":
        await query.edit_message_text("🔍 **Damia API**\n\nОтправьте ссылку на тендер для анализа через Damia API.")

async def get_tender_info(tender_number):
    """
    Получает информацию о тендере из TenderGuru API.
    """
    # Проверяем API ключ
    if not TENDER_GURU_API_KEY or TENDER_GURU_API_KEY == "your-tenderguru-api-key-here":
        error_msg = "API ключ TenderGuru не настроен. Установите TENDER_GURU_API_KEY в config.py"
        print(f"\n❌ {error_msg}", flush=True)
        logging.error(error_msg)
        return None
    
    print(f"\n🔑 TenderGuru API Key: {TENDER_GURU_API_KEY[:10]}...", flush=True)
    logging.info(f"TenderGuru API Key: {TENDER_GURU_API_KEY[:10]}...")
    
    # Пробуем разные варианты параметров
    params_variants = [
        {
            "key": TENDER_GURU_API_KEY,
            "tender": tender_number
        },
        {
            "key": TENDER_GURU_API_KEY,
            "regNumber": tender_number
        },
        {
            "key": TENDER_GURU_API_KEY,
            "tender": tender_number,
            "dtype": "json"
        },
        {
            "key": TENDER_GURU_API_KEY,
            "regNumber": tender_number,
            "dtype": "json"
        },
        {
            "api_code": TENDER_GURU_API_KEY,
            "tender": tender_number
        },
        {
            "api_code": TENDER_GURU_API_KEY,
            "regNumber": tender_number
        },
        {
            "api_code": TENDER_GURU_API_KEY,
            "tender": tender_number,
            "dtype": "json"
        },
        {
            "api_code": TENDER_GURU_API_KEY,
            "regNumber": tender_number,
            "dtype": "json"
        },
        {
            "api_code": TENDER_GURU_API_KEY,
            "id": tender_number
        },
        {
            "api_code": TENDER_GURU_API_KEY,
            "id": tender_number,
            "dtype": "json"
        }
    ]
    
    for i, params in enumerate(params_variants):
        # Логируем запрос к API
        log_api_request("TenderGuru", TENDERGURU_API_URL, params)
        logging.info(f"Trying TenderGuru API variant {i+1}: {params}")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(TENDERGURU_API_URL, params=params) as resp:
                logging.info(f"TenderGuru API response status: {resp.status}")
                if resp.status == 200:
                    try:
                        # Получаем текст ответа для логирования
                        response_text = await resp.text()
                        print(f"\n🔍 TenderGuru API Raw Response: {response_text}", flush=True)
                        logging.info(f"TenderGuru API raw response: {response_text}")
                        
                        # Проверяем, что ответ не пустой
                        if not response_text.strip():
                            print(f"⚠️ Empty response from TenderGuru API for tender_number {tender_number}", flush=True)
                            logging.warning(f"Empty response from TenderGuru API for tender_number {tender_number}")
                            continue
                        
                        # Пытаемся парсить JSON
                        data = await resp.json(content_type=None)
                        
                        # Логируем полный ответ
                        log_api_response("TenderGuru", TENDERGURU_API_URL, params, data, resp.status)
                        
                        if isinstance(data, dict):
                            print(f"\n📋 TenderGuru API response keys: {list(data.keys())}", flush=True)
                            logging.info(f"TenderGuru API response keys: {list(data.keys())}")
                            
                            # Ищем тендер в разных возможных ключах
                            for key in [tender_number, "Items", "items", "data", "result", "tender", "tenders"]:
                                if key in data:
                                    print(f"\n✅ Found data in key: {key}", flush=True)
                                    logging.info(f"Found data in key: {key}")
                                    if key == tender_number:
                                        return data[key]
                                    elif isinstance(data[key], list) and len(data[key]) > 0:
                                        return data[key][0]
                                    elif isinstance(data[key], dict):
                                        return data[key]
                            
                            # Если не нашли в стандартных ключах, проверяем все ключи
                            for key, value in data.items():
                                if isinstance(value, dict) and any(field in value for field in ['TenderName', 'Name', 'ID', 'id']):
                                    print(f"\n✅ Found tender data in key: {key}", flush=True)
                                    logging.info(f"Found tender data in key: {key}")
                                    return value
                                elif isinstance(value, list) and len(value) > 0 and isinstance(value[0], dict):
                                    if any(field in value[0] for field in ['TenderName', 'Name', 'ID', 'id']):
                                        print(f"\n✅ Found tender data in list key: {key}", flush=True)
                                        logging.info(f"Found tender data in list key: {key}")
                                        return value[0]
                        
                        elif isinstance(data, list) and len(data) > 0:
                            print(f"\n✅ TenderGuru API returned list with {len(data)} items", flush=True)
                            logging.info(f"TenderGuru API returned list with {len(data)} items")
                            # Пропускаем элементы, где только ключ 'Total'
                            for item in data:
                                if isinstance(item, dict) and any(k in item for k in ['ID', 'TenderName', 'Name', 'id']):
                                    print(f"\n✅ Found tender item in list: {item}", flush=True)
                                    logging.info(f"Found tender item in list: {item}")
                                    return item
                            # Если не нашли — возвращаем первый элемент (для отладки)
                            return data[0]
                        
                        print(f"\n⚠️ No tender found in TenderGuru API response for tender_number {tender_number}", flush=True)
                        logging.warning(f"No tender found in TenderGuru API response for tender_number {tender_number}")
                        
                    except json.JSONDecodeError as e:
                        print(f"❌ JSON decode error from TenderGuru API variant {i+1}: {e}", flush=True)
                        print(f"Response text: {response_text}", flush=True)
                        logging.error(f"JSON decode error from TenderGuru API variant {i+1}: {e}")
                        logging.error(f"Response text: {response_text}")
                        continue
                    except Exception as e:
                        print(f"❌ Error processing TenderGuru API response variant {i+1}: {e}", flush=True)
                        logging.error(f"Error processing TenderGuru API response variant {i+1}: {e}")
                        continue
                else:
                    print(f"❌ Failed to get tender from TenderGuru API variant {i+1}: {resp.status}", flush=True)
                    logging.error(f"Failed to get tender from TenderGuru API variant {i+1}: {resp.status}")
    
    logging.warning(f"All TenderGuru API variants failed for tender_number {tender_number}")
    return None

def log_api_request(api_name, endpoint, params):
    """
    Логирует запросы к API в файл и консоль
    """
    timestamp = logging.Formatter().formatTime(logging.LogRecord('', 0, '', 0, '', (), None))
    
    # Логируем в файл
    api_logger.info(f"=== {api_name.upper()} API REQUEST ===")
    api_logger.info(f"Timestamp: {timestamp}")
    api_logger.info(f"Endpoint: {endpoint}")
    api_logger.info(f"Params: {json.dumps(params, ensure_ascii=False, indent=2)}")
    api_logger.info("=" * 50)
    
    # Логируем в консоль с принудительным выводом
    print(f"\n{'='*60}", flush=True)
    print(f"🚀 {api_name.upper()} API REQUEST", flush=True)
    print(f"{'='*60}", flush=True)
    print(f"📅 Timestamp: {timestamp}", flush=True)
    print(f"📡 Endpoint: {endpoint}", flush=True)
    print(f"🔧 Params: {json.dumps(params, ensure_ascii=False, indent=2)}", flush=True)
    print(f"{'='*60}\n", flush=True)
    
    # Также логируем через основной логгер
    logging.info(f"=== {api_name.upper()} API REQUEST ===")
    logging.info(f"Timestamp: {timestamp}")
    logging.info(f"Endpoint: {endpoint}")
    logging.info(f"Params: {json.dumps(params, ensure_ascii=False, indent=2)}")
    logging.info("=" * 50)

def log_api_response(api_name, endpoint, params, response_data, status_code=200):
    """
    Логирует полные ответы API в файл и консоль
    """
    timestamp = logging.Formatter().formatTime(logging.LogRecord('', 0, '', 0, '', (), None))
    
    # Логируем в файл
    api_logger.info(f"=== {api_name.upper()} API RESPONSE ===")
    api_logger.info(f"Timestamp: {timestamp}")
    api_logger.info(f"Endpoint: {endpoint}")
    api_logger.info(f"Params: {json.dumps(params, ensure_ascii=False, indent=2)}")
    api_logger.info(f"Status: {status_code}")
    api_logger.info(f"Response: {json.dumps(response_data, ensure_ascii=False, indent=2)}")
    api_logger.info("=" * 50)
    
    # Логируем в консоль с принудительным выводом
    print(f"\n{'='*60}", flush=True)
    print(f"🔍 {api_name.upper()} API RESPONSE", flush=True)
    print(f"{'='*60}", flush=True)
    print(f"📅 Timestamp: {timestamp}", flush=True)
    print(f"📡 Endpoint: {endpoint}", flush=True)
    print(f"🔧 Params: {json.dumps(params, ensure_ascii=False, indent=2)}", flush=True)
    print(f"📊 Status: {status_code}", flush=True)
    print(f"📄 Response: {json.dumps(response_data, ensure_ascii=False, indent=2)}", flush=True)
    print(f"{'='*60}\n", flush=True)
    
    # Также логируем через основной логгер
    logging.info(f"=== {api_name.upper()} API RESPONSE ===")
    logging.info(f"Timestamp: {timestamp}")
    logging.info(f"Endpoint: {endpoint}")
    logging.info(f"Params: {json.dumps(params, ensure_ascii=False, indent=2)}")
    logging.info(f"Status: {status_code}")
    logging.info(f"Response: {json.dumps(response_data, ensure_ascii=False, indent=2)}")
    logging.info("=" * 50)
    
    # Если статус не 200, логируем ошибку отдельно
    if status_code != 200:
        api_logger.error(f"API ERROR - {api_name}: Status {status_code}")
        api_logger.error(f"Endpoint: {endpoint}")
        api_logger.error(f"Params: {json.dumps(params, ensure_ascii=False, indent=2)}")
        api_logger.error(f"Response: {json.dumps(response_data, ensure_ascii=False, indent=2)}")

def parse_tender_info(data):
    """
    Преобразует словарь тендера из TenderGuru API в структуру для UI-отображения.
    Извлекает МАКСИМАЛЬНО возможную информацию.
    """
    print(f"\n🔍 Parsing TenderGuru data: {json.dumps(data, ensure_ascii=False, indent=2)}", flush=True)
    logging.info(f"Parsing TenderGuru data: {json.dumps(data, ensure_ascii=False, indent=2)}")
    
    # Выводим все доступные ключи
    print(f"\n📋 Available keys in TenderGuru data: {list(data.keys())}", flush=True)
    logging.info(f"Available keys in TenderGuru data: {list(data.keys())}")
    
    def safe_get(key, default="—"):
        value = data.get(key)
        if value is None or value == "":
            return default
        return str(value)

    # Пытаемся найти цену в разных полях
    price_raw = None
    for price_key in ['Price', 'price', 'Amount', 'amount', 'Sum', 'sum']:
        if price_key in data:
            price_raw = data[price_key]
            break
    
    if price_raw and str(price_raw).replace('.', '').replace(',', '').isdigit():
        try:
            price = f"{int(float(str(price_raw).replace(',', ''))):,} ₽".replace(",", " ")
        except:
            price = f"{price_raw} ₽"
    else:
        price = "Не указано"

    # Пытаемся найти название в разных полях
    name = None
    for name_key in ['TenderName', 'Name', 'name', 'Title', 'title', 'Subject', 'subject']:
        if name_key in data:
            name = data[name_key]
            break
    
    # Пытаемся найти регион в разных полях
    region = None
    for region_key in ['Region', 'region', 'RegionName', 'regionName', 'Location', 'location']:
        if region_key in data:
            region = data[region_key]
            break
    
    # Пытаемся найти заказчика в разных полях
    customer = None
    for customer_key in ['Customer', 'customer', 'CustomerName', 'customerName', 'Client', 'client']:
        if customer_key in data:
            customer = data[customer_key]
            break
    
    # Пытаемся найти ЭТП в разных полях
    etp = None
    for etp_key in ['Etp', 'etp', 'EtpName', 'etpName', 'Platform', 'platform']:
        if etp_key in data:
            etp = data[etp_key]
            break
    
    # Пытаемся найти URL в разных полях
    url = None
    for url_key in ['TenderLinkInner', 'Url', 'url', 'Link', 'link', 'TenderLink', 'tenderLink']:
        if url_key in data:
            url = data[url_key]
            break
    
    # Пытаемся найти ID в разных полях
    tender_id = None
    for id_key in ['ID', 'id', 'TenderID', 'tenderID', 'Number', 'number']:
        if id_key in data:
            tender_id = data[id_key]
            break

    # Извлекаем ВСЮ доступную информацию
    tender_info = {
        "id": safe_get('ID') if tender_id is None else str(tender_id),
        "name": safe_get('TenderName') if name is None else str(name),
        "region": safe_get('Region') if region is None else str(region),
        "category": safe_get('Category'),
        "price": price,
        "deadline": safe_get('EndTime'),
        "published": safe_get('Date'),
        "etp": safe_get('Etp') if etp is None else str(etp),
        "url": safe_get('TenderLinkInner') if url is None else str(url),
        "customer": safe_get('Customer') if customer is None else str(customer),
        "tender_num_outer": safe_get('TenderNumOuter'),
        "fz": safe_get('Fz'),
        "api_tender_info": safe_get('ApiTenderInfo'),
        "user_id": safe_get('User_id'),
        "search_fragment": data.get('searchFragmentXML', {}),
        "source": "tenderguru",
        "raw_data": data,  # Сохраняем сырые данные для полного анализа
        # Добавляем новые поля для документов и дополнительной информации
        "docs_xml": data.get('docsXML', {}),
        "api_protokol_info": safe_get('ApiProtokolInfo'),
        "api_pred_info": safe_get('ApiPredInfo'),
        "api_contract_info": safe_get('ApiContractInfo'),
        "api_izm_info": safe_get('ApiIzmInfo'),
        "api_char_link_tender": safe_get('ApiCharLinkTender'),
        "api_char_link_tender_vcontract": safe_get('ApiCharLinkTenderVcontract')
    }

    print(f"\n✅ Extracted TenderGuru info: {json.dumps(tender_info, ensure_ascii=False, indent=2)}", flush=True)
    logging.info(f"Extracted TenderGuru data: {json.dumps(tender_info, ensure_ascii=False, indent=2)}")
    
    return tender_info

class DamiaAPI:
    """
    Класс для работы с API-Закупки (damia.ru)
    """
    @staticmethod
    async def get_tender_by_number(reg_number):
        """
        Получает информацию о закупке по номеру извещения.
        """
        if not reg_number:
            logging.error("No reg_number provided to DamiaAPI.get_tender_by_number")
            return None
        
        params = {
            "regn": reg_number,
            "key": DAMIA_API_KEY
        }
        # Логируем запрос к API
        log_api_request("Damia", f"{DAMIA_API_URL}/zakupka", params)
        logging.info(f"Requesting tender from Damia API: {params}")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{DAMIA_API_URL}/zakupka", params=params) as resp:
                logging.info(f"Damia API response status: {resp.status}")
                if resp.status == 200:
                    try:
                        # Получаем текст ответа для логирования
                        response_text = await resp.text()
                        print(f"\n🔍 Damia API Raw Response: {response_text}", flush=True)
                        logging.info(f"Damia API raw response: {response_text}")
                        
                        # Проверяем, что ответ не пустой
                        if not response_text.strip():
                            print(f"⚠️ Empty response from Damia API for reg_number {reg_number}", flush=True)
                            logging.warning(f"Empty response from Damia API for reg_number {reg_number}")
                            return None
                        
                        # Пытаемся парсить JSON
                        data = await resp.json(content_type=None)
                        
                        # Логируем полный ответ
                        log_api_response("Damia", f"{DAMIA_API_URL}/zakupka", params, data, resp.status)
                        
                        if reg_number in data:
                            tender_data = data[reg_number]
                            return tender_data
                        else:
                            logging.warning(f"No tender found in Damia API for reg_number {reg_number}")
                            
                    except json.JSONDecodeError as e:
                        logging.error(f"JSON decode error from Damia API: {e}")
                        logging.error(f"Response text: {response_text}")
                        return None
                    except Exception as e:
                        logging.error(f"Error processing Damia API response: {e}")
                        return None
                else:
                    logging.error(f"Failed to get tender from Damia API {reg_number}: {resp.status}")
        return None

    @staticmethod
    async def search_tenders(query, from_date=None, to_date=None, region=None, min_price=None, max_price=None):
        """
        Поиск закупок по ключевым словам и параметрам.
        """
        params = {
            "q": query,
            "key": DAMIA_API_KEY
        }
        
        if from_date:
            params["from_date"] = from_date
        if to_date:
            params["to_date"] = to_date
        if region:
            params["region"] = region
        if min_price:
            params["min_price"] = min_price
        if max_price:
            params["max_price"] = max_price
            
        # Логируем запрос к API
        log_api_request("Damia", f"{DAMIA_API_URL}/zsearch", params)
        logging.info(f"Searching tenders in Damia API: {params}")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{DAMIA_API_URL}/zsearch", params=params) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    log_api_response("Damia", f"{DAMIA_API_URL}/zsearch", params, data, resp.status)
                    return data
                else:
                    logging.error(f"Failed to search tenders in Damia API: {resp.status}")
        return None

    @staticmethod
    async def check_supplier_rnp(inn):
        """
        Проверяет наличие поставщика в реестре недобросовестных поставщиков.
        """
        params = {
            "inn": inn,
            "key": DAMIA_API_KEY
        }
        
        # Логируем запрос к API
        log_api_request("Damia", f"{DAMIA_API_URL}/rnp", params)
        
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{DAMIA_API_URL}/rnp", params=params) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    log_api_response("Damia", f"{DAMIA_API_URL}/rnp", params, data, resp.status)
                    return data
                else:
                    logging.error(f"Failed to check RNP in Damia API: {resp.status}")
        return None

    @staticmethod
    async def check_supplier_sro(req):
        """
        Проверяет наличие в реестре саморегулируемых организаций.
        """
        params = {
            "req": req,
            "key": DAMIA_API_KEY
        }
        
        # Логируем запрос к API
        log_api_request("Damia", f"{DAMIA_API_URL}/sro", params)
        
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{DAMIA_API_URL}/sro", params=params) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    log_api_response("Damia", f"{DAMIA_API_URL}/sro", params, data, resp.status)
                    return data
                else:
                    logging.error(f"Failed to check SRO in Damia API: {resp.status}")
        return None

    @staticmethod
    async def check_supplier_eruz(req):
        """
        Проверяет наличие в едином реестре участников закупок.
        """
        params = {
            "req": req,
            "key": DAMIA_API_KEY
        }
        
        # Логируем запрос к API
        log_api_request("Damia", f"{DAMIA_API_URL}/eruz", params)
        
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{DAMIA_API_URL}/eruz", params=params) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    log_api_response("Damia", f"{DAMIA_API_URL}/eruz", params, data, resp.status)
                    return data
                else:
                    logging.error(f"Failed to check ERUZ in Damia API: {resp.status}")
        return None

def parse_damia_tender_info(data):
    """
    Преобразует данные тендера из Damia API в унифицированный формат.
    Извлекает МАКСИМАЛЬНО возможную информацию.
    """
    def safe_get(obj, key, default="—"):
        if isinstance(obj, dict):
            return obj.get(key) or default
        return default

    # Извлекаем основную информацию
    region = safe_get(data, 'Регион')
    fz = safe_get(data, 'ФЗ')
    date_publ = safe_get(data, 'ДатаПубл')
    date_okonch = safe_get(data, 'ДатаОконч')
    date_nach = safe_get(data, 'ДатаНач')
    time_nach = safe_get(data, 'ВремяНач')
    time_okonch = safe_get(data, 'ВремяОконч')
    date_rassm = safe_get(data, 'ДатаРассм')
    date_aukts = safe_get(data, 'ДатаАукц')
    time_aukts = safe_get(data, 'ВремяАукц')
    
    # Информация о заказчике (полная)
    zakazchik = data.get('Заказчик', [])
    customer_info = []
    if isinstance(zakazchik, list):
        for cust in zakazchik:
            customer_info.append({
                "ogrn": safe_get(cust, 'ОГРН'),
                "inn": safe_get(cust, 'ИНН'),
                "name_full": safe_get(cust, 'НаимПолн'),
                "name_short": safe_get(cust, 'НаимСокр'),
                "address": safe_get(cust, 'АдресПолн'),
                "head_fio": safe_get(cust, 'РукФИО'),
                "head_inn": safe_get(cust, 'РукИННФЛ')
            })
    elif isinstance(zakazchik, dict):
        customer_info.append({
            "ogrn": safe_get(zakazchik, 'ОГРН'),
            "inn": safe_get(zakazchik, 'ИНН'),
            "name_full": safe_get(zakazchik, 'НаимПолн'),
            "name_short": safe_get(zakazchik, 'НаимСокр'),
            "address": safe_get(zakazchik, 'АдресПолн'),
            "head_fio": safe_get(zakazchik, 'РукФИО'),
            "head_inn": safe_get(zakazchik, 'РукИННФЛ')
        })
    
    # Размещающая организация
    razm_org = data.get('РазмОрг', {})
    razm_org_info = {
        "ogrn": safe_get(razm_org, 'ОГРН'),
        "inn": safe_get(razm_org, 'ИНН'),
        "name_full": safe_get(razm_org, 'НаимПолн'),
        "name_short": safe_get(razm_org, 'НаимСокр'),
        "address": safe_get(razm_org, 'АдресПолн'),
        "head_fio": safe_get(razm_org, 'РукФИО'),
        "head_inn": safe_get(razm_org, 'РукИННФЛ')
    }
    
    # Контакты
    kontakty = data.get('Контакты', {})
    contacts_info = {
        "resp_person": safe_get(kontakty, 'ОтвЛицо'),
        "phone": safe_get(kontakty, 'Телефон'),
        "email": safe_get(kontakty, 'Email')
    }
    
    # Информация о продукте (полная)
    produkt = data.get('Продукт', {})
    product_info = {
        "okpd": safe_get(produkt, 'ОКПД'),
        "name": safe_get(produkt, 'Название'),
        "objects": produkt.get('ОбъектыЗак', [])
    }
    
    # Начальная цена (полная)
    nach_cena = data.get('НачЦена', {})
    price_info = {
        "amount": safe_get(nach_cena, 'Сумма'),
        "currency_code": safe_get(nach_cena, 'ВалютаКод'),
        "currency_name": safe_get(nach_cena, 'ВалютаНаим', 'Российский рубль')
    }
    
    # Обеспечения
    obesp_uchast = data.get('ОбеспУчаст', {})
    obesp_isp = data.get('ОбеспИсп', {})
    obesp_garant = data.get('ОбеспГарант', {})
    
    # ЭТП
    etp = data.get('ЭТП', {})
    etp_info = {
        "code": safe_get(etp, 'Код'),
        "name": safe_get(etp, 'Наименование'),
        "url": safe_get(etp, 'Url')
    }
    
    # Документы (полная информация)
    documents = data.get('Документы', [])
    docs_info = []
    for doc in documents:
        docs_info.append({
            "name": safe_get(doc, 'Название'),
            "date": safe_get(doc, 'ДатаРазм'),
            "edition": safe_get(doc, 'Редакция'),
            "files": doc.get('Файлы', [])
        })
    
    # Протокол
    protokol = data.get('Протокол', {})
    protocol_info = {
        "type": safe_get(protokol, 'Тип'),
        "number": safe_get(protokol, 'Номер'),
        "date": safe_get(protokol, 'Дата'),
        "applications": protokol.get('Заявки', []),
        "additional_info": safe_get(protokol, 'ДопИнфо'),
        "url": safe_get(protokol, 'Url')
    }
    
    # Контракты
    kontrakty = data.get('Контракты', [])
    
    # Статус
    status = data.get('Статус', {})
    status_info = {
        "status": safe_get(status, 'Статус'),
        "reason": safe_get(status, 'Причина'),
        "date": safe_get(status, 'Дата')
    }
    
    # Условия
    usloviya = data.get('Условия', {})
    
    # Форматируем цену для отображения
    if price_info["amount"] and str(price_info["amount"]).replace('.', '').isdigit():
        try:
            price_display = f"{float(price_info['amount']):,.0f} ₽".replace(",", " ")
        except:
            price_display = f"{price_info['amount']} {price_info['currency_name']}"
    else:
        price_display = "Не указано"
    
    # Формируем полную карточку
    tender_info = {
        "id": data.get('РегНомер', '—'),
        "name": product_info["name"],
        "region": region,
        "category": f"ФЗ-{fz}" if fz else "—",
        "price": price_display,
        "deadline": date_okonch,
        "published": date_publ,
        "etp": etp_info["name"],
        "url": etp_info["url"],
        "customer": customer_info[0]["name_full"] if customer_info else "Не указано",
        "status": status_info["status"],
        "source": "damia",
        
        # Дополнительная информация
        "fz": fz,
        "date_start": date_nach,
        "time_start": time_nach,
        "time_end": time_okonch,
        "date_consideration": date_rassm,
        "date_auction": date_aukts,
        "time_auction": time_aukts,
        "customers": customer_info,
        "razm_org": razm_org_info,
        "contacts": contacts_info,
        "product": product_info,
        "price_details": price_info,
        "obesp_uchast": obesp_uchast,
        "obesp_isp": obesp_isp,
        "obesp_garant": obesp_garant,
        "etp_details": etp_info,
        "documents": docs_info,
        "protocol": protocol_info,
        "contracts": kontrakty,
        "status_details": status_info,
        "conditions": usloviya,
        "smp_sono": data.get('СМПиСОНО', False),
        "sposob_razm": safe_get(data, 'СпособРазм'),
        "razm_rol": safe_get(data, 'РазмРоль'),
        "mesto_postav": safe_get(data, 'МестоПостав'),
        "srok_postav": safe_get(data, 'СрокПостав'),
        "avans_procent": data.get('АвансПроцент', 0),
        
        # Сохраняем сырые данные
        "raw_data": data
    }

    # Логируем извлеченную информацию
    logging.info(f"Extracted Damia data: {json.dumps(tender_info, ensure_ascii=False, indent=2)}")
    
    return tender_info

async def fetch_tender_card_and_docs(reg_number, fz=None):
    """
    Получает карточку тендера и список файлов документации по номеру закупки (reg_number) или внутреннему id.
    Возвращает (card, files), где card — словарь с основной инфой, files — список файлов (dict: name, url).
    """
    params = {"dtype": "json", "api_code": TENDER_GURU_API_KEY}
    if reg_number.isdigit() and len(reg_number) > 10:
        params["tend_num"] = reg_number
    else:
        params["id"] = reg_number
    if fz == "fz223":
        params["fz"] = "fz223"
    async with aiohttp.ClientSession() as session:
        async with session.get(TENDERGURU_API_URL, params=params) as resp:
            if resp.status != 200:
                return None, []
            data = await resp.json(content_type=None)
            if isinstance(data, list):
                card = data[0]
            else:
                card = data
            # Сначала ищем DocLink1/2
            files = []
            for key in ["DocLink1", "DocLink2"]:
                if card.get(key):
                    files.append({"name": key, "url": card[key]})
            # Если файлов нет — делаем второй запрос
            if not files:
                params2 = {"mode": "customerTenderDocs", "purchaseNumber": reg_number, "dtype": "json", "api_code": TENDER_GURU_API_KEY}
                if fz == "fz223":
                    params2["fz"] = "fz223"
                async with session.get(TENDERGURU_API_URL, params=params2) as resp2:
                    if resp2.status == 200:
                        docs = await resp2.json(content_type=None)
                        if isinstance(docs, list):
                            for doc in docs:
                                url = doc.get("View") or doc.get("DocPath")
                                if url and not url.startswith("http"):
                                    url = "https://www.tenderguru.ru" + url
                                if url:
                                    files.append({"name": doc.get("Filename", "Документ"), "url": url})
            return card, files

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("analyze", analyze_tender_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, wait_for_link_handler))
    app.run_polling() 