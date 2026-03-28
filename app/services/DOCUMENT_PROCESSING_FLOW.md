# Document Processing Flow

## Purpose

`app/services/document_processing.py` is the orchestration boundary for document intake.

It is intentionally not Telegram-specific:
- no `message.answer(...)`
- no keyboard building
- no UI copy ownership

Telegram handlers remain responsible for:
- reading updates and callback payloads
- access and upload-entry checks
- user-facing texts
- Telegram markup

## Current Service Responsibilities

`DocumentProcessingService` owns:
- OCR orchestration with retry
- extraction orchestration
- semantic unsupported-document reject after extraction
- preview preparation
- pending preview state ownership
- duplicate-check orchestration on project selection
- immediate save vs duplicate-warning decision
- duplicate-confirm save orchestration

## Result Objects

Preview stage:
- `DocumentOCRReady`
- `DocumentPreviewReady`
- `DocumentPreviewFailure`

Project-selection stage:
- `DocumentProjectSelectionDuplicate`
- `DocumentProjectSelectionSaved`
- `DocumentProjectSelectionFailure`

Duplicate-confirm save stage:
- `DocumentDuplicateSaveSuccess`
- `DocumentDuplicateSaveFailure`

These DTOs are the stable boundary between the service layer and
`app/handlers/documents.py`.

## Flow Map

### 1. Upload -> Preview

Handler responsibilities:
- validate access
- reject unsupported file formats and oversize uploads
- download photo / image / PDF first page
- send progress messages

Service responsibilities:
- `begin_pending_preview(...)`
- `run_ocr(...)`
- `build_preview_from_ocr(...)`
- `store_pending_preview(...)`

Outputs:
- preview ready
- OCR failure
- extraction failure
- semantic unsupported-document failure
- pending-state failure

### 2. Preview -> Project Selection

Handler responsibilities:
- parse callback payload
- load project
- show duplicate warning or save confirmation text

Service responsibilities:
- `resolve_project_selection(...)`
- duplicate check
- save immediately when there is no blocking duplicate branch
- store updated pending state when duplicate confirmation is required

Outputs:
- duplicate warning
- saved
- project-selection failure

### 3. Duplicate Warning -> Confirm Save

Handler responsibilities:
- callback entry
- fetch project for the already selected pending document
- show final success or error text

Service responsibilities:
- `save_duplicate_confirmed(...)`
- final save after duplicate confirmation
- pending-flow cleanup on success

Outputs:
- duplicate save success
- duplicate save failure

## Temp File Ownership

`PreparedUpload` defines the ownership rules:
- only temp files from `tmp/` belong here
- `source_temp_path` is always cleaned by the processing service
- `ocr_temp_path` is cleaned by the processing service on preview failure
- on preview success, ownership of `ocr_temp_path` transfers to pending state
- persistent files from `storage/` must never be passed here

This keeps cleanup deterministic and prevents handlers from managing temp-file
lifecycle directly.

## Semantic Reject Gate

The service now performs a deterministic post-extraction check before preview:
- guest bill / precheck style documents are rejected
- payment invoices are rejected

Current reasons:
- `unsupported_guest_bill`
- `unsupported_payment_invoice`

Handlers only map these reasons to user-facing messages.

## Changelog Of The Refactor

Moved out of `app/handlers/documents.py`:
- service boundary and DTOs
- OCR retry and timeout orchestration
- extraction orchestration
- preview text preparation
- pending preview state begin/store
- duplicate-check orchestration
- immediate save on project selection
- duplicate-confirm save orchestration
- semantic unsupported-document gate

Remaining in `app/handlers/documents.py`:
- Telegram entry points
- callback parsing
- access checks
- upload type and size checks
- progress / error / success messages
- keyboard selection

## Why This Boundary Matters

The current split prepares the codebase for:
- channel-agnostic intake in the future
- cheaper regression testing around document scenarios
- routing by document family without growing the handler again
- further OCR / extraction performance work inside one service boundary
