#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль для генерации единого промпта анализа тендера
Объединяет данные из TenderGuru API и очищенный текст документации
"""

import json
from typing import Dict, List, Optional
from datetime import datetime

class TenderPromptBuilder:
    """
    Класс для построения промптов анализа тендеров
    """
    
    def __init__(self, max_text_length: int = 15000):
        """
        Инициализация построителя промптов
        
        Args:
            max_text_length: Максимальная длина текста документации в промпте
        """
        self.max_text_length = max_text_length
    
    def extract_product_list(self, tender_data: Dict) -> List[Dict]:
        """
        Извлекает список товаров из данных тендера
        
        Args:
            tender_data: Данные тендера из API
            
        Returns:
            List[Dict]: Список товаров с информацией о количестве и ценах
        """
        products = []
        
        # Пытаемся извлечь товары из HTML в поле Info
        info_html = tender_data.get('Info', '')
        if info_html:
            # Простой парсинг HTML для извлечения товаров
            import re
            
            # Паттерн для поиска товаров в HTML
            product_pattern = r'&lt;b&gt;Наименование товара, работы, услуги:&lt;/b&gt; ([^&]+)&lt;br /&gt;.*?&lt;b&gt;Количество:&lt;/b&gt; (\d+).*?&lt;b&gt;Цена за ед\.изм\.:&lt;/b&gt; ([\d.]+) рублей.*?&lt;b&gt;Стоимость:&lt;/b&gt; ([\d.]+) рублей'
            
            matches = re.findall(product_pattern, info_html, re.DOTALL)
            
            for match in matches:
                name, qty, price, total = match
                products.append({
                    'name': name.strip(),
                    'qty': int(qty),
                    'price': float(price),
                    'sum': float(total)
                })
        
        return products
    
    def format_price(self, price_str: str) -> str:
        """
        Форматирует цену для отображения
        
        Args:
            price_str: Цена в виде строки
            
        Returns:
            str: Отформатированная цена
        """
        try:
            price = float(price_str)
            return f"{price:,.2f}".replace(',', ' ')
        except (ValueError, TypeError):
            return price_str
    
    def format_date(self, date_str: str) -> str:
        """
        Форматирует дату для отображения
        
        Args:
            date_str: Дата в формате DD-MM-YYYY
            
        Returns:
            str: Отформатированная дата
        """
        try:
            if date_str:
                date_obj = datetime.strptime(date_str, "%d-%m-%Y")
                return date_obj.strftime("%d.%m.%Y")
        except (ValueError, TypeError):
            pass
        return date_str
    
    def build_analysis_prompt(self, tender_data: Dict, cleaned_text: str) -> str:
        """
        Строит единый промпт для анализа тендера
        
        Args:
            tender_data: Данные тендера из TenderGuru API
            cleaned_text: Очищенный текст документации
            
        Returns:
            str: Полный промпт для OpenAI
        """
        
        # Извлекаем основные данные
        tender_number = tender_data.get('TenderNumOuter', 'Не указан')
        tender_name = tender_data.get('TenderName', 'Не указано')
        customer = tender_data.get('Customer', 'Не указан')
        region = tender_data.get('Region', 'Не указан')
        price = self.format_price(tender_data.get('Price', '0'))
        end_time = self.format_date(tender_data.get('EndTime', ''))
        tender_link = tender_data.get('TenderLink', '')
        tender_link_inner = tender_data.get('TenderLinkInner', '')
        
        # Извлекаем список товаров
        products = self.extract_product_list(tender_data)
        
        # Обрезаем текст документации если нужно
        if len(cleaned_text) > self.max_text_length:
            truncated_text = cleaned_text[:self.max_text_length] + "\n\n[Текст обрезан для экономии токенов]"
        else:
            truncated_text = cleaned_text
        
        # Строим промпт
        prompt_parts = []
        
        # Заголовок
        prompt_parts.append("🔍 АНАЛИЗ ТЕНДЕРА")
        prompt_parts.append("=" * 60)
        prompt_parts.append("")
        
        # Общая информация о тендере
        prompt_parts.append("🧾 ОБЩАЯ ИНФОРМАЦИЯ О ТЕНДЕРЕ:")
        prompt_parts.append("")
        prompt_parts.append(f"• Номер тендера: {tender_number}")
        prompt_parts.append(f"• Название: {tender_name}")
        prompt_parts.append(f"• Заказчик: {customer}")
        prompt_parts.append(f"• Регион: {region}")
        prompt_parts.append(f"• Начальная цена: {price} ₽")
        if end_time:
            prompt_parts.append(f"• Подача заявок до: {end_time}")
        if tender_link:
            prompt_parts.append(f"• Ссылка на тендер: {tender_link}")
        if tender_link_inner:
            prompt_parts.append(f"• Ссылка TenderGuru: {tender_link_inner}")
        prompt_parts.append("")
        
        # Позиции товаров (если есть)
        if products:
            prompt_parts.append("📎 ПОЗИЦИИ ТОВАРОВ:")
            prompt_parts.append("")
            total_sum = 0
            for product in products:
                name = product['name']
                qty = product['qty']
                price = product['price']
                sum_val = product['sum']
                total_sum += sum_val
                prompt_parts.append(f"• {name} — {qty} шт × {price:.2f} ₽ = {sum_val:.2f} ₽")
            
            prompt_parts.append(f"")
            prompt_parts.append(f"📊 Итого по позициям: {total_sum:.2f} ₽")
            prompt_parts.append("")
        
        # Документация тендера
        prompt_parts.append("📄 ДОКУМЕНТАЦИЯ ТЕНДЕРА:")
        prompt_parts.append("")
        prompt_parts.append("<<<")
        prompt_parts.append(truncated_text)
        prompt_parts.append(">>>")
        prompt_parts.append("")
        
        # Задание для анализа
        prompt_parts.append("🔍 ПРОАНАЛИЗИРУЙ:")
        prompt_parts.append("")
        prompt_parts.append("1. Что требуется по техническому заданию?")
        prompt_parts.append("2. Какие обязательные параметры товара, упаковки, страны происхождения?")
        prompt_parts.append("3. Есть ли ограничения для СМП/СОНО?")
        prompt_parts.append("4. Какие риски и неочевидные нюансы присутствуют?")
        prompt_parts.append("5. Какие документы необходимо подготовить для участия?")
        prompt_parts.append("6. Есть ли особые требования к поставщику?")
        prompt_parts.append("7. Какие сроки поставки и условия оплаты?")
        prompt_parts.append("")
        prompt_parts.append("💡 Предоставь структурированный анализ с выделением ключевых моментов и рекомендаций.")
        
        return "\n".join(prompt_parts)
    
    def build_simple_prompt(self, tender_data: Dict, cleaned_text: str) -> str:
        """
        Строит упрощенный промпт для быстрого анализа
        
        Args:
            tender_data: Данные тендера из TenderGuru API
            cleaned_text: Очищенный текст документации
            
        Returns:
            str: Упрощенный промпт
        """
        
        tender_name = tender_data.get('TenderName', 'Не указано')
        customer = tender_data.get('Customer', 'Не указан')
        price = self.format_price(tender_data.get('Price', '0'))
        
        # Обрезаем текст
        if len(cleaned_text) > self.max_text_length:
            truncated_text = cleaned_text[:self.max_text_length] + "\n\n[Текст обрезан]"
        else:
            truncated_text = cleaned_text
        
        prompt = f"""Анализ тендера: {tender_name}
