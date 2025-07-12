#!/usr/bin/env python3
"""
Модуль для очистки текста от бюрократической воды и мусорных блоков.
Удаляет юридические, процедурные и неинформативные фрагменты,
оставляя только полезную техническую информацию.
"""

import re
import logging
from difflib import SequenceMatcher
from typing import List, Tuple

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def clean_text_blocks(raw_text: str) -> str:
    """
    Удаляет строки и абзацы, содержащие "мусор" — юридические, 
    процедурные и неинформативные фрагменты.
    
    Args:
        raw_text: Исходный текст из документа
        
    Returns:
        str: Очищенный текст без мусорных блоков
    """
    # Паттерны для удаления бюрократической воды
    USELESS_PATTERNS = [
        # Участники и заявки
        "участник закупки", "оформление заявки", "подача заявки", 
        "сведения о заказчике", "данные заказчика", "информация о заказчике",
        "участника закупки", "участников закупки", "заявка на участие",
        
        # Контрактные обязательства
        "контракт вступает в силу", "права и обязанности сторон", 
        "порядок расчетов", "оплата осуществляется", "срок оплаты",
        "гарантийное обязательство", "ответственность сторон", 
        "реквизиты сторон", "расторжение контракта", "форс-мажор",
        "конфиденциальность", "порядок приемки", "акт выполненных работ",
        
        # Юридические формулировки
        "в соответствии со статьей", "на основании приказа", 
        "в случае", "при нарушении", "в установленном порядке",
        "согласно требованиям", "в порядке", "в соответствии с",
        "настоящий контракт", "настоящий договор", "стороны договорились",
        
        # Процедурные моменты
        "порядок подачи", "срок подачи", "место подачи", "способ подачи",
        "требования к оформлению", "состав заявки", "форма заявки",
        "критерии оценки", "методика оценки", "баллы", "оценка заявок",
        
        # Общие бюрократические фразы
        "приложение к контракту", "приложение к договору", 
        "неотъемлемая часть", "является неотъемлемой частью",
        "вступает в силу", "действует до", "действует с",
        "утверждено", "согласовано", "одобрено", "принято",
        
        # Приложения
        "приложение", "приложения",
        
        # Служебная информация
        "лист согласования", "виза", "подпись", "дата", "номер",
        "регистрационный номер", "инвентарный номер", "код",
        "форма", "бланк", "шаблон", "образец", "реквизиты",
        
        # Неинформативные блоки
        "дополнительная информация", "примечания", "примечание",
        "особые условия", "дополнительные условия", "иные условия",
        "прочие условия", "прочее", "другое", "иное"
    ]
    
    # Дополнительные паттерны для удаления
    USELESS_REGEX_PATTERNS = [
        r'^\s*№\s*\d+.*$',  # Номера документов
        r'^\s*\d+\.\s*$',   # Нумерованные пункты без содержания
        r'^\s*[а-я]\.\s*$', # Буквенные пункты без содержания
        r'^\s*-\s*$',       # Пустые пункты с дефисом
        r'^\s*\.\s*$',      # Точки
        r'^\s*,\s*$',       # Запятые
        r'^\s*;\s*$',       # Точки с запятой
    ]
    
    lines = raw_text.splitlines()
    result = []
    removed_count = 0
    
    for line in lines:
        original_line = line
        line = line.strip()
        
        # Пропускаем пустые строки
        if not line:
            continue
            
        # Проверяем на мусорные паттерны
        text_lower = line.lower()
        is_useless = False
        
        # Проверяем точные совпадения
        for pattern in USELESS_PATTERNS:
            if pattern in text_lower:
                is_useless = True
                break
        
        # Проверяем регулярные выражения
        if not is_useless:
            for regex_pattern in USELESS_REGEX_PATTERNS:
                if re.match(regex_pattern, line, re.IGNORECASE):
                    is_useless = True
                    break
        
        # Проверяем на слишком короткие строки (менее 10 символов)
        if len(line) < 10 and not any(char.isdigit() for char in line):
            is_useless = True
        
        if is_useless:
            removed_count += 1
            logger.debug(f"Удалена строка: {original_line[:50]}...")
            continue
        
        result.append(original_line)
    
    cleaned_text = "\n".join(result)
    
    logger.info(f"Очистка завершена. Удалено {removed_count} строк из {len(lines)}")
    logger.info(f"Размер текста: {len(raw_text)} → {len(cleaned_text)} символов")
    
    return cleaned_text

