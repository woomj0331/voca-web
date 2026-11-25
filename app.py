#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 2026-11-25 - voca-web - Flask 웹 앱: 단어 등록·암기·시험·학습 통계 화면 (VOCA-FR-001~034)
# 파일 위치: app.py

"""라우트 모음. SQL 은 store.py, 출제·계획 계산은 exam.py·study_plan.py 가 맡는다.

주소는 모두 '/' 기준이다. 서버가 /2026/voca-<학번>/ 아래로 옮겨 주므로 접두어를 코드에 쓰지 않는다.
메시지는 세션(쿠키) 대신 쿼리 문자열(msg)로 넘긴다. 그래서 SECRET_KEY 가 필요 없다.
"""

import json
import sqlite3
from datetime import datetime

from flask import Flask, abort, g, redirect, render_template, request, url_for

import db
import exam
import store
import study_plan

DEFAULT_PER_DAY = 10
MAX_PER_DAY = 200
MAX_EXAM_QUESTIONS = 100
TOP_WRONG_LIMIT = 10
MAX_CSV_BYTES = 5 * 1024 * 1024
TYPE_LABELS = {exam.TYPE_SHORT: "단답형", exam.TYPE_MC4: "4지선다", exam.TYPE_OX: "OX"}
DIRECTION_LABELS = {exam.DIRECTION_EN_KO: "영→한", exam.DIRECTION_KO_EN: "한→영",
                    exam.DIRECTION_MIXED: "섞기"}
TAG_LABELS = {study_plan.TAG_NEW: "신규", study_plan.TAG_PREV: "전날 복습",
              study_plan.TAG_WRONG: "자주 틀린 단어"}


def to_int(text, default, low=None, high=None):
    """문자열을 정수로 바꾼다. 실패하면 default, 범위를 벗어나면 가까운 끝으로 맞춘다."""
    try:
        value = int(text)
    except (TypeError, ValueError):
        return default
    if low is not None:
        value = max(low, value)
    if high is not None:
        value = min(high, value)
    return value


