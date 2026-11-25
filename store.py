#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 2026-11-25 - voca-web - 단어·암기·시험 이력의 DB 읽기/쓰기와 통계 집계 (VOCA-FR-001~004, 014, 026, 031~034)
# 파일 위치: store.py

"""SQL 은 이 파일에만 둔다. 화면(app.py)은 여기 함수만 부른다.

시각은 'YYYY-MM-DDTHH:MM:SS' 문자열로 저장한다(서버 로컬 시각).
"""

import csv
import io
import json
import sqlite3
from datetime import datetime

from exam import Stat, Word

CSV_ENCODING = "utf-8-sig"          # 제공 CSV 는 UTF-8 BOM 파일이다
CSV_HEADER_TERMS = {"term", "영단어"}
PAGE_SIZE = 50


def now_text():
    return datetime.now().isoformat(timespec="seconds")


def parse_time(text):
    try:
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None


# ---------- 단어 (VOCA-FR-001~004) ----------

def _insert_word(conn, term, meaning):
    """커밋하지 않고 한 줄 넣는다. 영단어가 이미 있으면 False."""
    try:
        conn.execute("INSERT INTO words (term, meaning, created_at) VALUES (?, ?, ?)",
                     (term, meaning, now_text()))
        return True
    except sqlite3.IntegrityError:
        return False


def add_word(conn, term, meaning):
    """단어를 등록한다. 영단어가 이미 있으면(대소문자 무시) 등록하지 않고 False."""
    added = _insert_word(conn, term, meaning)
    conn.commit()
    return added


def update_word(conn, word_id, term, meaning):
    """수정한다. 결과: 'ok', 'duplicate'(다른 단어와 영단어가 겹침), 'missing'."""
    try:
        cursor = conn.execute("UPDATE words SET term = ?, meaning = ? WHERE id = ?",
                              (term, meaning, word_id))
        conn.commit()
    except sqlite3.IntegrityError:
        return "duplicate"
    return "ok" if cursor.rowcount else "missing"


def delete_word(conn, word_id):
    conn.execute("DELETE FROM words WHERE id = ?", (word_id,))
    conn.commit()


def count_words(conn):
    return conn.execute("SELECT COUNT(*) FROM words").fetchone()[0]


def search_words(conn, query, page):
    """영단어 또는 뜻에 query 가 들어간 단어를 PAGE_SIZE 개씩 돌려준다. (행 목록, 전체 개수)."""
    like = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    where = "WHERE term LIKE ? ESCAPE '\\' OR meaning LIKE ? ESCAPE '\\'"
    total = conn.execute(f"SELECT COUNT(*) FROM words {where}", (like, like)).fetchone()[0]
    rows = conn.execute(
        f"SELECT id, term, meaning FROM words {where} ORDER BY id LIMIT ? OFFSET ?",
        (like, like, PAGE_SIZE, (max(page, 1) - 1) * PAGE_SIZE)).fetchall()
    return rows, total


def all_words(conn):
    """등록 순서대로 전체 단어를 Word 로 돌려준다."""
    rows = conn.execute("SELECT id, term, meaning FROM words ORDER BY id").fetchall()
    return [Word(row["id"], row["term"], row["meaning"]) for row in rows]


def import_csv(conn, raw_bytes):
    """CSV(영단어,뜻)를 일괄 등록한다. 반환: (등록, 중복으로 건너뜀, 형식 오류로 건너뜀).

    중복 정책: 영단어가 이미 있으면(대소문자 무시) 기존 뜻을 유지하고 건너뛴다.
    파일은 디스크에 저장하지 않고 메모리에서 처리한다.
    """
    text = raw_bytes.decode(CSV_ENCODING)
    rows = list(csv.reader(io.StringIO(text)))
    if rows and rows[0] and rows[0][0].strip().lower() in CSV_HEADER_TERMS:
        rows = rows[1:]
    added = duplicated = invalid = 0
    for row in rows:
        if len(row) < 2 or not row[0].strip() or not row[1].strip():
            invalid += 1
        elif _insert_word(conn, row[0].strip(), row[1].strip()):
            added += 1
        else:
            duplicated += 1
    conn.commit()   # 한 번에 커밋한다. 행마다 커밋하면 2,000행에 13초가 걸렸다.
    return added, duplicated, invalid


# ---------- 암기 (VOCA-FR-011~014) ----------

def test_stats(conn):
    """단어별 시험 이력 요약 {word_id: Stat}. 시험 본 적 없는 단어는 들어 있지 않다."""
    rows = conn.execute(
        """SELECT word_id, COUNT(*) AS attempts, SUM(1 - correct) AS wrong, MAX(answered_at) AS last_time
           FROM exam_items WHERE correct IS NOT NULL GROUP BY word_id""").fetchall()
    return {row["word_id"]: Stat(row["attempts"], row["wrong"] or 0, parse_time(row["last_time"]))
            for row in rows}


