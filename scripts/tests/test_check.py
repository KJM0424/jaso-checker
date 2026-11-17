from check import CheckResult, check_draft, count_length, load_forbidden, numbers_in, parse_draft, split_sentences, style_warnings
from tests.test_check_bank import FRONT, index, make_bank, scene

LEDGER = "# 사실원장\n## 9. 가치관\n- [확정] \"무시\"\n## 10. 쓰면 안 되는 표현\n- [금지] 음성평가 \"전체 설계\", \"단독 개발\": 이유\n- [금지] 규제분석 \"팀장\"\n"
RULES = "# 작성규칙\n## 4. 문장 규칙\n## 4.1 AI 글 패턴\n- \"뿐만 아니라\"\n- \"성장할 수 있었습니다\"\n## 5. 가이드\n- \"이건 아님\"\n"
TAG = "[원본: 회의록/0001.pdf:1]"
HEAD = "| 사실 | 장면 | 근거 | 유형 |\n|---|---|---|---|\n"
LIMIT = "<!-- limit: 800, unit: chars, spaces: include -->\n"


def q(n, body, rows="", limit=LIMIT, title="제목"):
    return f"## 문항 {n}: {title}\n{limit}### 본문\n{body}\n### 근거\n{HEAD}{rows}"


def row(fact, sid="CV-01", tag=TAG, kind="사실"):
    return f"| {fact} | {sid} | {tag} | {kind} |\n"


def env(tmp_path, text, style=None):
    (tmp_path / "bank").mkdir(exist_ok=True)
    bank = make_bank(tmp_path / "bank", {"음성평가.md": FRONT + scene("CV-01") + scene("CV-02", "둘째")}, index(["CV-01", "CV-02"]))
    ledger = tmp_path / "ledger.md"
    ledger.write_text(LEDGER, encoding="utf-8")
    rules = tmp_path / "rules.md"
    rules.write_text(RULES, encoding="utf-8")
    d = tmp_path / "draft.md"
    d.write_text(text, encoding="utf-8")
    style_path = None
    if style is not None:
        style_path = tmp_path / "style.md"
        style_path.write_text(style, encoding="utf-8")
    return d, bank, ledger, rules, style_path


def run(tmp_path, text, style=None) -> CheckResult:
    d, bank, ledger, rules, style_path = env(tmp_path, text, style)
    return check_draft(d, bank, ledger, rules, style_path)


def test_split_sentences_keeps_decimals():
    assert split_sentences("중앙값은 0.25초였다. 다음 문장.") == ["중앙값은 0.25초였다.", "다음 문장."]


def test_count_chars_exclude_spaces():
    assert count_length("가나 다", "chars", "exclude") == 3
    assert count_length("가나 다", "chars", "include") == 4


def test_count_bytes_hangul_2_and_3():
    assert count_length("가a", "bytes", "include", hangul=2) == 3
    assert count_length("가a", "bytes", "include", hangul=3) == 4


def test_numbers_in():
    assert numbers_in("12,345,678원 중 0.25초, 30개.") == ["12,345,678", "0.25", "30"]


def test_digit_inside_latin_token_ignored(tmp_path):
    assert numbers_in("S3 경로와 GPT-4o, 1e6, 4821abc를 썼다.") == []
    r = run(tmp_path, q(1, "S3 경로와 GPT-4o를 썼다."))
    assert not any("숫자" in e for e in r.errors)


def test_load_forbidden_from_ledger_all_quotes(tmp_path):
    d, bank, ledger, rules, _ = env(tmp_path, q(1, "x."))
    fb = load_forbidden(ledger, bank, rules)
    assert fb["전체 설계"] == "사실원장 10절"
    assert fb["단독 개발"] == "사실원장 10절"
    assert fb["팀장"] == "사실원장 10절"
    assert "무시" not in fb
    assert fb["10배 빠름"] == "CV-01 금지"
    assert fb["뿐만 아니라"] == "작성규칙 4.1"
    assert "이건 아님" not in fb


def test_forbidden_in_draft_reported(tmp_path):
    r = run(tmp_path, q(1, "첫 문장이다. 팀장으로 했다.", row("팀장")))
    assert "문항 1: 금지 표현 '팀장' (사실원장 10절)" in r.errors


