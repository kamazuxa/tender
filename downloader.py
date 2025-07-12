#!/usr/bin/env python3
"""
Модуль для скачивания документов тендера на сервер
"""

import asyncio
import aiohttp
import os
import tempfile
import shutil
import json
import logging
import re
from typing import List, Dict, Optional, Tuple

# Настраиваем логирование
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

class TenderDocumentDownloader:
    """
    Класс для скачивания документов тендера
    """
    
    def __init__(self):
        self.session = None
        self.temp_dir = None
    
    async def __aenter__(self):
        """Асинхронный контекстный менеджер - вход"""
        self.session = aiohttp.ClientSession()
        self.temp_dir = tempfile.mkdtemp()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Асинхронный контекстный менеджер - выход"""
        if self.session:
            await self.session.close()
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def extract_documents_from_tender_data(self, tender_data) -> List[Dict]:
        """
        Извлекает документы из данных тендера
        
        Args:
            tender_data: Данные тендера (список или словарь)
            
        Returns:
            List[Dict]: Список документов с полями url, name, size
        """
        docs = []
        
        if isinstance(tender_data, list) and len(tender_data) > 0:
            # Берем первый элемент (пропускаем Total)
            item = tender_data[0]
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
        
        return docs
    
    def clean_filename(self, filename: str) -> str:
        """
        Очищает имя файла от HTML тегов и недопустимых символов
        
        Args:
            filename: Исходное имя файла
            
        Returns:
            str: Очищенное имя файла
        """
        # Удаляем HTML теги
        clean_name = re.sub(r'<[^>]+>', '', filename)
        # Заменяем недопустимые символы на подчеркивание
        clean_name = re.sub(r'[<>:"/\\|?*]', '_', clean_name)
        # Убираем лишние пробелы
        clean_name = clean_name.strip()
        # Если имя пустое, возвращаем дефолтное
        if not clean_name:
            clean_name = "document.pdf"
        return clean_name
    
    async def download_document(self, doc: Dict) -> Optional[str]:
        """
        Скачивает один документ
        
        Args:
            doc: Словарь с информацией о документе (url, name, size)
            
        Returns:
            Optional[str]: Путь к скачанному файлу или None при ошибке
        """
        url = doc.get('url') or doc.get('link')
        name = doc.get('name', 'document.pdf')
        
        if not url:
            logging.error("No URL provided for document")
            return None
        
        # Очищаем имя файла
        clean_name = self.clean_filename(name)
        file_path = os.path.join(self.temp_dir, clean_name)
        
        try:
            logging.info(f"Downloading document: {url}")
            async with self.session.get(url) as resp:
                if resp.status == 200:
                    content = await resp.read()
                    with open(file_path, "wb") as f:
                        f.write(content)
                    logging.info(f"Successfully downloaded: {clean_name} ({len(content)} bytes)")
                    return file_path
                else:
                    logging.error(f"Failed to download document: {url}, status: {resp.status}")
                    return None
        except Exception as e:
            logging.error(f"Exception while downloading document {url}: {e}")
            return None
    
    async def download_all_documents(self, tender_data) -> Tuple[List[str], List[str]]:
        """
        Скачивает все документы тендера
        
        Args:
            tender_data: Данные тендера
            
        Returns:
            Tuple[List[str], List[str]]: (список путей к успешно скачанным файлам, список ошибок)
        """
        docs = self.extract_documents_from_tender_data(tender_data)
        
        if not docs:
            return [], ["Документы не найдены в данных тендера"]
        
        logging.info(f"Found {len(docs)} documents to download")
        
        # Скачиваем документы параллельно
        download_tasks = [self.download_document(doc) for doc in docs]
        results = await asyncio.gather(*download_tasks, return_exceptions=True)
        
        successful_downloads = []
        errors = []
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                errors.append(f"Ошибка скачивания документа {i+1}: {result}")
            elif result is not None:
                successful_downloads.append(result)
            else:
                errors.append(f"Не удалось скачать документ {i+1}")
        
        return successful_downloads, errors
    
    def create_archive(self, file_paths: List[str], tender_id: str) -> Optional[str]:
        """
        Создает ZIP архив из скачанных файлов
        
        Args:
            file_paths: Список путей к файлам
            tender_id: ID тендера для имени архива
            
        Returns:
            Optional[str]: Путь к созданному архиву или None при ошибке
        """
        if not file_paths:
            return None
        
        try:
            # Создаем архив в той же временной директории
            archive_path = shutil.make_archive(
                os.path.join(self.temp_dir, f"tender_{tender_id}_docs"), 
                'zip', 
                self.temp_dir
            )
            logging.info(f"Created archive: {archive_path}")
            return archive_path
        except Exception as e:
            logging.error(f"Error creating archive: {e}")
            return None
    
    async def download_tender_documents(self, tender_data, tender_id: str) -> Dict:
        """
        Основной метод для скачивания документов тендера
        
        Args:
            tender_data: Данные тендера
            tender_id: ID тендера
            
        Returns:
            Dict: Результат операции с полями:
                - success: bool - успешность операции
                - archive_path: Optional[str] - путь к архиву
                - file_paths: List[str] - пути к отдельным файлам
                - errors: List[str] - список ошибок
                - total_files: int - общее количество файлов
                - downloaded_files: int - количество скачанных файлов
        """
        try:
            # Скачиваем все документы
            file_paths, errors = await self.download_all_documents(tender_data)
            
            if not file_paths:
                return {
                    'success': False,
                    'archive_path': None,
                    'file_paths': [],
                    'errors': errors,
                    'total_files': 0,
                    'downloaded_files': 0
                }
            
            # Создаем архив
            archive_path = self.create_archive(file_paths, tender_id)
            
            return {
                'success': True,
                'archive_path': archive_path,
                'file_paths': file_paths,
                'errors': errors,
                'total_files': len(self.extract_documents_from_tender_data(tender_data)),
                'downloaded_files': len(file_paths)
            }
            
        except Exception as e:
            logging.error(f"Error in download_tender_documents: {e}")
            return {
                'success': False,
                'archive_path': None,
                'file_paths': [],
                'errors': [f"Общая ошибка: {e}"],
                'total_files': 0,
                'downloaded_files': 0
            }

# Функция для удобного использования
async def download_tender_documents(tender_data, tender_id: str) -> Dict:
    """
    Удобная функция для скачивания документов тендера
    
    Args:
        tender_data: Данные тендера
        tender_id: ID тендера
        
    Returns:
        Dict: Результат операции
    """
    async with TenderDocumentDownloader() as downloader:
        return await downloader.download_tender_documents(tender_data, tender_id)

# Пример использования
if __name__ == "__main__":
    async def test_downloader():
        """Тестовая функция"""
        # Пример данных тендера (замените на реальные)
        test_tender_data = [
            {
                "docsXML": {
                    "document": [
                        {
                            "link": "http://example.com/test.pdf",
                            "name": "test.pdf"
                        }
                    ]
                }
            }
        ]
        
        result = await download_tender_documents(test_tender_data, "test_123")
        print(f"Result: {json.dumps(result, indent=2, ensure_ascii=False)}")
    
    asyncio.run(test_downloader()) 