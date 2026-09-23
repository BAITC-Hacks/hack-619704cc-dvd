"""Strict, versioned interchange format. Skill values are current snapshots."""
import json
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Identifier = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_-]{1,64}$")]
Label = Annotated[str, StringConstraints(min_length=1, max_length=120)]
Score = Annotated[int, Field(strict=True, ge=0, le=100)]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Requirement(Record):
    target: Annotated[int, Field(strict=True, ge=1, le=100)]
    weight: Annotated[int, Field(strict=True, ge=1, le=5)] = 1
    critical: bool = False


class Employee(Record):
    id: Identifier
    name: Label
    role: Label
    grade: Label
    next_grade: Label
    tenure_months: Annotated[int, Field(ge=12, le=60)]
    skills: dict[Label, Score] = Field(min_length=1, max_length=30)
    requirements: dict[Label, Requirement] = Field(min_length=1, max_length=30)
    preferred_formats: list[Label] = Field(default_factory=list, max_length=10)
    opted_in: bool = True

    @model_validator(mode="after")
    def required_skills_exist(self):
        if not self.requirements.keys() <= self.skills.keys():
            raise ValueError("Для каждого требования нужен текущий уровень навыка")
        if self.grade == self.next_grade:
            raise ValueError("Следующий грейд должен отличаться от текущего")
        return self


class Activity(Record):
    id: Identifier
    title: Label
    format: Label
    grades: list[Label] = Field(min_length=1, max_length=10)
    gains: dict[Label, Annotated[int, Field(ge=1, le=30)]] = Field(min_length=1, max_length=10)
    prerequisites: dict[Label, Score] = Field(default_factory=dict, max_length=30)
    minutes: Annotated[int, Field(ge=5, le=480)]
    xp: Annotated[int, Field(ge=0, le=300)]
    due_days: Annotated[int, Field(ge=1, le=90)] = 14
    voluntary: bool = True


class History(Record):
    employee_id: Identifier
    activity_id: Identifier
    status: Literal["completed", "missed", "declined", "started"]
    date: Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")]
    due_date: str | None = None
    xp: Annotated[int, Field(ge=0, le=360)] = 0

    @model_validator(mode="after")
    def valid_dates(self):
        date.fromisoformat(self.date)
        if self.due_date:
            date.fromisoformat(self.due_date)
        return self


class Dataset(Record):
    schema_version: Literal[1]
    synthetic: Literal[True]
    employees: list[Employee] = Field(min_length=1, max_length=200)
    activities: list[Activity] = Field(min_length=1, max_length=200)
    history: list[History] = Field(default_factory=list, max_length=5000)

    @model_validator(mode="after")
    def references(self):
        employees = {p.id for p in self.employees}
        activities = {a.id for a in self.activities}
        catalog = {a.id: a for a in self.activities}
        if len(employees) != len(self.employees) or len(activities) != len(self.activities):
            raise ValueError("Повторяющиеся ID сотрудников или активностей")
        states = {}
        for h in self.history:
            if h.employee_id not in employees or h.activity_id not in activities:
                raise ValueError("История ссылается на неизвестный профиль или активность")
            if h.xp and (h.status != "completed" or not catalog[h.activity_id].voluntary):
                raise ValueError("XP допустимы только за завершённую добровольную активность")
            pair = (h.employee_id, h.activity_id)
            if h.status in {"completed", "started"}:
                if pair in states:
                    raise ValueError("У пары сотрудник/активность может быть только одно текущее состояние started/completed")
                states[pair] = h.status
        return self


def parse_dataset(raw: bytes) -> dict:
    if len(raw) > 2_000_000:
        raise ValueError("Датасет должен быть меньше 2 МБ")
    return Dataset.model_validate(json.loads(raw.decode("utf-8-sig"))).model_dump()
