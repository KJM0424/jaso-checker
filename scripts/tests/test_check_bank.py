import unicodedata

from check_bank import check_bank, check_scene, parse_bank_file

FIELDS = ["문항유형", "상황", "본인행동", "결과", "한계", "역할경계", "고유디테일", "각도", "금지", "꼬리질문", "본인기억", "상태"]
FRONT = "---\n경험: 음성평가\n등급: 주력\n기간: 2024.03~06\n팀: 4인\n본인역할_요약: 서버\n핵심숫자:\n- 로그 30건\n경험_금지:\n- \"전체 설계\"\n---\n"


def scene(sid="CV-01", title="단위 오류", omit=(), **over):
    vals = {
        "문항유형": "문제해결, 실패",
        "상황": "분석 모듈을 맡았다. [원본: 회의록/0001.pdf:1]",
        "본인행동": "다시 쟀다. [분석: 검토문서 2.1절]",
        "결과": "원인을 찾았다. [분석: 검토문서 2.1절]",
        "한계": "아직 고치지 않았다. [분석: 검토문서 5.1절]",
        "역할경계": "본인: 분석 모듈. 팀: 배포",
        "고유디테일": "초와 밀리초 [원본: module.py:42]",
        "각도": "판단이 바뀐 순간",
        "금지": "- \"10배 빠름\": 단위 오류",
        "꼬리질문": "- 왜 몰랐나 → 검토문서 2.1절",
        "본인기억": "",
        "상태": "본인확인필요",
    }
    vals.update(over)
    out = f"## {sid} {title}\n"
    for f in FIELDS:
        if f in omit:
            continue
        out += f"### {f}\n{vals[f]}\n"
    return out


def index(ids, filename="음성평가.md"):
    rows = "\n".join(f"| {i} | 음성평가 | 제목 | 주력 | 문제해결 | 본인확인필요 | {filename} |" for i in ids)
    return "# 색인\n| ID | 경험 | 제목 | 등급 | 문항유형 | 상태 | 파일 |\n|---|---|---|---|---|---|---|\n" + rows + "\n"


def make_bank(tmp_path, files, idx):
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    (tmp_path / "00_색인.md").write_text(idx, encoding="utf-8")
    return tmp_path


def test_parse_scene_fields(tmp_path):
    p = tmp_path / "음성평가.md"
    p.write_text(FRONT + scene(), encoding="utf-8")
    front, scenes = parse_bank_file(p)
    assert front["경험"] == "음성평가"
    assert front["핵심숫자"] == ["로그 30건"]
    assert scenes[0].id == "CV-01"
    assert scenes[0].title == "단위 오류"
    assert set(scenes[0].fields) == set(FIELDS)
    assert scenes[0].fields["상태"] == "본인확인필요"


def test_missing_field_reported(tmp_path):
    p = tmp_path / "음성평가.md"
    p.write_text(FRONT + scene(omit=("한계",)), encoding="utf-8")
    _, scenes = parse_bank_file(p)
    assert "missing field: 한계" in check_scene(scenes[0])


def test_no_evidence_reported(tmp_path):
    p = tmp_path / "음성평가.md"
    p.write_text(FRONT + scene(상황="태그 없는 문장."), encoding="utf-8")
    _, scenes = parse_bank_file(p)
    problems = check_scene(scenes[0])
    assert "no evidence: 상황" in problems
    assert not any("본인기억" in x for x in problems)


def test_duplicate_id_reported(tmp_path):
    bank = make_bank(tmp_path, {"음성평가.md": FRONT + scene(), "규제분석.md": FRONT + scene()}, index(["CV-01"]))
    assert "duplicate id: CV-01" in check_bank(bank)


def test_index_matches_files_despite_nfd(tmp_path):
    nfc = unicodedata.normalize("NFC", "동아리.md")
    nfd = unicodedata.normalize("NFD", "동아리.md")
    bank = make_bank(tmp_path, {nfc: FRONT + scene("SC-01")}, index(["SC-01"], filename=nfd))
    assert not any(x.startswith("index:") for x in check_bank(bank))


def test_index_missing_id_reported(tmp_path):
    bank = make_bank(tmp_path, {"규제분석.md": FRONT + scene("RT-01") + scene("RT-02", "둘째")}, index(["RT-01"], "규제분석.md"))
    assert "index: missing id: RT-02" in check_bank(bank)
