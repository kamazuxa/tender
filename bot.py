import logging
import requests
import os
from aiogram import Bot, Dispatcher, types, executor
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import TELEGRAM_BOT_TOKEN, TENDERGURU_API_KEY, OPENAI_API_KEY
from downloader import download_tender_documents
from analyzer import analyze_tender_documents

TENDERGURU_API_URL = "https://www.tenderguru.ru/api2.3/export"

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher(bot)

# Словарь для хранения информации о тендерах по пользователям
user_tenders = {}

def create_tender_keyboard(tender_number: str) -> InlineKeyboardMarkup:
    """Создает клавиатуру с кнопками для работы с тендером"""
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("📥 Скачать документы", callback_data=f"download_{tender_number}"),
        InlineKeyboardButton("🤖 Анализ документации с помощью ИИ", callback_data=f"analyze_{tender_number}")
    )
    return keyboard

@dp.message_handler(commands=["start", "help"])
async def send_welcome(message: types.Message):
    await message.reply(
        "Привет! Я бот для анализа тендеров через TenderGuru.\n\n"
        "Используй команду /tender <номер> для получения информации о тендере.\n"
        "Например: /tender 0372200186425000005"
    )

@dp.message_handler(commands=["tender"])
async def get_tender_info(message: types.Message):
    args = message.get_args()
    if not args:
        await message.reply("Пожалуйста, укажи номер тендера: /tender <номер>")
        return
    
    tender_number = args.strip()
    user_id = message.from_user.id
    
    # Отправляем сообщение о начале обработки
    processing_msg = await message.reply("🔍 Получаю информацию о тендере...")
    
    try:
        # Получаем информацию о тендере
        params = {
            "kwords": tender_number,
            "api_code": TENDERGURU_API_KEY,
            "dtype": "json"
        }
        
        response = requests.get(TENDERGURU_API_URL, params=params)
        if response.status_code != 200:
            await processing_msg.edit_text(f"❌ Ошибка запроса к TenderGuru API: {response.status_code}")
            return
        
        data = response.json()
        if not data or len(data) < 2:
            await processing_msg.edit_text("❌ Тендер не найден.")
            return
        
        tender_info = data[1]  # Берем данные тендера
        
        # Сохраняем информацию о тендере для пользователя
        user_tenders[user_id] = {
            'tender_number': tender_number,
            'tender_info': tender_info
        }
        
        # Формируем информацию о тендере
        info_text = f"""
📋 **Информация о тендере {tender_number}**

🏷 **Название:** {tender_info.get('TenderName', 'Не указано')}
👤 **Заказчик:** {tender_info.get('Customer', 'Не указано')}
📍 **Регион:** {tender_info.get('Region', 'Не указано')}
💰 **Цена:** {tender_info.get('Price', 'Не указано')} руб.
📅 **Дата окончания:** {tender_info.get('EndTime', 'Не указано')}
🏢 **Площадка:** {tender_info.get('Etp', 'Не указано')}
        """
        
        # Создаем клавиатуру с кнопками
        keyboard = create_tender_keyboard(tender_number)
        
        await processing_msg.edit_text(info_text, reply_markup=keyboard, parse_mode='Markdown')
                    
    except Exception as e:
        await processing_msg.edit_text(f"❌ Ошибка: {e}")

@dp.callback_query_handler(lambda c: c.data.startswith('download_'))
async def download_documents(callback_query: types.CallbackQuery):
    tender_number = callback_query.data.split('_')[1]
    user_id = callback_query.from_user.id
    
    # Проверяем, есть ли информация о тендере у пользователя
    if user_id not in user_tenders or user_tenders[user_id]['tender_number'] != tender_number:
        await callback_query.answer("❌ Информация о тендере не найдена. Запросите тендер заново.")
        return
    
    # Отправляем сообщение о начале скачивания
    processing_msg = await callback_query.message.reply("📥 Скачиваю документы...")
    
    try:
        # Скачиваем документы
        result = download_tender_documents(tender_number)
        
        if result['success']:
            # Отправляем архив пользователю
            with open(result['archive_path'], 'rb') as archive:
                await bot.send_document(
                    chat_id=callback_query.from_user.id,
                    document=archive,
                    caption=f"📦 Документы тендера {tender_number}\n"
                           f"📄 Скачано файлов: {result['total_files']}"
                )
            
            await processing_msg.edit_text("✅ Документы успешно скачаны и отправлены!")
            
            # Сохраняем пути к файлам для анализа
            user_tenders[user_id]['downloaded_files'] = result['file_paths']
            
        else:
            await processing_msg.edit_text(f"❌ Ошибка при скачивании: {result.get('error', 'Неизвестная ошибка')}")
    
    except Exception as e:
        await processing_msg.edit_text(f"❌ Ошибка: {e}")
    
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data.startswith('analyze_'))
async def analyze_documents(callback_query: types.CallbackQuery):
    tender_number = callback_query.data.split('_')[1]
    user_id = callback_query.from_user.id
    
    # Проверяем, есть ли информация о тендере у пользователя
    if user_id not in user_tenders or user_tenders[user_id]['tender_number'] != tender_number:
        await callback_query.answer("❌ Информация о тендере не найдена. Запросите тендер заново.")
        return
    
    # Проверяем, есть ли скачанные файлы
    if 'downloaded_files' not in user_tenders[user_id] or not user_tenders[user_id]['downloaded_files']:
        await callback_query.answer("❌ Сначала скачайте документы тендера.")
        return
    
    # Отправляем сообщение о начале анализа
    processing_msg = await callback_query.message.reply("🤖 Анализирую документы с помощью ИИ...")
    
    try:
        # Анализируем документы
        file_paths = user_tenders[user_id]['downloaded_files']
        tender_info = user_tenders[user_id]['tender_info']
        
        analysis_result = analyze_tender_documents(file_paths, tender_info)
        
        if analysis_result['success']:
            # Отправляем результат анализа
            analysis_text = analysis_result['analysis']
            
            # Разбиваем длинный текст на части, если нужно
            if len(analysis_text) > 4096:
                parts = [analysis_text[i:i+4096] for i in range(0, len(analysis_text), 4096)]
                for i, part in enumerate(parts):
                    if i == 0:
                        await processing_msg.edit_text(f"📊 **Анализ тендера {tender_number}** (часть {i+1}/{len(parts)})\n\n{part}", parse_mode='Markdown')
                    else:
                        await bot.send_message(
                            chat_id=callback_query.from_user.id,
                            text=f"📊 **Анализ тендера {tender_number}** (часть {i+1}/{len(parts)})\n\n{part}",
                            parse_mode='Markdown'
                        )
            else:
                await processing_msg.edit_text(f"📊 **Анализ тендера {tender_number}**\n\n{analysis_text}", parse_mode='Markdown')
            
        else:
            await processing_msg.edit_text(f"❌ Ошибка при анализе: {analysis_result.get('error', 'Неизвестная ошибка')}")
    
    except Exception as e:
        await processing_msg.edit_text(f"❌ Ошибка: {e}")
    
    await callback_query.answer()

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True) 