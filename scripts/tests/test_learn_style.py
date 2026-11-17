import subprocess
import sys
from pathlib import Path

from learn_style import Edit, append_log, collect, compare_report, diff_edits, new_numbers, parse_submission

SCRIPT = Path(__file__).resolve().parent.parent / "learn_style.py"
HEADER = "# 말투 기록\n\n| 지원서 | 문항 | 초안 | 제출본 |\n|---|---|---|---|\n"


def final(*bodies):
    return "".join(f"## 문항 {n}: 제목\n{b}\n" for n, b in bodies)


def draft(*bodies):
    return "".join(f"## 문항 {n}: 제목\n<!-- limit: 500, unit: chars, spaces: include -->\n### 본문\n{b}\n### 근거\n| 사실 | 장면 | 근거 | 유형 |\n|---|---|---|---|\n" for n, b in bodies)


def rows(log):
    return [l for l in log.read_text(encoding="utf-8").splitlines() if l.startswith("|") and not l.startswith(("| 지원서", "|---"))]


def test_changed_sentence_recorded():
    assert diff_edits("가. 나.", "가. 다.", 1) == [Edit(1, "나.", "다.")]


def test_unchanged_sentences_not_recorded():
    assert diff_edits("가. 나.", "가. 나.", 1) == []


def test_whitespace_only_change_ignored():
    assert diff_edits("가 나.", "가  나 .", 1) == []
    assert diff_edits("가, 나.", "가 나.", 1) == []


def test_deleted_sentence_recorded():
    assert diff_edits("가. 나.", "가.", 1) == [Edit(1, "나.", "")]


def test_added_sentence_recorded():
    assert diff_edits("가.", "가. 다.", 1) == [Edit(1, "", "다.")]


def test_parse_submission_with_or_without_body_heading():
    assert parse_submission("## 문항 1: 제목\n가. 나.\n## 문항 3: 제목\n### 본문\n다.\n### 근거\n| x |\n") == {1: "가. 나.", 3: "다."}


def test_question_only_in_submission_all_new():
    edits = collect(draft((1, "가.")), final((1, "가."), (3, "새 문장. 또 문장.")))
    assert edits == [Edit(3, "", "새 문장."), Edit(3, "", "또 문장.")]


def test_no_draft_all_new():
    assert collect(None, final((1, "가. 나."))) == [Edit(1, "", "가."), Edit(1, "", "나.")]


def test_question_only_in_draft_ignored():
    assert collect(draft((1, "가."), (2, "나.")), final((1, "가."))) == []


def test_rerun_does_not_duplicate(tmp_path):
    log = tmp_path / "log.md"
    log.write_text(HEADER, encoding="utf-8")
    append_log(log, "다른회사", [Edit(1, "x.", "y.")])
    append_log(log, "가상은행", [Edit(1, "가.", "나.")])
    n1 = len(rows(log))
    assert append_log(log, "가상은행", [Edit(1, "가.", "나.")]) == 1
    assert len(rows(log)) == n1
    assert any("다른회사" in r for r in rows(log))


def test_pipe_and_newline_escaped(tmp_path):
    log = tmp_path / "log.md"
    log.write_text(HEADER, encoding="utf-8")
    append_log(log, "a", [Edit(1, "", "a|b\nc")])
    assert rows(log) == ["| a | 1 |  | a\\|b c |"]


def test_new_numbers_reported():
    assert new_numbers(draft((1, "12개.")), final((1, "12개. 70대."))) == {1: ["70"]}


def test_new_numbers_without_draft_all_reported():
    assert new_numbers(None, final((1, "3개."))) == {1: ["3"]}


def test_plain_text_submission_reported(tmp_path):
    assert parse_submission("머리 없는 글") == {}
    f = tmp_path / "f.md"
    f.write_text("머리 없는 글", encoding="utf-8")
    log = tmp_path / "log.md"
    log.write_text(HEADER, encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), "--application", "a", "--final", str(f), "--log", str(log)], capture_output=True, text=True)
    assert r.returncode == 2
    assert "문항 머리 없음" in r.stdout


def test_cli_reports_rows_and_new_numbers(tmp_path):
    d = tmp_path / "d.md"
    d.write_text(draft((1, "가.")), encoding="utf-8")
    f = tmp_path / "f.md"
    f.write_text(final((1, "나 70대.")), encoding="utf-8")
    log = tmp_path / "log.md"
    log.write_text(HEADER, encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), "--application", "a", "--final", str(f), "--draft", str(d), "--log", str(log)], capture_output=True, text=True)
    assert r.returncode == 0
    assert "기록 1행" in r.stdout
    assert "새 숫자: 문항 1: 70" in r.stdout


