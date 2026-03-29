from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

HELP_MENU_PREFIX = "help:menu:"
HELP_TOPIC_PREFIX = "help:topic:"

OWNER_HELP_TOPICS = [
    ("owner_create_company", "🏢 Создать компанию"),
    ("owner_manager_invite", "👤 Назначить первого руководителя"),
    ("owner_users_and_roles", "👥 Пользователи и роли"),
    ("owner_block_unblock_user", "⛔ Блокировка и доступ"),
    ("owner_company_archive", "📦 Архивация компании"),
    ("owner_no_documents", "📄 Почему owner без документов"),
    ("owner_system_status", "📊 Статус системы"),
]

MANAGER_HELP_TOPICS = [
    ("manager_upload_document", "📥 Загрузить документ"),
    ("manager_supported_documents", "📄 Какие документы подходят"),
    ("manager_project_selection", "📁 Выбор проекта"),
    ("manager_create_project", "🆕 Создать проект"),
    ("manager_archive_project", "🗂 Архивный проект"),
    ("manager_invite_employee", "👥 Пригласить сотрудника"),
    ("manager_block_employee", "⛔ Заблокировать сотрудника"),
    ("manager_my_documents", "📄 Мои документы"),
    ("manager_duplicates", "⚠️ Дубли"),
    ("manager_reports", "📊 Отчеты"),
    ("manager_accountant_export", "🧾 Архив для бухгалтера"),
    ("manager_document_errors", "❗ Ошибки документа"),
]

EMPLOYEE_HELP_TOPICS = [
    ("employee_upload_document", "📥 Загрузить документ"),
    ("employee_supported_documents", "📄 Какие документы подходят"),
    ("employee_choose_project", "📁 Как выбрать проект"),
    ("employee_my_documents", "📄 Мои документы"),
    ("employee_document_items", "📋 Позиции документа"),
    ("employee_no_project", "❓ Нет нужного проекта"),
    ("employee_invite_problem", "🔑 Проблема с invite-кодом"),
    ("employee_document_errors", "❗ Ошибка обработки документа"),
    ("employee_contact_manager", "🆘 Когда обращаться к руководителю"),
]

HELP_TOPICS = {
    "platform_owner": dict(OWNER_HELP_TOPICS),
    "manager": dict(MANAGER_HELP_TOPICS),
    "employee": dict(EMPLOYEE_HELP_TOPICS),
}

HELP_TOPIC_ALIASES = {
    "platform_owner": {
        "owner_assign_manager": "owner_manager_invite",
        "owner_no_projects": "owner_no_documents",
    },
    "manager": {
        "manager_remove_employee": "manager_block_employee",
        "manager_document_problem": "manager_document_errors",
    },
    "employee": {},
}