def test_scene_forbidden_applies_only_to_cited_scenes(tmp_path):
    (tmp_path / "bank").mkdir()
    other = FRONT.replace("음성평가", "해커톤") + scene("CF-01", "대회", 금지='- "대상": 수상 표기 오류')
    bank = make_bank(tmp_path / "bank", {"음성평가.md": FRONT + scene("CV-01"), "해커톤.md": other}, index(["CV-01"]) + index(["CF-01"], "해커톤.md"))
    ledger = tmp_path / "ledger.md"
    ledger.write_text(LEDGER, encoding="utf-8")
    rules = tmp_path / "rules.md"
    rules.write_text(RULES, encoding="utf-8")
    d = tmp_path / "d.md"
    d.write_text(q(1, "중소기업을 대상으로 썼다.", row("중소기업", "CV-01")), encoding="utf-8")
    assert not any("금지 표현 '대상'" in e for e in check_draft(d, bank, ledger, rules).errors)
    d.write_text(q(1, "중소기업을 대상으로 썼다.", row("중소기업", "CF-01")), encoding="utf-8")
    assert "문항 1: 금지 표현 '대상' (CF-01 금지)" in check_draft(d, bank, ledger, rules).errors


def test_same_phrase_in_two_scenes_caught_for_either(tmp_path):
    (tmp_path / "bank").mkdir()
    a = FRONT + scene("CV-01", 금지='- "겹침표현": 이유')
    b = FRONT.replace("음성평가", "해커톤") + scene("CF-01", "대회", 금지='- "겹침표현": 이유')
    bank = make_bank(tmp_path / "bank", {"음성평가.md": a, "해커톤.md": b}, index(["CV-01"]) + index(["CF-01"], "해커톤.md"))
    ledger = tmp_path / "ledger.md"
    ledger.write_text(LEDGER, encoding="utf-8")
    rules = tmp_path / "rules.md"
    rules.write_text(RULES, encoding="utf-8")
    d = tmp_path / "d.md"
    d.write_text(q(1, "겹침표현을 썼다.", row("겹침표현", "CF-01")), encoding="utf-8")
    assert any("금지 표현 '겹침표현'" in e for e in check_draft(d, bank, ledger, rules).errors)


def test_number_without_fact_row_is_error(tmp_path):
    r = run(tmp_path, q(1, "1,234,500원을 썼다."))
    assert "문항 1: 숫자 '1,234,500원' 사실 행 없음" in r.errors


def test_number_covered_by_fact_row_passes(tmp_path):
    r = run(tmp_path, q(1, "1,234,500원을 썼다.", row("1,234,500원")))
    assert not any("숫자" in e for e in r.errors)


def test_sentence_without_numbers_needs_no_row(tmp_path):
    r = run(tmp_path, q(1, "그래서 제가 하겠다고 했습니다."))
    assert not any("근거" in e or "숫자" in e or "사실" in e for e in r.errors)


def test_fact_not_in_body_is_error(tmp_path):
    r = run(tmp_path, q(1, "본문이다.", row("없는 구절")))
    assert "문항 1: 사실 구절 '없는 구절' 본문에 없음" in r.errors


def test_tag_must_exist_in_scene(tmp_path):
    r = run(tmp_path, q(1, "본문이다.", row("본문", tag="[원본: 지어냄.pdf:1]")))
    assert "문항 1: 근거 '[원본: 지어냄.pdf:1]'가 CV-01에 없음" in r.errors


def test_real_tag_in_scene_passes(tmp_path):
    r = run(tmp_path, q(1, "본문이다.", row("본문")))
    assert not any("근거" in e for e in r.errors)


def test_blank_scene_needs_known_source(tmp_path):
    r = run(tmp_path, q(1, "본문이다.", row("본문", "", "어딘가")))
    assert "문항 1: 근거 출처 불명 '어딘가'" in r.errors
    r2 = run(tmp_path, q(1, "본문이다.", row("본문", "", "2_기업분석 고유 사실 1")))
    assert not any("출처 불명" in e for e in r2.errors)


def test_unknown_scene_reported(tmp_path):
    r = run(tmp_path, q(1, "본문이다.", row("본문", "CV-09")))
    assert "문항 1: 장면 CV-09 없음" in r.errors


def test_unapproved_proposal_is_error(tmp_path):
    r = run(tmp_path, q(1, "본문이다.", row("본문", "", "나의말", "제안")))
    assert "문항 1: 미승인 제안 '본문'" in r.errors
    r2 = run(tmp_path, q(1, "본문이다.", row("본문", "", "나의말", "승인")))
    assert not any("제안" in e for e in r2.errors)


