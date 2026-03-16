from dataclasses import dataclass


@dataclass(slots=True)
class PendingAction:
    action: str


_pending_actions: dict[int, PendingAction] = {}


def set_pending_action(telegram_user_id: int, action: str) -> None:
    _pending_actions[telegram_user_id] = PendingAction(action=action)


def get_pending_action(telegram_user_id: int) -> PendingAction | None:
    return _pending_actions.get(telegram_user_id)


def pop_pending_action(telegram_user_id: int) -> PendingAction | None:
    return _pending_actions.pop(telegram_user_id, None)
