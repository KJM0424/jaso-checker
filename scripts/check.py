"""자소서 초안 검사기 (정해진 답이 있는 검사만).

초안 형식(references/formats.md와 같다):
    ## 문항 1: 제목
    <!-- limit: 500, unit: chars, spaces: include -->      (bytes면 hangul: 2 또는 3 추가)
    ### 본문
    문장들
    ### 근거
    | 사실 | 장면 | 근거 | 유형 |
    | 30개 중 7개 | SC-02 | [원본: ...] | 사실 |

오류(통과를 막음): 분량, 금지 표현, 사실 행 없는 숫자, 본문에 없는 사실 구절, 없는 장면,
장면에 없는 근거, 출처 불명, 미승인 제안, 장면 중복.
경고(통과를 막지 않음): 수치 개수, 어미·시작어 반복, 문장 길이 균일, 접속어, 문항 간 겹침, 말투.

사용:
    python3 check.py <초안.md> --bank 07_경험뱅크 --ledger 01_나/사실원장.md --rules 08_작성규칙/작성규칙.md --style 01_나/말투.md
"""

from __future__ import annotations

import argparse
import re
import statistics
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from check_bank import EVIDENCE_RE, INDEX_FILE, parse_bank_file

QUESTION_RE = re.compile(r"^## 문항 (\d+)\s*[:：]?\s*(.*)$")
LIMIT_RE = re.compile(r"<!--\s*(.*?)\s*-->")
QUOTE_RE = re.compile(r'"([^"]+)"')
LATIN_UNIT = r"(?:ms|ns|us|s|MB|GB|KB|TB|k|K|x|cm|px|fps|TPS|QPS)"  # 300ms, 26MB처럼 숫자에 붙어도 수치로 본다
NUMBER_RE = re.compile(rf"(?<![A-Za-z0-9.,-])\d[\d,.]*(?={LATIN_UNIT}?(?![A-Za-z0-9]))")
LATIN_UNIT_RE = re.compile(rf"{LATIN_UNIT}(?![A-Za-z0-9])")
TAGS_RE = re.compile(rf"(?:{EVIDENCE_RE.pattern}\s*)+")
KINDS = ("사실", "제안", "승인")
NO_UNIT = set(" \t\n.,;:!?()[]\"'~-")
CELL_SPLIT_RE = re.compile(r"(?<!\\)\|")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
CONNECTIVE_RE = re.compile(r"(?:^|\s)(또한|그리고|특히|따라서)(?=\s|,)")
DATE_RE = re.compile(r"\d{4}년|\d{1,2}월(?:\s?\d{1,2}일)?|(?<![\d월])\d{1,2}일")
MIN_RATIO = 0.9
KNOWN_SOURCES = ("1_공고_전형", "2_기업분석", "사실원장", "나의말", "사용자 답변")
ENDING_LEN = 5  # 존댓말은 끝 3글자가 늘 "습니다"라서 5글자로 본다
UNIFORM_CV = 0.2
NUMBER_REQUIRED_TYPES = {"직무역량", "문제해결"}  # 그 밖의 유형은 수치가 선택 (레퍼런스 카드 1109)
OVERLAP_LEN = 12  # 참고 인용과 공백 없이 이만큼 이어서 같으면 표절 위험


@dataclass
class EvidenceRow:
    fact: str
    scene: str
    tag: str
    kind: str


@dataclass
class Question:
    number: int
    title: str = ""
    limit: int | None = None
    unit: str = "chars"
    spaces: str = "include"
    hangul: int = 3
    body: str = ""
    evidence: list[EvidenceRow] = field(default_factory=list)
    old_format: bool = False
    qtype: str = ""


@dataclass
class CheckResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE_SPLIT_RE.split(text.strip()) if s.strip()]


def count_length(text: str, unit: str, spaces: str, hangul: int = 3) -> int:
    if spaces == "exclude":
        text = re.sub(r"\s", "", text)
    if unit == "bytes":
        return sum(1 if ord(c) < 128 else hangul for c in text)
    return len(text)


def numbers_in(text: str) -> list[str]:
    return [m.group(0).rstrip(".,") for m in NUMBER_RE.finditer(text)]


