# QA Automation with AI Agents — PoC

## Пайплайн

1. Из контекста задачи извлекаются правила.
2. Из правил и OpenAPI генерируются тест-кейсы.
3. Из тест-кейсов и OpenAPI генерируется execution plan.
4. Execution plan исполняется против mock API.
5. По результатам прогона строится review-отчёт, только на упавшие сценарии, если их нет не строится.

LLM используется там, где нужен смысловой разбор и проектирование тестов. Обычный код используется там, где важны предсказуемость и контроль: для deterministic gates, нормализации JSON-артефактов и запуска runner. Такой разрез соответствует текущему execution guide: skill-driven стадии разделены gate-слоем, а Stage 4 полностью выполняется детерминированным Python-кодом.

## Архитектура

### Где используется LLM

LLM/agent используется для следующих стадий:

* извлечение правил из [context.md](agent/input/context.md);
* генерация тест-кейсов из [rules.json](output/rules.json) и [open_api.json](agent/input/open_api.json);
* генерация `execution_plan_{endpointId}.json`;
* review результатов исполнения и сбор итогового [review_report.json](output/review_report.json). 

### Где используется обычный детерминированный код

Детерминированный код отвечает за:

* валидацию candidate-артефактов после каждой skill-driven стадии;
* нормализацию артефактов к канонической JSON-форме;
* остановку пайплайна при failed gate;
* исполнение HTTP-сценариев;
* сбор `execution_report_{endpointId}.json`.

Gate-слой расположен между skill-driven стадиями и следующим шагом пайплайна: он валидирует артефакт, отклоняет его со структурированными ошибками при нарушениях и нормализует перед сохранением или передачей дальше. 

подробней в [workflow.md](workflow.md)
## Поток данных

Высокоуровневый flow выглядит так:

```text
agent/input/context.md
  -> rules extraction
  -> output/rules.json

output/rules.json + agent/input/open_api.json
  -> test case generation
  -> output/test_cases.json

output/test_cases.json + agent/input/open_api.json
  -> execution planning
  -> output/execution_plan.json

output/execution_plan.json
  -> deterministic executor
  -> output/execution_report.json

output/execution_report.json
  -> result review
  -> output/review_report.json
```

Ожидаемые выходные артефакты именно такие: `rules.json`, `test_cases_{endpointId}.json`, `execution_plan_{endpointId}.json`, `execution_report_{endpointId}.json`, `review_report.json`. 

## Запуск

### 1. Поднять моки

```bash
docker compose -f mock/docker-compose.yml up --build
```

### 2. Подготовить входные файлы

Пайплайн ожидает, что в репозитории уже есть входные артефакты:

* `agent/input/context.md`
* `agent/input/open_api.json`

Для стадии планирования также используется format reference для execution plan:

* `agent/json_examples/execution_plan.json` 

### 3. Запустить пайплайн через Claude Code

Из корня репозитория пайплайн запускается через skill:

```text
/run_pipeline
```

Именно orchestration skill запускает стадии по порядку, применяет deterministic gates после каждой skill-driven стадии и останавливается на первом failed gate. Для полного пайплайна нет одного shell-командного entry point: shell CLI есть только у deterministic executor на Stage 4. 

### 4. При необходимости отдельно запустить executor

Если нужно прогнать уже готовый `execution_plan.json` вручную, deterministic executor можно вызвать напрямую:

```bash
python -m src.executor.runner \
  --plan output/execution_plan.json \
  --report output/execution_report.json \
  --base-url http://localhost:8080
```

Executor читает валидированный `execution_plan.json`, подставляет binding templates, отправляет HTTP-запросы по шагам, проверяет assertions и записывает полный self-contained `execution_report.json`.

## Что получается на выходе

После успешного прогона в `output/` появляются:

* `output/rules.json` — извлечённые бизнес-правила;
* `output/test_cases_{endpointId}.json` — абстрактные тест-кейсы по endpoint’ам;
* `output/execution_plan_{endpointId}.json` — исполняемые сценарии с HTTP-деталями;
* `output/execution_report_{endpointId}.json` — step-level результаты исполнения;
* `output/review_report.json` — итоговый review по результатам прогона. 

## Почему пайплайн устроен именно так

Я сознательно разделил reasoning и execution.

Модель полезна для того, чтобы:

* извлекать ограничения из текстового описания;
* предлагать positive / negative / boundary coverage;
* строить сценарные заготовки;
* анализировать результаты прогонов.

Но модель не должна бесконтрольно определять итоговый формат артефакта или исполнять сценарии напрямую. Поэтому между LLM-стадиями и следующими шагами стоит deterministic gate layer. Наиболее строгая граница — Stage 3, потому что именно `execution_plan.json` дальше уходит в executor без дополнительной “интерпретации”. Для этой границы применяются shape, contract conformance, assertion whitelist, binding validity и normalization.

## Воспроизводимость

В этом PoC воспроизводимость обеспечивается следующими принципами:

* skill-driven стадии работают с фиксированными артефактами и ожидаемыми JSON-структурами;
* каждый JSON-артефакт после модели проходит deterministic validation;
* артефакты нормализуются в каноническую форму перед следующим шагом;
* стадии запускаются в фиксированном порядке;
* пайплайн не пытается молча “починить” невалидный output модели. 

## Assumptions

В проекте сделаны следующие допущения:

* вместо реального API используется локальный mock;
* `context.md` содержит достаточно информации, чтобы из него можно было извлечь тестируемые бизнес-правила;
* `open_api.json` существует и рассматривается как transport-level source of truth;
* output модели полезен только после deterministic validation.

## Не реализовано

У меня как то не так много токенов так что: 
* автоматическую перегенерацию артефакта после failed gate;
* проверку правил или сценариев второй моделью;
* отдельную проверку всех выполненных тестов на предмет слабых assertions;
* self-healing или repair loop поверх LLM output;
* усложнение runner-слоя дальше чем базовые нужды раннера.

## Итог

У меня минут 30 реального времени ушло, правда с лимитами вышло несколько больше   
