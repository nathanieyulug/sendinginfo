from flask import Flask, render_template, request, jsonify, send_from_directory, flash, redirect, url_for, session
import os
import sqlite3
import uuid
import random
from datetime import datetime, timedelta
import threading
import time

from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "supersecretkey"

# ---- Paths / Config ----
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
DB_PATH = os.path.join(BASE_DIR, "users.db")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Allow up to 2GB (works on VPS; free hosts may limit actual request size)
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024 * 1024  # 2GB

# ---- DB helpers ----
def db_conn():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = db_conn()
    c = conn.cursor()
    # users table (unchanged)
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            email TEXT UNIQUE,
            password TEXT
        )
    """)
    # files table (NEW)
    c.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            filename TEXT,
            created_at TEXT,
            max_downloads INTEGER,
            current_downloads INTEGER
        )
    """)
    conn.commit()
    conn.close()
    print("✅ Database initialized")

init_db()

# ---- Auto-clean job: delete files after 24 hours OR if file missing ----
def cleanup_job():
    while True:
        try:
            conn = db_conn()
            c = conn.cursor()
            c.execute("SELECT id, code, filename, created_at, max_downloads, current_downloads FROM files")
            rows = c.fetchall()
            now = datetime.utcnow()
            for row in rows:
                fid, code, filename, created_at, max_d, cur_d = row
                file_path = os.path.join(UPLOAD_FOLDER, f"{code}_{filename}")
                expired_time = datetime.fromisoformat(created_at) + timedelta(hours=24)
                delete_needed = False
                # delete if 24h old
                if now >= expired_time:
                    delete_needed = True
                # or file missing on disk
                if not os.path.exists(file_path):
                    delete_needed = True
                if delete_needed:
                    try:
                        if os.path.exists(file_path):
                            os.remove(file_path)
                    except Exception:
                        pass
                    c.execute("DELETE FROM files WHERE id=?", (fid,))
                    conn.commit()
        except Exception as e:
            print("Cleanup error:", e)
        finally:
            try:
                conn.close()
            except Exception:
                pass
        # run every 2 hours
        time.sleep(2 * 60 * 60)

# start background cleaner
t = threading.Thread(target=cleanup_job, daemon=True)
t.start()

# ---- Routes ----
@app.route("/")
def home():
    user = session.get("user")
    return render_template("index.html", user=user)

# ---------- REGISTER ----------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        email = request.form["email"]
        password = request.form["password"]

        if not username or not email or not password:
            flash("Please fill in all fields!", "error")
            return redirect(url_for("register"))

        hashed_password = generate_password_hash(password)
        conn = db_conn()
        c = conn.cursor()
        try:
            c.execute("INSERT INTO users (username, email, password) VALUES (?, ?, ?)",
                      (username, email, hashed_password))
            conn.commit()
            flash("Account created successfully! Please log in.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Username or Email already exists!", "error")
        finally:
            conn.close()
    return render_template("register.html")

# ---------- LOGIN ----------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        conn = db_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE email=?", (email,))
        user = c.fetchone()
        conn.close()

        if user and check_password_hash(user[3], password):
            session["user"] = user[1]
            flash(f"Welcome back, {user[1]}!", "success")
            return redirect(url_for("home"))
        else:
            flash("Invalid email or password.", "error")
    return render_template("login.html")

# ---------- RESET ----------
@app.route("/reset", methods=["GET", "POST"])
def reset():
    if request.method == "POST":
        email = request.form["email"]
        new_password = request.form["password"]

        if not email or not new_password:
            flash("Please fill in all fields!", "error")
            return redirect(url_for("reset"))

        hashed_password = generate_password_hash(new_password)
        conn = db_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE email=?", (email,))
        user = c.fetchone()

        if user:
            c.execute("UPDATE users SET password=? WHERE email=?", (hashed_password, email))
            conn.commit()
            flash("Password reset successful! Please log in.", "success")
            conn.close()
            return redirect(url_for("login"))
        else:
            flash("No account found with that email.", "error")
            conn.close()
    return render_template("reset.html")

# ---------- LOGOUT ----------
@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("home"))