def create_app(db_path=None):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024
    app.config["DB_PATH_OVERRIDE"] = db_path
    db.init_db(db_path)

    def conn():
        if "conn" not in g:
            g.conn = db.connect(app.config["DB_PATH_OVERRIDE"])
        return g.conn

    @app.teardown_appcontext
    def close_conn(_error):
        opened = g.pop("conn", None)
        if opened is not None:
            opened.close()

    app.jinja_env.globals.update(TYPE_LABELS=TYPE_LABELS, DIRECTION_LABELS=DIRECTION_LABELS,
                                 TAG_LABELS=TAG_LABELS)

    # ---------- 통계 (첫 화면) ----------

    @app.route("/")
    def home():
        per_day = to_int(request.args.get("per_day"), DEFAULT_PER_DAY, 1, MAX_PER_DAY)
        return render_template(
            "stats.html", per_day=per_day, progress=store.progress_summary(conn(), per_day),
            by_exam=store.score_by_exam(conn()), by_date=store.score_by_date(conn()),
            top_wrong=store.top_wrong_words(conn(), TOP_WRONG_LIMIT))

    # ---------- 단어 ----------

    @app.route("/words")
    def words():
        query = request.args.get("q", "").strip()
        page = to_int(request.args.get("page"), 1, 1)
        rows, total = store.search_words(conn(), query, page)
        pages = max(1, -(-total // store.PAGE_SIZE))
        return render_template("words.html", rows=rows, total=total, query=query, page=page,
                               pages=pages, msg=request.args.get("msg", ""))

    def back_to_words(message):
        return redirect(url_for("words", msg=message))

    @app.post("/words/add")
    def words_add():
        term = request.form.get("term", "").strip()
        meaning = request.form.get("meaning", "").strip()
        if not term or not meaning:
            return back_to_words("영단어와 뜻을 모두 입력하세요.")
        if store.add_word(conn(), term, meaning):
            return back_to_words(f"'{term}' 등록 완료")
        return back_to_words(f"'{term}' 은(는) 이미 등록돼 있습니다.")

    @app.post("/words/<int:word_id>/edit")
    def words_edit(word_id):
        term = request.form.get("term", "").strip()
        meaning = request.form.get("meaning", "").strip()
        if not term or not meaning:
            return back_to_words("영단어와 뜻을 모두 입력하세요.")
        result = store.update_word(conn(), word_id, term, meaning)
        if result == "missing":
            abort(404)
        if result == "duplicate":
            return back_to_words(f"'{term}' 은(는) 다른 단어로 이미 등록돼 있습니다.")
        return back_to_words(f"'{term}' 수정 완료")

    @app.post("/words/<int:word_id>/delete")
    def words_delete(word_id):
        store.delete_word(conn(), word_id)
        return back_to_words("삭제했습니다.")

    @app.post("/words/import")
    def words_import():
        upload = request.files.get("csv_file")
        if upload is None or not upload.filename:
            return back_to_words("CSV 파일을 선택하세요.")
        raw = upload.read(MAX_CSV_BYTES + 1)
        if len(raw) > MAX_CSV_BYTES:
            return back_to_words("파일이 너무 큽니다(5MB 이하).")
        try:
            added, duplicated, invalid = store.import_csv(conn(), raw)
        except UnicodeDecodeError:
            return back_to_words("UTF-8 CSV 파일이 아닙니다.")
        return back_to_words(
            f"가져오기 완료: {added}개 등록, 중복 {duplicated}개 건너뜀, 형식 오류 {invalid}개 건너뜀")

    # ---------- 암기 ----------

    @app.route("/study")
    def study():
        per_day = to_int(request.args.get("per_day"), DEFAULT_PER_DAY, 1, MAX_PER_DAY)
        progress = store.progress_summary(conn(), per_day)
        day = to_int(request.args.get("day"), progress["current_day"], 1)
        index = to_int(request.args.get("i"), 0, 0)
        plan = study_plan.build_day_plan(store.all_words(conn()), store.test_stats(conn()), day, per_day)
        item = plan[index] if index < len(plan) else None
        return render_template("study.html", day=day, per_day=per_day, index=index, plan=plan,
                               item=item, total_days=progress["total_days"])

    @app.post("/study/next")
    def study_next():
        day = to_int(request.form.get("day"), 1, 1)
        per_day = to_int(request.form.get("per_day"), DEFAULT_PER_DAY, 1, MAX_PER_DAY)
        index = to_int(request.form.get("i"), 0, 0)
        word_id = to_int(request.form.get("word_id"), 0)
        tag = request.form.get("tag", "")
        if tag not in TAG_LABELS:
            abort(400)
        try:
            store.log_study(conn(), word_id, day, tag)
        except sqlite3.IntegrityError:
            abort(400)
        return redirect(url_for("study", day=day, per_day=per_day, i=index + 1))

    # ---------- 시험 ----------

    @app.route("/exam")
    def exam_form():
        return render_template("exam_form.html", total=store.count_words(conn()),
                               msg=request.args.get("msg", ""), types=exam.TYPES,
                               directions=exam.DIRECTIONS)

    @app.post("/exam/start")
    def exam_start():
        word_list = store.all_words(conn())
        count = to_int(request.form.get("count"), 10, 1, MAX_EXAM_QUESTIONS)
        direction = request.form.get("direction", exam.DIRECTION_EN_KO)
        types = [t for t in request.form.getlist("types") if t in exam.TYPES]
        if direction not in exam.DIRECTIONS:
            direction = exam.DIRECTION_EN_KO
        if not word_list:
            return redirect(url_for("exam_form", msg="먼저 단어를 등록하세요."))
        if not types:
            return redirect(url_for("exam_form", msg="출제 형식을 하나 이상 고르세요."))
        if exam.TYPE_MC4 in types and len(word_list) < exam.MC_CHOICES:
            return redirect(url_for("exam_form", msg="4지선다는 단어가 4개 이상일 때 쓸 수 있습니다."))
        rng = exam.make_rng()
        picked = exam.pick_exam_words(word_list, store.test_stats(conn()), count, datetime.now(), rng)
        questions = [exam.build_question(word, exam.resolve_direction(direction, rng),
                                         rng.choice(types), word_list, rng) for word in picked]
        exam_id = store.create_exam(conn(), direction, questions)
        return redirect(url_for("exam_question", exam_id=exam_id, seq=1))

    @app.route("/exam/<int:exam_id>/<int:seq>")
    def exam_question(exam_id, seq):
        exam_row = store.get_exam(conn(), exam_id)
        item = store.get_item(conn(), exam_id, seq)
        if exam_row is None or item is None:
            abort(404)
        if exam_row["finished_at"]:
            return redirect(url_for("exam_result", exam_id=exam_id))
        if item["correct"] is not None:   # 이미 답한 문항이면 다음으로 보낸다
            return redirect(next_step(exam_row, seq))
        choices = json.loads(item["choices_json"]) if item["choices_json"] else []
        return render_template("exam_question.html", exam=exam_row, item=item, seq=seq,
                               choices=choices)

    def next_step(exam_row, seq):
        if seq >= exam_row["question_count"]:
            store.finish_exam(conn(), exam_row["id"])
            return url_for("exam_result", exam_id=exam_row["id"])
        return url_for("exam_question", exam_id=exam_row["id"], seq=seq + 1)

    @app.post("/exam/<int:exam_id>/<int:seq>")
    def exam_answer(exam_id, seq):
        exam_row = store.get_exam(conn(), exam_id)
        item = store.get_item(conn(), exam_id, seq)
        if exam_row is None or item is None:
            abort(404)
        if item["correct"] is None and not exam_row["finished_at"]:
            response = request.form.get("response", "")
            correct = exam.grade(item["qtype"], json.loads(item["answer_json"]), response)
            store.record_answer(conn(), item["id"], response, correct)
        return redirect(next_step(exam_row, seq))

    @app.route("/exam/<int:exam_id>/result")
    def exam_result(exam_id):
        exam_row = store.get_exam(conn(), exam_id)
        if exam_row is None:
            abort(404)
        rows = store.exam_items_with_words(conn(), exam_id)
        unanswered = [row["seq"] for row in rows if row["correct"] is None]
        if unanswered:
            return redirect(url_for("exam_question", exam_id=exam_id, seq=unanswered[0]))
        wrong = []
        for row in rows:
            if row["correct"]:
                continue
            choices = json.loads(row["choices_json"]) if row["choices_json"] else []
            answer = json.loads(row["answer_json"])
            response = json.loads(row["response_json"]) if row["response_json"] else ""
            given = choices[int(response)] if row["qtype"] == exam.TYPE_MC4 and str(response).isdigit() \
                and int(response) < len(choices) else response
            wrong.append({"seq": row["seq"], "prompt": row["prompt"], "shown": row["shown"],
                          "qtype": row["qtype"], "given": given,
                          "answer": exam.answer_text(row["qtype"], answer, choices, row["direction"],
                                                     row["term"], row["meaning"])})
        right = sum(row["correct"] for row in rows)
        return render_template("exam_result.html", exam=exam_row, right=right, total=len(rows),
                               rate=round(100 * right / len(rows)) if rows else 0, wrong=wrong)

    return app


app = create_app()


if __name__ == "__main__":   # 개발용 직접 실행. 서버에서는 gunicorn 이 app 을 띄운다.
    app.run(host="0.0.0.0", port=8080)
