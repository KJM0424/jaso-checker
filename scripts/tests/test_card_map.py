import re
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[2]
FORMATS = SKILL / "references/formats.md"
CARDS = SKILL / "cards"  # 레퍼런스 카드는 이 저장소에 없다. 카드 폴더를 두면 파일 대응까지 검사한다
TYPES = ["직무역량", "문제해결", "협업", "갈등", "실패", "리더십", "성장", "지원동기", "포부"]


def card_map():
    text = FORMATS.read_text(encoding="utf-8")
    section = text.split("## 유형별 레퍼런스 카드", 1)[1].split("\n## ", 1)[0]
    rows = [l.split("|")[1:-1] for l in section.splitlines() if l.startswith("|") and not l.startswith(("| 유형", "|---"))]
    return {r[0].strip(): re.findall(r"`([^`]+\.md)`", r[1]) for r in rows}


def test_every_type_has_a_row():
    assert sorted(card_map()) == sorted(TYPES)


def test_every_named_card_exists():
    if not CARDS.is_dir():
        pytest.skip("레퍼런스 카드 폴더 없음")
    for qtype, cards in card_map().items():
        for c in cards:
            assert (CARDS / c).is_file(), f"{qtype}: {c}"