def truncate_text(text: str, max_chars: int = 15000) -> str:
    """
    Обрезает очищенный текст до заданного количества символов.
    
    Args:
        text: Текст для обрезки
        max_chars: Максимальное количество символов (по умолчанию 15000)
        
    Returns:
        str: Обрезанный текст
    """
    if len(text) <= max_chars:
        return text
    
    # Обрезаем до max_chars символов
    truncated = text[:max_chars]
    
    # Пытаемся обрезать по границе слова
    last_space = truncated.rfind(' ')
    if last_space > max_chars * 0.9:  # Если последнее слово не слишком далеко
        truncated = truncated[:last_space]
    
    logger.info(f"Текст обрезан: {len(text)} → {len(truncated)} символов")
    
    return truncated

def preprocess_parsed_text(text: str, max_chars: int = 15000, use_advanced_cleaning: bool = True) -> dict:
    """
    Полный пайплайн: очистка + обрезка.
    
    Args:
        text: Исходный текст из документа
        max_chars: Максимальное количество символов (по умолчанию 15000)
        use_advanced_cleaning: Использовать углублённую очистку (по умолчанию True)
        
    Returns:
        dict: Словарь с очищенным текстом и статистикой очистки
    """
    logger.info(f"Начинаю предобработку текста размером {len(text)} символов")
    
    if use_advanced_cleaning:
        # Используем углублённую очистку и структурирование
        clean_result = clean_and_structure_text(text)
        logger.info("Применена углублённая очистка и структурирование")
        final_text = clean_result["text"]
        stats = clean_result["stats"]
    else:
        # Используем базовую очистку
        final_text = clean_text_blocks(text)
        stats = get_cleaning_stats(text, final_text)
        logger.info("Применена базовая очистка")
    
    # Обрезаем до нужной длины
    result = truncate_text(final_text, max_chars)
    
    # Обновляем статистику
    stats["final_length"] = len(result)
    stats["truncated"] = len(final_text) != len(result)
    
    logger.info(f"Предобработка завершена. Итоговый размер: {len(result)} символов")
    
    return {
        "text": result,
        "stats": stats
    }

def extract_technical_info(text: str) -> str:
    """
    Дополнительная функция для извлечения только технической информации.
    
    Args:
        text: Очищенный текст
        
    Returns:
        str: Текст с технической информацией
    """
    # Ключевые слова для технической информации
    TECHNICAL_KEYWORDS = [
        "технические характеристики", "характеристики", "параметры", 
        "размеры", "габариты", "вес", "масса", "объем", "количество",
        "гост", "ту", "стандарт", "требования к", "качество", "сорт",
        "марка", "тип", "модель", "наименование", "название товара",
        "упаковка", "тара", "срок поставки", "сроки", "место поставки",
        "условия поставки", "комплектация", "состав", "материал",
        "цвет", "размер", "длина", "ширина", "высота", "диаметр"
    ]
    
    lines = text.splitlines()
    result = []
    
    for line in lines:
        line_lower = line.lower()
        # Проверяем, содержит ли строка технические ключевые слова
        if any(keyword in line_lower for keyword in TECHNICAL_KEYWORDS):
            result.append(line)
    
    return "\n".join(result)

