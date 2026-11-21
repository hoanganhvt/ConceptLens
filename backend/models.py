from .language import tr
from typing import Literal
from pydantic import BaseModel, Field, model_validator


class Topic(BaseModel):
    title: str = Field(min_length=1)
    goal: str = Field(min_length=1)


class Chapter(BaseModel):
    title: str
    topics: list[Topic] = Field(min_length=1)


class Roadmap(BaseModel):
    title: str
    goal: str
    chapters: list[Chapter] = Field(min_length=1)


class Section(BaseModel):
    title: str
    text: str = Field(min_length=1)


class Illustration(BaseModel):
    section: int = Field(ge=0)
    title: str
    instruction: str
    explanation: str
    mode: Literal["motion", "interactive"]
    html: str = Field(min_length=1, max_length=16000)
    css: str = Field(max_length=8000)
    js: str = Field(min_length=1, max_length=12000)


class Question(BaseModel):
    prompt: str
    kind: Literal["choice", "number"]
    choices: list[str]
    answer: str
    explanation: str

    @model_validator(mode="after")
    def valid_answer(self):
        if self.kind == "choice" and (len(set(self.choices)) < 2 or self.answer not in self.choices):
            raise ValueError(tr("Đáp án phải nằm trong các lựa chọn.", "The answer must match one of the choices."))
        if self.kind == "number":
            from .physics import quantity
            quantity(self.answer)
        return self


class Lesson(BaseModel):
    intro: str
    sections: list[Section] = Field(min_length=1)
    illustrations: list[Illustration] = Field(min_length=1)
    quiz: list[Question] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_sections(self):
        if any(item.section >= len(self.sections) for item in self.illustrations):
            raise ValueError(tr("Minh họa phải thuộc một mục của bài.", "Each illustration must belong to a lesson section."))
        return self


class Motion(BaseModel):
    acceleration: float = Field(default=9.81, ge=-100, le=100)
    velocity: float = Field(default=0, ge=-100, le=100)
    duration: float = Field(default=4, ge=0.1, le=60)

