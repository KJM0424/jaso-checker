"""제출본에서 사용자가 바꾸거나 새로 쓴 문장을 말투 기록에 쌓는다.

초안에서 그대로 남은 문장은 Claude 문장이므로 기록하지 않는다. 공백·문장부호만 다른 문장도 같은 것으로 본다.

사용:
    python3 learn_style.py --application 가상은행_IT운영 --final 4_제출본_1109.md --draft 3_초안_1109.md --log 01_나/말투_기록.md
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from check import QUESTION_RE, numbers_in, split_sentences

PUNCT_RE = re.compile(r"[\s.,!?·:;'\"()\[\]~-]")


@dataclass
class Edit:
    question: int
    before: str
    after: str


def parse_submission(text: str) -> dict[int, str]:
    """`## 문항 N` 머리로 나눠 본문만 돌려준다. `### 본문` 칸이 있어도 없어도 읽고, `### 근거` 이후와 주석은 뺀다."""
    out: dict[int, list[str]] = {}
    cur: int | None = None
    skip = False
    for line in text.splitlines():
        m = QUESTION_RE.match(line)
        if m:
            cur = int(m.group(1))
            out[cur] = []
            skip = False
            continue
        if cur is None:
            continue
        if line.startswith("### "):
            skip = line[4:].strip() != "본문"
            continue
        if skip or line.lstrip().startswith("<!--"):
            continue
        out[cur].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


def _norm(sentence: str) -> str:
    return PUNCT_RE.sub("", sentence)


SOURCE_SHARE = 0.5  # 제출본 문장의 글자 절반 이상이 초안 문장에서 왔으면 그 문장을 고친 것
REWRITE_SHARE = 0.25  # 문장 수가 다른 구간에서 출처 없는 두 문장을 고쳐 쓴 것으로 볼 최소 겹침


def _share(candidate: str, sentence: str) -> float:
    """sentence의 글자 중 candidate와 2글자 이상 이어서 같은 부분의 비율."""
    s = _norm(sentence)
    blocks = difflib.SequenceMatcher(None, _norm(candidate), s, autojunk=False).get_matching_blocks()
    return sum(m.size for m in blocks if m.size >= 2) / max(len(s), 1)


def _source(sentence: str, candidates: list[str]) -> int | None:
    """제출본 문장이 초안 후보 중 어느 문장에서 왔는지. 가장 많이 겹치는 문장, 절반 미만이면 None."""
    best, best_share = None, SOURCE_SHARE
    for i, c in enumerate(candidates):
        share = _share(c, sentence)
        if share >= best_share:
            best, best_share = i, share
    return best


def _pair(before: list[str], after: list[str], question: int) -> list[Edit]:
    """바뀐 구간 안에서 제출본 문장을 출처 초안 문장에 묶는다. 한 문장을 둘로 나눈 것은 한 행이 된다.
    출처를 못 찾은 문장끼리는 같은 자리(앞뒤로 묶인 문장 사이)에 있을 때만 바꿔 쓴 것으로 짝짓고,
    문장 수가 다른 구간에서는 조금이라도 겹쳐야 짝짓는다. 남으면 새로 쓴 문장 또는 지운 문장이다."""
    owner = [_source(s, before) for s in after]
    min_share = REWRITE_SHARE if len(before) != len(after) else 0.0
    anchors = list(owner)
    loose_before = [i for i in range(len(before)) if i not in owner]
    for j, o in enumerate(anchors):
        if o is not None:
            continue
        prev = max((x for x in anchors[:j] if x is not None), default=-1)
        nxt = min((x for x in anchors[j + 1 :] if x is not None), default=len(before))
        slot = [i for i in loose_before if prev < i < nxt and _share(before[i], after[j]) >= min_share]
        if slot:
            owner[j] = slot[0]
            loose_before.remove(slot[0])
    groups: dict[int, list[str]] = {i: [] for i in range(len(before))}
    lead: list[str] = []
    trailing: dict[int, list[str]] = {i: [] for i in range(len(before))}
    last = None
    for s, o in zip(after, owner):
        if o is None:
            (lead if last is None else trailing[last]).append(s)
        else:
            groups[o].append(s)
            last = o
    edits: list[Edit] = []
    for i, b in enumerate(before):
        if groups[i] and lead:
            edits.extend(Edit(question, "", s) for s in lead)
            lead = []
        joined = " ".join(groups[i])
        if _norm(joined) != _norm(b):
            edits.append(Edit(question, b, joined))
        edits.extend(Edit(question, "", s) for s in trailing[i])
    edits.extend(Edit(question, "", s) for s in lead)
    return edits


def diff_edits(draft_body: str, final_body: str, question: int) -> list[Edit]:
    a = split_sentences(draft_body)
    b = split_sentences(final_body)
    edits: list[Edit] = []
    sm = difflib.SequenceMatcher(None, [_norm(s) for s in a], [_norm(s) for s in b], autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op != "equal":
            edits.extend(_pair(a[i1:i2], b[j1:j2], question))
    return edits


def collect(draft_text: str | None, final_text: str) -> list[Edit]:
    draft = parse_submission(draft_text) if draft_text else {}
    edits: list[Edit] = []
    for n, body in sorted(parse_submission(final_text).items()):
        edits.extend(diff_edits(draft.get(n, ""), body, n))
    return edits


def new_numbers(draft_text: str | None, final_text: str) -> dict[int, list[str]]:
    draft = parse_submission(draft_text) if draft_text else {}
    out: dict[int, list[str]] = {}
    for n, body in sorted(parse_submission(final_text).items()):
        known = set(numbers_in(draft.get(n, "")))
        fresh = [x for x in dict.fromkeys(numbers_in(body)) if x not in known]
        if fresh:
            out[n] = fresh
    return out


def _titles(text: str) -> dict[int, str]:
    return {int(m.group(1)): m.group(2).strip() for m in map(QUESTION_RE.match, text.splitlines()) if m}


def compare_report(draft_text: str | None, final_text: str) -> list[str]:
    """어느 문항을 무엇과 비교했는지. 번호가 밀려 초안 문장이 사용자 문장으로 기록되는 일을 사람이 보게 한다."""
    if not draft_text:
        return ["초안 없음: 전부 새 문장으로 기록"]
    draft, final = parse_submission(draft_text), parse_submission(final_text)
    d_titles, f_titles = _titles(draft_text), _titles(final_text)
    lines = []
    for n, body in sorted(final.items()):
        if n not in draft:
            lines.append(f"초안에 없음: 문항 {n} (전부 새 문장으로 기록)")
            continue
        lines.append(f"비교: 문항 {n} (기록 {len(diff_edits(draft[n], body, n))}행)")
        if d_titles.get(n) != f_titles.get(n):
            lines.append(f"경고: 문항 {n} 제목이 초안과 다름 ('{d_titles.get(n)}' / '{f_titles.get(n)}')")
    lines.extend(f"제출본에 없음: 초안 문항 {n}" for n in sorted(set(draft) - set(final)))
    return lines


def _cell(text: str) -> str:
    return re.sub(r"\s*\n\s*", " ", text).replace("|", "\\|").strip()


def append_log(log: Path, application: str, edits: list[Edit]) -> int:
    """같은 지원서의 행을 지우고 다시 쓴다. 같은 제출본을 두 번 줘도 기록이 부풀지 않는다."""
    lines = log.read_text(encoding="utf-8").rstrip("\n").split("\n")
    prefix = f"| {_cell(application)} |"
    kept = [l for l in lines if not l.startswith(prefix)]
    kept.extend(f"{prefix} {e.question} | {_cell(e.before)} | {_cell(e.after)} |" for e in edits)
    log.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return len(edits)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="제출본에서 말투 기록 쌓기")
    ap.add_argument("--application", required=True)
    ap.add_argument("--final", required=True)
    ap.add_argument("--draft", default=None)
    ap.add_argument("--log", required=True)
    a = ap.parse_args(argv)
    final_text = Path(a.final).read_text(encoding="utf-8")
    if not parse_submission(final_text):
        print("문항 머리 없음: --final을 '## 문항 N: 제목'으로 나눠 주세요")
        return 2
    draft_text = Path(a.draft).read_text(encoding="utf-8") if a.draft else None
    for line in compare_report(draft_text, final_text):
        print(line)
    print(f"기록 {append_log(Path(a.log), a.application, collect(draft_text, final_text))}행")
    for n, nums in new_numbers(draft_text, final_text).items():
        print(f"새 숫자: 문항 {n}: {', '.join(nums)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
