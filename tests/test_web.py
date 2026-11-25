#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 2026-11-25 - voca-web - 웹 흐름 테스트: 등록·CSV·암기·시험·통계 (VOCA-FR-001~034, NFR-003)
# 파일 위치: tests/test_web.py

import io
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DB_PATH", os.path.join(tempfile.gettempdir(), "voca_import_check.db"))

import db
import store
from app import create_app

SAMPLE_CSV = os.path.join(os.path.dirname(__file__), "..", "samples", "sample_words.csv")


class WebTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "sub", "voca.db")   # 상위 폴더도 없는 빈 상태
        self.client = create_app(self.db_path).test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, term, meaning):
        return self.client.post("/words/add", data={"term": term, "meaning": meaning},
                                follow_redirects=True)

    def load_sample(self):
        with open(SAMPLE_CSV, "rb") as handle:
            return self.client.post("/words/import", data={"csv_file": (handle, "w.csv")},
                                    content_type="multipart/form-data", follow_redirects=True)

    def rows(self, sql):
        conn = db.connect(self.db_path)
        try:
            return conn.execute(sql).fetchall()
        finally:
            conn.close()

    def start(self, **overrides):
        data = {"count": "5", "direction": "mixed", "types": ["short", "mc4", "ox"]}
        data.update(overrides)
        return self.client.post("/exam/start", data=data)

    def finish_exam(self):
        response = self.start()
        self.assertEqual(response.status_code, 302)
        exam_id = int(re.search(r"/exam/(\d+)/1", response.headers["Location"]).group(1))
        for seq in range(1, 6):
            page = self.client.get(f"/exam/{exam_id}/{seq}").get_data(as_text=True)
            self.assertIn(f"시험 {seq} / 5", page)
            self.client.post(f"/exam/{exam_id}/{seq}", data={"response": "zzz-wrong"})
        return exam_id


