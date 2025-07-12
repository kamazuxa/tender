# TenderBot - Telegram Bot для анализа тендеров

## Описание

TenderBot - это Telegram бот для анализа тендеров через различные API (TenderGuru, Damia API). Бот позволяет получать информацию о тендерах, скачивать документы и проверять поставщиков в различных реестрах.

## Система логирования API

Бот имеет детальную систему логирования всех API запросов и ответов. Все логи сохраняются в папке `logs/`.

### Структура лог-файлов

- `logs/api_responses.log` - Основной лог-файл со всеми API ответами
- `logs/tenderguru_api.log` - Логи только для TenderGuru API
- `logs/damia_api.log` - Логи только для Damia API  
- `logs/api_errors.log` - Логи ошибок API (статус не 200)

### Что логируется

#### Запросы к API
- Временная метка
- Название API (TenderGuru/Damia)
- Endpoint
- Параметры запроса (JSON)

#### Ответы API
- Временная метка
- Название API
- Endpoint
- Параметры запроса
- HTTP статус
- Полный ответ (JSON)

#### Ошибки
- Все запросы со статусом не 200 автоматически дублируются в `api_errors.log`

### Примеры логов

#### Запрос к TenderGuru API
```
=== TENDERGURU API REQUEST ===
Timestamp: 2024-01-15 10:30:45
Endpoint: https://www.tenderguru.ru/api2.3/export
Params: {
  "regNumber": "0123456789012345678",
  "dtype": "json",
  "api_code": "your-api-key"
}
==================================================
```

#### Ответ от TenderGuru API
```
=== TENDERGURU API RESPONSE ===
Timestamp: 2024-01-15 10:30:46
Endpoint: https://www.tenderguru.ru/api2.3/export
Params: {
  "regNumber": "0123456789012345678",
  "dtype": "json",
  "api_code": "your-api-key"
}
Status: 200
Response: {
  "Items": [
    {
      "ID": "73321617",
      "TenderName": "Ремонт помещения",
      "Customer": "ООО Заказчик",
      "Price": "1000000",
      "DateEnd": "2024-02-15"
    }
  ]
}
==================================================
```

## Настройка

1. Скопируйте `config.py.example` в `config.py`
2. Укажите ваши API ключи:
   - `TENDER_GURU_API_KEY` - ключ для TenderGuru API
   - `DAMIA_API_KEY` - ключ для Damia API
   - `TELEGRAM_BOT_TOKEN` - токен Telegram бота

## Запуск

```bash
python bot.py
```

## Поддерживаемые API

### TenderGuru API
- Получение информации о тендерах по номеру
- Получение списка площадок
- Скачивание документов

### Damia API
- Получение информации о закупках
- Поиск тендеров
- Проверка поставщиков в реестрах (РНП, СРО, ЕРУЗ)

## Структура проекта

```
tender/
├── bot.py              # Основной файл бота
├── config.py           # Конфигурация
├── README.md           # Документация
└── logs/               # Папка с логами
    ├── api_responses.log
    ├── tenderguru_api.log
    ├── damia_api.log
    └── api_errors.log
``` 