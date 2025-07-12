#!/usr/bin/env python3
"""
Тестовый скрипт для проверки получения документов тендера
"""

import asyncio
import aiohttp
import json
from config import TENDER_GURU_API_KEY

async def test_get_documents():
    """Тестирует получение документов тендера"""
    
    # URL для получения документов (из логов)
    api_tender_info_url = "https://www.tenderguru.ru/api2.3/export?id=87490003&api_code=&dtype=json"
    
    print(f"🔍 Тестируем получение документов...")
    print(f"📡 URL: {api_tender_info_url}")
    
    async with aiohttp.ClientSession() as session:
        async with session.get(api_tender_info_url) as resp:
            print(f"📊 Status: {resp.status}")
            
            if resp.status == 200:
                data = await resp.json(content_type=None)
                print(f"📄 Response keys: {list(data[0].keys()) if data and isinstance(data, list) else 'No data'}")
                
                # Ищем документы
                docs = []
                if isinstance(data, list) and len(data) > 0:
                    item = data[0]
                    
                    # Проверяем ограничения
                    if item.get('TenderLinkEtp', '').startswith('Только для подписчиков'):
                        print("🔒 Документы ограничены для платных подписчиков")
                        print(f"💡 TenderLinkEtp: {item.get('TenderLinkEtp')}")
                        print(f"💡 EisLink: {item.get('EisLink')}")
                        print(f"💡 Info: {item.get('Info')}")
                    
                    # Ищем документы в разных ключах
                    for key in ['files', 'attachments', 'docs', 'documents', 'download_links', 'documentation', 'Files', 'Documents', 'docsXML', 'productsXML']:
                        if key in item and isinstance(item[key], list):
                            docs.extend(item[key])
                            print(f"📁 Найдено {len(item[key])} документов в ключе '{key}'")
                
                print(f"📋 Всего документов найдено: {len(docs)}")
                
                if docs:
                    for i, doc in enumerate(docs):
                        print(f"📄 Документ {i+1}: {doc}")
                else:
                    print("❌ Документы не найдены")
                    
            else:
                print(f"❌ Ошибка: {resp.status}")

if __name__ == "__main__":
    asyncio.run(test_get_documents())