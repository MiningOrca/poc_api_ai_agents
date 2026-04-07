# determination-orchestration — QA Automation with AI Agents PoC

## Описание

Проект показывает не “один большой промпт для генерации тестов”, а управляемый пайплайн:

* детерминированно подготавливает входные данные из спецификации и OpenAPI,
* генерирует тест-кейсы через LLM,
* генерирует step-level сценарии,
* запускает их против локального mock API,
* отправляет в LLM-аудит только failed или suspicious результаты.

## Что делает пайплайн

1. Из [context.md](agent/input/context.md) детерминированно строит [spec_sections.json](agent/input/spec_sections.json)
2. Из [spec_sections.json](agent/input/spec_sections.json) детерминированно строит [rules_views.json](agent/input/rules_views.json)
3. Из [open_api.json](agent/input/open_api.json) детерминированно строит [contract.json](agent/input/contract.json)
4. Для каждого endpoint генерирует abstract test cases
5. Для каждого test case генерирует step/scenario draft и собирает executable scenario
6. Запускает сценарии против mock API
7. Отправляет только failed/suspicious результаты в LLM-аудит
8. Складывает финальные артефакты в [output](agent/output)

## Входные файлы

Обязательные входы:
* [agent/input/open_api.json](agent/input/open_api.json)
* [agent/input/context.md](agent/input/context.md)

## Запуск

### Требования

* Python 3.12
* Docker / Docker Compose
* `pip`
* `OPENROUTER_API_KEY`

### Установка зависимостей

```bash
pip install -r requirements.txt
```

### Переменные окружения

```bash
export OPENROUTER_API_KEY="your_key_here"
```

### Поднять mock API

```bash
docker compose -f mock/docker-compose.yml up -d --build
```

### Запустить пайплайн

```bash
python agent/run_pipeline.py
```

## Архитектура

### Детерминированные этапы

Обычный код используется для:

* парсинга спецификации на секции,
* построения [rules_views.json](agent/input/rules_views.json),
* извлечения контракта из OpenAPI,
* сборки executable scenarios,
* запуска HTTP-запросов,
* runtime-проверок,
* prefilter перед аудитом.

### LLM-этапы

LLM используется для:

* генерации abstract test cases,
* генерации step-level scenario drafts,
* selective audit результатов.

## Роли моделей

### 1. Test Designer

Генерирует abstract test cases по endpoint’ам.

### 2. Step Designer

Генерирует step-level сценарные драфты для test cases.

### 3. Result Auditor

Анализирует только failed или suspicious результаты выполнения.

## Модели

### Test case generation

* `anthropic/claude-sonnet-4.6`
* temperature: `0.0`
* top_p: `0.2`
* max_output_tokens: `4000`

### Step generation

* `google/gemma-4-26b-a4b-it`
* temperature: `0.1`
* top_p: `1`
* max_output_tokens: `4000`

### Result audit

* `google/gemma-4-26b-a4b-it`
* temperature: `0.25`
* top_p: `1`
* max_output_tokens: `2000`

Промпты не вынесены в отдельные файлы и зафиксированы прямо в коде.

## Что проверяет раннер

Текущий раннер поддерживает только минимальный набор проверок:

* HTTP status code
* required response fields
* equality assertions

## Финальные артефакты

Финальные результаты пишутся в:

```text
agent/output/
```

Там находятся итоговые артефакты пайплайна:

* test cases
* scenarios
* run results
* final review report

## Ограничения и допущения

* Проект работает против локального mock API, а не реального backend.
* Base URL в текущем PoC захардкожен.
* Пайплайн не пытается автоматически перегенерировать артефакты, если этап или проверка не прошли.
* В LLM-аудит отправляются не все результаты, а только failed или suspicious.

## Кратко

Идея проекта простая:

* где можно обойтись детерминированным кодом — используется код;
* где нужен генеративный слой — используется LLM;
* дорогая модель используется только для test design;
* дешёвая модель используется для step generation и selective audit.