def number_keys(text: str) -> list[str]:
    """숫자와 바로 뒤 단위(한 글자 또는 영문 단위). '30개 중 7개' 행이 '팀 7명'의 7까지 덮지 않게 한다."""
    keys = []
    for m in NUMBER_RE.finditer(text):
        value = m.group(0).rstrip(".,")
        pos = m.start() + len(value)
        unit = LATIN_UNIT_RE.match(text, pos)
        if unit:
            keys.append(value + unit.group(0))
        elif pos < len(text) and text[pos] not in NO_UNIT:
            keys.append(value + text[pos])
        else:
            keys.append(value)
    return keys


def _quotes_in_section(lines: list[str], start_pat: str, stop_pat: str, line_filter=None) -> list[str]:
    out: list[str] = []
    active = False
    for line in lines:
        if re.match(start_pat, line):
            active = True
            continue
        if active and re.match(stop_pat, line):
            active = False
        if active and (line_filter is None or line_filter(line)):
            out.extend(QUOTE_RE.findall(line))
    return out


def forbidden_entries(ledger: Path, bank_dir: Path, rules: Path) -> list[tuple[str, str]]:
    """(표현, 출처) 목록. 같은 표현이 여러 장면에 있으면 출처마다 한 줄씩."""
    out: list[tuple[str, str]] = []
    if ledger.exists():
        lines = ledger.read_text(encoding="utf-8").splitlines()
        for phrase in _quotes_in_section(lines, r"^## 10\.", r"^## ", lambda l: l.startswith("- [금지]")):
            out.append((phrase, "사실원장 10절"))
    if bank_dir.exists():
        for p in sorted(bank_dir.glob("*.md")):
            if p.name.startswith("_") or p.name == INDEX_FILE:
                continue
            front, scenes = parse_bank_file(p)
            for s in scenes:
                for phrase in QUOTE_RE.findall(s.fields.get("금지", "")):
                    out.append((phrase, f"{s.id} 금지"))
            for item in front.get("경험_금지", []) if isinstance(front.get("경험_금지"), list) else []:
                for phrase in QUOTE_RE.findall(item):
                    out.append((phrase, f"{front.get('경험', p.stem)} 경험_금지"))
    if rules.exists():
        lines = rules.read_text(encoding="utf-8").splitlines()
        for phrase in _quotes_in_section(lines, r"^## 4\.1", r"^## ", lambda l: l.startswith("- ")):
            out.append((phrase, "작성규칙 4.1"))
    return out


def load_forbidden(ledger: Path, bank_dir: Path, rules: Path) -> dict[str, str]:
    fb: dict[str, str] = {}
    for phrase, src in forbidden_entries(ledger, bank_dir, rules):
        fb.setdefault(phrase, src)
    return fb


def load_reference_quotes(refs: Path | None) -> list[tuple[str, str]]:
    """레퍼런스 카드의 `## 짧은 인용` 절에 있는 따옴표 문자열과 카드 이름."""
    out: list[tuple[str, str]] = []
    if refs is None or not refs.exists():
        return out
    for p in sorted(refs.glob("*.md")):
        if p.name.startswith("_"):
            continue
        lines = p.read_text(encoding="utf-8").splitlines()
        out.extend((qt, p.stem) for qt in _quotes_in_section(lines, r"^## 짧은 인용", r"^## "))
    return out


def overlaps(quote: str, body: str, n: int = OVERLAP_LEN) -> bool:
    a = re.sub(r"\s", "", quote)
    b = re.sub(r"\s", "", body)
    return any(a[i : i + n] in b for i in range(0, max(len(a) - n + 1, 0)))


def load_style_phrases(style: Path | None) -> list[str]:
    if style is None or not style.exists():
        return []
    lines = style.read_text(encoding="utf-8").splitlines()
    return _quotes_in_section(lines, r"^## 안 쓰는 표현", r"^## ", lambda l: l.startswith("- "))


def _apply_limit(q: Question, comment: str) -> None:
    for part in comment.split(","):
        k, _, v = part.partition(":")
        k, v = k.strip(), v.strip()
        if k == "limit" and v.isdigit():
            q.limit = int(v)
        elif k == "unit":
            q.unit = v
        elif k == "spaces":
            q.spaces = v
        elif k == "hangul" and v.isdigit():
            q.hangul = int(v)
        elif k == "type":
            q.qtype = v


def _parse_row(line: str) -> list[str]:
    cells = CELL_SPLIT_RE.split(line.strip().strip("|"))
    return [c.strip().replace("\\|", "|") for c in cells]


