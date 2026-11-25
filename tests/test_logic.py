#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 2026-11-25 - voca-web - 출제·채점·암기 계획 단위 테스트 (VOCA-FR-011, 013, 022~024)
# 파일 위치: tests/test_logic.py

import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import exam
import study_plan
from exam import Stat, Word

NOW = datetime(2026, 11, 25, 12, 0, 0)
WORDS = [Word(i, f"word{i}", f"뜻{i}") for i in range(1, 31)]


class WeightTest(unittest.TestCase):
    def test_never_tested_is_heaviest_base(self):
        self.assertEqual(exam.word_weight(None, NOW), 4.0)
        self.assertEqual(exam.word_weight(Stat(), NOW), 4.0)

    def test_old_and_wrong_raise_weight(self):
        fresh = Stat(4, 0, NOW - timedelta(days=1))
        old = Stat(4, 0, NOW - timedelta(days=30))
        wrong = Stat(4, 4, NOW - timedelta(days=1))
        self.assertEqual(exam.word_weight(fresh, NOW), 1.0)
        self.assertEqual(exam.word_weight(old, NOW), 3.0)
        self.assertEqual(exam.word_weight(wrong, NOW), 5.0)

    def test_pick_count_and_no_duplicates(self):
        picked = exam.pick_exam_words(WORDS, {}, 10, NOW, exam.make_rng(1))
        self.assertEqual(len(picked), 10)
        self.assertEqual(len({w.id for w in picked}), 10)

    def test_pick_more_than_available(self):
        self.assertEqual(len(exam.pick_exam_words(WORDS, {}, 99, NOW, exam.make_rng(1))), 30)

    def test_wrong_words_picked_more_often(self):
        stats = {w.id: Stat(10, 0, NOW) for w in WORDS}
        stats[1] = Stat(10, 10, NOW)          # 1번만 늘 틀림
        hits = sum(1 for seed in range(300)
                   if WORDS[0] in exam.pick_exam_words(WORDS, stats, 3, NOW, exam.make_rng(seed)))
        self.assertGreater(hits, 100)         # 무작위(3/30=10%)보다 훨씬 자주 뽑힌다


class QuestionTest(unittest.TestCase):
    def setUp(self):
        self.rng = exam.make_rng(7)

    def test_short_direction(self):
        q = exam.build_question(WORDS[0], exam.DIRECTION_EN_KO, exam.TYPE_SHORT, WORDS, self.rng)
        self.assertEqual((q.prompt, q.answer), ("word1", "뜻1"))
        q = exam.build_question(WORDS[0], exam.DIRECTION_KO_EN, exam.TYPE_SHORT, WORDS, self.rng)
        self.assertEqual((q.prompt, q.answer), ("뜻1", "word1"))

    def test_mc4_has_four_unique_choices_with_answer(self):
        q = exam.build_question(WORDS[0], exam.DIRECTION_EN_KO, exam.TYPE_MC4, WORDS, self.rng)
        self.assertEqual(len(q.choices), 4)
        self.assertEqual(len(set(q.choices)), 4)
        self.assertEqual(q.choices[q.answer], "뜻1")

    def test_ox_answer_matches_shown(self):
        for seed in range(30):
            q = exam.build_question(WORDS[0], exam.DIRECTION_EN_KO, exam.TYPE_OX, WORDS,
                                    exam.make_rng(seed))
            self.assertEqual(q.answer == "O", q.shown == "뜻1")

    def test_mixed_resolves_to_concrete_direction(self):
        seen = {exam.resolve_direction(exam.DIRECTION_MIXED, exam.make_rng(s)) for s in range(20)}
        self.assertEqual(seen, {exam.DIRECTION_KO_EN, exam.DIRECTION_EN_KO})

    def test_unknown_type_raises(self):
        with self.assertRaises(ValueError):
            exam.build_question(WORDS[0], exam.DIRECTION_EN_KO, "zzz", WORDS, self.rng)


class GradeTest(unittest.TestCase):
    def test_short_ignores_case_and_spaces(self):
        self.assertTrue(exam.grade(exam.TYPE_SHORT, "Apple", "  apple "))
        self.assertFalse(exam.grade(exam.TYPE_SHORT, "apple", ""))

    def test_mc4(self):
        self.assertTrue(exam.grade(exam.TYPE_MC4, 2, "2"))
        self.assertFalse(exam.grade(exam.TYPE_MC4, 2, "1"))
        self.assertFalse(exam.grade(exam.TYPE_MC4, 2, ""))

    def test_ox(self):
        self.assertTrue(exam.grade(exam.TYPE_OX, "O", "o"))
        self.assertFalse(exam.grade(exam.TYPE_OX, "O", "X"))


class StudyPlanTest(unittest.TestCase):
    def test_day1_has_only_new_words(self):
        plan = study_plan.build_day_plan(WORDS, {}, 1, 10)
        self.assertEqual([p.word.id for p in plan], list(range(1, 11)))
        self.assertTrue(all(p.tag == study_plan.TAG_NEW for p in plan))

    def test_day2_mixes_previous_day_review(self):
        plan = study_plan.build_day_plan(WORDS, {}, 2, 10)
        tags = [p.tag for p in plan]
        self.assertEqual(tags.count(study_plan.TAG_NEW), 10)
        self.assertEqual(tags.count(study_plan.TAG_PREV), 3)   # ceil(10 * 0.3)

    def test_wrong_words_are_added_up_to_limit(self):
        stats = {w.id: Stat(4, 4, NOW) for w in WORDS[:5]}
        plan = study_plan.build_day_plan(WORDS, stats, 3, 10)
        self.assertEqual(sum(1 for p in plan if p.tag == study_plan.TAG_WRONG), 2)  # floor(10*0.2)

    def test_no_duplicate_words(self):
        stats = {w.id: Stat(4, 4, NOW) for w in WORDS}
        plan = study_plan.build_day_plan(WORDS, stats, 2, 10)
        ids = [p.word.id for p in plan]
        self.assertEqual(len(ids), len(set(ids)))

    def test_day_out_of_range_is_empty(self):
        self.assertEqual(study_plan.build_day_plan(WORDS, {}, 99, 10), [])

    def test_invalid_args(self):
        with self.assertRaises(ValueError):
            study_plan.build_day_plan(WORDS, {}, 0, 10)

    def test_total_days(self):
        self.assertEqual(study_plan.total_days(30, 10), 3)
        self.assertEqual(study_plan.total_days(31, 10), 4)


if __name__ == "__main__":
    unittest.main()
