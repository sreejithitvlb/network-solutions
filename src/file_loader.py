import re
import tomllib
from pathlib import Path
from typing import Any

from models import Database, Manual, ManualSection

MANUAL_PATH: Path = Path(__file__).parents[1] / "datasource" / "tech_support_manual.md"
HEADING_PATTERN: re.Pattern[str] = re.compile(r"(?m)^(#{1,6}) (.+)$")


# Journeys 1, 2 and 3
def load_database(path: Path) -> Database:
    with path.open("rb") as f:
        raw: dict[str, Any] = tomllib.load(f)
    return Database.model_validate(raw)


# Journey 2
def load_manual(path: Path) -> Manual:
    """Split the manual at every heading. Each section gets a key (S1, S2, ...) and its path of parent headings."""
    text: str = path.read_text(encoding="utf-8")
    matches: list[re.Match[str]] = list(HEADING_PATTERN.finditer(text))
    titles: list[str] = []
    sections: dict[str, ManualSection] = {}
    for number, match in enumerate(matches, start=1):
        level: int = len(match.group(1))
        heading: str = match.group(2)
        del titles[level - 1 :]
        titles.append(heading)
        body_end: int = matches[number].start() if number < len(matches) else len(text)
        key: str = f"S{number}"
        sections[key] = ManualSection(
            key=key,
            heading=heading,
            path=" > ".join(titles),
            text=text[match.end() : body_end].strip(),
        )
    return Manual(sections=sections)