def clean_and_structure_text(text: str) -> dict:
    """
    Очищает, удаляет дубли, форматирует ключевые блоки тендерной документации
    
    Args:
        text: Исходный текст тендерной документации
        
    Returns:
        dict: Словарь с очищенным текстом и статистикой очистки
    """
    if not text:
        return {
            "text": "",
            "stats": {
                "underscore_lines_removed": 0,
                "long_numbers_removed": 0,
                "duplicates_removed": 0,
                "key_headers_found": 0,
                "original_length": 0,
                "cleaned_length": 0
            }
        }
    
    logging.info("Начинаем углублённую очистку и структурирование текста")
    
    # Инициализируем статистику
    stats = {
        "underscore_lines_removed": 0,
        "long_numbers_removed": 0,
        "duplicates_removed": 0,
        "key_headers_found": 0,
        "original_length": len(text),
        "cleaned_length": 0
    }
    
    # Разбиваем на строки
    lines = text.split('\n')
    original_line_count = len(lines)
    logging.info(f"Исходное количество строк: {original_line_count}")
    
    # 1. Удаление технического мусора
    cleaned_lines = []
    for line in lines:
        # Пропускаем строки только с подчёркиваниями и специальными символами
        if re.match(r'^\s*[«"»№@_\-\s\.]+$', line):
            stats["underscore_lines_removed"] += 1
            logging.debug(f"Удалена строка с специальными символами: {line[:50]}...")
            continue
            
        # Пропускаем строки с шаблонами типа "_____________ «____» ______________"
        if re.match(r'^\s*[_\-\s]+[«"»№@\s]+[_\-\s]+$', line):
            stats["underscore_lines_removed"] += 1
            logging.debug(f"Удалена строка с шаблонными символами: {line[:50]}...")
            continue
            
        # Пропускаем строки только с подчёркиваниями
        if re.match(r'^\s*[«"]?_+["»]?\s*$', line):
            stats["underscore_lines_removed"] += 1
            logging.debug(f"Удалена строка с подчёркиваниями: {line[:50]}...")
            continue
            
        # Пропускаем шаблонные пустые даты/подписи
        if re.match(r'^\s*[«"]?\s*_{2,}\s+[_.]+$', line):
            stats["underscore_lines_removed"] += 1
            logging.debug(f"Удалена строка с пустыми датами: {line[:50]}...")
            continue
            
        # Пропускаем строки только с точками и подчёркиваниями
        if re.match(r'^\s*[._]+\s*$', line):
            stats["underscore_lines_removed"] += 1
            logging.debug(f"Удалена строка с точками/подчёркиваниями: {line[:50]}...")
            continue
            
        # Пропускаем строки с ИКЗ (длинные цифровые коды)
        if re.match(r'^\s*ИКЗ\s*:\s*\d{15,}\s*$', line):
            stats["long_numbers_removed"] += 1
            logging.debug(f"Удалена строка с ИКЗ: {line[:50]}...")
            continue
            
        # Пропускаем пустые строки с техническими символами
        if re.match(r'^\s*[«"»\s_\.]+\s*$', line):
            stats["underscore_lines_removed"] += 1
            logging.debug(f"Удалена строка с техническими символами: {line[:50]}...")
            continue
            
        # Пропускаем строки, содержащие только "Приложение" или "Приложения"
        if re.match(r'^\s*(Приложение|Приложения)\s*$', line, re.IGNORECASE):
            stats["underscore_lines_removed"] += 1
            logging.debug(f"Удалена строка с 'Приложение': {line[:50]}...")
            continue
            
        # Пропускаем строки, начинающиеся с "Приложение №" и содержащие только технические символы
        if re.match(r'^\s*Приложение\s*№\s*\d*\s*[«"»№@_\-\s\.]*$', line, re.IGNORECASE):
            stats["underscore_lines_removed"] += 1
            logging.debug(f"Удалена строка с 'Приложение №': {line[:50]}...")
            continue
            
        cleaned_lines.append(line)
    
    logging.info(f"После удаления технического мусора: {len(cleaned_lines)} строк")
    logging.info(f"Удалено строк с подчёркиваниями: {stats['underscore_lines_removed']}")
    
    # 2. Удаление длинных цифровых ID
    text_without_ids = '\n'.join(cleaned_lines)
    # Подсчитываем количество удаленных длинных чисел
    long_numbers = re.findall(r'\b\d{15,}\b', text_without_ids)
    stats["long_numbers_removed"] += len(long_numbers)
    
    # Удаляем длинные числа
    text_without_ids = re.sub(r'\b\d{15,}\b', '', text_without_ids)
    cleaned_lines = text_without_ids.split('\n')
    
    logging.info(f"Удалено длинных цифровых ID (15+ цифр): {len(long_numbers)}")
    
    # Определяем паттерны для ключевых блоков (используются в нескольких местах)
    key_patterns = [
        (r'требования.*качеств', '**Требования к качеству товара**'),
        (r'гарантийный\s+срок', '**Гарантийный срок**'),
        (r'требования.*упаковк', '**Требования к упаковке**'),
        (r'срок\s+поставк', '**Срок поставки**'),
        (r'место\s+поставк', '**Место поставки**'),
        (r'поставляемый\s+товар', '**Поставляемый товар**'),
        (r'товар\s+должен', '**Требования к товару**'),
        (r'технические\s+характеристик', '**Технические характеристики**'),
        (r'условия\s+поставк', '**Условия поставки**'),
        (r'условия\s+оплат', '**Условия оплаты**'),
        (r'ответственность', '**Ответственность сторон**'),
        (r'форс-мажор', '**Форс-мажор**'),
        (r'расторжение\s+контракт', '**Расторжение контракта**'),
        (r'приёмка\s+товар', '**Приёмка товара**'),
        (r'документация', '**Документация**'),
        (r'энергетическая\s+эффективность', '**Энергетическая эффективность**'),
    ]
    
    # 3. Удаление почти дублирующихся блоков
    deduplicated_lines = []
    for i, line in enumerate(cleaned_lines):
        if not line.strip():  # Пропускаем пустые строки
            deduplicated_lines.append(line)
            continue
            
        is_duplicate = False
        # Сравниваем с предыдущими строками
        for j in range(max(0, i-10), i):  # Проверяем последние 10 строк
            if j < len(deduplicated_lines) and deduplicated_lines[j].strip():
                similarity = SequenceMatcher(None, line.strip(), deduplicated_lines[j].strip()).ratio()
                if similarity > 0.85:
                    is_duplicate = True
                    stats["duplicates_removed"] += 1
                    logging.debug(f"Найден дубликат (схожесть {similarity:.2f}): '{line[:50]}...'")
                    break
        
        # Дополнительная проверка на дублирование заголовков
        if not is_duplicate and line.strip():
            line_lower = line.lower().strip()
            # Проверяем, не является ли это дублирующимся заголовком
            for prev_line in deduplicated_lines[-5:]:  # Проверяем последние 5 строк
                if prev_line.strip():
                    prev_lower = prev_line.lower().strip()
                    # Если обе строки содержат ключевые слова заголовков
                    if any(re.search(pattern, line_lower) for pattern, _ in key_patterns) and \
                       any(re.search(pattern, prev_lower) for pattern, _ in key_patterns):
                        # Проверяем схожесть
                        if SequenceMatcher(None, line_lower, prev_lower).ratio() > 0.7:
                            is_duplicate = True
                            stats["duplicates_removed"] += 1
                            logging.debug(f"Найден дублирующийся заголовок: '{line[:50]}...'")
                            break
        
        if not is_duplicate:
            deduplicated_lines.append(line)
    
    logging.info(f"После удаления дубликатов: {len(deduplicated_lines)} строк")
    logging.info(f"Удалено дубликатов: {stats['duplicates_removed']}")
    
    # 4. Выделение ключевых блоков
    structured_lines = []
    
    # Отслеживаем уже добавленные заголовки
    added_headers = set()
    
    for line in deduplicated_lines:
        line_lower = line.lower().strip()
        
        # Проверяем, является ли строка заголовком ключевого блока
        is_key_header = False
        for pattern, header in key_patterns:
            if re.search(pattern, line_lower):
                # Проверяем, не добавляли ли мы уже этот заголовок
                if header not in added_headers:
                    structured_lines.append('')  # Пустая строка перед заголовком
                    structured_lines.append(header)
                    added_headers.add(header)
                    stats["key_headers_found"] += 1
                    is_key_header = True
                    logging.debug(f"Выделен ключевой блок: {header}")
                    break
                else:
                    # Если заголовок уже был, просто добавляем содержимое
                    is_key_header = True
                    break
        
        if not is_key_header:
            # Если это не заголовок, но содержит ключевые слова, добавляем маркер
            if any(re.search(pattern, line_lower) for pattern, _ in key_patterns):
                if line.strip() and not line.strip().startswith('**'):
                    structured_lines.append(f"• {line}")
                else:
                    structured_lines.append(line)
            else:
                structured_lines.append(line)
    
    # 5. Финальная очистка
    final_text = '\n'.join(structured_lines)
    
    # Удаляем множественные пустые строки
    final_text = re.sub(r'\n\s*\n\s*\n+', '\n\n', final_text)
    
    # Удаляем строки, содержащие только специальные символы
    lines = final_text.split('\n')
    cleaned_lines = []
    for line in lines:
        # Пропускаем строки, содержащие только специальные символы
        if re.match(r'^\s*[«"»№@_\-\s\.]+$', line):
            continue
        # Пропускаем строки с шаблонами типа "_____________ «____» ______________"
        if re.match(r'^\s*[_\-\s]+[«"»№@\s]+[_\-\s]+$', line):
            continue
        cleaned_lines.append(line)
    
    final_text = '\n'.join(cleaned_lines)
    
    # Удаляем лишние пробелы в начале и конце
    final_text = final_text.strip()
    
    stats["cleaned_length"] = len(final_text)
    
    logging.info(f"Финальная очистка завершена. Исходный размер: {stats['original_length']} символов, "
                f"итоговый размер: {stats['cleaned_length']} символов")
    logging.info(f"Выделено ключевых заголовков: {stats['key_headers_found']}")
    
    return {
        "text": final_text,
        "stats": stats
    }