Заказчик: {customer}
Цена: {price} ₽

Документация:
{truncated_text}

Проанализируй тендер и выдели ключевые требования, риски и особенности."""
        
        return prompt

def build_analysis_prompt(tender_data: Dict, cleaned_text: str) -> str:
    """
    Функция-обертка для быстрого создания промпта анализа
    
    Args:
        tender_data: Данные тендера из TenderGuru API
        cleaned_text: Очищенный текст документации
        
    Returns:
        str: Полный промпт для OpenAI
    """
    builder = TenderPromptBuilder()
    return builder.build_analysis_prompt(tender_data, cleaned_text) 

def build_final_prompt(data: dict) -> str:
    """
    Создает финальный промпт для анализа тендера, объединяя summary, items и text.
    
    Args:
        data: Словарь с данными тендера
            {
                "summary": {
                    "number": "0372200186425000005",
                    "title": "Поставка канцелярских товаров",
                    "customer": "ГБДОУ детский сад № 21",
                    "region": "Санкт-Петербург",
                    "price": 30727.40,
                    "deadline": "11.07.2025",
                    "link": "http://zakupki.gov.ru/...",
                    "tenderguru": "https://www.tenderguru.ru/..."
                },
                "items": [
                    {"name": "пишущий узел", "qty": 20, "price": 37.51, "total": 750.20},
                    {"name": "быстросохнущие чернила", "qty": 6, "price": 68.60, "total": 411.60}
                ],
                "text": {
                    "content": "ОПИСАНИЕ ОБЪЕКТА ЗАКУПКИ...",
                    "length": 7353,
                    "sources": ["Описание объекта закупки.docx"]
                }
            }
    
    Returns:
        str: Готовый промпт для отправки в OpenAI
    """
    
    # Извлекаем данные
    summary = data.get("summary", {})
    items = data.get("items", [])
    text_data = data.get("text", {})
    
    # Форматируем цену
    def format_price(price):
        if price is None:
            return "Не указана"
        try:
            return f"{float(price):,.2f}".replace(',', ' ')
        except (ValueError, TypeError):
            return str(price)
    
    # Строим промпт
    prompt_parts = []
    
    # Заголовок
    prompt_parts.append("🔍 АНАЛИЗ ТЕНДЕРА")
    prompt_parts.append("=" * 60)
    prompt_parts.append("")
    
    # Общая информация
    prompt_parts.append("🧾 ОБЩАЯ ИНФОРМАЦИЯ:")
    
    if summary.get("number"):
        prompt_parts.append(f"• Номер тендера: {summary['number']}")
    
    if summary.get("title"):
        prompt_parts.append(f"• Название: {summary['title']}")
    
    if summary.get("customer"):
        prompt_parts.append(f"• Заказчик: {summary['customer']}")
    
    if summary.get("region"):
        prompt_parts.append(f"• Регион: {summary['region']}")
    
    if summary.get("price"):
        prompt_parts.append(f"• Начальная цена: {format_price(summary['price'])} ₽")
    
    if summary.get("deadline"):
        prompt_parts.append(f"• Срок подачи заявок: {summary['deadline']}")
    
    if summary.get("link"):
        prompt_parts.append(f"• Ссылка на тендер: {summary['link']}")
    
    if summary.get("tenderguru"):
        prompt_parts.append(f"• Ссылка TenderGuru: {summary['tenderguru']}")
    
    prompt_parts.append("")
    
    # Позиции товаров
    if items:
        prompt_parts.append("📦 ПОЗИЦИИ ТОВАРОВ:")
        
        total_sum = 0
        for item in items:
            name = item.get("name", "Не указано")
            qty = item.get("qty", 0)
            price = item.get("price", 0)
            total = item.get("total", 0)
            total_sum += total
            
            prompt_parts.append(f"• {name} — {qty} шт × {format_price(price)} ₽ = {format_price(total)} ₽")
        
        prompt_parts.append(f"• ИТОГО по позициям: {format_price(total_sum)} ₽")
        prompt_parts.append("")
    
    # Извлеченный текст
    text_content = text_data.get("content", "")
    if text_content:
        prompt_parts.append("📄 ИЗВЛЕЧЁННЫЙ ТЕКСТ ИЗ ДОКУМЕНТАЦИИ:")
        prompt_parts.append("<<<")
        prompt_parts.append(text_content)
        prompt_parts.append(">>>")
        prompt_parts.append("")
    
    # Задание для анализа
    prompt_parts.append("🎯 Проанализируй тендер и выдай:")
    prompt_parts.append("- Основные требования и условия")
    prompt_parts.append("- Возможные риски или нестандартные условия")
    prompt_parts.append("- Есть ли потенциальные ловушки или завышенные требования")
    prompt_parts.append("- Итоговая сводка по тендеру")
    
    # Собираем промпт
    full_prompt = "\n".join(prompt_parts)
    
    # Ограничиваем длину до 16000 символов
    max_length = 16000
    if len(full_prompt) > max_length:
        # Находим позицию текста документации
        text_start = full_prompt.find("<<<")
        text_end = full_prompt.find(">>>")
        
        if text_start != -1 and text_end != -1:
            # Вычисляем доступное место для текста
            before_text = full_prompt[:text_start]
            after_text = full_prompt[text_end:]
            available_for_text = max_length - len(before_text) - len(after_text) - 10  # 10 для "..." и переносов
            
            if available_for_text > 100:  # Минимальная длина для текста
                # Обрезаем текст документации
                text_content = text_content[:available_for_text] + "\n\n[Текст обрезан для экономии токенов]"
                
                # Пересобираем промпт
                prompt_parts = []
                prompt_parts.append("🔍 АНАЛИЗ ТЕНДЕРА")
                prompt_parts.append("=" * 60)
                prompt_parts.append("")
                
                # Общая информация (повторяем)
                prompt_parts.append("🧾 ОБЩАЯ ИНФОРМАЦИЯ:")
                
                if summary.get("number"):
                    prompt_parts.append(f"• Номер тендера: {summary['number']}")
                
                if summary.get("title"):
                    prompt_parts.append(f"• Название: {summary['title']}")
                
                if summary.get("customer"):
                    prompt_parts.append(f"• Заказчик: {summary['customer']}")
                
                if summary.get("region"):
                    prompt_parts.append(f"• Регион: {summary['region']}")
                
                if summary.get("price"):
                    prompt_parts.append(f"• Начальная цена: {format_price(summary['price'])} ₽")
                
                if summary.get("deadline"):
                    prompt_parts.append(f"• Срок подачи заявок: {summary['deadline']}")
                
                if summary.get("link"):
                    prompt_parts.append(f"• Ссылка на тендер: {summary['link']}")
                
                if summary.get("tenderguru"):
                    prompt_parts.append(f"• Ссылка TenderGuru: {summary['tenderguru']}")
                
                prompt_parts.append("")
                
                # Позиции товаров (повторяем)
                if items:
                    prompt_parts.append("📦 ПОЗИЦИИ ТОВАРОВ:")
                    
                    total_sum = 0
                    for item in items:
                        name = item.get("name", "Не указано")
                        qty = item.get("qty", 0)
                        price = item.get("price", 0)
                        total = item.get("total", 0)
                        total_sum += total
                        
                        prompt_parts.append(f"• {name} — {qty} шт × {format_price(price)} ₽ = {format_price(total)} ₽")
                    
                    prompt_parts.append(f"• ИТОГО по позициям: {format_price(total_sum)} ₽")
                    prompt_parts.append("")
                
                # Обрезанный текст
                prompt_parts.append("📄 ИЗВЛЕЧЁННЫЙ ТЕКСТ ИЗ ДОКУМЕНТАЦИИ:")
                prompt_parts.append("<<<")
                prompt_parts.append(text_content)
                prompt_parts.append(">>>")
                prompt_parts.append("")
                
                # Задание для анализа
                prompt_parts.append("🎯 Проанализируй тендер и выдай:")
                prompt_parts.append("- Основные требования и условия")
                prompt_parts.append("- Возможные риски или нестандартные условия")
                prompt_parts.append("- Есть ли потенциальные ловушки или завышенные требования")
                prompt_parts.append("- Итоговая сводка по тендеру")
                
                full_prompt = "\n".join(prompt_parts)
            else:
                # Если места слишком мало, обрезаем весь промпт
                full_prompt = full_prompt[:max_length-100] + "\n\n[Промпт обрезан из-за ограничения по длине]"
    
    return full_prompt 

def structured_prompt_builder(tender_data: dict, clean_text: str, items: list[str]) -> str:
    """
    Создает структурированный промпт для анализа тендера в формате:
    summary (данные из TenderGuru)
    items (позиции товаров)
    text (очищенный текст из документации, с секциями)
    instructions (задание для OpenAI)
    
    Args:
        tender_data: Словарь с данными о тендере
        clean_text: Очищенный текст из документации
        items: Список строк товарных позиций
        
    Returns:
        str: Структурированный промпт для OpenAI
    """
    
    # Извлекаем данные из tender_data
    reg_number = tender_data.get("reg_number", "Не указан")
    title = tender_data.get("title", "Не указано")
    customer = tender_data.get("customer", "Не указан")
    region = tender_data.get("region", "Не указан")
    price = tender_data.get("price", "Не указана")
    deadline = tender_data.get("deadline", "Не указан")
    tender_url = tender_data.get("tender_url", "")
    tenderguru_url = tender_data.get("tenderguru_url", "")
    
    # Строим промпт по шаблону
    prompt_parts = []
    
    # Заголовок
    prompt_parts.append("🔍 АНАЛИЗ ТЕНДЕРА")
    prompt_parts.append("=" * 60)
    prompt_parts.append("")
    
    # Общая информация
    prompt_parts.append("🧾 ОБЩАЯ ИНФОРМАЦИЯ:")
    prompt_parts.append(f"• Номер тендера: {reg_number}")
    prompt_parts.append(f"• Название: {title}")
    prompt_parts.append(f"• Заказчик: {customer}")
    prompt_parts.append(f"• Регион: {region}")
    prompt_parts.append(f"• Начальная цена: {price}")
    prompt_parts.append(f"• Срок подачи заявок: {deadline}")
    if tender_url:
        prompt_parts.append(f"• Ссылка на тендер: {tender_url}")
    if tenderguru_url:
        prompt_parts.append(f"• Ссылка TenderGuru: {tenderguru_url}")
    prompt_parts.append("")
    
    # Позиции товаров
    if items:
        prompt_parts.append("📦 ПОЗИЦИИ ТОВАРОВ:")
        for item in items:
            prompt_parts.append(item)
        prompt_parts.append("")
    
    # Извлеченный текст из документации
    if clean_text:
        prompt_parts.append("📄 ИЗВЛЕЧЁННЫЙ ТЕКСТ ИЗ ДОКУМЕНТАЦИИ:")
        prompt_parts.append("<<<")
        prompt_parts.append(clean_text)
        prompt_parts.append(">>>")
        prompt_parts.append("")
    
    # Задание для анализа
    prompt_parts.append("🎯 Проанализируй тендер и выдай:")
    prompt_parts.append("- Основные требования и условия")
    prompt_parts.append("- Возможные риски или нестандартные условия")
    prompt_parts.append("- Есть ли потенциальные ловушки или завышенные требования")
    prompt_parts.append("- Итоговая сводка по тендеру")
    
    # Собираем финальный промпт
    full_prompt = "\n".join(prompt_parts)
    
    # Ограничиваем длину до 16000 символов
    max_length = 16000
    if len(full_prompt) > max_length:
        # Находим позицию текста документации
        text_start = full_prompt.find("<<<")
        text_end = full_prompt.find(">>>")
        
        if text_start != -1 and text_end != -1:
            # Вычисляем доступное место для текста
            before_text = full_prompt[:text_start]
            after_text = full_prompt[text_end:]
            available_for_text = max_length - len(before_text) - len(after_text) - 10  # 10 для "..." и переносов
            
            if available_for_text > 100:  # Минимальная длина для текста
                # Обрезаем текст документации
                clean_text = clean_text[:available_for_text] + "\n\n[Текст обрезан для экономии токенов]"
                
                # Пересобираем промпт
                prompt_parts = []
                
                # Заголовок
                prompt_parts.append("🔍 АНАЛИЗ ТЕНДЕРА")
                prompt_parts.append("=" * 60)
                prompt_parts.append("")
                
                # Общая информация
                prompt_parts.append("🧾 ОБЩАЯ ИНФОРМАЦИЯ:")
                prompt_parts.append(f"• Номер тендера: {reg_number}")
                prompt_parts.append(f"• Название: {title}")
                prompt_parts.append(f"• Заказчик: {customer}")
                prompt_parts.append(f"• Регион: {region}")
                prompt_parts.append(f"• Начальная цена: {price}")
                prompt_parts.append(f"• Срок подачи заявок: {deadline}")
                if tender_url:
                    prompt_parts.append(f"• Ссылка на тендер: {tender_url}")
                if tenderguru_url:
                    prompt_parts.append(f"• Ссылка TenderGuru: {tenderguru_url}")
                prompt_parts.append("")
                
                # Позиции товаров
                if items:
                    prompt_parts.append("📦 ПОЗИЦИИ ТОВАРОВ:")
                    for item in items:
                        prompt_parts.append(item)
                    prompt_parts.append("")
                
                # Обрезанный текст
                prompt_parts.append("📄 ИЗВЛЕЧЁННЫЙ ТЕКСТ ИЗ ДОКУМЕНТАЦИИ:")
                prompt_parts.append("<<<")
                prompt_parts.append(clean_text)
                prompt_parts.append(">>>")
                prompt_parts.append("")
                
                # Задание для анализа
                prompt_parts.append("🎯 Проанализируй тендер и выдай:")
                prompt_parts.append("- Основные требования и условия")
                prompt_parts.append("- Возможные риски или нестандартные условия")
                prompt_parts.append("- Есть ли потенциальные ловушки или завышенные требования")
                prompt_parts.append("- Итоговая сводка по тендеру")
                
                full_prompt = "\n".join(prompt_parts)
            else:
                # Если места слишком мало, обрезаем весь промпт
                full_prompt = full_prompt[:max_length-100] + "\n\n[Промпт обрезан из-за ограничения по длине]"
    
    return full_prompt


def extract_sections_from_text(clean_text: str) -> list[str]:
    """
    Извлекает секции из текста, если в нем есть выделенные заголовки
    
    Args:
        clean_text: Очищенный текст с возможными заголовками
        
    Returns:
        list[str]: Список найденных секций
    """
    import re
    
    # Паттерн для поиска заголовков в формате **ЗАГОЛОВОК**
    section_pattern = r'\*\*([^*]+)\*\*'
    sections = re.findall(section_pattern, clean_text)
    
    return sections 