def parse_draft(text: str) -> list[Question]:
    qs: list[Question] = []
    cur: Question | None = None
    section = None
    for line in text.splitlines():
        m = QUESTION_RE.match(line)
        if m:
            cur = Question(number=int(m.group(1)), title=m.group(2).strip())
            qs.append(cur)
            section = None
            continue
        if cur is None:
            continue
        lm = LIMIT_RE.search(line)
        if lm and "limit" in lm.group(1):
            _apply_limit(cur, lm.group(1))
            continue
        if line.startswith("### "):
            section = line[4:].strip()
            continue
        if section == "본문":
            cur.body = (cur.body + "\n" + line) if cur.body else line
        elif section == "근거" and line.startswith("|"):
            cells = _parse_row(line)
            if cells[0] == "문장":
                cur.old_format = True
            elif cells[0] == "사실" or set(cells[0]) <= {"-", ":"}:
                continue
            elif len(cells) >= 4:
                cur.evidence.append(EvidenceRow(cells[0], cells[1], cells[2], cells[3]))
    for q in qs:
        q.body = q.body.strip()
    return qs


def _ending(sentence: str) -> str:
    return sentence.rstrip(".!? ")[-ENDING_LEN:]


def _first_word(sentence: str) -> str:
    parts = sentence.split()
    return parts[0] if parts else ""


def _last_word(sentence: str) -> str:
    parts = sentence.rstrip(".!? ").split()
    return parts[-1] if parts else ""


def style_warnings(questions: list[Question]) -> list[str]:
    w: list[str] = []
    openings: dict[int, str] = {}
    closings: dict[int, str] = {}
    dama: list[int] = []
    for q in questions:
        tag = f"문항 {q.number}"
        n = len(numbers_in(q.body))
        if n == 0 and (not q.qtype or q.qtype in NUMBER_REQUIRED_TYPES):
            w.append(f"{tag}: 수치 0개")
        elif n >= 4:
            w.append(f"{tag}: 수치 4개 이상 ({n}개)")
        dates = DATE_RE.findall(q.body)
        if len(dates) >= 2:
            w.append(f"{tag}: 날짜 2개 이상 ({len(dates)}개)")
        sentences = split_sentences(q.body)
        if not sentences:
            continue
        for i in range(len(sentences) - 2):
            e = _ending(sentences[i])
            if e and e == _ending(sentences[i + 1]) == _ending(sentences[i + 2]):
                w.append(f"{tag}: 같은 어미 3연속 '{e}'")
                break
        if len(sentences) >= 4:
            lengths = [len(s) for s in sentences]
            cv = statistics.pstdev(lengths) / statistics.mean(lengths)
            if cv < UNIFORM_CV:
                w.append(f"{tag}: 문장 길이가 균일 (변동계수 {cv:.2f})")
        for word, count in Counter(_first_word(s) for s in sentences).items():
            if count >= 3:
                w.append(f"{tag}: 같은 시작어 3회 '{word}'")
        for para in q.body.split("\n"):
            k = len(CONNECTIVE_RE.findall(para))
            if k >= 3:
                w.append(f"{tag}: 접속어 과다 ({k}개)")
        openings[q.number] = _first_word(sentences[0])
        closings[q.number] = _last_word(sentences[-1])
        if "다만" in q.body:
            dama.append(q.number)
    numbers = sorted(openings)
    for i, a in enumerate(numbers):
        for b in numbers[i + 1 :]:
            if openings[a] and openings[a] == openings[b]:
                w.append(f"문항 {a}·{b}: 첫 어절 겹침 '{openings[a]}'")
            if closings[a] and closings[a] == closings[b]:
                w.append(f"문항 {a}·{b}: 끝 문장 어미 겹침 '{closings[a]}'")
    if len(dama) >= 2:
        w.append(f"'다만' {len(dama)}개 문항에서 사용")
    return w


