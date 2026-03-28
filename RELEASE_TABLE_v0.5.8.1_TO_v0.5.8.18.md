# Таблица релизов v0.5.8.1 - v0.5.8.18

Диапазон: от `v0.5.8.1` до `v0.5.8.18`.

## Краткая таблица

| Версия | Tag commit | Основное добавление | Что изменено / убрано |
|---|---|---|---|
| `v0.5.8.1` | `2e6604f` | backup setup guide | Базовая точка после inline navigation и storage-flow |
| `v0.5.8.2` | `7344aac` | PDF upload + DeepSeek proxy with retries | OCR flow расширен с photo/image до PDF |
| `v0.5.8.3` | `6b21419` | accountant ZIP export + manifest links | Добавлен новый export-сценарий |
| `v0.5.8.4` | `55c3f6e` | periods/custom year для accountant export | Выгрузка стала фильтроваться по document date |
| `v0.5.8.5` | `613fbce` | manager Excel dashboard export | OCR.Space release закреплен на engine 2 |
| `v0.5.8.6` | `7e963e2` | hardening manager Excel export | Подрезаны и выровнены Excel sheets |
| `v0.5.8.7` | `a2029c4` | filtered employee my documents flow | Улучшен employee self-service просмотр |
| `v0.5.8.8` | `efb9db0` | VAT fields end-to-end + accountant manifest VAT columns | Схема документа и БД расширены под НДС |
| `v0.5.8.9` | `4230a3b` | VAT в manager dashboard / registry / preview | Excel и preview стали VAT-aware |
| `v0.5.8.10` | `ced18a0` | shared HTTP clients for OCR.Space and DeepSeek | Убрано повторное создание HTTP clients по hot path |
| `v0.5.8.11` | `dfc8c97` | image/PDF preprocessing moved to shared executor | Upload preprocessing разгружен и унифицирован |
| `v0.5.8.12` | `070baa1` | fiscalization flag pipeline | Document pipeline расширен полем фискализации |
| `v0.5.8.13` | `5dd0586` | invite schema fix after clean database reset | Исправлен reset/invite контур после чистой БД |
| `v0.5.8.14` | `03964df` | backup restore scripts and docs | Появился полноценный host-side backup/restore contour |
| `v0.5.8.15` | `d0c8e10` | stronger handwritten extraction and VAT fixes | Убраны шумные unnamed rows и улучшен mixed VAT |
| `v0.5.8.16` | `f925b94` | shared temp cleanup utility | Ручной cleanup temp-файлов вытеснен единым слоем |
| `v0.5.8.17` | `14df2e9` | document_processing service refactor | Handler перестал быть центром document orchestration |
| `v0.5.8.18` | `4d8aa32` | flow boundary note and release closure | Document-processing block формально оформлен и закрыт |

## Детализация по версиям

### v0.5.8.1
- Commit: `2e6604f`
- Message: `Add backup setup guide`
- Добавлено:
  - guide по backup setup;
  - база для дальнейшего backup contour.
- Изменено / убрано:
  - без функциональных removals.

### v0.5.8.2
- Tag commit: `7344aac`
- Вошедшие ключевые изменения:
  - `ef47e00` `Add PDF upload to OCR flow`
  - `7344aac` `Route DeepSeek via proxy with retries`
- Добавлено:
  - PDF upload в OCR flow;
  - proxy/retry contour для DeepSeek.
- Изменено / убрано:
  - document intake перестал быть только image-flow.

### v0.5.8.3
- Tag commit: `6b21419`
- Вошедшие ключевые изменения:
  - `7f83c40` `Add inline accountant archive export`
  - `36565f9` `Adjust accountant export menu label and order`
  - `6b21419` `Add clickable file links to accountant manifest`
- Добавлено:
  - бухгалтерский ZIP export;
  - manifest со ссылками на файлы.
- Изменено / убрано:
  - menu export flow перестроен под inline-сценарий.

### v0.5.8.4
- Tag commit: `55c3f6e`
- Вошедшие ключевые изменения:
  - `ab11119` `Add accountant export periods and custom year`
  - `55c3f6e` `Filter accountant export by document date`
- Добавлено:
  - периоды и custom year для accountant export.
- Изменено / убрано:
  - фильтрация выгрузки переведена на `document_date`.

### v0.5.8.5
- Tag commit: `613fbce`
- Вошедшие ключевые изменения:
  - `2b5741f` `Add manager dashboard Excel export`
  - `deeb117` `Improve manager Excel export flow feedback`
  - `613fbce` `Confirm OCR.Space engine 2 for release`
- Добавлено:
  - manager dashboard Excel export;
  - UX feedback для Excel flow.
- Изменено / убрано:
  - OCR.Space engine 2 закреплен как release baseline.

### v0.5.8.6
- Tag commit: `7e963e2`
- Вошедшие ключевые изменения:
  - `dbaefb9` `Fix manager Excel period keyboard`
  - `592dccc` `Tighten manager Excel sheet widths`
  - `a56ff99` `Refine duplicate and registry Excel sheets`
  - `753b99a` `Fix Excel duplicate and registry row heights`
  - `7e963e2` `Trim registry Excel columns`
- Добавлено:
  - hardening и polishing manager Excel flow.
- Изменено / убрано:
  - лишняя ширина и шум в registry Excel сокращены.

### v0.5.8.7
- Commit: `a2029c4`
- Message: `Add filtered employee my documents flow`
- Добавлено:
  - отфильтрованный employee flow для `Мои документы`.
