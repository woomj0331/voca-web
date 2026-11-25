#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 2026-11-25 - voca-web - 일차별 암기 계획 생성 (VOCA-FR-011, FR-013)
# 파일 위치: study_plan.py

"""일차 계획 = 신규 단어 + 전날 복습 일부 + 자주 틀린 단어.

순수 함수만 둔다. DB 를 읽지 않고, 단어 목록과 시험 이력 요약(Stat)을 인자로 받는다.
데스크톱판(smart-voca)의 study_plan.py 를 웹 앱용으로 옮겼다.
"""

import math
from dataclasses import dataclass

TAG_NEW = "new"
TAG_PREV = "prev"
TAG_WRONG = "wrong"

PREV_REVIEW_RATIO = 0.3   # 전날 신규 단어 중 복습 비율
WRONG_RATIO = 0.2         # 하루 단어 수 대비 오답 복습 상한 비율
WRONG_MIN_ATTEMPTS = 2    # 오답 복습 대상이 되려면 최소 시도 횟수
WRONG_MIN_RATE = 0.5      # 오답 복습 대상의 최소 오답률


@dataclass(frozen=True)
class PlanItem:
    word: object   # exam.Word
    tag: str       # TAG_NEW, TAG_PREV, TAG_WRONG


def total_days(word_count, per_day):
    """전체 단어를 per_day 개씩 나눴을 때의 일차 수."""
    if per_day < 1:
        raise ValueError("하루 단어 수는 1 이상이어야 합니다.")
    return math.ceil(word_count / per_day)


def _new_words_of_day(words, day, per_day):
    start = (day - 1) * per_day
    return words[start:start + per_day]


def _wrong_candidates(words, stats, per_day):
    """자주 틀린 단어를 오답률 순으로 고른다. 최대 floor(0.2 × N)개."""
    limit = math.floor(WRONG_RATIO * per_day)
    candidates = []
    for word in words:
        stat = stats.get(word.id)
        if stat is None:
            continue
        if stat.attempts >= WRONG_MIN_ATTEMPTS and stat.wrong_rate >= WRONG_MIN_RATE:
            candidates.append((stat.wrong_rate, stat.wrong, word))
    candidates.sort(key=lambda item: (-item[0], -item[1], item[2].id))
    return [word for _, _, word in candidates[:limit]]


def build_day_plan(words, stats, day, per_day):
    """선택한 일차의 암기 계획을 만든다.

    words 는 등록 순서(id 오름차순)로 정렬돼 있어야 한다. stats 의 key 는 word.id.
    반환: PlanItem 목록. 같은 단어는 한 번만 넣고, 우선순위는 신규 > 전날 > 오답.
    단어장 범위를 벗어난 일차는 신규 단어가 없으므로 빈 목록을 돌려준다.
    """
    if day < 1 or per_day < 1:
        raise ValueError("일차와 하루 단어 수는 1 이상이어야 합니다.")

    new_words = _new_words_of_day(words, day, per_day)
    if not new_words:
        return []

    prev_words = []
    if day > 1:
        previous_new = _new_words_of_day(words, day - 1, per_day)
        prev_count = math.ceil(PREV_REVIEW_RATIO * len(previous_new))
        prev_words = previous_new[:prev_count]

    wrong_words = _wrong_candidates(words, stats, per_day)

    plan = []
    seen = set()
    for tag, group in ((TAG_NEW, new_words), (TAG_PREV, prev_words), (TAG_WRONG, wrong_words)):
        for word in group:
            if word.id in seen:
                continue
            seen.add(word.id)
            plan.append(PlanItem(word=word, tag=tag))
    return plan
