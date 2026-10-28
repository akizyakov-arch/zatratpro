"""Company result shared by all identity adapters."""
from dataclasses import dataclass

@dataclass(slots=True)
class Company:
    id: int
    name: str
    status: str
    owner_user_id: int | None = None
    manager_user_id: int | None = None

    @property
    def is_active(self) -> bool:
        return self.status == "active"
