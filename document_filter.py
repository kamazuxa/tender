import os
import zipfile
import logging
import tempfile
import re
from pathlib import Path
from typing import List, Optional
import hashlib
from text_cleaner import preprocess_parsed_text

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    import rarfile
    RAR_SUPPORT = True
except ImportError:
    logger.warning("rarfile не установлен. RAR архивы не будут поддерживаться.")
    RAR_SUPPORT = False

def normalize_filename(filename: str) -> str:
    """
    Нормализует имя файла перед анализом:
    - удаляет расширение
    - заменяет _, - на пробел
    - удаляет повторяющиеся пробелы
    - приводит к нижнему регистру
    
    Args:
        filename: Исходное имя файла
        
    Returns:
        str: Нормализованное имя файла
    """
    name = re.sub(r'\.\w+$', '', filename)  # убираем расширение
    name = name.replace("_", " ").replace("-", " ")
    name = re.sub(r'\s+', ' ', name)  # двойные пробелы → один
    return name.strip().lower()

def is_useful_document(filename: str) -> bool:
    """
    Фильтрация документов по следующим правилам:
    
    🟩 ✅ Включаем, если:
    - имя файла содержит полезные слова (из must_include)
    - имя короткое (менее 25 символов) и не содержит мусора (например, 123.pdf)
    
    🟥 ❌ Исключаем, если:
    - имя содержит мусорные слова (из must_exclude)
    - это Excel-файл (.xls/.xlsx)
    - длинное имя (25+ символов), которое не содержит ни одного ключевого слова
    
    Args:
        filename: Название файла
        
    Returns:
        bool: True если файл подходит для анализа
    """
    ext = Path(filename).suffix.lower()
    if ext in [".xls", ".xlsx"]:
        logger.debug(f"❌ Файл отфильтрован (Excel формат): {filename}")
        return False  # ❌ Excel исключаем

    name = normalize_filename(filename)

    # Ключевые слова, которые ДОЛЖНЫ быть в названии (гарантированно полезные)
    must_include = [
        "тз", "техническое задание", "описание объекта", "описание закупки",
        "ведомость поставки", "спецификация", "размеры", "габариты", 
        "сорт", "состав продукции", "характеристики", "параметры", 
        "гост", "ту", "условия поставки", "требования к товару",
        "потребительские свойства", "качество товара", "декларация соответствия"
    ]

    # Ключевые слова, которые НЕ ДОЛЖНЫ быть в названии (гарантированно бесполезные)
    must_exclude = [
        "контракт", "договор", "проект контракта", "проект договора",
        "инструкция", "требования к заявке", "состав заявки", "оформление заявки",
        "заявка", "заявление", "нмцк", "обоснование", "расчет", 
        "уведомление", "гарантия", "обязательство", "оценка", 
        "методика", "баллы", "контроль", "лист согласования", 
        "форма", "цп", "решение", "протокол", "анкета", 
        "согласие", "образец заполнения", "реквизиты", "регистр",
        "сведения о заказчике", "данные заказчика", "сопроводительное", 
        "участник закупки", "участника", "отчет"
    ]

    # Явный мусор
    if any(skip in name for skip in must_exclude):
        logger.debug(f"❌ Файл отфильтрован (исключающие слова): {filename} (нормализовано: '{name}')")
        return False

    # Явно полезный
    if any(key in name for key in must_include):
        logger.info(f"✅ Файл прошел фильтрацию (полезные слова): {filename} (нормализовано: '{name}')")
        return True

    # Нейтральные имена — короткие числовые файлы типа "123.pdf"
    if len(name) <= 25 and name.replace(" ", "").isalnum():
        logger.info(f"✅ Файл прошел фильтрацию (короткое нейтральное имя): {filename} (нормализовано: '{name}')")
        return True

    # Всё остальное — игнор
    logger.debug(f"❌ Файл отфильтрован (длинное неинформативное имя): {filename} (нормализовано: '{name}')")
    return False

def is_really_useful_by_text(text: str) -> bool:
    """
    Фильтрует файл по содержимому.
    
    Args:
        text: Текст содержимого файла
        
    Returns:
        bool: True если содержимое содержит важную информацию
    """
    text = text.lower()
    
    useful_markers = [
        "наименование товара", "характеристики", "срок поставки", "требования к",
        "техническое задание", "гост", "ту", "упаковка", "сорт", "размер",
        "технические характеристики", "параметры", "спецификация", "описание",
        "качество", "марка", "тип", "модель", "комплектация", "состав"
    ]
    
    result = any(marker in text for marker in useful_markers)
    
    if result:
        logger.info(f"✅ Файл прошел фильтрацию по содержимому")
    else:
        logger.debug(f"❌ Файл отфильтрован по содержимому")
    
    return result