def extract_key_sections(text: str) -> dict:
    """
    Извлекает ключевые секции из текста тендера
    
    Args:
        text: Очищенный текст тендера
        
    Returns:
        Словарь с ключевыми секциями
    """
    sections = {}
    current_section = None
    current_content = []
    
    lines = text.split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Проверяем, является ли строка заголовком секции
        if line.startswith('**') and line.endswith('**'):
            # Сохраняем предыдущую секцию
            if current_section and current_content:
                sections[current_section] = '\n'.join(current_content).strip()
            
            # Начинаем новую секцию
            current_section = line.strip('*')
            current_content = []
        elif current_section:
            current_content.append(line)
    
    # Сохраняем последнюю секцию
    if current_section and current_content:
        sections[current_section] = '\n'.join(current_content).strip()
    
    return sections


def get_cleaning_stats(original_text: str, cleaned_text: str) -> dict:
    """
    Возвращает статистику очистки текста
    
    Args:
        original_text: Исходный текст
        cleaned_text: Очищенный текст
        
    Returns:
        Словарь со статистикой
    """
    original_lines = len(original_text.split('\n'))
    cleaned_lines = len(cleaned_text.split('\n'))
    original_chars = len(original_text)
    cleaned_chars = len(cleaned_text)
    
    return {
        'original_lines': original_lines,
        'cleaned_lines': cleaned_lines,
        'lines_removed': original_lines - cleaned_lines,
        'lines_reduction_percent': round((original_lines - cleaned_lines) / original_lines * 100, 2) if original_lines > 0 else 0,
        'original_chars': original_chars,
        'cleaned_chars': cleaned_chars,
        'chars_removed': original_chars - cleaned_chars,
        'chars_reduction_percent': round((original_chars - cleaned_chars) / original_chars * 100, 2) if original_chars > 0 else 0
    }

 