HELP_TEXTS = {
    "platform_owner": {
        "owner_create_company": "Создайте компанию и укажите ее название. После создания бот выдаст invite-код для первого руководителя. Компания появится в разделе «Компании».",
        "owner_manager_invite": "Первый руководитель подключается по invite-коду. Если код утерян или не использован, его можно показать заново, сбросить или перевыпустить в карточке компании.",
        "owner_users_and_roles": "В разделе «Пользователи» можно посмотреть карточку пользователя и при необходимости привязать его к компании как manager или employee. Это используется для ручного управления доступом.",
        "owner_block_unblock_user": "Если нужно закрыть доступ к компании, пользователя можно заблокировать. Позже доступ можно восстановить. Документы и история при этом не удаляются.",
        "owner_company_archive": "Архивация закрывает компанию для дальнейшей работы. Используйте ее для неактуальных или отключенных клиентов.",
        "owner_no_documents": "Owner управляет системой, компаниями и доступами. Загрузка документов, проекты и отчеты — рабочая зона manager и сотрудников внутри компании.",
        "owner_system_status": "Статус системы показывает сводные цифры: пользователей, компаний, managers, employees, проектов и документов. Это быстрый общий контроль по системе.",
        "owner_invite_problem": "Если invite-код не сработал, откройте карточку компании и покажите, сбросьте или перевыпустите код заново.",
        "owner_support": "Если вопрос не связан с компанией или доступом, проверьте общий статус системы и текущую карточку пользователя.",
    },
    "manager": {
        "manager_upload_document": "Отправьте фото или PDF документа. Бот распознает текст, соберет данные и покажет preview. После этого нужно выбрать проект для сохранения.",
        "manager_supported_documents": "Лучше всего подходят кассовые чеки, БСО, накладные, акты, УПД, транспортные накладные и РКО. Счета на оплату и гостевые счета без фискального чека не сохраняются как затраты.",
        "manager_project_selection": "После preview бот показывает список активных проектов. Без выбора проекта документ не сохранится. Если нужного проекта нет, сначала создайте его.",
        "manager_create_project": "Проект можно создать в разделе «Проекты» или прямо во время сохранения документа. Там же доступно переименование проекта.",
        "manager_archive_project": "Архивный проект остается в системе, но новые документы в него не сохраняются. Используйте архив для завершенных проектов, которые нужно сохранить в истории.",
        "manager_invite_employee": "В разделе «Сотрудники» можно выдать invite-код сотруднику. После входа он подключится к вашей компании и сможет загружать документы в доступные проекты.",
        "manager_block_employee": "Сотрудника можно заблокировать или восстановить. Это закрывает или возвращает доступ к компании, но уже сохраненные документы остаются в системе.",
        "manager_my_documents": "В разделе «Мои документы» доступны ваши загруженные документы. Можно открыть карточку документа, посмотреть позиции и перейти к оригиналу.",
        "manager_duplicates": "Если система находит точный или вероятный дубль, бот предупреждает об этом перед сохранением. Можно отменить загрузку или сохранить документ принудительно.",
        "manager_reports": "В отчетах доступны сводки по проектам, сотрудникам и дублям. Также можно собрать Excel-отчет по выбранному периоду.",
        "manager_accountant_export": "Для бухгалтера можно собрать архив чеков за неделю, месяц, квартал или год. Бот подготовит файл и отправит его отдельным сообщением.",
        "manager_document_errors": "Если документ не обработался, проверьте качество фото, формат файла и размер. Поддерживаются изображения и PDF. Если у вас уже есть незавершенный документ, сначала завершите его сохранение или отмените загрузку.",
        "manager_employee_limit": "Если сотрудник не подключается, проверьте актуальность invite-кода, статус компании и доступность сотрудника в списке компании.",
        "manager_support": "Если проблема не решается стандартным сценарием, проверьте роль пользователя, статус компании и последние действия в карточке сотрудника или документа.",
    },
    "employee": {
        "employee_upload_document": "Отправьте фото или PDF документа. Бот распознает данные, покажет preview и предложит выбрать проект. После выбора проекта документ будет сохранен.",
        "employee_supported_documents": "Подходят фото документов целиком и PDF без защиты. Лучше всего работают чеки и другие первичные документы с хорошо читаемым текстом.",
        "employee_choose_project": "После обработки бот покажет список доступных проектов кнопками. Выберите нужный проект — без этого документ не сохранится.",
        "employee_my_documents": "В разделе «Мои документы» можно посмотреть свои последние документы. Там доступен просмотр карточки и позиций документа.",
        "employee_document_items": "Если у документа есть позиции, их можно открыть из карточки документа. Это помогает проверить, что именно было распознано и сохранено.",
        "employee_no_project": "Если нужного проекта нет в списке, вы не сможете создать его самостоятельно. Обратитесь к руководителю компании.",
        "employee_invite_problem": "Invite-код может не сработать, если он введен с ошибкой, истек или был сброшен. Попросите у руководителя новый код.",
        "employee_document_errors": "Если бот не смог обработать файл, попробуйте отправить более четкое фото или PDF. Также ошибка возможна, если предыдущий документ еще не завершен.",
        "employee_contact_manager": "К руководителю нужно обращаться, если нет доступа к компании, не видно проекта или нужен новый invite-код. Управление проектами и сотрудниками доступно только manager.",
    },
}


def build_help_topics_keyboard(menu_kind: str) -> InlineKeyboardMarkup:
    topics = HELP_TOPICS.get(menu_kind, HELP_TOPICS["employee"])
    rows = [
        [InlineKeyboardButton(text=title, callback_data=f"{HELP_TOPIC_PREFIX}{menu_kind}:{topic_id}")]
        for topic_id, title in topics.items()
    ]
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="nav:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_help_topic_keyboard(menu_kind: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"{HELP_MENU_PREFIX}{menu_kind}")],
        ]
    )


def get_help_topic_text(menu_kind: str, topic_id: str) -> str | None:
    role_topics = HELP_TEXTS.get(menu_kind, {})
    text_value = role_topics.get(topic_id)
    if text_value is not None:
        return text_value
    alias_topic_id = HELP_TOPIC_ALIASES.get(menu_kind, {}).get(topic_id)
    if alias_topic_id is None:
        return None
    return role_topics.get(alias_topic_id)