def extract_text_from_file(file_path: str) -> Optional[str]:
    """
    Извлекает текст из файла для анализа содержимого.
    
    Args:
        file_path: Путь к файлу
        
    Returns:
        Optional[str]: Извлеченный текст или None при ошибке
    """
    try:
        file_ext = Path(file_path).suffix.lower()
        
        if file_ext == '.txt':
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        elif file_ext == '.pdf':
            # Для PDF используем PyPDF2 (если установлен)
            try:
                import PyPDF2
                with open(file_path, 'rb') as f:
                    pdf_reader = PyPDF2.PdfReader(f)
                    text = ""
                    for page in pdf_reader.pages:
                        text += page.extract_text() + "\n"
                    return text
            except ImportError:
                logger.warning("PyPDF2 не установлен. PDF файлы не будут анализироваться по содержимому.")
                return None
        elif file_ext == '.docx':
            # Для DOCX используем python-docx (если установлен)
            try:
                import docx
                doc = docx.Document(file_path)
                text = ""
                for paragraph in doc.paragraphs:
                    text += paragraph.text + "\n"
                return text
            except ImportError:
                logger.warning("python-docx не установлен. DOCX файлы не будут анализироваться по содержимому.")
                return None
        else:
            logger.debug(f"Неподдерживаемый формат для извлечения текста: {file_ext}")
            return None
            
    except Exception as e:
        logger.error(f"Ошибка при извлечении текста из {file_path}: {e}")
        return None

def extract_and_filter_archive(archive_path: str, dest_dir: str) -> List[str]:
    """
    Распаковывает .zip или .rar, фильтрует файлы по названию.
    
    Args:
        archive_path: Путь к архиву
        dest_dir: Директория для распаковки
        
    Returns:
        List[str]: Список путей к отфильтрованным файлам
    """
    filtered_files = []
    
    try:
        if archive_path.endswith(".zip"):
            archive = zipfile.ZipFile(archive_path)
            logger.info(f"Распаковываю ZIP архив: {archive_path}")
        elif archive_path.endswith(".rar"):
            if not RAR_SUPPORT:
                logger.error("RAR архивы не поддерживаются. Установите rarfile: pip install rarfile")
                return []
            archive = rarfile.RarFile(archive_path)
            logger.info(f"Распаковываю RAR архив: {archive_path}")
        else:
            logger.warning(f"Неподдерживаемый формат архива: {archive_path}")
            return []
        
        # Распаковываем архив
        archive.extractall(dest_dir)
        
        # Проходим по всем файлам в распакованной директории
        for root, _, files in os.walk(dest_dir):
            for file in files:
                # Очищаем имя файла от символов перевода строки и лишних пробелов
                clean_filename = file.replace('\n', ' ').replace('\r', ' ').strip()
                clean_filename = re.sub(r'\s+', ' ', clean_filename)  # множественные пробелы → один
                
                full_path = os.path.join(root, file)
                clean_full_path = os.path.join(root, clean_filename)
                
                # Переименовываем файл если имя изменилось
                if file != clean_filename:
                    try:
                        os.rename(full_path, clean_full_path)
                        logger.info(f"Переименован файл: '{file}' → '{clean_filename}'")
                        full_path = clean_full_path
                    except Exception as e:
                        logger.warning(f"Не удалось переименовать файл '{file}': {e}")
                
                # Проверяем, прошел ли файл фильтрацию
                if is_useful_document(clean_filename):
                    # Используем Path().as_posix() для корректного пути
                    normalized_path = Path(full_path).as_posix()
                    filtered_files.append(normalized_path)
                    logger.info(f"Найден полезный файл в архиве: {clean_filename}")
                else:
                    logger.debug(f"Файл отфильтрован в архиве: {clean_filename}")
        
        logger.info(f"Из архива {archive_path} отфильтровано {len(filtered_files)} файлов")
        
    except Exception as e:
        logger.error(f"Ошибка при обработке архива {archive_path}: {e}")
    
    return filtered_files

