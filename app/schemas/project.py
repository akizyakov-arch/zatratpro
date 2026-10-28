from dataclasses import dataclass


@dataclass(slots=True)
class Project:
    id: int
    company_id: int
    name: str
    status: str

    @property
    def is_archived(self) -> bool:
        return self.status == "archived"


