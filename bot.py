import logging
from config import TELEGRAM_BOT_TOKEN, TENDER_GURU_API_KEY
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import re
from urllib.parse import urlparse, parse_qs
import aiohttp
import os
import tempfile
import shutil

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

TENDERGURU_API_URL = "https://www.tenderguru.ru/api2.3/export"

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
            logging.info(f"Requesting platforms: {params}")
            async with session.get(TENDERGURU_API_URL, params=params) as resp:
                logging.info(f"Response status: {resp.status}")
                if resp.status == 200:
                    data = await resp.json(content_type=None)
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
    await update.message.reply_text("Привет! Я TenderBot. Введите /help для справки.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        logging.info(f"Requesting tender by number: {params}")
        async with aiohttp.ClientSession() as session:
            async with session.get(TENDERGURU_API_URL, params=params) as resp:
                logging.info(f"Tender API response status: {resp.status}")
                if resp.status == 200:
                    data = await resp.json(content_type=None)
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
    keyboard = [[InlineKeyboardButton("Отправить ссылку на тендер", callback_data="wait_for_link")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Отправь ссылку на тендер с любой площадки:\n"
        "✅ zakupki.gov.ru\n"
        "✅ sberbank-ast.ru\n"
        "✅ b2b-center.ru\n"
        "✅ roseltorg.ru\n"
        "✅ torgi.gov.ru\n"
        "✅ zakazrf.ru\n"
        "✅ и др.",
        reply_markup=reply_markup
    )

async def get_tender_documents(api_tender_info_url):
    docs = []
    async with aiohttp.ClientSession() as session:
        async with session.get(api_tender_info_url) as resp:
            if resp.status == 200:
                data = await resp.json(content_type=None)
                for key in ['files', 'attachments', 'docs', 'documents', 'download_links', 'documentation']:
                    if key in data and isinstance(data[key], list):
                        docs.extend(data[key])
    return docs

async def wait_for_link_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if message and message.text:
        url = message.text.strip()
        reg_number, platform = await extract_tender_info_from_url(url)
        if not reg_number:
            await message.reply_text(
                "❗ Не удалось определить номер тендера из ссылки.\n"
                "Проверьте корректность ссылки или попробуйте другую площадку."
            )
            return
        if not platform:
            await message.reply_text(
                "❗ Не удалось определить площадку по ссылке.\n"
                "Проверьте корректность ссылки или попробуйте другую площадку."
            )
            return
        data = await TenderGuruAPI.get_tender_by_number(reg_number)
        if data:
            api_tender_info_url = None
            # Пытаемся найти ссылку на подробный JSON
            if hasattr(data, 'get'):
                api_tender_info_url = data.get('ApiTenderInfo')
            if not api_tender_info_url:
                # Иногда это поле может быть в item
                api_tender_info_url = None
                # (оставляем None, если не найдено)
            keyboard = [
                [InlineKeyboardButton("🧠 Анализ документации", callback_data=f"analyze_docs_{reg_number}")],
                [InlineKeyboardButton("📎 Документы", callback_data=f"show_docs_{reg_number}")],
                [InlineKeyboardButton("📥 Скачать документацию", callback_data=f"download_docs_{reg_number}")],
                [InlineKeyboardButton("📊 Похожие закупки", callback_data="similar_tenders")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            text = (
                f"📄 Тендер №{data['reg_number']}\n\n"
                f"🏛️ Заказчик: {data['customer_name']}\n"
                f"📝 Предмет: {data['purchase_subject']}\n"
                f"💰 НМЦК: {data['price']}\n"
                f"📅 Дедлайн: {data['deadline']}\n"
                f"📍 Место поставки: {data['location']}\n"
                f"🌐 Площадка: {platform}"
            )
            # Сохраняем ссылку на подробный JSON в context.user_data
            if api_tender_info_url:
                context.user_data[f'api_tender_info_url_{reg_number}'] = api_tender_info_url
            await message.reply_text(text, reply_markup=reply_markup)
        else:
            await message.reply_text(
                "❗ Не удалось найти тендер по номеру.\n"
                "Возможно, он отсутствует в базе TenderGuru или ссылка некорректна."
            )
    else:
        if message:
            await message.reply_text(
                "❗ Пожалуйста, отправьте ссылку на тендер текстом."
            )

async def download_all_files(reg_number):
    """
    Получает список файлов по reg_number через TenderGuruAPI, скачивает их, архивирует в .zip и возвращает путь к архиву.
    """
    params = {
        "regNumber": reg_number,
        "dtype": "json",
        "api_code": TENDER_GURU_API_KEY
    }
    logging.info(f"Requesting files for tender: {params}")
    async with aiohttp.ClientSession() as session:
        async with session.get(TENDERGURU_API_URL, params=params) as resp:
            logging.info(f"Files API response status: {resp.status}")
            if resp.status == 200:
                data = await resp.json(content_type=None)
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
    query = update.callback_query
    if query:
        await query.answer()
        data = getattr(query, 'data', None)
        if data:
            if data.startswith("analyze_docs_"):
                await query.edit_message_text("🧠 Анализ документации (будет реализовано)")
            elif data.startswith("show_docs_"):
                reg_number = data.split('_')[-1]
                api_tender_info_url = context.user_data.get(f'api_tender_info_url_{reg_number}')
                if not api_tender_info_url:
                    await query.edit_message_text("❗ Не удалось найти ссылку на подробную информацию о тендере.")
                    return
                docs = await get_tender_documents(api_tender_info_url)
                buttons = []
                for doc in docs:
                    url = doc.get('url') or doc.get('Url')
                    name = doc.get('name') or doc.get('Name') or url
                    if url and name:
                        buttons.append([InlineKeyboardButton(text=name, url=url)])
                if buttons:
                    reply_markup = InlineKeyboardMarkup(buttons)
                    await query.edit_message_text("📎 Документы по тендеру:", reply_markup=reply_markup)
                else:
                    await query.edit_message_text("Документация по тендеру не найдена.")
            elif data.startswith("download_docs_"):
                reg_number = data.split('_')[-1]
                await query.edit_message_text("⏳ Скачиваем документацию...")
                archive_path = await download_all_files(reg_number)
                chat_id = query.message.chat_id if query.message else None
                if archive_path and chat_id:
                    try:
                        await context.bot.send_document(chat_id=chat_id, document=open(archive_path, "rb"), filename=f"tender_{reg_number}_docs.zip")
                        logging.info(f"Sent archive {archive_path} to chat {chat_id}")
                    except Exception as e:
                        logging.error(f"Error sending archive to chat {chat_id}: {e}")
                    os.remove(archive_path)
                else:
                    if chat_id:
                        await context.bot.send_message(chat_id=chat_id, text="Документация не найдена или не удалось скачать файлы.")
                    logging.warning(f"Документация не найдена или не удалось скачать файлы для {reg_number}")
            elif data == "similar_tenders":
                await query.edit_message_text("📊 Похожие закупки (будет реализовано позже)")
            elif data == "wait_for_link":
                await query.edit_message_text("Отправьте ссылку на тендер сообщением.")

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("analyze", analyze_tender_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, wait_for_link_handler))
    app.run_polling() 