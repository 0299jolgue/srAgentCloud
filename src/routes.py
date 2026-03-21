import os
import sys
import re
import json
import shutil
import queue
import sqlite3
import subprocess
import threading
import time
from datetime import datetime

from flask import request, jsonify, render_template, Response, stream_with_context, send_file

from config import PROJECTS_DIR, DB_PATH, read_config, write_config
from database import get_db, save_message
from state import get_state, _running_processes, _proc_lock
from agent import build_system_prompt, run_agent

def register_routes(app):
    """Register all Flask routes on the given app instance."""

    # ─── Pages ────────────────────────────────────────────────────────────────

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/admin")
    def admin_page():
        return render_template("admin.html")

    # ─── Projects ─────────────────────────────────────────────────────────────

    @app.route("/api/projects", methods=["GET"])
    def list_projects():
        with get_db() as conn:
            rows = conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
        return jsonify([dict(r) for r in rows])

    @app.route("/api/projects", methods=["POST"])
    def create_project():
        data = request.get_json()
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "Name required"}), 400

        folder_name = re.sub(r"[^\w\-]", "_", name)
        path = os.path.join(PROJECTS_DIR, folder_name)
        if os.path.exists(path):
            return jsonify({"error": "Project folder already exists"}), 400

        os.makedirs(path, exist_ok=True)

        try:
            result = subprocess.run(
                [sys.executable, "-m", "venv", os.path.join(path, "venv")],
                capture_output=True, text=True, timeout=120
            )
            venv_ok = result.returncode == 0
        except Exception:
            venv_ok = False

        with get_db() as conn:
            cur = conn.execute("INSERT INTO projects (name, path) VALUES (?, ?)", (name, path))
            project_id = cur.lastrowid
            tcur = conn.execute("INSERT INTO threads (project_id, title) VALUES (?, ?)", (project_id, "Main Thread"))
            thread_id = tcur.lastrowid

        return jsonify({"id": project_id, "name": name, "path": path,
                        "venv_created": venv_ok, "default_thread_id": thread_id})

    # ─── Threads ──────────────────────────────────────────────────────────────

    @app.route("/api/projects/<int:pid>/threads", methods=["GET"])
    def list_threads(pid):
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM threads WHERE project_id=? ORDER BY created_at ASC", (pid,)
            ).fetchall()
        return jsonify([dict(r) for r in rows])

    @app.route("/api/projects/<int:pid>/threads", methods=["POST"])
    def create_thread(pid):
        data = request.get_json()
        title = (data.get("title") or "").strip()
        if not title:
            return jsonify({"error": "Title required"}), 400
        with get_db() as conn:
            if not conn.execute("SELECT id FROM projects WHERE id=?", (pid,)).fetchone():
                return jsonify({"error": "Project not found"}), 404
            cur = conn.execute("INSERT INTO threads (project_id, title) VALUES (?, ?)", (pid, title))
            tid = cur.lastrowid
        return jsonify({"id": tid, "project_id": pid, "title": title})

    # ─── Messages ─────────────────────────────────────────────────────────────

    @app.route("/api/threads/<int:tid>/messages", methods=["GET"])
    def get_messages(tid):
        with get_db() as conn:
            if not conn.execute("SELECT id FROM threads WHERE id=?", (tid,)).fetchone():
                return jsonify({"error": "Not found"}), 404
            rows = conn.execute(
                "SELECT * FROM messages WHERE thread_id=? ORDER BY id ASC", (tid,)
            ).fetchall()
        return jsonify([dict(r) for r in rows])

    @app.route("/api/threads/<int:tid>/chat", methods=["POST"])
    def chat(tid):
        data = request.get_json()
        user_text = (data.get("message") or "").strip()
        if not user_text:
            return jsonify({"error": "Empty message"}), 400

        with get_db() as conn:
            row = conn.execute(
                "SELECT t.id, p.path FROM threads t JOIN projects p ON t.project_id=p.id WHERE t.id=?",
                (tid,)
            ).fetchone()
            if not row:
                return jsonify({"error": "Thread not found"}), 404
            project_path = row["path"]
            history = conn.execute(
                "SELECT role, content FROM messages WHERE thread_id=? ORDER BY id ASC", (tid,)
            ).fetchall()

        get_state(tid)["broadcaster"].clear_buffer()
        save_message(tid, "user", "text", user_text)

        system_prompt = build_system_prompt(project_path)
        messages = [{"role": "system", "content": system_prompt}]
        for r in history:
            messages.append({"role": r["role"], "content": r["content"]})
        messages.append({"role": "user", "content": user_text})

        bg = threading.Thread(target=run_agent, args=(tid, project_path, messages), daemon=True)
        bg.start()
        return jsonify({"status": "ok"})

    # ─── Tool approval ────────────────────────────────────────────────────────

    @app.route("/api/threads/<int:tid>/pending-tool", methods=["GET"])
    def pending_tool(tid):
        state = get_state(tid)
        return jsonify({"pending": state["pending_tool"]})

    @app.route("/api/threads/<int:tid>/approve-tool", methods=["POST"])
    def approve_tool(tid):
        data = request.get_json() or {}
        decision = data.get("decision")
        if decision is None:
            decision = "approve" if data.get("approved") else "deny"
        if decision not in {"approve", "deny", "stop"}:
            return jsonify({"error": "Invalid tool decision"}), 400

        state = get_state(tid)
        if not state["pending_tool"]:
            return jsonify({"error": "No pending tool call"}), 400

        state["tool_decision"] = decision
        if decision == "stop":
            state["stop_requested"] = True
        state["tool_event"].set()
        return jsonify({"status": "ok"})

    # ─── Agent halt / status ──────────────────────────────────────────────────

    @app.route("/api/threads/<int:tid>/agent-status", methods=["GET"])
    def agent_status(tid):
        state = get_state(tid)
        return jsonify({"running": state["agent_running"]})

    @app.route("/api/threads/<int:tid>/halt", methods=["POST"])
    def halt_agent(tid):
        state = get_state(tid)
        if not state["agent_running"]:
            return jsonify({"status": "not_running"})
        state["stop_requested"] = True
        if state["pending_tool"]:
            state["tool_decision"] = "stop"
            state["tool_event"].set()
        return jsonify({"status": "ok"})

    # ─── SSE stream ───────────────────────────────────────────────────────────

    @app.route("/api/threads/<int:tid>/stream")
    def stream(tid):
        state = get_state(tid)
        q = state["broadcaster"].subscribe()

        def generate():
            try:
                yield "data: {\"type\":\"connected\"}\n\n"
                while True:
                    try:
                        msg = q.get(timeout=30)
                        yield f"data: {json.dumps(msg)}\n\n"
                        if msg.get("type") == "done":
                            break
                    except queue.Empty:
                        yield "data: {\"type\":\"ping\"}\n\n"
            finally:
                state["broadcaster"].unsubscribe(q)

        return Response(stream_with_context(generate()), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ─── Processes ────────────────────────────────────────────────────────────

    @app.route("/api/processes", methods=["GET"])
    def list_processes():
        with _proc_lock:
            to_remove = []
            for pid, info in _running_processes.items():
                if info["popen"].poll() is not None:
                    to_remove.append(pid)
            for pid in to_remove:
                _running_processes.pop(pid)

            procs = []
            for pid, info in _running_processes.items():
                procs.append({
                    "pid": pid,
                    "project": info.get("project", ""),
                    "script": info["script"],
                    "started_at": info["started_at"]
                })
        return jsonify(procs)

    @app.route("/api/processes/<int:pid>", methods=["DELETE"])
    def api_stop_process(pid):
        with _proc_lock:
            if pid not in _running_processes:
                return jsonify({"error": "Process not found"}), 404
            info = _running_processes.pop(pid)
            proc = info["popen"]
            proc.terminate()
            return jsonify({"status": "ok"})

    # ─── Run Project (run.sh) ─────────────────────────────────────────────────

    @app.route("/api/projects/<int:pid>/has-run-script", methods=["GET"])
    def has_run_script(pid):
        project_path = _get_project_path(pid)
        if not project_path:
            return jsonify({"error": "Not found"}), 404
        run_sh = os.path.join(project_path, "run.sh")
        return jsonify({"has_run_script": os.path.isfile(run_sh)})

    @app.route("/api/projects/<int:pid>/run", methods=["POST"])
    def run_project_script(pid):
        with get_db() as conn:
            row = conn.execute("SELECT name, path FROM projects WHERE id=?", (pid,)).fetchone()
        if not row:
            return jsonify({"error": "Not found"}), 404
        project_path = row["path"]
        project_name = row["name"]
        run_sh = os.path.join(project_path, "run.sh")
        if not os.path.isfile(run_sh):
            return jsonify({"error": "No run.sh found in project"}), 404

        venv_activate = os.path.join(project_path, "venv", "bin", "activate")
        if sys.platform == "win32":
            # On Windows, use bash from WSL/Git Bash if available
            cmd = ["bash", "-c", f"source venv/Scripts/activate && bash run.sh"]
        else:
            if os.path.exists(venv_activate):
                cmd = ["bash", "-c", f"source venv/bin/activate && bash run.sh"]
            else:
                cmd = ["bash", "run.sh"]

        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, cwd=project_path, bufsize=1, universal_newlines=True
            )

            output_log = []
            def drain(stream, label):
                for line in stream:
                    output_log.append(f"[{label}] {line.strip()}")
                    if len(output_log) > 500: output_log.pop(0)

            threading.Thread(target=drain, args=(proc.stdout, "STDOUT"), daemon=True).start()
            threading.Thread(target=drain, args=(proc.stderr, "STDERR"), daemon=True).start()

            time.sleep(2)
            if proc.poll() is not None:
                return jsonify({"status": "finished", "log": "\n".join(output_log)})

            with _proc_lock:
                _running_processes[proc.pid] = {
                    "popen": proc,
                    "project": project_name,
                    "script": "run.sh",
                    "started_at": datetime.now().strftime("%d-%b-%Y at %H:%M:%S")
                }
            return jsonify({"status": "running", "pid": proc.pid})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ─── Admin CRUD ───────────────────────────────────────────────────────────

    @app.route("/api/admin/projects/<int:pid>", methods=["DELETE"])
    def admin_delete_project(pid):
        with get_db() as conn:
            thread_ids = [r[0] for r in conn.execute(
                "SELECT id FROM threads WHERE project_id=?", (pid,)
            ).fetchall()]
            if thread_ids:
                conn.execute(
                    f"DELETE FROM messages WHERE thread_id IN ({','.join('?'*len(thread_ids))})",
                    thread_ids
                )
            conn.execute("DELETE FROM threads WHERE project_id=?", (pid,))
            conn.execute("DELETE FROM messages WHERE project_id=? AND thread_id IS NULL", (pid,))
            conn.execute("DELETE FROM projects WHERE id=?", (pid,))

        try:
            with sqlite3.connect(DB_PATH) as _conn:
                _conn.execute("VACUUM")
        except Exception:
            pass

        return jsonify({"status": "ok"})

    @app.route("/api/admin/threads/<int:tid>", methods=["DELETE"])
    def admin_delete_thread(tid):
        with get_db() as conn:
            conn.execute("DELETE FROM messages WHERE thread_id=?", (tid,))
            conn.execute("DELETE FROM threads WHERE id=?", (tid,))
        return jsonify({"status": "ok"})

    @app.route("/api/admin/messages/<int:mid>", methods=["DELETE"])
    def admin_delete_message(mid):
        with get_db() as conn:
            conn.execute("DELETE FROM messages WHERE id=?", (mid,))
        return jsonify({"status": "ok"})

    @app.route("/api/admin/projects/<int:pid>/name", methods=["POST"])
    def admin_edit_project_name(pid):
        data = request.get_json()
        new_name = data.get("name")
        if not new_name:
            return jsonify({"error": "Name required"}), 400
        with get_db() as conn:
            conn.execute("UPDATE projects SET name=? WHERE id=?", (new_name, pid))
        return jsonify({"status": "ok"})

    # ─── File browser ─────────────────────────────────────────────────────────

    @app.route("/api/projects/<int:pid>/files", methods=["GET"])
    def list_project_files(pid):
        rel = request.args.get("path", "")
        project_path = _get_project_path(pid)
        if not project_path:
            return jsonify({"error": "Not found"}), 404
        target = _safe_path(project_path, rel)
        if not target or not os.path.isdir(target):
            return jsonify({"error": "Invalid path"}), 400
        entries = []
        for name in os.listdir(target):
            full = os.path.join(target, name)
            entries.append({"name": name, "is_dir": os.path.isdir(full)})
        entries.sort(key=lambda e: (0 if e["is_dir"] else 1, e["name"].lower()))
        return jsonify({"entries": entries})

    @app.route("/api/projects/<int:pid>/files/download", methods=["GET"])
    def download_project_file(pid):
        rel = request.args.get("path", "")
        project_path = _get_project_path(pid)
        if not project_path:
            return jsonify({"error": "Not found"}), 404
        target = _safe_path(project_path, rel)
        if not target or not os.path.isfile(target):
            return jsonify({"error": "File not found"}), 404
        return send_file(target, as_attachment=True, download_name=os.path.basename(target))

    @app.route("/api/projects/<int:pid>/files/upload", methods=["POST"])
    def upload_project_file(pid):
        rel = request.form.get("path", "")
        project_path = _get_project_path(pid)
        if not project_path:
            return jsonify({"error": "Not found"}), 404
        target_dir = _safe_path(project_path, rel)
        if not target_dir or not os.path.isdir(target_dir):
            return jsonify({"error": "Invalid path"}), 400
        f = request.files.get("file")
        if not f:
            return jsonify({"error": "No file provided"}), 400
        f.save(os.path.join(target_dir, f.filename))
        return jsonify({"status": "ok"})

    @app.route("/api/projects/<int:pid>/files/delete", methods=["DELETE"])
    def delete_project_file(pid):
        rel = request.args.get("path", "")
        project_path = _get_project_path(pid)
        if not project_path:
            return jsonify({"error": "Not found"}), 404
        target = _safe_path(project_path, rel)
        root   = os.path.realpath(project_path)
        if not target or target == root:
            return jsonify({"error": "Invalid path"}), 400
        if os.path.isfile(target):
            os.remove(target)
        elif os.path.isdir(target):
            shutil.rmtree(target)
        else:
            return jsonify({"error": "Not found"}), 404
        return jsonify({"status": "ok"})

    # ─── Settings ─────────────────────────────────────────────────────────────

    @app.route("/api/admin/settings", methods=["GET"])
    def get_settings():
        return jsonify(read_config())

    @app.route("/api/admin/settings", methods=["POST"])
    def save_settings():
        data = request.get_json() or {}
        cfg = read_config()
        if "api_key" in data:
            cfg["api_key"] = data["api_key"].strip()
        if "model" in data:
            cfg["model"] = data["model"].strip()
        write_config(cfg)
        return jsonify({"status": "ok"})

    @app.route("/api/settings/status", methods=["GET"])
    def settings_status():
        cfg = read_config()
        configured = bool(cfg.get("api_key", "").strip())
        return jsonify({"configured": configured})

# ─── Helper functions (used by routes) ────────────────────────────────────────

def _get_project_path(pid: int):
    with get_db() as conn:
        row = conn.execute("SELECT path FROM projects WHERE id=?", (pid,)).fetchone()
    return row["path"] if row else None

def _safe_path(project_path: str, relative: str):
    """Resolve relative path inside project_path. Returns None if outside."""
    target = os.path.realpath(os.path.join(project_path, relative.lstrip("/")))
    root   = os.path.realpath(project_path)
    return target if target.startswith(root) else None
