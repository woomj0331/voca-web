#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 2026-11-25 - voca-web - SQLite 연결과 테이블 자동 생성 (VOCA-NFR-002, NFR-003)
# 파일 위치: db.py

"""SQLite 접속과 스키마. 파일 위치는 환경변수 DB_PATH 를 따른다(없으면 현재 폴더의 voca.db).

처음 실행하면 init_db() 가 테이블을 만든다. 이미 있으면 그대로 둔다(CREATE IF NOT EXISTS).
"""

import os
import sqlite3

DEFAULT_DB_PATH = "voca.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS words (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    term TEXT NOT NULL COLLATE NOCASE UNIQUE,
    meaning TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS study_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    day INTEGER NOT NULL,
    tag TEXT NOT NULL,
    studied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS exams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    direction TEXT NOT NULL,
    question_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS exam_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_id INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    qtype TEXT NOT NULL,
    direction TEXT NOT NULL,
    prompt TEXT NOT NULL,
    choices_json TEXT,
    answer_json TEXT NOT NULL,
    shown TEXT,
    response_json TEXT,
    correct INTEGER,
    answered_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_study_log_word ON study_log(word_id);
CREATE INDEX IF NOT EXISTS idx_exam_items_word ON exam_items(word_id);
CREATE INDEX IF NOT EXISTS idx_exam_items_exam ON exam_items(exam_id, seq);
"""


def db_path():
    return os.environ.get("DB_PATH", DEFAULT_DB_PATH)


def connect(path=None):
    """연결을 만든다. 행을 이름으로 읽을 수 있게 하고 외래키를 켠다."""
    conn = sqlite3.connect(path or db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path=None):
    """테이블이 없으면 만든다. 상위 폴더가 없으면 먼저 만든다."""
    target = path or db_path()
    parent = os.path.dirname(os.path.abspath(target))
    os.makedirs(parent, exist_ok=True)
    conn = connect(target)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