def filter_documents(paths: List[str], check_content: bool = False) -> List[str]:
    """
    Принимает список путей к файлам и архивам, фильтрует, возвращает список файлов для анализа.
    
    Args:
        paths: Список путей к файлам и архивам
        check_content: Проверять ли содержимое файлов (вторичная фильтрация)
        
    Returns:
        List[str]: Список отфильтрованных файлов
    """
    result = []
    temp_dirs_to_cleanup = []  # Список временных папок для очистки
    
    logger.info(f"Начинаю фильтрацию {len(paths)} файлов/архивов")
    
    for path in paths:
        path_obj = Path(path)
        
        if not path_obj.exists():
            logger.warning(f"Файл не найден: {path}")
            continue
            
        if path_obj.suffix.lower() in ['.zip', '.rar']:
            # Обрабатываем архив
            logger.info(f"Обрабатываю архив: {path}")
            
            # Создаем временную папку в download_files/temp_cleaned/ вместо системной
            temp_dir = Path("download_files/temp_cleaned")
            temp_dir.mkdir(parents=True, exist_ok=True)
            
            # Создаем уникальную подпапку для этого архива
            import uuid
            unique_temp_dir = temp_dir / f"extract_{uuid.uuid4().hex[:8]}"
            unique_temp_dir.mkdir(exist_ok=True)
            
            # Добавляем папку в список для очистки
            temp_dirs_to_cleanup.append(unique_temp_dir)
            
            extracted = extract_and_filter_archive(str(path), str(unique_temp_dir))
            result.extend(extracted)
                
        elif is_useful_document(path_obj.name):
            # Обычный файл прошел фильтрацию по названию
            # Используем Path().as_posix() для корректного пути
            normalized_path = path_obj.as_posix()
            result.append(normalized_path)
            
            # Дополнительная проверка по содержимому (если включена)
            if check_content:
                text = extract_text_from_file(normalized_path)
                if text and not is_really_useful_by_text(text):
                    logger.info(f"Файл отфильтрован по содержимому: {path}")
                    result.remove(normalized_path)
        else:
            logger.debug(f"Файл отфильтрован по названию: {path}")
    
    logger.info(f"Фильтрация завершена. Найдено {len(result)} полезных файлов")
    
    # Сохраняем список временных папок для последующей очистки
    if hasattr(filter_documents, '_temp_dirs'):
        filter_documents._temp_dirs.extend(temp_dirs_to_cleanup)
    else:
        filter_documents._temp_dirs = temp_dirs_to_cleanup
    
    return result

def cleanup_temp_dirs():
    """
    Очищает все временные папки, созданные во время фильтрации.
    Вызывается после завершения анализа.
    """
    if hasattr(filter_documents, '_temp_dirs') and filter_documents._temp_dirs:
        import shutil
        for temp_dir in filter_documents._temp_dirs:
            try:
                if temp_dir.exists():
                    shutil.rmtree(temp_dir)
                    logger.debug(f"Временная папка очищена: {temp_dir}")
            except Exception as e:
                logger.warning(f"Не удалось очистить временную папку {temp_dir}: {e}")
        
        # Очищаем список
        filter_documents._temp_dirs = []
        logger.info("Все временные папки очищены")

def filter_documents_with_content_check(paths: List[str]) -> List[str]:
    """
    Удобная функция для фильтрации с проверкой содержимого.
    
    Args:
        paths: Список путей к файлам и архивам
        
    Returns:
        List[str]: Список отфильтрованных файлов
    """
    return filter_documents(paths, check_content=True)