def check_draft(draft: Path, bank_dir: Path, ledger: Path, rules: Path, style: Path | None = None, refs: Path | None = None) -> CheckResult:
    result = CheckResult()
    qs = parse_draft(draft.read_text(encoding="utf-8"))
    if not qs:
        result.errors.append("문항 없음")
        return result
    scene_text: dict[str, str] = {}
    scene_exp: dict[str, str] = {}
    for p in bank_dir.glob("*.md"):
        if p.name.startswith("_") or p.name == INDEX_FILE:
            continue
        front, scenes = parse_bank_file(p)
        for s in scenes:
            scene_text[s.id] = "\n".join(s.fields.values())
            scene_exp[s.id] = str(front.get("경험", p.stem))
    # 장면·경험의 금지어는 이 초안이 쓴 장면과 경험에만 적용한다 (예: 한 경험의 금지어 "대상"이 다른 문항에 걸리지 않게)
    cited = {r.scene for q in qs for r in q.evidence if r.scene}
    cited_exp = {scene_exp[sid] for sid in cited if sid in scene_exp}
    allowed_src = {f"{sid} 금지" for sid in cited} | {f"{e} 경험_금지" for e in cited_exp} | {"사실원장 10절", "작성규칙 4.1"}
    forbidden: dict[str, str] = {}
    for phrase, src in forbidden_entries(ledger, bank_dir, rules):
        if src in allowed_src:
            forbidden.setdefault(phrase, src)
    style_phrases = load_style_phrases(style)
    ref_quotes = load_reference_quotes(refs)
    used: dict[str, list[int]] = {}
    for q in qs:
        tag = f"문항 {q.number}"
        if q.limit is None:
            result.errors.append(f"{tag}: 분량 제한 없음")
        else:
            n = count_length(q.body, q.unit, q.spaces, q.hangul)
            if n > q.limit:
                result.errors.append(f"{tag}: 분량 초과 {n}/{q.limit} ({q.unit}, {q.spaces})")
            elif n < q.limit * MIN_RATIO:
                result.errors.append(f"{tag}: 분량 부족 {n}/{q.limit} ({q.unit}, {q.spaces})")
        for phrase, src in forbidden.items():
            if phrase in q.body:
                result.errors.append(f"{tag}: 금지 표현 '{phrase}' ({src})")
        for quote, card in ref_quotes:
            if overlaps(quote, q.body):
                result.errors.append(f"{tag}: 참고 인용과 겹침 '{quote[:20]}…' ({card} 카드)")
        for phrase in style_phrases:
            if phrase in q.body:
                result.warnings.append(f"{tag}: 안 쓰는 표현 '{phrase}' (말투)")
        if q.old_format:
            result.errors.append(f"{tag}: 옛 근거 형식")
            continue
        covered: set[str] = set()
        flat_body = re.sub(r"\s+", " ", q.body)
        for r in q.evidence:
            covered.update(number_keys(r.fact))
            if re.sub(r"\s+", " ", r.fact) not in flat_body:
                result.errors.append(f"{tag}: 사실 구절 '{r.fact}' 본문에 없음")
            if r.scene and r.scene not in scene_text:
                result.errors.append(f"{tag}: 장면 {r.scene} 없음")
            if r.kind not in KINDS:
                result.errors.append(f"{tag}: 유형 '{r.kind}' 모름")
            elif r.kind == "제안":
                result.errors.append(f"{tag}: 미승인 제안 '{r.fact}'")
            elif r.kind == "사실":
                if r.scene:
                    if not TAGS_RE.fullmatch(r.tag):
                        result.errors.append(f"{tag}: 근거 '{r.tag}' 형식이 아님")
                    elif r.scene in scene_text:
                        for m in EVIDENCE_RE.finditer(r.tag):
                            if m.group(0) not in scene_text[r.scene]:
                                result.errors.append(f"{tag}: 근거 '{m.group(0)}'가 {r.scene}에 없음")
                elif not r.tag.startswith(KNOWN_SOURCES):
                    result.errors.append(f"{tag}: 근거 출처 불명 '{r.tag}'")
            if r.scene and q.number not in used.setdefault(r.scene, []):
                used[r.scene].append(q.number)
        for num in dict.fromkeys(number_keys(q.body)):
            if num not in covered:
                result.errors.append(f"{tag}: 숫자 '{num}' 사실 행 없음")
    for sid, nums in used.items():
        if len(nums) > 1:
            result.errors.append(f"장면 중복: {sid} ({', '.join(f'문항 {n}' for n in nums)})")
    result.warnings.extend(style_warnings(qs))
    return result


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="자소서 초안 검사기")
    ap.add_argument("draft")
    ap.add_argument("--bank", required=True)
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--rules", required=True)
    ap.add_argument("--style", default=None)
    ap.add_argument("--refs", default=None)
    a = ap.parse_args(argv)
    r = check_draft(Path(a.draft), Path(a.bank), Path(a.ledger), Path(a.rules), Path(a.style) if a.style else None, Path(a.refs) if a.refs else None)
    for e in r.errors:
        print(f"오류: {e}")
    for w in r.warnings:
        print(f"경고: {w}")
    if r.errors:
        print(f"FAIL (오류 {len(r.errors)}, 경고 {len(r.warnings)})")
        return 1
    print(f"OK (경고 {len(r.warnings)})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
