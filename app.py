import os
import csv
import sqlite3
from datetime import datetime
from flask import Flask, request, redirect, url_for, render_template, send_file, jsonify, abort
from werkzeug.utils import secure_filename

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(APP_ROOT, "uploads")
DB_PATH = os.path.join(APP_ROOT, "instance", "app.db")

ALLOWED_EXTS = {"mp4", "mov", "mkv", "webm"}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024  # 2GB
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS projects (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      created_at TEXT NOT NULL
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS videos (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      project_id INTEGER NOT NULL,
      filename TEXT NOT NULL,
      original_name TEXT NOT NULL,
      fps REAL,
      duration REAL,
      created_at TEXT NOT NULL,
      FOREIGN KEY(project_id) REFERENCES projects(id)
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS annotations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        video_id INTEGER NOT NULL,
        type TEXT NOT NULL,
        t_start REAL NOT NULL,
        t_end REAL,
        dominant_category TEXT,
        core_decision TEXT,
        risk TEXT,
        note TEXT,
        order_index INTEGER DEFAULT 0,
        created_at TEXT NOT NULL
    );
    """)
    conn.commit()
    conn.close()


def allowed_file(name: str) -> bool:
    if "." not in name:
        return False
    ext = name.rsplit(".", 1)[1].lower()
    return ext in ALLOWED_EXTS


def fmt_mmss(seconds: float) -> str:
    if seconds is None:
        return ""
    seconds = max(0.0, float(seconds))
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"


@app.route("/")
def index():
    conn = db()
    projects = conn.execute("SELECT * FROM projects ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("index.html", projects=projects)


@app.route("/projects/new", methods=["POST"])
def new_project():
    name = (request.form.get("name") or "").strip()
    if not name:
        name = "Untitled Project"
    conn = db()
    cur = conn.cursor()
    cur.execute("INSERT INTO projects (name, created_at) VALUES (?, ?)",
                (name, datetime.utcnow().isoformat()))
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    return redirect(url_for("project", project_id=pid))


@app.route("/projects/<int:project_id>")
def project(project_id):
    conn = db()
    proj = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if not proj:
        conn.close()
        abort(404)
    videos = conn.execute("SELECT * FROM videos WHERE project_id=? ORDER BY id DESC", (project_id,)).fetchall()
    conn.close()
    return render_template("project.html", project=proj, videos=videos)


@app.route("/projects/<int:project_id>/upload", methods=["POST"])
def upload_video(project_id):
    f = request.files.get("file")
    if not f or f.filename == "":
        return jsonify({"ok": False, "error": "No file"}), 400
    if not allowed_file(f.filename):
        return jsonify({"ok": False, "error": "Unsupported file type"}), 400

    original_name = f.filename
    safe = secure_filename(original_name)
    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    stored_name = f"{stamp}_{safe}"
    path = os.path.join(UPLOAD_DIR, stored_name)
    f.save(path)

    fps = request.form.get("fps")
    fps = float(fps) if fps and fps.strip() else None

    conn = db()
    cur = conn.cursor()
    cur.execute("""
      INSERT INTO videos (project_id, filename, original_name, fps, duration, created_at)
      VALUES (?, ?, ?, ?, ?, ?)
    """, (project_id, stored_name, original_name, fps, None, datetime.utcnow().isoformat()))
    vid = cur.lastrowid
    conn.commit()
    conn.close()

    return jsonify({"ok": True, "video_id": vid})


@app.route("/media/<path:filename>")
def media(filename):
    return send_file(os.path.join(UPLOAD_DIR, filename), conditional=True)


@app.route("/api/videos/<int:video_id>")
def api_video(video_id):
    conn = db()
    v = conn.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
    if not v:
        conn.close()
        return jsonify({"ok": False, "error": "Not found"}), 404
    ann = conn.execute("""
      SELECT * FROM annotations WHERE video_id=? ORDER BY order_index ASC, t_start ASC, id ASC
    """, (video_id,)).fetchall()
    conn.close()
    return jsonify({
        "ok": True,
        "video": dict(v),
        "annotations": [dict(a) for a in ann]
    })


@app.route("/api/videos/<int:video_id>/update_meta", methods=["POST"])
def api_update_meta(video_id):
    data = request.get_json(force=True)
    fps = data.get("fps")
    duration = data.get("duration")
    conn = db()
    conn.execute("UPDATE videos SET fps=?, duration=? WHERE id=?",
                 (fps, duration, video_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/videos/<int:video_id>/annotations", methods=["POST"])
def api_add_annotation(video_id):
    data = request.get_json(force=True)
    a_type = data.get("type")
    if a_type not in ("segmentation", "observation"):
        return jsonify({"ok": False, "error": "Invalid type"}), 400

    t_start = float(data.get("t_start", 0))
    t_end = data.get("t_end")
    t_end = float(t_end) if (t_end is not None and str(t_end).strip() != "") else None

    dominant_category = (data.get("dominant_category") or "").strip()
    core_decision = (data.get("core_decision") or "").strip()
    risk = (data.get("risk") or "").strip()
    note = (data.get("note") or "").strip()

    conn = db()
    cur = conn.cursor()
    cur.execute("""
      INSERT INTO annotations
      (video_id, type, t_start, t_end, dominant_category, core_decision, risk, note, created_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (video_id, a_type, t_start, t_end, dominant_category, core_decision, risk, note, datetime.utcnow().isoformat()))
    ann_id = cur.lastrowid
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "id": ann_id})


