from contextvars import ContextVar


language = ContextVar("study_language", default="vi")


def tr(vi: str, en: str) -> str:
    return en if language.get() == "en" else vi
