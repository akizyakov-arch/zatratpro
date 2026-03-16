from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

HELP_MENU_PREFIX = "help:menu:"
HELP_TOPIC_PREFIX = "help:topic:"

OWNER_HELP_TOPICS = [
    ("owner_create_company", "🏢 Создать компанию"),
    ("owner_assign_manager", "👤 Назначить руководителя"),
    ("owner_no_projects", "❓ Почему нет проектов"),
    ("owner_invite_problem", "🔑 Проблема с кодом"),
    ("owner_support", "🆘 Поддержка"),
]

MANAGER_HELP_TOPICS = [
    ("manager_upload_document", "📥 Загрузить документ"),
    ("manager_create_project", "📁 Создать проект"),
    ("manager_invite_employee", "👥 Пригласить сотрудника"),
    ("manager_remove_employee", "🗑 Удалить сотрудника"),
    ("manager_document_problem", "⚠️ Проблема с документом"),
    ("manager_employee_limit", "👥 Лимит сотрудников"),
    ("manager_support", "🆘 Поддержка"),
]

EMPLOYEE_HELP_TOPICS = [
    ("employee_upload_document", "📥 Загрузить документ"),
    ("employee_choose_project", "📁 Выбрать проект"),
    ("employee_my_documents", "📄 Мои документы"),
    ("employee_no_project", "❓ Нет нужного проекта"),
    ("employee_invite_problem", "🔑 Проблема с кодом"),
    ("employee_contact_manager", "🆘 Обратиться к руководителю"),
]

HELP_TOPICS = {
    "platform_owner": dict(OWNER_HELP_TOPICS),
    "manager": dict(MANAGER_HELP_TOPICS),
    "employee": dict(EMPLOYEE_HELP_TOPICS),
}

HELP_TEXTS = {
    "platform_owner": {
        "owner_create_company": "Создайте компанию и передайте код приглашения будущему руководителю.\nПосле входа он сможет управлять проектами и сотрудниками.",
        "owner_assign_manager": "Откройте компанию, выдайте код приглашения и передайте его человеку.\nПосле входа он станет руководителем компании.",
        "owner_no_projects": "Владелец системы не работает с проектами.\nПроекты доступны только внутри компаний их руководителям и сотрудникам.",
        "owner_invite_problem": "Код может не работать, если он:\n\n- уже использован\n- истёк\n- был сброшен\n- введён с ошибкой\n\nВыдайте новый код приглашения.",
        "owner_support": "Если проблема не решается — обратитесь к администратору системы.",
    },
    "manager": {
        "manager_upload_document": "Отправьте фото документа.\nПосле обработки выберите проект — документ будет сохранён.",
        "manager_create_project": "Откройте раздел «Проекты» и нажмите «Создать проект».\nТакже проект можно создать во время загрузки документа.",
        "manager_invite_employee": "Откройте «Сотрудники» → «Пригласить».\nПередайте сотруднику код — он войдёт в компанию.",
        "manager_remove_employee": "Выберите сотрудника в списке и нажмите «Исключить».\nОн потеряет доступ к данным компании.",
        "manager_document_problem": "Проверьте:\n\n- выбран ли проект\n- проект не архивный\n- фото читаемое\n\nЕсли не помогло — отправьте документ повторно.",
        "manager_employee_limit": "В компании может быть не более 10 сотрудников.\nЧтобы добавить нового — сначала удалите одного из текущих.",
        "manager_support": "Если проблема не решается — обратитесь к владельцу системы или в поддержку.",
    },
    "employee": {
        "employee_upload_document": "Отправьте фото документа.\nПосле обработки выберите проект и подтвердите сохранение.",
        "employee_choose_project": "После загрузки документа бот покажет доступные проекты кнопками.\nВыберите нужный.",
        "employee_my_documents": "В разделе отображаются ваши последние документы.\nДоступен только просмотр.",
        "employee_no_project": "Сотрудник не может создавать проекты.\nОбратитесь к руководителю — он добавит проект.",
        "employee_invite_problem": "Код может не работать, если он:\n\n- уже использован\n- истёк\n- введён с ошибкой\n\nПопросите новый код у руководителя.",
        "employee_contact_manager": "Если что-то не работает — обратитесь к руководителю компании.",
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
    return HELP_TEXTS.get(menu_kind, {}).get(topic_id)
