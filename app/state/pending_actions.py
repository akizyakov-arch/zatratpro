from dataclasses import dataclass, field


@dataclass(slots=True)
class PendingAction:
    action: str
    payload: dict[str, str | int] = field(default_factory=dict)


_pending_actions: dict[int, PendingAction] = {}


def set_pending_action(telegram_user_id: int, action: str, payload: dict[str, str | int] | None = None) -> None:
    _pending_actions[telegram_user_id] = PendingAction(action=action, payload=payload or {})


def get_pending_action(telegram_user_id: int) -> PendingAction | None:
    return _pending_actions.get(telegram_user_id)


def pop_pending_action(telegram_user_id: int) -> PendingAction | None:
    return _pending_actions.pop(telegram_user_id, None)
