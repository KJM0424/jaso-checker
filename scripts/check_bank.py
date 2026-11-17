"""경험 뱅크 형식 검사기.

07_경험뱅크/의 경험 파일(앞부분 + `## XX-NN 제목` 장면 + `### 칸`)과 00_색인.md를 검사한다.
표준 라이브러리만 쓴다.

사용:
    python3 check_bank.py 07_경험뱅크
"""

from __future__ import annotations

import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

SCENE_FIELDS = ["문항유형", "상황", "본인행동", "결과", "한계", "역할경계", "고유디테일", "각도", "금지", "꼬리질문", "본인기억", "상태"]
EVIDENCE_FIELDS = ["상황", "본인행동", "결과", "한계", "고유디테일"]
EVIDENCE_RE = re.compile(r"\[(원본|분석|본인 기억)[^\]]*\]")
QUESTION_TYPES = {"직무역량", "문제해결", "협업", "갈등", "실패", "리더십", "성장"}
STATUSES = {"확정", "본인확인필요"}
SCENE_HEAD_RE = re.compile(r"^## ([A-Z]{2}-\d{2})\s+(.*)$")
FIELD_HEAD_RE = re.compile(r"^### (.+?)\s*$")
INDEX_FILE = "00_색인.md"


@dataclass
class Scene:
    id: str
    title: str
    fields: dict[str, str] = field(default_factory=dict)
    file: str = ""


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def parse_front_matter(text: str) -> dict[str, str | list[str]]:
    """`---` 사이의 `키: 값`과 그 아래 `- 항목` 목록만 읽는다."""
    out: dict[str, str | list[str]] = {}
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return out
    key = None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.startswith("- ") and key is not None:
            cur = out.get(key)
            if not isinstance(cur, list):
                cur = []
                out[key] = cur
            cur.append(line[2:].strip())
        elif ":" in line and not line.startswith(" "):
            key, _, val = line.partition(":")
            key = key.strip()
            out[key] = val.strip()
    return out


def _split_front(text: str) -> tuple[str, str]:
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return "\n".join(lines[: i + 1]), "\n".join(lines[i + 1 :])
    return "", text


def parse_bank_file(path: Path) -> tuple[dict, list[Scene]]:
    text = path.read_text(encoding="utf-8")
    front_text, body = _split_front(text)
    front = parse_front_matter(front_text)
    scenes: list[Scene] = []
    cur: Scene | None = None
    cur_field: str | None = None
    for line in body.splitlines():
        m = SCENE_HEAD_RE.match(line)
        if m:
            cur = Scene(id=m.group(1), title=m.group(2).strip(), file=_nfc(path.name))
            scenes.append(cur)
            cur_field = None
            continue
        if cur is None:
            continue
        f = FIELD_HEAD_RE.match(line)
        if f:
            cur_field = f.group(1)
            cur.fields[cur_field] = ""
            continue
        if cur_field is not None:
            cur.fields[cur_field] = (cur.fields[cur_field] + "\n" + line).strip("\n")
    for s in scenes:
        s.fields = {k: v.strip() for k, v in s.fields.items()}
    return front, scenes


def check_scene(s: Scene) -> list[str]:
    problems: list[str] = []
    for f in SCENE_FIELDS:
        if f not in s.fields:
            problems.append(f"missing field: {f}")
    for f in EVIDENCE_FIELDS:
        val = s.fields.get(f, "")
        if val and not EVIDENCE_RE.search(val):
            problems.append(f"no evidence: {f}")
    status = s.fields.get("상태", "")
    if "상태" in s.fields and status not in STATUSES:
        problems.append("bad status")
    types = [t.strip() for t in re.split(r"[,、，/]", s.fields.get("문항유형", "")) if t.strip()]
    for t in types:
        if t not in QUESTION_TYPES:
            problems.append(f"bad type: {t}")
    return problems


def _index_rows(index_path: Path) -> list[tuple[str, str]]:
    """색인 표에서 (ID, 파일) 목록. 헤더가 `| ID |`로 시작하는 표만 읽는다."""
    rows: list[tuple[str, str]] = []
    if not index_path.exists():
        return rows
    in_table = False
    file_col = None
    for line in index_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("| ID |"):
            in_table = True
            cols = [c.strip() for c in line.strip("|").split("|")]
            file_col = cols.index("파일") if "파일" in cols else None
            continue
        if in_table:
            if not line.startswith("|"):
                in_table = False
                continue
            cols = [c.strip() for c in line.strip("|").split("|")]
            if not cols or set(cols[0]) <= {"-", ":"}:
                continue
            fname = cols[file_col] if file_col is not None and file_col < len(cols) else ""
            rows.append((cols[0], fname))
    return rows


def check_bank(bank_dir: Path) -> list[str]:
    problems: list[str] = []
    seen: dict[str, str] = {}
    all_ids: set[str] = set()
    for p in sorted(bank_dir.glob("*.md")):
        name = _nfc(p.name)
        if name == INDEX_FILE or name.startswith("_"):
            continue
        _, scenes = parse_bank_file(p)
        for s in scenes:
            for prob in check_scene(s):
                problems.append(f"{name} {s.id}: {prob}")
            if s.id in seen:
                problems.append(f"duplicate id: {s.id}")
            seen[s.id] = name
            all_ids.add(s.id)
    index_ids: set[str] = set()
    for sid, fname in _index_rows(bank_dir / INDEX_FILE):
        index_ids.add(sid)
        if sid not in all_ids:
            problems.append(f"index: unknown id: {sid}")
        elif fname and _nfc(fname) != seen[sid]:
            problems.append(f"index: file mismatch: {sid} ({fname} != {seen[sid]})")
    for sid in sorted(all_ids - index_ids):
        problems.append(f"index: missing id: {sid}")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("사용: check_bank.py <뱅크 폴더>")
        return 2
    problems = check_bank(Path(argv[0]))
    if problems:
        print("\n".join(problems))
        print(f"FAIL ({len(problems)})")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