def test_duplicate_scene_across_questions(tmp_path):
    r = run(tmp_path, q(1, "하나.", row("하나")) + q(2, "둘.", row("둘")))
    assert "장면 중복: CV-01 (문항 1, 문항 2)" in r.errors


def test_missing_limit_reported(tmp_path):
    r = run(tmp_path, q(1, "본문이다.", limit=""))
    assert "문항 1: 분량 제한 없음" in r.errors


def test_over_and_under_limit(tmp_path):
    r = run(tmp_path, q(1, "가" * 811 + "."))
    assert "문항 1: 분량 초과 812/800 (chars, include)" in r.errors
    r2 = run(tmp_path, q(1, "가" * 649 + "."))
    assert "문항 1: 분량 부족 650/800 (chars, include)" in r2.errors


def test_old_format_reported_once(tmp_path):
    old = "## 문항 1: 제목\n" + LIMIT + "### 본문\n7월에 썼다. 8월에 썼다.\n### 근거\n| 문장 | 장면 | 근거 |\n|---|---|---|\n| 1 | CV-01 | [원본: a] |\n"
    r = run(tmp_path, old)
    assert r.errors.count("문항 1: 옛 근거 형식") == 1
    assert not any("숫자" in e for e in r.errors)


def test_parse_draft_reads_limit_and_evidence():
    qs = parse_draft(q(1, "하나.", row("하나"), limit="<!-- limit: 1000, unit: bytes, hangul: 2, spaces: exclude -->\n"))
    x = qs[0]
    assert (x.number, x.limit, x.unit, x.spaces, x.hangul) == (1, 1000, "bytes", "exclude", 2)
    assert x.evidence[0].fact == "하나"
    assert x.evidence[0].scene == "CV-01"
    assert x.evidence[0].tag == TAG
    assert x.evidence[0].kind == "사실"


def warns(body_by_q):
    text = "".join(q(n, b) for n, b in body_by_q.items())
    return style_warnings(parse_draft(text))


def test_style_warnings_do_not_block(tmp_path):
    body = "할 수 있습니다. 볼 수 있습니다. 갈 수 있습니다."
    r = run(tmp_path, q(1, body))
    assert any("같은 어미 3연속" in w for w in r.warnings)
    assert not any("어미" in e for e in r.errors)


def test_different_past_endings_not_warned():
    assert not any("같은 어미" in w for w in warns({1: "썼습니다. 올렸습니다. 남겼습니다."}))


def test_uniform_sentence_length_warned():
    assert any("문장 길이가 균일" in w for w in warns({1: "가나다라마바. 사아자차카타. 파하가나다라. 마바사아자차."}))


def test_varied_sentence_length_not_warned():
    assert not any("문장 길이가 균일" in w for w in warns({1: "짧다. 이 문장은 앞 문장보다 훨씬 길게 이어지는 문장입니다. 또 짧다. 그리고 다시 조금 길어지는 문장입니다."}))


def test_same_start_word_warned():
    assert any("같은 시작어 3회 '제가'" in w for w in warns({1: "제가 썼다. 제가 갔다. 제가 봤다."}))


def test_connectives_warned():
    assert any("접속어 과다" in w for w in warns({1: "또한 썼다. 그리고 갔다. 특히 봤다."}))


def test_same_opening_across_questions_warned():
    assert any("문항 1·2: 첫 어절 겹침 '제'" in w for w in warns({1: "제 역량은 이것입니다.", 2: "제 도전은 저것입니다."}))


def test_same_last_word_across_questions_warned():
    assert any("문항 1·2: 끝 문장 어미 겹침 '지원합니다'" in w for w in warns({1: "그래서 지원합니다.", 2: "이 때문에 지원합니다."}))


def test_dama_two_questions_warned():
    assert any("'다만' 2개 문항에서 사용" in w for w in warns({1: "다만 못 했습니다.", 2: "다만 안 했습니다."}))


def test_style_file_phrase_warned(tmp_path):
    style = "# 말투\n## 안 쓰는 표현\n- \"도모\"\n## 후보\n- \"무시됨\"\n"
    r = run(tmp_path, q(1, "협력을 도모했다. 무시됨도 있다."), style)
    assert "문항 1: 안 쓰는 표현 '도모' (말투)" in r.warnings
    assert not any("무시됨" in w for w in r.warnings)
    assert not any("도모" in e for e in r.errors)


