from pathlib import Path
from .language import tr


PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"


def prompt(*names: str) -> str:
    return "\n\n".join(
        (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8").strip().replace("{language}", tr("Vietnamese", "English"))
        for name in names
    )