- Изменено / убрано:
  - self-view документов стал более управляемым.

### v0.5.8.8
- Tag commit: `efb9db0`
- Вошедшие ключевые изменения:
  - `3711985` `Add VAT fields database migration`
  - `05b3bc9` `Extend extraction prompt with VAT fields`
  - `cb0f896` `Add VAT fields to document schema`
  - `4dc2964` `Persist VAT fields with documents`
  - `efb9db0` `Add VAT columns to accountant manifest`
- Добавлено:
  - НДС-поля в БД, схеме, extraction и accountant manifest.
- Изменено / убрано:
  - документная модель стала VAT-aware.

### v0.5.8.9
- Tag commit: `4230a3b`
- Вошедшие ключевые изменения:
  - `db353fb` `Add VAT to manager Excel dashboard and registry`
  - `c8b35ea` `Add VAT amount KPI to manager dashboard`
  - `18a81ba` `Add VAT columns to manager dashboard tables`
  - `f16f9c1` `Add VAT columns to manager report sheets`
  - `c25f0ac` `Show VAT in document preview`
  - `4230a3b` `Add item VAT to manager registry sheet`
- Добавлено:
  - VAT в manager preview, dashboard и Excel sheets.
- Изменено / убрано:
  - preview и отчетность расширены НДС-данными.

### v0.5.8.10
- Commit: `ced18a0`
- Message: `Reuse shared HTTP clients for OCR and DeepSeek`
- Добавлено:
  - shared HTTP clients для OCR.Space и DeepSeek.
- Изменено / убрано:
  - убрано повторное создание клиентов по hot path.

### v0.5.8.11
- Tag commit: `dfc8c97`
- Вошедшие ключевые изменения:
  - `d2c8b72` `Move image preprocessing to shared executor`
  - `67a3ee1` `Move image and PDF preprocessing to shared executor`
  - `dfc8c97` `Move image and PDF preprocessing to shared executor`
- Добавлено:
  - shared executor для preprocessing image/PDF.
- Изменено / убрано:
  - preprocessing вынесен из handler hot path.

### v0.5.8.12
- Tag commit: `070baa1`
- Вошедшие ключевые изменения:
  - `a1cdaf5` `Add fiscalization flag to documents`
  - `7a2a55c` `Add fiscalization flag pipeline`
  - `070baa1` `Add fiscalization flag to document pipeline`
- Добавлено:
  - признак фискализации в document pipeline.
- Изменено / убрано:
  - схема и extraction расширены под фискальные признаки.

### v0.5.8.13
- Tag commit: `5dd0586`
- Вошедшие ключевые изменения:
  - `5d8ecf1` `Acknowledge manager invite callback immediately`
  - `5dd0586` `Fix invite schema after clean database reset`
- Добавлено:
  - устойчивость invite/reset scenario.
- Изменено / убрано:
  - исправлен post-reset schema contour.

### v0.5.8.14
- Commit: `03964df`
- Message: `Add backup restore scripts and docs`
- Добавлено:
  - backup script;
  - restore script;
  - bootstrap VPS script;
  - backup/restore docs.
- Изменено / убрано:
  - backup contour перестал быть только ad-hoc инструкцией.

### v0.5.8.15
- Tag commit: `d0c8e10`
- Вошедшие ключевые изменения:
  - `edb2294` `Make extraction prompt more conservative`
  - `6998509` `Filter bogus unnamed table items`
  - `c254ea7` `Detect mixed VAT in receipts more accurately`
  - `1d0f91a` `Normalize VAT scope before preview`
  - `31dc940` `Make mixed VAT detection OCR-tolerant`
  - `a418ecd` `Relax mixed VAT no-VAT signal matching`
  - `d0c8e10` `Drop unnamed numeric table rows more aggressively`
- Добавлено:
  - более консервативный extraction;
  - устойчивый mixed VAT detection;
  - фильтрация шумных unnamed строк.
- Изменено / убрано:
  - из preview и save flow вытеснен мусорный numeric tail рукописных накладных.

### v0.5.8.16
- Tag commit: `f925b94`
- Вошедшие ключевые изменения:
  - `fefef96` `Centralize temp cleanup in document upload flow`
  - `813eb9e` `Use shared temp cleanup in pending and file services`
  - `f925b94` `Use shared temp cleanup in export handlers`
- Добавлено:
  - единый temp cleanup utility.
- Изменено / убрано:
  - ручной scattered cleanup в handlers/services заметно сокращен.

### v0.5.8.17
- Tag commit: `14df2e9`
- Вошедшие ключевые изменения:
  - `7bc4914` `Add document processing service boundary`
  - `4ea35a0` `Move preview pipeline into document processing service`
  - `76ff9f9` `Move pending preview state into document processing service`
  - `5b0e554` `Move project selection flow into document processing service`
  - `d22ed38` `Move duplicate confirm save into document processing service`
  - `6b8f004` `Reject unsupported guest bills and payment invoices`
  - `14df2e9` `Slim document handler duplicate save callback`
- Добавлено:
  - `document_processing.py` как orchestration boundary;
  - semantic reject неподходящих документов.
- Изменено / убрано:
  - `handlers/documents.py` перестал быть центром document orchestration.

### v0.5.8.18
- Commit: `4d8aa32`
- Message: `Document document processing flow boundary`
- Добавлено:
  - `DOCUMENT_PROCESSING_FLOW.md` с flow map, DTO boundary и ownership rules.
- Изменено / убрано:
  - document-processing refactor formalized and closed as a documented architecture block.