@app.route("/api/annotations/<int:ann_id>", methods=["DELETE"])
def api_delete_annotation(ann_id):
    conn = db()
    conn.execute("DELETE FROM annotations WHERE id=?", (ann_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/export/<int:video_id>/segmentation.csv")
def export_segmentation(video_id):
    conn = db()
    v = conn.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
    if not v:
        conn.close()
        abort(404)
    rows = conn.execute("""
      SELECT * FROM annotations
      WHERE video_id=? AND type='segmentation'
      ORDER BY order_index ASC, t_start ASC
    """, (video_id,)).fetchall()
    conn.close()

    out_path = os.path.join(APP_ROOT, f"segmentation_{video_id}.csv")
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["segment", "time_start(mm:ss)", "time_end(mm:ss)", "dominant_category", "core_player_decision", "risk",
                    "t_start_seconds", "t_end_seconds"])
        for i, r in enumerate(rows, 1):
            w.writerow([f"S{i}", fmt_mmss(r["t_start"]), fmt_mmss(r["t_end"]),
                        r["dominant_category"], r["core_decision"], r["risk"],
                        r["t_start"], r["t_end"]])

    return send_file(out_path, as_attachment=True, download_name=f"segmentation_{video_id}.csv")


@app.route("/export/<int:video_id>/observations.csv")
def export_observations(video_id):
    conn = db()
    v = conn.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
    if not v:
        conn.close()
        abort(404)
    rows = conn.execute("""
      SELECT * FROM annotations
      WHERE video_id=? AND type='observation'
      ORDER BY t_start ASC, id ASC
    """, (video_id,)).fetchall()
    conn.close()

    fps = v["fps"]
    out_path = os.path.join(APP_ROOT, f"observations_{video_id}.csv")
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["time(mm:ss)", "note", "t_seconds", "frame_index(if_fps)", "fps"])
        for r in rows:
            frame_index = ""
            if fps and fps > 0:
                frame_index = int(round(float(r["t_start"]) * float(fps)))
            w.writerow([fmt_mmss(r["t_start"]), r["note"], r["t_start"], frame_index, fps or ""])

    return send_file(out_path, as_attachment=True, download_name=f"observations_{video_id}.csv")

@app.route("/api/annotations/<int:ann_id>", methods=["PUT"])
def api_update_annotation(ann_id):
    data = request.get_json(force=True)

    conn = db()
    conn.execute("""
        UPDATE annotations
        SET
            t_start=?,
            t_end=?,
            dominant_category=?,
            core_decision=?,
            risk=?,
            note=?
        WHERE id=?
    """, (
        data.get("t_start"),
        data.get("t_end"),
        data.get("dominant_category"),
        data.get("core_decision"),
        data.get("risk"),
        data.get("note"),
        ann_id
    ))

    conn.commit()
    conn.close()

    return jsonify({"ok": True})

@app.route("/api/annotations/reorder", methods=["POST"])
def api_reorder_annotations():
    data = request.get_json(force=True)
    order = data.get("order")

    conn = db()

    for idx, ann_id in enumerate(order):
        conn.execute(
            "UPDATE annotations SET order_index=? WHERE id=?",
            (idx, ann_id)
        )

    conn.commit()
    conn.close()

    return jsonify({"ok": True})




if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5001)