def test_split_sentence_paired_with_its_source():
    d = "그때는 틀릴 경우를 가정하지 않았는데, 보고서에 없는 책 이름이 있었습니다. 그 뒤로 정확성이 중요해졌습니다."
    f = "그때는 틀릴 경우를 가정하지 않았습니다. 그런데 보고서에 없는 책 이름이 있었습니다. 그 뒤로 정확성이 더 중요해졌습니다."
    assert diff_edits(d, f, 1) == [
        Edit(1, "그때는 틀릴 경우를 가정하지 않았는데, 보고서에 없는 책 이름이 있었습니다.", "그때는 틀릴 경우를 가정하지 않았습니다. 그런데 보고서에 없는 책 이름이 있었습니다."),
        Edit(1, "그 뒤로 정확성이 중요해졌습니다.", "그 뒤로 정확성이 더 중요해졌습니다."),
    ]


def test_unrelated_new_sentence_not_paired():
    d = "처음에는 장비 점검 절차를 익히겠습니다. 그다음에는 화면 개선 과제를 기획하겠습니다."
    f = "처음에는 장비 점검 절차를 곁에서 익히겠습니다. 시작은 운영입니다. 그다음에는 화면 개선 과제를 직접 기획하겠습니다."
    assert diff_edits(d, f, 1) == [
        Edit(1, "처음에는 장비 점검 절차를 익히겠습니다.", "처음에는 장비 점검 절차를 곁에서 익히겠습니다."),
        Edit(1, "", "시작은 운영입니다."),
        Edit(1, "그다음에는 화면 개선 과제를 기획하겠습니다.", "그다음에는 화면 개선 과제를 직접 기획하겠습니다."),
    ]


def test_split_with_punctuation_only_ignored():
    assert diff_edits("서버를 맡았고, 콜백을 보냈다.", "서버를 맡았고. 콜백을 보냈다.", 1) == []


def test_deleted_and_added_in_different_places_not_paired():
    d = "회의록은 팀원과 함께 썼습니다. 마감 날 시험 실행을 돌려 점수를 확인했습니다."
    f = "마감 날 시험 실행을 돌렸습니다. 점수를 확인했습니다. 문제가 생기면 흐름부터 글로 남기겠습니다."
    assert diff_edits(d, f, 1) == [
        Edit(1, "회의록은 팀원과 함께 썼습니다.", ""),
        Edit(1, "마감 날 시험 실행을 돌려 점수를 확인했습니다.", "마감 날 시험 실행을 돌렸습니다. 점수를 확인했습니다."),
        Edit(1, "", "문제가 생기면 흐름부터 글로 남기겠습니다."),
    ]


def test_unrelated_sentences_in_uneven_block_not_paired():
    d = "동아리방 의자는 남는 의자가 있는지 먼저 물었다가 사지 않았습니다."
    f = "직접 해 보니 꾸준함은 일을 끝까지 하게 만드는 힘이었습니다. 생각도 순서를 거치니 하나로 모였습니다."
    assert diff_edits(d, f, 1) == [
        Edit(1, d, ""),
        Edit(1, "", "직접 해 보니 꾸준함은 일을 끝까지 하게 만드는 힘이었습니다."),
        Edit(1, "", "생각도 순서를 거치니 하나로 모였습니다."),
    ]


def test_report_lists_compared_and_unmatched_questions():
    assert compare_report(draft((1, "가."), (2, "나.")), final((1, "가. 라."), (3, "다."))) == [
        "비교: 문항 1 (기록 1행)",
        "초안에 없음: 문항 3 (전부 새 문장으로 기록)",
        "제출본에 없음: 초안 문항 2",
    ]


def test_report_without_draft():
    assert compare_report(None, final((1, "가."))) == ["초안 없음: 전부 새 문장으로 기록"]


def test_title_mismatch_warned():
    d = draft((1, "가.")).replace("제목", "입사 이유")
    f = final((1, "가.")).replace("제목", "10년 후 비전")
    assert "경고: 문항 1 제목이 초안과 다름 ('입사 이유' / '10년 후 비전')" in compare_report(d, f)


def test_cli_prints_report(tmp_path):
    d = tmp_path / "d.md"
    d.write_text(draft((1, "가.")), encoding="utf-8")
    f = tmp_path / "f.md"
    f.write_text(final((1, "가."), (2, "나.")), encoding="utf-8")
    log = tmp_path / "log.md"
    log.write_text(HEADER, encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), "--application", "a", "--final", str(f), "--draft", str(d), "--log", str(log)], capture_output=True, text=True)
    assert "초안에 없음: 문항 2 (전부 새 문장으로 기록)" in r.stdout
