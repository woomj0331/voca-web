#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 2026-11-25 - voca-web - 시험 출제 가중치·문제 생성·채점 (VOCA-FR-021~025)
# 파일 위치: exam.py

"""시험 로직. 순수 함수만 둔다(DB·웹 비의존, 난수기는 인자로 받는다).

데스크톱판(smart-voca)의 exam.py 를 웹 앱용으로 옮겼다.
단어는 Word(id, term, meaning), 시험 이력은 Stat 으로 받는다.
"""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

DIRECTION_KO_EN = "ko_en"   # 한→영: 뜻을 보고 영단어를 쓴다
DIRECTION_EN_KO = "en_ko"   # 영→한: 영단어를 보고 뜻을 쓴다
DIRECTION_MIXED = "mixed"   # 섞기: 문제마다 두 방향 중 무작위
TYPE_SHORT = "short"        # 단답형
TYPE_MC4 = "mc4"            # 4지선다
TYPE_OX = "ox"              # OX형

DIRECTIONS = (DIRECTION_EN_KO, DIRECTION_KO_EN, DIRECTION_MIXED)
TYPES = (TYPE_SHORT, TYPE_MC4, TYPE_OX)

BASE_WEIGHT = 1.0
WEIGHT_NEVER_TESTED = 3.0
WEIGHT_OLD = 2.0
WEIGHT_WRONG_RATE = 4.0
OLD_AFTER = timedelta(days=7)
MC_CHOICES = 4
MC_DISTRACTORS = MC_CHOICES - 1


@dataclass(frozen=True)
class Word:
    id: int
    term: str
    meaning: str


@dataclass
class Stat:
    """한 단어의 시험 이력 요약. attempts=0 이면 시험 본 적 없는 단어다."""
    attempts: int = 0
    wrong: int = 0
    last_time: Optional[datetime] = None

    @property
    def wrong_rate(self):
        return self.wrong / self.attempts if self.attempts else 0.0


@dataclass
class Question:
    word: Word
    direction: str                  # DIRECTION_KO_EN 또는 DIRECTION_EN_KO
    qtype: str                      # TYPE_SHORT, TYPE_MC4, TYPE_OX
    prompt: str                     # 화면에 보여줄 문제 문장
    answer: object                  # short: 정답 문자열, mc4: 보기 인덱스, ox: "O" 또는 "X"
    choices: Optional[list] = None  # mc4 보기 목록
    shown: Optional[str] = None     # ox: 제시된 쌍의 답 쪽 문자열


def normalize(text):
    """앞뒤 공백을 없애고 소문자로 바꾼다(단답 채점용)."""
    return str(text).strip().lower()


def word_weight(stat, now):
    """출제 가중치. stat 이 None 이거나 시도 0회면 '본 적 없는 단어'다 (VOCA-FR-022)."""
    weight = BASE_WEIGHT
    if stat is None or stat.attempts == 0:
        return weight + WEIGHT_NEVER_TESTED
    if stat.last_time is None or now - stat.last_time >= OLD_AFTER:
        weight += WEIGHT_OLD
    weight += WEIGHT_WRONG_RATE * stat.wrong_rate
    return weight


def pick_exam_words(words, stats, count, now, rng):
    """가중치 비례로 중복 없이 count 개를 고른다.

    방법: 각 단어에 key = u ** (1/w) (u 는 0~1 난수)를 주고 큰 순서로 고른다.
    가중치 w 가 클수록 key 가 1 쪽으로 몰리므로 자주 뽑힌다.
    stats 의 key 는 word.id 다. count 가 단어 수보다 크면 단어 수만큼만 뽑는다.
    """
    count = min(count, len(words))
    if count <= 0:
        return []
    keyed = []
    for word in words:
        weight = word_weight(stats.get(word.id), now)
        keyed.append((rng.random() ** (1.0 / weight), word))
    keyed.sort(key=lambda item: item[0], reverse=True)
    return [word for _, word in keyed[:count]]


def resolve_direction(choice, rng):
    """설정 값(ko_en, en_ko, mixed)을 문제 한 개의 실제 방향으로 바꾼다."""
    if choice == DIRECTION_MIXED:
        return rng.choice([DIRECTION_KO_EN, DIRECTION_EN_KO])
    return choice


def _sides(word, direction):
    """(문제 쪽 텍스트, 답 쪽 텍스트)를 방향에 맞춰 돌려준다."""
    if direction == DIRECTION_KO_EN:
        return word.meaning, word.term
    return word.term, word.meaning


def _other_answers(word, pool, direction):
    """같은 방향 기준 '답 쪽' 후보 중 정답이 아닌 것을 중복 없이 모은다."""
    own = _sides(word, direction)[1].lower()
    seen = set()
    candidates = []
    for other in pool:
        answer_side = _sides(other, direction)[1]
        key = answer_side.lower()
        if key == own or key in seen or other.id == word.id:
            continue
        seen.add(key)
        candidates.append(answer_side)
    return candidates


def build_question(word, direction, qtype, pool, rng):
    """단어 한 개로 문제를 만든다. 방향은 DIRECTION_KO_EN 또는 DIRECTION_EN_KO 여야 한다."""
    if direction not in (DIRECTION_KO_EN, DIRECTION_EN_KO):
        raise ValueError(f"알 수 없는 방향입니다: {direction}")
    prompt, correct = _sides(word, direction)
    others = _other_answers(word, pool, direction)

    if qtype == TYPE_SHORT:
        return Question(word, direction, TYPE_SHORT, prompt, correct)

    if qtype == TYPE_MC4:
        distractors = rng.sample(others, min(MC_DISTRACTORS, len(others)))
        choices = distractors + [correct]
        rng.shuffle(choices)
        return Question(word, direction, TYPE_MC4, prompt,
                        answer=choices.index(correct), choices=choices)

    if qtype == TYPE_OX:
        is_true_pair = rng.random() < 0.5
        if is_true_pair or not others:
            shown, answer = correct, "O"
        else:
            shown, answer = rng.choice(others), "X"
        return Question(word, direction, TYPE_OX, prompt, answer=answer, shown=shown)

    raise ValueError(f"알 수 없는 문제 유형입니다: {qtype}")


def grade(qtype, answer, response):
    """응답이 맞으면 True.

    short: 문자열(앞뒤 공백·대소문자 무시), mc4: 보기 인덱스(int), ox: "O"/"X".
    응답이 비었거나 형식이 틀리면 오답으로 본다.
    """
    if qtype == TYPE_SHORT:
        return normalize(response) == normalize(answer)
    if qtype == TYPE_MC4:
        try:
            return int(response) == int(answer)
        except (TypeError, ValueError):
            return False
    if qtype == TYPE_OX:
        return str(response).strip().upper() == str(answer)
    raise ValueError(f"알 수 없는 문제 유형입니다: {qtype}")


def answer_text(qtype, answer, choices, direction, term, meaning):
    """결과 화면에 보여 줄 정답 문구를 만든다."""
    if qtype == TYPE_MC4:
        return choices[int(answer)]
    if qtype == TYPE_OX:
        if answer == "O":
            return "O (맞는 쌍)"
        real = term if direction == DIRECTION_KO_EN else meaning
        return f"X (틀린 쌍, 실제: {real})"
    return str(answer)


def make_rng(seed=None):
    """테스트에서 고정 시드를 넣기 위한 난수기 생성 함수."""
    return random.Random(seed)