class DatabaseInitTest(WebTestCase):
    def test_tables_created_from_empty(self):
        names = {r["name"] for r in self.rows("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"words", "study_log", "exams", "exam_items"} <= names)

    def test_every_page_opens_when_empty(self):
        for path in ("/", "/words", "/study", "/exam"):
            self.assertEqual(self.client.get(path).status_code, 200, path)


class WordsTest(WebTestCase):
    def test_add_and_list(self):                       # VOCA-FR-001, 002
        self.assertIn("등록 완료", self.add("apple", "사과").get_data(as_text=True))
        self.assertIn("사과", self.client.get("/words").get_data(as_text=True))

    def test_duplicate_is_rejected_case_insensitive(self):
        self.add("apple", "사과")
        self.assertIn("이미 등록", self.add("APPLE", "다른 뜻").get_data(as_text=True))
        self.assertEqual(len(self.rows("SELECT * FROM words")), 1)

    def test_edit_and_delete(self):
        self.add("apple", "사과")
        word_id = self.rows("SELECT id FROM words")[0]["id"]
        self.client.post(f"/words/{word_id}/edit", data={"term": "apple", "meaning": "애플"})
        self.assertEqual(self.rows("SELECT meaning FROM words")[0]["meaning"], "애플")
        self.client.post(f"/words/{word_id}/delete")
        self.assertEqual(self.rows("SELECT * FROM words"), [])

    def test_search_by_term_and_meaning(self):         # VOCA-FR-004
        self.add("apple", "사과")
        self.add("book", "책")
        by_term = self.client.get("/words?q=app").get_data(as_text=True)
        by_meaning = self.client.get("/words?q=책").get_data(as_text=True)
        self.assertIn("apple", by_term)
        self.assertNotIn(">book<", by_term)
        self.assertIn("book", by_meaning)

    def test_search_treats_percent_literally(self):
        self.add("apple", "사과")
        self.assertNotIn(">apple<", self.client.get("/words?q=%25").get_data(as_text=True))

    def test_csv_import_with_bom_and_duplicates(self):  # VOCA-FR-003
        self.add("apple", "기존 뜻")
        text = self.load_sample().get_data(as_text=True)
        self.assertIn("중복 1개", text)
        count = self.rows("SELECT COUNT(*) AS n FROM words")[0]["n"]
        self.assertEqual(count, 31)                     # sample 31단어, apple 은 기존 것 유지
        self.assertEqual(self.rows("SELECT meaning FROM words WHERE term='apple'")[0]["meaning"],
                         "기존 뜻")

    def test_csv_invalid_rows_skipped_and_wrong_encoding(self):
        data = "영단어,뜻\nonly_one\n,빈단어\nok,좋아\n".encode("utf-8-sig")
        self.assertEqual(store.import_csv(db.connect(self.db_path), data), (1, 0, 2))
        response = self.client.post("/words/import", content_type="multipart/form-data",
                                    data={"csv_file": (io.BytesIO("가나다".encode("cp949")), "x.csv")},
                                    follow_redirects=True)
        self.assertIn("UTF-8", response.get_data(as_text=True))


class StudyTest(WebTestCase):
    def test_study_logs_each_card(self):               # VOCA-FR-012, 014
        self.load_sample()
        page = self.client.get("/study?day=1&per_day=5").get_data(as_text=True)
        self.assertIn("1 / 5", page)
        word_id = re.search(r'name="word_id" value="(\d+)"', page).group(1)
        self.client.post("/study/next", data={"day": 1, "per_day": 5, "i": 0, "word_id": word_id,
                                              "tag": "new"})
        rows = self.rows("SELECT * FROM study_log")
        self.assertEqual((len(rows), rows[0]["day"], rows[0]["tag"]), (1, 1, "new"))

    def test_study_finish_page_and_bad_input(self):
        self.load_sample()
        self.assertIn("암기를 마쳤습니다", self.client.get("/study?day=1&per_day=5&i=5").get_data(as_text=True))
        bad = self.client.post("/study/next", data={"day": 1, "word_id": 99999, "tag": "new"})
        self.assertEqual(bad.status_code, 400)


class ExamTest(WebTestCase):
    def test_exam_needs_words(self):
        self.assertIn("먼저 단어를", self.client.get(self.start().headers["Location"]).get_data(as_text=True))

    def test_exam_requires_a_type(self):
        self.load_sample()
        self.assertIn("형식을 하나", self.client.get(self.start(types=[]).headers["Location"]).get_data(as_text=True))

    def test_full_exam_flow_and_history(self):         # VOCA-FR-021, 025, 026
        self.load_sample()
        exam_id = self.finish_exam()
        result = self.client.get(f"/exam/{exam_id}/result").get_data(as_text=True)
        self.assertIn("/ 5 정답", result)
        items = self.rows(f"SELECT * FROM exam_items WHERE exam_id={exam_id}")
        self.assertEqual(len(items), 5)
        self.assertTrue(all(i["answered_at"] and i["correct"] in (0, 1) and i["qtype"] and i["direction"]
                            for i in items))
        self.assertIsNotNone(self.rows(f"SELECT finished_at FROM exams WHERE id={exam_id}")[0][0])

    def test_answer_cannot_be_changed_twice(self):
        self.load_sample()
        response = self.start(count="1", types=["short"])
        exam_id = int(re.search(r"/exam/(\d+)/1", response.headers["Location"]).group(1))
        item = self.rows(f"SELECT answer_json FROM exam_items WHERE exam_id={exam_id}")[0]
        correct_text = __import__("json").loads(item["answer_json"])
        self.client.post(f"/exam/{exam_id}/1", data={"response": "wrong"})
        self.client.post(f"/exam/{exam_id}/1", data={"response": correct_text})
        self.assertEqual(self.rows(f"SELECT correct FROM exam_items WHERE exam_id={exam_id}")[0][0], 0)

    def test_mc4_needs_four_words(self):
        for i in range(3):
            self.add(f"w{i}", f"뜻{i}")
        self.assertIn("4개 이상", self.client.get(self.start(types=["mc4"]).headers["Location"]).get_data(as_text=True))


class StatsTest(WebTestCase):
    def test_stats_come_from_history(self):            # VOCA-FR-031~034
        self.load_sample()
        page = self.client.get("/study?day=1&per_day=5").get_data(as_text=True)
        word_id = re.search(r'name="word_id" value="(\d+)"', page).group(1)
        self.client.post("/study/next", data={"day": 1, "per_day": 5, "i": 0, "word_id": word_id, "tag": "new"})
        self.finish_exam()
        stats = self.client.get("/?per_day=5").get_data(as_text=True)
        self.assertIn("암기한 단어 1 / 31개", stats)
        self.assertIn("1회", stats)                                     # 회차별
        self.assertIn("0 / 5", stats)                                   # 전부 오답
        self.assertRegex(stats, r"<td>1 / 1</td>")                      # TOP 오답 단어의 틀린 횟수


class LinkRuleTest(WebTestCase):
    """R-04: 첫 화면과 주요 화면의 주소는 따옴표로 감싼 '/' 시작 경로여야 한다."""

    def test_no_host_or_unquoted_attributes(self):
        self.load_sample()
        for path in ("/", "/words", "/study", "/exam"):
            html = self.client.get(path).get_data(as_text=True)
            self.assertNotRegex(html, r"https?://", path)
            self.assertNotRegex(html, r"""(?:href|src|action)=[^"'\s]""", path)
        css = self.client.get("/static/style.css")
        self.assertEqual(css.status_code, 200)
        css.close()


if __name__ == "__main__":
    unittest.main()