def collect_clean_texts(file_paths: list, tender_number: str) -> dict:
    """
    Полный пайплайн: фильтрация, распаковка, дедупликация, очистка, сбор итогового текста.
    Возвращает структуру {text, length, sources} и логирует все этапы.
    """
    import shutil
    from pathlib import Path
    import os
    import logging

    logger = logging.getLogger(__name__)
    logger.info(f"\n=== СТАРТ ОБРАБОТКИ ТЕНДЕРА {tender_number} ===")

    # 1. Создаем temp_cleaned/{tender_number}
    temp_dir = Path(f"download_files/temp_cleaned/{tender_number}")
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    # 2. Поддерживаемые расширения
    allowed_ext = {'.doc', '.docx', '.pdf', '.txt'}

    # 3. Распаковка архивов и сбор всех файлов
    all_files = []
    archive_files = set()
    for path in file_paths:
        p = Path(path)
        if p.suffix.lower() in ['.zip', '.rar']:
            logger.info(f"Распаковка архива: {p.name}")
            extract_dir = temp_dir / p.stem
            extract_dir.mkdir(exist_ok=True)
            try:
                if p.suffix.lower() == '.zip':
                    with zipfile.ZipFile(str(p), 'r') as zf:
                        zf.extractall(str(extract_dir))
                elif p.suffix.lower() == '.rar':
                    try:
                        import rarfile
                        with rarfile.RarFile(str(p)) as rf:
                            rf.extractall(str(extract_dir))
                    except Exception as e:
                        logger.warning(f"RAR архив не поддержан: {p.name} — {e}")
                        continue
                # Собираем все файлы из архива
                for root, _, files in os.walk(str(extract_dir)):
                    for f in files:
                        full_path = Path(root) / f
                        all_files.append(full_path)
                        archive_files.add(full_path.name)
            except Exception as e:
                logger.warning(f"Ошибка при распаковке {p.name}: {e}")
        else:
            all_files.append(p)

    # 4. Фильтрация по имени и расширению
    filtered = []
    ignored = []
    for f in all_files:
        ext = f.suffix.lower()
        if ext not in allowed_ext:
            logger.info(f"Игнорирован по расширению: {f.name}")
            ignored.append(f)
            continue
        if not is_useful_document(f.name):
            logger.info(f"Игнорирован по фильтру: {f.name}")
            ignored.append(f)
            continue
        filtered.append(f)

    # 5. Дедупликация по имени и содержимому
    seen_names = set()
    seen_hashes = set()
    unique_files = []
    hash_to_file = {}
    name_to_file = {}
    for f in filtered:
        norm_name = normalize_filename(f.name)
        try:
            with open(f, 'rb') as file:
                content = file.read()
                file_hash = hashlib.md5(content).hexdigest()
        except Exception as e:
            logger.warning(f"Не удалось прочитать файл {f}: {e}")
            continue
        # Приоритет: если дублируется, берем из архива
        if file_hash in seen_hashes:
            logger.info(f"Дубликат по содержимому: {f.name}")
            continue
        if norm_name in seen_names:
            logger.info(f"Дубликат по имени: {f.name}")
            continue
        seen_hashes.add(file_hash)
        seen_names.add(norm_name)
        hash_to_file[file_hash] = f
        name_to_file[norm_name] = f
        unique_files.append(f)

    logger.info(f"\nИтого после дедупликации: {len(unique_files)} файлов")
    for f in unique_files:
        logger.info(f"Включен в анализ: {f.name}")

    # 6. Извлечение, очистка и сбор текста
    from document_filter import extract_text_from_file
    sources = []
    texts = []
    cleaning_stats = {
        "underscore_lines_removed": 0,
        "long_numbers_removed": 0,
        "duplicates_removed": 0,
        "key_headers_found": 0
    }
    
    for f in unique_files:
        logger.info(f"\nОбработка файла: {f.name}")
        text = extract_text_from_file(str(f))
        if not text:
            logger.info(f"Пропущен (не удалось извлечь текст): {f.name}")
            continue
        
        before = len(text)
        clean_result = preprocess_parsed_text(text)
        clean_text = clean_result["text"]
        file_stats = clean_result["stats"]
        
        # Суммируем статистику
        for key in cleaning_stats:
            if key in file_stats:
                cleaning_stats[key] += file_stats[key]
        
        after = len(clean_text)
        logger.info(f"Текст очищен: {before} → {after} символов")
        
        # Выводим детальную статистику для файла
        logger.info(f"✅ Файл обработан: {f.name}")
        logger.info(f"• Исходный размер: {before}")
        logger.info(f"• После очистки: {after}")
        logger.info(f"• Удалено строк с '____': {file_stats.get('underscore_lines_removed', 0)}")
        logger.info(f"• Удалено длинных чисел: {file_stats.get('long_numbers_removed', 0)}")
        logger.info(f"• Удалено дубликатов: {file_stats.get('duplicates_removed', 0)}")
        logger.info(f"• Выделено заголовков: {file_stats.get('key_headers_found', 0)}")
        
        if after > 0:
            texts.append(clean_text)
            sources.append({
                "filename": f.name,
                "length": after,
                "original_length": before
            })
            logger.info(f"Добавлен в итоговый текст: {f.name}")
        else:
            logger.info(f"Пропущен (пустой после очистки): {f.name}")

    full_text = "\n\n".join(texts)
    logger.info(f"\n=== Итоговый очищенный текст: {len(full_text)} символов из {len(sources)} файлов ===")
    logger.info(f"Источники: {[s['filename'] for s in sources]}")

    if not sources:
        logger.warning("Не найдено подходящих файлов для обработки")
        return {
            "success": False,
            "text": "",
            "length": 0,
            "sources": [],
            "log": cleaning_stats,
            "error": "Не найдено подходящих файлов для обработки"
        }

    return {
        "success": True,
        "text": full_text,
        "length": len(full_text),
        "sources": sources,
        "log": cleaning_stats
    }

 