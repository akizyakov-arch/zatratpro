# ZATRATPRO — TECH SPEC
## Document Financial Normalization

## 1. Статус предыдущего блока

Блок `document routing` считать отдельным завершенным этапом.

Что уже реализовано:
- extraction strategy switch;
- family routing на стороне Python;
- prompt registry;
- family-specific prompts;
- type-priority fixes;
- strict fallback skeleton для noisy / low-signal OCR;
- базовые prompt/display корректировки для `goods_invoice`, `upd`, `cash_receipt`.

Дальнейшие проблемы лежат уже не в routing, а в согласовании финансовых полей документа.

---

## 2. Новый блок

### Document Financial Normalization

---

## 3. Почему это отдельный блок

Routing отвечает за:
- выбор extraction strategy;
- выбор prompt family;
- candidate document type;
- extraction mode (`default` / `strict`).

Но текущие ошибки уже другого класса:
- `vat_total_amount` путается с `total`;
- `line_total` и `vat_amount` имеют разную семантику в разных типах документов;
- preview вынужден компенсировать противоречивые поля;
- `DocumentSchema` начал обрастать ad-hoc OCR/VAT hotfix-логикой.

Это означает, что следующий этап должен быть оформлен как отдельный normalization block, а не как продолжение routing.

---

## 4. Цель

Сделать отдельный слой финансовой нормализации после extraction, чтобы:
- устойчиво согласовывать `total`, `vat_total_amount`, `vat_scope`, `line_total`, `vat_amount`;
- перестать чинить VAT/итоги по одному кейсу;
- убрать финансовые эвристики из `DocumentSchema`;
- дать понятную основу для preview и save flow.

---

## 5. Основная проблема

Сейчас в системе смешаны несколько задач:
- OCR / LLM extraction;
- schema validation;
- document type detection;
- item sanitization;
- VAT / totals heuristics;
- preview formatting.

Из-за этого:
- логика расползается между schema, prompts и preview;
- поведение по чекам, накладным и УПД регулируется точечными патчами;
- одно и то же поле может трактоваться по-разному в разных документах;
- preview может показывать формально заполненное, но фактически неверное значение.

---

## 6. Что нужно сделать

### 6.1. Зафиксировать семантику финансовых полей

Нужно явно определить смысл полей:
- `total`
- `vat_total_amount`
- `vat_scope`
- `line_total`
- `vat_amount`
- `price`

Минимум по типам:
- `cash_receipt`
- `goods_invoice`
- `upd`
- `vat_invoice`
- `transport_invoice`

### Рекомендуемая база

#### `cash_receipt`
- `total` = итог чека;
- `vat_total_amount` = НДС по документу из итогового блока;
- `vat_scope` = `document`, `mixed`, `no_vat`, `unknown`;
- line-level VAT необязателен.

#### `goods_invoice`
- если по строкам есть отдельные колонки:
  - `line_total` = сумма строки без НДС;
  - `vat_amount` = НДС по строке;
- `total` = итог документа;
- `vat_total_amount` = итог НДС по документу, если надежно виден.

#### `upd`
- по строкам:
  - `line_total` = сумма без НДС;
  - `vat_amount` = НДС по строке;
- `total` = итог документа, обычно с НДС.

#### `vat_invoice`
- приоритет у VAT fields и totals block;
- line-level структура вторична относительно итоговых полей.

#### `transport_invoice`
- line math и VAT зависят от формы;
- нужно явно определить, какие поля извлекаются надежно, а какие лучше гасить в `null`.

---

### 6.2. Вынести financial normalization из schema

Не держать дальше бизнес-эвристики VAT/total внутри `DocumentSchema`.

Рекомендуемый отдельный слой:
- `app/services/document_financials.py`
или
- `app/services/document_normalization.py`

Этот слой должен получать:
- extraction payload;
- `raw_text`;
- `document_type`;
- line items.

И возвращать уже финансово согласованный результат.

---

### 6.3. Сделать per-document-type financial resolvers

Нужны минимум:
- `ReceiptFinancialResolver`
- `GoodsInvoiceFinancialResolver`
- `UPDFinancialResolver`

Дальше при необходимости:
- `VATInvoiceFinancialResolver`
- `TransportInvoiceFinancialResolver`

---

### 6.4. Перейти к candidate-based resolution

