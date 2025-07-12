#!/usr/bin/env python3
"""
Модуль для скачивания документов тендера на сервер
"""

import requests
import os
import zipfile
import re
import logging
from typing import List, Dict, Optional, Tuple
from urllib.parse import urlparse, unquote
from config import TENDERGURU_API_KEY

TENDERGURU_API_URL = "https://www.tenderguru.ru/api2.3/export"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TenderDocumentDownloader:
    """
    Класс для скачивания документов тендера
    """
    
    def __init__(self):
        self.download_dir = "download_files"
        self.session = requests.Session()
        # Устанавливаем User-Agent для избежания блокировки
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
        # Создаем папку для скачивания, если её нет
        if not os.path.exists(self.download_dir):
            os.makedirs(self.download_dir)

    def get_tender_subdir(self, tender_number: str) -> str:
        """Возвращает путь к подпапке для тендера"""
        subdir = os.path.join(self.download_dir, tender_number)
        if not os.path.exists(subdir):
            os.makedirs(subdir)
        return subdir

    def get_tender_info(self, tender_number: str) -> Dict:
        """
        Получает информацию о тендере через TenderGuru API
        
        Args:
            tender_number: Номер тендера
            
        Returns:
            Dict: Информация о тендере
        """
        try:
            # Первый запрос - поиск тендера
            params = {
                "kwords": tender_number,
                "api_code": TENDERGURU_API_KEY,
                "dtype": "json"
            }
            
            response = self.session.get(TENDERGURU_API_URL, params=params)
            if response.status_code != 200:
                logger.error(f"Ошибка первого запроса к TenderGuru API: {response.status_code}")
                return None
            
            data = response.json()
            if not data or len(data) < 2:  # Первый элемент - Total, второй - данные тендера
                logger.error("Тендер не найден")
                return None
            
            tender_info = data[1]  # Берем данные тендера
            
            # Второй запрос - детальная информация
            tender_id = tender_info.get('ID')
            if not tender_id:
                logger.error("ID тендера не найден")
                return tender_info
            
            detail_params = {
                "id": tender_id,
                "api_code": TENDERGURU_API_KEY,
                "dtype": "json"
            }
            
            detail_response = self.session.get(TENDERGURU_API_URL, params=detail_params)
            if detail_response.status_code == 200:
                detail_data = detail_response.json()
                if detail_data and len(detail_data) > 0:
                    # Объединяем информацию
                    tender_info.update(detail_data[0])
            
            return tender_info
            
        except Exception as e:
            logger.error(f"Ошибка при получении информации о тендере: {e}")
            return None
    
    def extract_document_links(self, info_html: str) -> List[Dict]:
        """
        Извлекает ссылки на документы из HTML
        
        Args:
            info_html: HTML с информацией о тендере
            
        Returns:
            List[Dict]: Список документов с ссылками и названиями
        """
        documents = []
        
        # Декодируем HTML entities
        import html
        decoded_html = html.unescape(info_html)
        
        # Удаляем CDATA обертку если есть
        if '![CDATA[' in decoded_html:
            decoded_html = decoded_html.replace('![CDATA[', '').replace(']]', '')
        
        # Ищем ссылки на документы в формате zakupki.gov.ru
        pattern = r'href="(https://zakupki\.gov\.ru/44fz/filestore/public/1\.0/download/priz/file\.html\?uid=[^"]+)"[^>]*>([^<]+)</a>'
        matches = re.findall(pattern, decoded_html)
        
        for url, name in matches:
            # Очищаем название от лишних символов
            clean_name = re.sub(r'[<>:"/\\|?*]', '_', name.strip())
            if clean_name:
                documents.append({
                    'url': url,
                    'name': clean_name,
                    'filename': self._generate_filename(clean_name, url)
                })
        
        return documents
    
    def _generate_filename(self, name: str, url: str) -> str:
        """
        Генерирует имя файла на основе названия и URL
        
        Args:
            name: Название документа
            url: URL документа
            
        Returns:
            str: Имя файла
        """
        # Пытаемся извлечь расширение из URL
        parsed_url = urlparse(url)
        path = parsed_url.path
        
        # Определяем расширение по названию или URL
        if '.docx' in name.lower() or '.docx' in path.lower():
            ext = '.docx'
        elif '.doc' in name.lower() or '.doc' in path.lower():
            ext = '.doc'
        elif '.pdf' in name.lower() or '.pdf' in path.lower():
            ext = '.pdf'
        elif '.xlsx' in name.lower() or '.xlsx' in path.lower():
            ext = '.xlsx'
        elif '.xls' in name.lower() or '.xls' in path.lower():
            ext = '.xls'
        elif '.rtf' in name.lower() or '.rtf' in path.lower():
            ext = '.rtf'
        else:
            ext = '.pdf'  # По умолчанию
        
        # Очищаем название и добавляем расширение
        clean_name = re.sub(r'[<>:"/\\|?*]', '_', name.strip())
        return f"{clean_name}{ext}"
    
    def download_document(self, doc: Dict, subdir: str) -> Optional[str]:
        """
        Скачивает один документ в подпапку тендера
        """
        try:
            url = doc['url']
            filename = doc['filename']
            file_path = os.path.join(subdir, filename)
            if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                logger.info(f"Документ уже скачан (кеш): {file_path}")
                return file_path
            logger.info(f"Скачиваю документ: {filename}")
            response = self.session.get(url, stream=True)
            if response.status_code == 200:
                with open(file_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                logger.info(f"Документ скачан: {file_path}")
                return file_path
            else:
                logger.error(f"Ошибка скачивания {filename}: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Ошибка при скачивании документа {doc.get('name', 'unknown')}: {e}")
            return None
    
    def create_zip_archive(self, file_paths: List[str], tender_number: str, subdir: str) -> Optional[str]:
        """
        Создает ZIP архив из скачанных файлов в подпапке тендера
        """
        if not file_paths:
            return None
        archive_name = f"tender_{tender_number}_documents.zip"
        archive_path = os.path.join(subdir, archive_name)
        if os.path.exists(archive_path):
            logger.info(f"Архив уже существует (кеш): {archive_path}")
            return archive_path
        try:
            with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for file_path in file_paths:
                    if os.path.exists(file_path):
                        zipf.write(file_path, os.path.basename(file_path))
            logger.info(f"Создан архив: {archive_path}")
            return archive_path
        except Exception as e:
            logger.error(f"Ошибка при создании архива: {e}")
            return None

    def download_all_documents(self, tender_number: str) -> Tuple[List[str], List[str], Dict, str]:
        """
        Скачивает все документы тендера в подпапку, возвращает путь к подпапке
        """
        try:
            tender_info = self.get_tender_info(tender_number)
            if not tender_info:
                return [], ["Не удалось получить информацию о тендере"], {}, ""
            info_html = tender_info.get('Info', '')
            documents = self.extract_document_links(info_html)
            subdir = self.get_tender_subdir(tender_number)
            if not documents:
                return [], ["Документы не найдены"], tender_info, subdir
            logger.info(f"Найдено документов: {len(documents)}")
            downloaded_files = []
            errors = []
            for doc in documents:
                file_path = self.download_document(doc, subdir)
                if file_path:
                    downloaded_files.append(file_path)
                else:
                    errors.append(f"Не удалось скачать: {doc['name']}")
            return downloaded_files, errors, tender_info, subdir
        except Exception as e:
            logger.error(f"Ошибка при скачивании документов: {e}")
            return [], [f"Общая ошибка: {str(e)}"], {}, ""

    def download_tender_documents(self, tender_number: str) -> Dict:
        """
        Основная функция для скачивания документов тендера с кешированием
        """
        try:
            downloaded_files, errors, tender_info, subdir = self.download_all_documents(tender_number)
            if not downloaded_files:
                return {
                    'success': False,
                    'error': 'Документы не найдены или не удалось скачать',
                    'tender_info': tender_info,
                    'errors': errors
                }
            archive_path = self.create_zip_archive(downloaded_files, tender_number, subdir)
            return {
                'success': True,
                'archive_path': archive_path,
                'file_paths': downloaded_files,
                'tender_info': tender_info,
                'errors': errors,
                'total_files': len(downloaded_files)
            }
        except Exception as e:
            logger.error(f"Ошибка в download_tender_documents: {e}")
            return {
                'success': False,
                'error': str(e),
                'tender_info': {},
                'errors': [str(e)]
            }

# Функция для удобного использования
def download_tender_documents(tender_number: str) -> Dict:
    """
    Удобная функция для скачивания документов тендера
    
    Args:
        tender_number: Номер тендера
        
    Returns:
        Dict: Результат операции
    """
    downloader = TenderDocumentDownloader()
    return downloader.download_tender_documents(tender_number)

if __name__ == "__main__":
    # Тестовая функция
    print("Тест скачивания документов тендера 0372200186425000005")
    result = download_tender_documents("0372200186425000005")
    print(f"Результат: {result}") 