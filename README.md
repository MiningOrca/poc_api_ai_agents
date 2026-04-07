# determination-orchestration
Идея примерно т  акая же, но больше дела ется с помощью кода 

пайплайн 
1. детерменированно генерируем  [spec_sections.json](agent/input/spec_sections.json) с помощью [build_spec_sections.py](agent/extractors/build_spec_sections.py)
2. детерменированно генерируем [rules_views.json](agent/input/rules_views.json) с помощью [build_rules_views.py](agent/extractors/build_rules_views.py)
3. детерменированно генерируем [contract.json](agent/input/contract.json) с помощью [openapi_contract_builder.py](agent/extractors/openapi_contract_builder.py)
4. для каждого эндпоинта генерируем [test_cases](agent/output/test_cases) с помощью [llm_test_designer.py](agent/llm/test_designer/llm_test_designer.py)
5. для каждого тест кейса отдельно генерируем [scenarios](agent/output/scenarios) для каждого степа и склеиваем с помощью [scenario_builder.py](agent/llm/step_designer/scenario_builder.py)
6. для каждого сценария запускаем [test_runner.py](agent/runner/test_runner.py) на выходе получая [run_results](agent/output/run_results)
7. для каждого подозрительного результат/ошибки считаем нужно ли отправить в ллм на проверку [result_review_prefilter.py](agent/llm/result_reviewver/result_review_prefilter.py)
8. проверка через ллм [llm_result_review.py](agent/llm/result_reviewver/llm_result_review.py) и финальный репорт в корень [output](agent/output)

архитектурные решения 
- используем дорогую модель только на этапе генерации [test_cases](agent/output/test_cases), остальное генерим дешевой геммой
- нет попыток перегенерить если не прошли чек
- убраны ассерты кроме equal 
- ассерты по статус коду/обязательным полям генерит код
- отправляем на ревью только подозрительные тесты

запуск через 
[run_pipeline.py](agent/run_pipeline.py)
указать нужно 
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY",
                               "")
[docker-compose.yml](mock/docker-compose.yml) ну и моки через компос запустить