def test_number_count_warned():
    assert any("수치 0개" in w for w in warns({1: "숫자가 없다."}))
    assert any("수치 4개 이상 (4개)" in w for w in warns({1: "1개, 2개, 3개, 4개."}))


def test_posting_is_known_source(tmp_path):
    r = run(tmp_path, q(1, "기획과 운영을 한 직무로 뽑습니다.", row("기획과 운영", "", "1_공고_전형 주요 업무")))
    assert not any("출처 불명" in e for e in r.errors)


def test_many_dates_warned():
    assert any("날짜 2개 이상 (3개)" in w for w in warns({1: "2023년에 시작했다. 9월 17일에 했다. 12일에 끝났다."}))


def test_one_date_and_semesters_not_warned():
    assert not any("날짜" in w for w in warns({1: "1학기와 2학기에 했다. 9월에 끝났다."}))


def test_type_comment_parsed():
    qs = parse_draft(q(1, "본문.", limit="<!-- limit: 500, unit: chars, spaces: include, type: 갈등 -->\n"))
    assert qs[0].qtype == "갈등"


def test_zero_numbers_warned_only_for_required_types():
    def w(t):
        return style_warnings(parse_draft(q(1, "숫자가 없다.", limit=f"<!-- limit: 500, unit: chars, spaces: include, type: {t} -->\n")))
    assert any("수치 0개" in x for x in w("직무역량"))
    assert any("수치 0개" in x for x in w("문제해결"))
    assert not any("수치 0개" in x for x in w("갈등"))
    assert not any("수치 0개" in x for x in w("포부"))


def test_reference_quote_overlap_is_error(tmp_path):
    refs = tmp_path / "refs"
    refs.mkdir()
    (refs / "협업.md").write_text('# 협업\n## 짧은 인용 (최대 5개)\n- "프론트 기능이 삼십 퍼센트밖에 완성되지 않은 상태에서" — URL\n## 우리 작성규칙과 다른 점\n', encoding="utf-8")
    d, bank, ledger, rules, _ = env(tmp_path, q(1, "당시 프론트 기능이 삼십 퍼센트밖에 완성되지 않은 상태였습니다."))
    r = check_draft(d, bank, ledger, rules, None, refs)
    assert any("참고 인용과 겹침" in e for e in r.errors)
    d.write_text(q(1, "당시 화면 기능이 거의 비어 있었습니다."), encoding="utf-8")
    assert not any("참고 인용과 겹침" in e for e in check_draft(d, bank, ledger, rules, None, refs).errors)


def test_unknown_kind_is_error(tmp_path):
    r = run(tmp_path, q(1, "본문이다.", row("본문", kind="추론")))
    assert "문항 1: 유형 '추론' 모름" in r.errors
    r2 = run(tmp_path, q(1, "본문이다.", row("본문", kind="")))
    assert "문항 1: 유형 '' 모름" in r2.errors


def test_empty_or_partial_tag_is_error(tmp_path):
    r = run(tmp_path, q(1, "본문이다.", row("본문", tag="")))
    assert "문항 1: 근거 '' 형식이 아님" in r.errors
    r2 = run(tmp_path, q(1, "본문이다.", row("본문", tag="[원본")))
    assert "문항 1: 근거 '[원본' 형식이 아님" in r2.errors


def test_two_tags_in_one_cell_pass(tmp_path):
    r = run(tmp_path, q(1, "본문이다.", row("본문", tag=f"{TAG} {TAG}")))
    assert not any("근거" in e for e in r.errors)


def test_number_with_latin_unit_checked(tmp_path):
    assert numbers_in("응답을 300ms에서 10ms로, 26MB를 3x 줄였다.") == ["300", "10", "26", "3"]
    assert numbers_in("K8s, EC2, H100, 5G") == []
    r = run(tmp_path, q(1, "응답을 10ms로 줄였다."))
    assert "문항 1: 숫자 '10ms' 사실 행 없음" in r.errors


def test_number_with_other_unit_not_covered(tmp_path):
    r = run(tmp_path, q(1, "30개 중 7개를 맡았고 팀 7명과 일했다.", row("30개 중 7개")))
    assert "문항 1: 숫자 '7명' 사실 행 없음" in r.errors
    assert not any("'7개'" in e or "'30개'" in e for e in r.errors)