# ---------- UPLOAD (PUBLIC) ----------
@app.route("/upload", methods=["POST"])
def upload_file():
    """
    Public upload.
    - Generates 6-digit code: e.g., 428519
    - max_downloads defaults to 1 (single share)
    - If client sends max_downloads >1, we store that value
    - File auto-deletes when downloads reach max OR after 24h (cleanup thread)
    """
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "No file selected!"}), 400

    # terms agreement must be accepted client-side; we enforce server-side too:
    agreed = request.form.get("agreed_terms", "false").lower() == "true"
    if not agreed:
        return jsonify({"error": "Please accept Terms, Privacy & Disclaimer before uploading."}), 400

    # read max_downloads, default = 1
    try:
        max_downloads = int(request.form.get("max_downloads", "1"))
        if max_downloads < 1:
            max_downloads = 1
        if max_downloads > 100:
            max_downloads = 100  # hard safety upper bound
    except ValueError:
        max_downloads = 1

    # 6-digit numeric code
    code = str(random.randint(100000, 999999))

    # store file as "<code>_<originalname>"
    safe_name = file.filename
    filepath = os.path.join(UPLOAD_FOLDER, f"{code}_{safe_name}")
    file.save(filepath)

    # insert DB record
    conn = db_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO files (code, filename, created_at, max_downloads, current_downloads)
        VALUES (?, ?, ?, ?, ?)
    """, (code, safe_name, datetime.utcnow().isoformat(), max_downloads, 0))
    conn.commit()
    conn.close()

    return jsonify({
        "message": "File uploaded successfully!",
        "code": code,
        "max_downloads": max_downloads,
        "expires_in_hours": 24
    })

# ---------- DOWNLOAD (PUBLIC) ----------
@app.route("/download/<code>")
def download_file(code):
    """
    - Find file by 6-digit code
    - Increment current_downloads
    - If reached max_downloads -> delete file & DB row after sending
    """
    conn = db_conn()
    c = conn.cursor()
    c.execute("SELECT id, filename, created_at, max_downloads, current_downloads FROM files WHERE code=?", (code,))
    row = c.fetchone()

    if not row:
        conn.close()
        return jsonify({"error": "Invalid or expired code!"}), 404

    fid, filename, created_at, max_downloads, current_downloads = row
    file_path = os.path.join(UPLOAD_FOLDER, f"{code}_{filename}")

    # 24h expiry check
    if datetime.utcnow() >= datetime.fromisoformat(created_at) + timedelta(hours=24):
        # delete if still exists
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass
        c.execute("DELETE FROM files WHERE id=?", (fid,))
        conn.commit()
        conn.close()
        return jsonify({"error": "This file has expired."}), 410

    # file missing on disk?
    if not os.path.exists(file_path):
        c.execute("DELETE FROM files WHERE id=?", (fid,))
        conn.commit()
        conn.close()
        return jsonify({"error": "File not found. It may have been removed."}), 410

    # increment downloads
    new_count = current_downloads + 1
    c.execute("UPDATE files SET current_downloads=? WHERE id=?", (new_count, fid))
    conn.commit()
    conn.close()

    # Serve file
    response = send_from_directory(UPLOAD_FOLDER, f"{code}_{filename}", as_attachment=True)

    # If limit reached, remove file & DB after response (in background)
    if new_count >= max_downloads:
        def _delete_after_send():
            time.sleep(1)  # tiny delay
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception:
                pass
            conn2 = db_conn()
            c2 = conn2.cursor()
            c2.execute("DELETE FROM files WHERE id=?", (fid,))
            conn2.commit()
            conn2.close()
        threading.Thread(target=_delete_after_send, daemon=True).start()

    return response

# ---------- LEGAL PAGES ----------
@app.route("/privacy")
def privacy():
    return render_template("privacy.html")

@app.route("/terms")
def terms():
    return render_template("terms.html")

@app.route("/disclaimer")
def disclaimer():
    return render_template("disclaimer.html")

@app.route("/about")
def about():
    return render_template("about.html")

# ---------- MAIN ----------
if __name__ == "__main__":
    app.run(debug=False)
