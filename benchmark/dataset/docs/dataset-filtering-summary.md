# Сводка фильтрации датасета

Анализируемый запуск: `benchmark/dataset/runs/2026_05_05_08_59_47`

## 1) Общий результат

- Всего записей после парсинга (`raw`): **1929**
- Прошли все фильтры (`clean`): **202**
- Отклонены: **1727**

## 2) Применённые фильтры (формальные критерии)

Запись включается в итоговый датасет, если одновременно выполняются:

1. `is_python_function` — в записи есть непустой исходный код функции.
2. `has_explicit_contract` — найден хотя бы один явный контракт (decorator или PEP316-блок).
3. `has_type_info_minimum` — есть явная аннотация возвращаемого типа и явные типы аргументов.
4. `has_normalized_postcondition` — удалось получить непустое нормализованное постусловие.
5. `non_trivial_contract` — постусловие не является тривиальным (таутологии).
6. `duplicate_reject == false` — запись не является семантическим дублем уже принятой записи.

Итоговое правило отбора:

`accept = is_python_function AND has_explicit_contract AND has_type_info_minimum AND has_normalized_postcondition AND non_trivial_contract AND NOT duplicate_reject`

## 3) Отсев по шагам пайплайна

| Шаг | До фильтра | После фильтра | Отсеяно на шаге |
|---|---:|---:|---:|
| `is_python_function` | 1929 | 1929 | 0 |
| `has_explicit_contract` | 1929 | 601 | 1328 |
| `has_type_info_minimum` | 601 | 579 | 22 |
| `has_normalized_postcondition` | 579 | 371 | 208 |
| `non_trivial_contract` | 371 | 371 | 0 |
| `duplicate_reject == false` | 371 | 202 | 169 |

## 4) Независимая статистика отказов (на уровне raw)

Ниже показано, сколько записей не прошло каждый конкретный критерий независимо от остальных:

- `is_python_function`: 0
- `has_explicit_contract`: 1328
- `has_type_info_minimum`: 35
- `has_normalized_postcondition`: 1552
- `non_trivial_contract`: 1552
- `duplicate_reject == true`: 169

## 5) Разбивка по источникам

| Источник | Raw | Clean | Отклонено |
|---|---:|---:|---:|
| `python_by_contract` | 1852 | 156 | 1696 |
| `crosshair_examples` | 77 | 46 | 31 |