def log_study(conn, word_id, day, tag):
    """암기 이력 한 건을 남긴다."""
    conn.execute("INSERT INTO study_log (word_id, day, tag, studied_at) VALUES (?, ?, ?, ?)",
                 (word_id, day, tag, now_text()))
    conn.commit()


# ---------- 시험 (VOCA-FR-021~026) ----------

def create_exam(conn, direction, questions):
    """시험과 문항을 한 번에 만든다. 반환: exam_id."""
    cursor = conn.execute(
        "INSERT INTO exams (created_at, direction, question_count) VALUES (?, ?, ?)",
        (now_text(), direction, len(questions)))
    exam_id = cursor.lastrowid
    for seq, question in enumerate(questions, start=1):
        conn.execute(
            """INSERT INTO exam_items (exam_id, seq, word_id, qtype, direction, prompt,
                                       choices_json, answer_json, shown)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (exam_id, seq, question.word.id, question.qtype, question.direction, question.prompt,
             json.dumps(question.choices, ensure_ascii=False) if question.choices else None,
             json.dumps(question.answer, ensure_ascii=False), question.shown))
    conn.commit()
    return exam_id


def get_exam(conn, exam_id):
    return conn.execute("SELECT * FROM exams WHERE id = ?", (exam_id,)).fetchone()


def get_item(conn, exam_id, seq):
    return conn.execute("SELECT * FROM exam_items WHERE exam_id = ? AND seq = ?",
                        (exam_id, seq)).fetchone()


def record_answer(conn, item_id, response, correct):
    """문항의 응답과 정오를 남긴다. 이미 답한 문항이면 바꾸지 않는다(False)."""
    cursor = conn.execute(
        """UPDATE exam_items SET response_json = ?, correct = ?, answered_at = ?
           WHERE id = ? AND correct IS NULL""",
        (json.dumps(response, ensure_ascii=False), 1 if correct else 0, now_text(), item_id))
    conn.commit()
    return cursor.rowcount == 1


def finish_exam(conn, exam_id):
    conn.execute("UPDATE exams SET finished_at = ? WHERE id = ? AND finished_at IS NULL",
                 (now_text(), exam_id))
    conn.commit()


def exam_items_with_words(conn, exam_id):
    """결과 화면용: 문항 + 단어 정보."""
    return conn.execute(
        """SELECT i.*, w.term, w.meaning FROM exam_items i JOIN words w ON w.id = i.word_id
           WHERE i.exam_id = ? ORDER BY i.seq""", (exam_id,)).fetchall()


# ---------- 통계 (VOCA-FR-031~034) ----------

def progress_summary(conn, per_day):
    """진도 현황: 현재 일차, 암기한 단어 수 / 전체, 전체 일차 수."""
    total = count_words(conn)
    last_day = conn.execute("SELECT MAX(day) FROM study_log").fetchone()[0]
    studied = conn.execute("SELECT COUNT(DISTINCT word_id) FROM study_log").fetchone()[0]
    days = -(-total // per_day) if total else 0
    return {"current_day": last_day or 1, "studied": studied, "total": total, "total_days": days}


def score_by_exam(conn):
    """회차별 정답률(끝낸 시험만, 오래된 순)."""
    rows = conn.execute(
        """SELECT e.id, e.finished_at, SUM(i.correct) AS right_count, COUNT(*) AS total
           FROM exams e JOIN exam_items i ON i.exam_id = e.id
           WHERE e.finished_at IS NOT NULL GROUP BY e.id ORDER BY e.id""").fetchall()
    return [{"round": number, "exam_id": row["id"], "date": row["finished_at"][:10],
             "right": row["right_count"], "total": row["total"],
             "rate": round(100 * row["right_count"] / row["total"])}
            for number, row in enumerate(rows, start=1)]


def score_by_date(conn):
    """날짜별 정답률(푼 문항 기준, 오래된 순)."""
    rows = conn.execute(
        """SELECT substr(answered_at, 1, 10) AS day, SUM(correct) AS right_count, COUNT(*) AS total
           FROM exam_items WHERE correct IS NOT NULL GROUP BY day ORDER BY day""").fetchall()
    return [{"date": row["day"], "right": row["right_count"], "total": row["total"],
             "rate": round(100 * row["right_count"] / row["total"])} for row in rows]


def top_wrong_words(conn, limit):
    """자주 틀리는 단어 상위 limit 개 (틀린 횟수 → 오답률 순)."""
    rows = conn.execute(
        """SELECT w.term, w.meaning, COUNT(*) AS attempts, SUM(1 - i.correct) AS wrong
           FROM exam_items i JOIN words w ON w.id = i.word_id
           WHERE i.correct IS NOT NULL GROUP BY w.id HAVING wrong > 0
           ORDER BY wrong DESC, 1.0 * wrong / attempts DESC, w.term LIMIT ?""", (limit,)).fetchall()
    return [{"term": row["term"], "meaning": row["meaning"], "attempts": row["attempts"],
             "wrong": row["wrong"], "rate": round(100 * row["wrong"] / row["attempts"])}
            for row in rows]