Для ключевых финансовых полей нужен не одиночный regex-fix, а модель кандидатов.

Для каждого документа собирать кандидаты на:
- `total`
- `vat_total_amount`
- `sum_without_vat` при необходимости

Источники кандидатов:
- LLM payload;
- OCR totals block;
- line items;
- line VAT fields.

Потом применять правила выбора:
- VAT не должен быть равен `total`;
- VAT должен быть меньше `total`;
- `sum_without_vat + vat_total_amount` может совпадать с `total`;
- при конфликте приоритет у явно размеченного totals block;
- если уверенности нет, лучше `null`, чем ложное значение.

---

### 6.5. Разграничить ответственность слоев

#### Routing layer
Отвечает за:
- family;
- candidate type;
- extraction mode;
- prompt selection.

#### Extraction layer
Отвечает за:
- получение JSON payload.

#### Financial normalization layer
Отвечает за:
- согласование totals / VAT / line amounts.

#### Schema layer
Отвечает за:
- форму данных;
- базовую нормализацию;
- минимальную валидацию.

#### Preview layer
Отвечает только за отображение уже согласованных полей.

---

## 7. Что важно не делать

Не делать в этом блоке:
- дальнейшие case-by-case regex-патчи прямо в `DocumentSchema`;
- смешивание routing и financial normalization;
- исправление preview вместо underlying financial semantics;
- большой рефакторинг handler-layer;
- изменения в duplicate flow;
- изменения в save flow, не связанные с нормализацией финансовых полей.

---

## 8. Архитектурная рекомендация

### Текущий статус
Routing block считать отдельным завершенным этапом.

### Следующий этап
Открыть новый блок:

`Document Financial Normalization`

И выполнять его отдельно от routing.

---

## 9. Рекомендуемые фазы

### Phase 1 — Field Semantics Spec
Зафиксировать семантику:
- `total`
- `vat_total_amount`
- `line_total`
- `vat_amount`
- `price`

по ключевым типам документов.

### Phase 2 — Golden Corpus
Собрать эталонный набор:
- чеки с НДС;
- чеки без НДС;
- mixed VAT чеки;
- товарные накладные;
- возвратные накладные;
- УПД;
- транспортные накладные;
- счета-фактуры.

Для каждого зафиксировать ожидаемые поля.

### Phase 3 — Financial Resolver Layer
Добавить отдельный normalization layer и перевести туда текущую VAT / total reconciliation logic.

### Phase 4 — ReceiptFinancialResolver
Закрыть `cash_receipt` и `bso`.

### Phase 5 — GoodsInvoiceFinancialResolver
Закрыть товарные накладные и line semantics.

### Phase 6 — UPDFinancialResolver
Закрыть УПД и related VAT semantics.

### Phase 7 — Preview Alignment
Подстроить preview под уже согласованные поля.

---

## 10. Definition of Done

Блок считается выполненным, если:

1. routing block формально отделен от financial normalization block;
2. финансовая логика больше не размазывается по schema и preview;
3. для `cash_receipt`, `goods_invoice`, `upd` есть явные правила financial resolution;
4. `vat_total_amount` не путается с `total`;
5. preview не показывает ложный VAT;
6. спорные значения гасятся в `null`, а не показываются неверно;
7. golden corpus прогоняется предсказуемо;
8. новые исправления не делаются через бесконечные точечные regex-hotfixes.

---

## 11. Короткая версия

Routing block считать отдельным завершенным этапом.

Следующий блок открыть отдельно:

`Document Financial Normalization`

Причина:
текущие ошибки лежат уже не в routing / prompt selection, а в согласовании `total`, `vat_total_amount`, `line_total`, `vat_amount` по типам документов.

Что делать:
- зафиксировать семантику финансовых полей по типам документов;
- вынести VAT / total reconciliation из `DocumentSchema` в отдельный normalization layer;
- сделать per-type financial resolvers:
  - `ReceiptFinancialResolver`
  - `GoodsInvoiceFinancialResolver`
  - `UPDFinancialResolver`
- собрать golden corpus документов;
- перестать чинить VAT по одному кейсу regex-патчами.

Цель:
устойчиво согласовывать `total / vat_total_amount / line_total / vat_amount` по разным типам документов без расползания логики по schema и preview.
