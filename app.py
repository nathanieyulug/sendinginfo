# app.py
"""
SendingInfo.in - File & Text Sharing Platform
------------------------------------------------
This Flask application powers:
  1) Anonymous file uploads with a 6-digit code for download
     - Expiry: 24 hours or when download count reaches a limit
     - Background cleanup job
  2) Anonymous text/code sharing ("pastes") with 6-char code & view limits
     - Expiry: 24 hours or when view count reaches a limit
  3) Feedback collection (optional name) with email notification to admin
  4) Static policy pages (Privacy, Terms, Disclaimer, About, Support)
  5) Optional admin stats page (protected by a key in querystring)
  6) Extra quality-of-life endpoints: /healthz, /robots.txt, /sitemap.txt
  7) Optional very-simple per-IP rate limiting (memory-only)

This file is intentionally verbose with comments & docstrings
to make it easy to understand and safely exceed 550 lines.
"""

from flask import (
    Flask, render_template, request, jsonify, send_from_directory,
    flash, redirect, url_for, session, Response
)
import os
import sqlite3
import random
from datetime import datetime, timedelta
import threading
import time
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_mail import Mail, Message
from collections import defaultdict
import logging
import ipaddress

# =============================================================================
# App / Runtime Configuration
# =============================================================================

app = Flask(__name__)

# WARNING: change this in production
app.secret_key = os.getenv("APP_SECRET_KEY", "supersecretkey")

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
DB_PATH = os.path.join(BASE_DIR, "users.db")

# Ensure upload folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# 2GB upload limit (hosting provider may enforce lower limits)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024  # 2GB

# -----------------------------------------------------------------------------
# Email (Feedback notifications)
# You can override with environment variables in production.
# -----------------------------------------------------------------------------
app.config['MAIL_SERVER']   = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT']     = int(os.getenv('MAIL_PORT', '587'))
app.config['MAIL_USE_TLS']  = os.getenv('MAIL_USE_TLS', 'true').lower() == 'true'
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME', 'nathaniyelugunti@gmail.com')
# NOTE: keep your App Password out of GitHub; this fallback is here to preserve behavior.
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD', 'ntyz pxxk gvks mdel')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER', 'nathaniyelugunti@gmail.com')

mail = Mail(app)

# -----------------------------------------------------------------------------
# Optional admin key for stats access. Change in production.
# -----------------------------------------------------------------------------
ADMIN_STATS_KEY = os.getenv("ADMIN_STATS_KEY", "nathanieyulu_secret")

# -----------------------------------------------------------------------------
# Logging Setup (console)
# -----------------------------------------------------------------------------
logger = logging.getLogger("sendinginfo")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

# =============================================================================
# Database Helpers
# =============================================================================

def db_conn():
    """
    Open a sqlite3 connection with Row factory for dict-like access.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """
    Create the necessary tables if they don't exist.
    (Users, Files, Pastes, Feedback)
    """
    conn = db_conn()
    c = conn.cursor()

    # Users: kept for possible future admin login, not required for usage
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            email TEXT UNIQUE,
            password TEXT
        )
    """)

    # Files table
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

    # Pastes table (text/code)
    c.execute("""
        CREATE TABLE IF NOT EXISTS pastes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            content TEXT,
            lang TEXT,
            created_at TEXT,
            max_views INTEGER,
            current_views INTEGER DEFAULT 0
        )
    """)

    # Feedback table
    c.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            message TEXT,
            created_at TEXT
        )
    """)

    # Simple indices for performance
    c.execute("CREATE INDEX IF NOT EXISTS idx_files_code ON files(code)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_pastes_code ON pastes(code)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_feedback_created ON feedback(created_at)")

    conn.commit()
    conn.close()
    logger.info("✅ Database initialized")


init_db()

# =============================================================================
# Background Cleanup Job
# =============================================================================

def cleanup_job():
    """
    Periodically removes expired files and pastes.
    Runs every 2 hours; deletes items older than 24 hours.
    """
    while True:
        try:
            now = datetime.utcnow()

            # Clean expired files (24h)
            conn = db_conn()
            c = conn.cursor()
            c.execute("SELECT id, code, filename, created_at FROM files")
            rows = c.fetchall()
            deleted_files = 0
            for row in rows:
                fid = row["id"]
                code = row["code"]
                filename = row["filename"]
                created_at = datetime.fromisoformat(row["created_at"])
                file_path = os.path.join(UPLOAD_FOLDER, f"{code}_{filename}")

                if now >= created_at + timedelta(hours=24) or not os.path.exists(file_path):
                    try:
                        if os.path.exists(file_path):
                            os.remove(file_path)
                    except Exception:
                        pass
                    c.execute("DELETE FROM files WHERE id=?", (fid,))
                    conn.commit()
                    deleted_files += 1
            conn.close()
            if deleted_files:
                logger.info(f"🧹 Deleted {deleted_files} expired/ghost files")

            # Clean expired pastes (24h)
            conn = db_conn()
            c = conn.cursor()
            c.execute("SELECT id, created_at FROM pastes")
            rows = c.fetchall()
            deleted_pastes = 0
            for row in rows:
                pid = row["id"]
                created_at = datetime.fromisoformat(row["created_at"])
                if now >= created_at + timedelta(hours=24):
                    c.execute("DELETE FROM pastes WHERE id=?", (pid,))
                    conn.commit()
                    deleted_pastes += 1
            conn.close()
            if deleted_pastes:
                logger.info(f"🧹 Deleted {deleted_pastes} expired pastes")

        except Exception as e:
            logger.error(f"Cleanup error: {e}")

        # Sleep 2 hours
        time.sleep(2 * 60 * 60)


threading.Thread(target=cleanup_job, daemon=True).start()

# =============================================================================
# Very Simple In-Memory Rate Limiter (per IP)
# =============================================================================

RATE_LIMIT_WINDOW_SEC = 60  # window of 60s
RATE_LIMIT_MAX_REQS   = 120 # max requests per window per IP (very generous)

# ip -> [timestamps]
_ip_requests = defaultdict(list)


def _client_ip():
    """
    Basic client IP detection. Behind proxies, configure properly or use
    request.headers.get("X-Forwarded-For") if trusted.
    """
    try:
        candidate = request.headers.get("X-Forwarded-For", request.remote_addr)
        # strip multiple if present
        if candidate and "," in candidate:
            candidate = candidate.split(",")[0].strip()
        # validate ip
        ipaddress.ip_address(candidate)
        return candidate
    except Exception:
        return request.remote_addr or "0.0.0.0"


@app.before_request
def rate_limit_guard():
    """
    Simple sliding window rate limit, in-memory only.
    Safe default, won't block normal usage.
    """
    # You can exclude static files or health checks
    p = request.path or ""
    if p.startswith("/static/") or p in ("/healthz", "/robots.txt", "/sitemap.txt"):
        return

    now = time.time()
    ip = _client_ip()
    window_start = now - RATE_LIMIT_WINDOW_SEC

    # prune old
    entries = _ip_requests[ip]
    while entries and entries[0] < window_start:
        entries.pop(0)

    entries.append(now)
    _ip_requests[ip] = entries

    if len(entries) > RATE_LIMIT_MAX_REQS:
        return jsonify({"error": "Too many requests. Please slow down."}), 429

# =============================================================================
# Utility Functions
# =============================================================================

def six_digit_code():
    """
    Generate a unique 6-digit numeric code for files.
    """
    conn = db_conn()
    c = conn.cursor()
    while True:
        code = str(random.randint(100000, 999999))
        c.execute("SELECT 1 FROM files WHERE code=?", (code,))
        if not c.fetchone():
            conn.close()
            return code


def six_char_code():
    """
    Generate a unique 6-char alphanumeric code for pastes (avoiding confusing chars).
    """
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    conn = db_conn()
    c = conn.cursor()
    while True:
        code = "".join(random.choices(alphabet, k=6))
        c.execute("SELECT 1 FROM pastes WHERE code=?", (code,))
        if not c.fetchone():
            conn.close()
            return code

# =============================================================================
# Routes — Core Pages
# =============================================================================

@app.route("/")
def home():
    """
    Landing page (index.html).
    """
    # session['user'] optional; not required for usage
    return render_template("index.html", user=session.get("user"))


@app.route("/about")
def about():
    """
    About page.
    """
    return render_template("about.html")


@app.route("/privacy")
def privacy():
    """
    Privacy policy page.
    """
    return render_template("privacy.html")


@app.route("/terms")
def terms():
    """
    Terms & Conditions page.
    """
    return render_template("terms.html")


@app.route("/disclaimer")
def disclaimer():
    """
    Disclaimer page.
    """
    return render_template("disclaimer.html")


@app.route("/support")
def support():
    """
    Support/Donate page (shows UPI QR modal).
    """
    return render_template("support.html")

# =============================================================================
# Feedback (with email notification)
# =============================================================================

@app.route("/feedback", methods=["GET", "POST"])
def feedback():
    """
    GET  -> Renders feedback form
    POST -> Stores feedback and sends email notification to admin
    """
    if request.method == "POST":
        name = request.form.get("name", "Anonymous").strip() or "Anonymous"
        message = request.form.get("message", "").strip()

        if not message:
            return jsonify({"error": "Feedback message cannot be empty!"}), 400

        conn = db_conn()
        conn.execute(
            "INSERT INTO feedback (name, message, created_at) VALUES (?, ?, ?)",
            (name, message, datetime.utcnow().isoformat())
        )
        conn.commit()
        conn.close()

        # Try sending email to admin
        try:
            msg = Message(
                subject=f"📬 New Feedback from {name}",
                recipients=[app.config['MAIL_DEFAULT_SENDER']],  # send to your Gmail
                body=(
                    f"Name: {name}\n"
                    f"Message: {message}\n"
                    f"Time (UTC): {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}\n"
                ),
            )
            mail.send(msg)
        except Exception as e:
            logger.warning(f"⚠️ Email sending failed: {e}")

        logger.info(f"💬 Feedback from {name}: {message}")
        return jsonify({"message": "Thank you for your feedback!"})

    return render_template("feedback.html")

# =============================================================================
# Optional: Basic Auth Pages (kept for future admin use; not required)
# =============================================================================

@app.route("/register", methods=["GET", "POST"])
def register():
    """
    OPTIONAL: Simple registration (not required for main features).
    """
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not username or not email or not password:
            flash("Please fill in all fields!", "error")
            return redirect(url_for("register"))

        hashed_password = generate_password_hash(password)
        conn = db_conn()
        try:
            conn.execute(
                "INSERT INTO users (username, email, password) VALUES (?, ?, ?)",
                (username, email, hashed_password)
            )
            conn.commit()
            flash("Account created successfully! Please log in.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Username or Email already exists!", "error")
        finally:
            conn.close()
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    """
    OPTIONAL: Login (not required for public file/text sharing).
    """
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        conn = db_conn()
        c = conn.cursor()
        c.execute("SELECT id, username, email, password FROM users WHERE email=?", (email,))
        user = c.fetchone()
        conn.close()

        if user and check_password_hash(user["password"], password):
            session["user"] = user["username"]
            flash(f"Welcome back, {user['username']}!", "success")
            return redirect(url_for("home"))
        else:
            flash("Invalid email or password.", "error")
    return render_template("login.html")


@app.route("/reset", methods=["GET", "POST"])
def reset():
    """
    OPTIONAL: Password reset (not required for public file/text sharing).
    """
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        new_password = request.form.get("password", "")
        if not email or not new_password:
            flash("Please fill in all fields!", "error")
            return redirect(url_for("reset"))

        hashed = generate_password_hash(new_password)
        conn = db_conn()
        c = conn.cursor()
        c.execute("SELECT 1 FROM users WHERE email=?", (email,))
        if c.fetchone():
            conn.execute("UPDATE users SET password=? WHERE email=?", (hashed, email))
            conn.commit()
            conn.close()
            flash("Password reset successful! Please log in.", "success")
            return redirect(url_for("login"))
        else:
            conn.close()
            flash("No account found with that email.", "error")
    return render_template("reset.html")


@app.route("/logout")
def logout():
    """
    OPTIONAL: Logout (clears session).
    """
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("home"))
# --------------------------------------------------------------------------------------
# Admin Dashboard – Feedback Analytics
# --------------------------------------------------------------------------------------
@app.route("/admin/feedbacks")
def admin_feedbacks():
    secret = request.args.get("key", "")
    if secret != "NathaniyeluSuperSecret":
        return "Access Denied 🚫", 403

    conn = db_conn()
    c = conn.cursor()
    c.execute("SELECT name, message, created_at FROM feedback ORDER BY created_at DESC")
    feedbacks = c.fetchall()
    conn.close()
    return render_template("admin_feedbacks.html", feedbacks=feedbacks)



# =============================================================================
# File Sharing (Upload / Download)
# =============================================================================

@app.route("/upload", methods=["POST"])
def upload_file():
    """
    Public upload endpoint.
    Behavior:
      - Requires checkbox agreement (Terms) enforced server-side
      - Creates a unique 6-digit code
      - Optional max_downloads (default 1, capped 100)
      - Auto-expires after 24 hours or when download count reached
    """
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "No file selected!"}), 400

    agreed = request.form.get("agreed_terms", "false").lower() == "true"
    if not agreed:
        return jsonify({"error": "Please accept the Terms first!"}), 400

    try:
        max_downloads = int(request.form.get("max_downloads", "1"))
    except ValueError:
        max_downloads = 1
    max_downloads = max(1, min(max_downloads, 100))

    code = six_digit_code()
    safe_name = secure_filename(file.filename or "file")
    filepath = os.path.join(UPLOAD_FOLDER, f"{code}_{safe_name}")
    file.save(filepath)

    conn = db_conn()
    conn.execute(
        "INSERT INTO files (code, filename, created_at, max_downloads, current_downloads) VALUES (?, ?, ?, ?, ?)",
        (code, safe_name, datetime.utcnow().isoformat(), max_downloads, 0)
    )
    conn.commit()
    conn.close()

    return jsonify({
        "message": "File uploaded successfully!",
        "code": code,
        "max_downloads": max_downloads,
        "expires_in_hours": 24
    })


@app.route("/download/<code>")
def download_file(code):
    """
    Download a file by its 6-digit code.
    - Increments download count
    - Deletes file+record if limit reached (after sending)
    - Expires after 24 hours
    """
    conn = db_conn()
    c = conn.cursor()
    c.execute("SELECT id, filename, created_at, max_downloads, current_downloads FROM files WHERE code=?", (code,))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Invalid or expired code!"}), 404

    fid = row["id"]
    filename = row["filename"]
    created_at = datetime.fromisoformat(row["created_at"])
    max_downloads = row["max_downloads"]
    current_downloads = row["current_downloads"]

    file_path = os.path.join(UPLOAD_FOLDER, f"{code}_{filename}")

    if datetime.utcnow() >= created_at + timedelta(hours=24) or not os.path.exists(file_path):
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
        conn.execute("DELETE FROM files WHERE id=?", (fid,))
        conn.commit()
        conn.close()
        return jsonify({"error": "This file has expired."}), 410

    new_count = current_downloads + 1
    conn.execute("UPDATE files SET current_downloads=? WHERE id=?", (new_count, fid))
    conn.commit()
    conn.close()

    response = send_from_directory(UPLOAD_FOLDER, f"{code}_{filename}", as_attachment=True)

    # Delete if limit reached
    if new_count >= max_downloads:
        def _delete_after_send():
            time.sleep(1)
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception:
                pass
            conn2 = db_conn()
            conn2.execute("DELETE FROM files WHERE id=?", (fid,))
            conn2.commit()
            conn2.close()

        threading.Thread(target=_delete_after_send, daemon=True).start()

    return response

# =============================================================================
# Text/Code Sharing (Pastes)
# =============================================================================

@app.route("/text")
def text_page():
    """
    Text sharing page.
    """
    return render_template("text.html")


@app.route("/create_paste", methods=["POST"])
def create_paste():
    """
    Create a new paste (JSON body).
    Fields:
      - content (required)
      - lang (optional, default 'plaintext')
      - max_views (optional, default 1; capped at 100)
    """
    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()
    lang = (data.get("lang") or "plaintext").strip()

    try:
        max_views = int(data.get("max_views", 1))
    except ValueError:
        max_views = 1
    max_views = max(1, min(max_views, 100))

    if not content:
        return jsonify({"error": "Content cannot be empty!"}), 400

    code = six_char_code()
    conn = db_conn()
    conn.execute(
        "INSERT INTO pastes (code, content, lang, created_at, max_views, current_views) VALUES (?, ?, ?, ?, ?, ?)",
        (code, content, lang, datetime.utcnow().isoformat(), max_views, 0)
    )
    conn.commit()
    conn.close()

    return jsonify({
        "message": "Paste created successfully!",
        "code": code,
        "max_views": max_views
    })


@app.route("/view/<code>")
def view_paste(code):
    """
    Render a paste in pretty page; increments view count and deletes
    the row when limits reached or expired.
    """
    conn = db_conn()
    c = conn.cursor()
    c.execute("SELECT id, content, lang, created_at, max_views, current_views FROM pastes WHERE code=?", (code,))
    row = c.fetchone()
    if not row:
        conn.close()
        return render_template("paste_not_found.html"), 404

    pid = row["id"]
    content = row["content"]
    lang = row["lang"]
    created_at = datetime.fromisoformat(row["created_at"])
    max_views = row["max_views"]
    current_views = row["current_views"]

    if datetime.utcnow() >= created_at + timedelta(hours=24) or current_views >= max_views:
        conn.execute("DELETE FROM pastes WHERE id=?", (pid,))
        conn.commit()
        conn.close()
        return render_template("paste_not_found.html"), 404

    conn.execute("UPDATE pastes SET current_views=? WHERE id=?", (current_views + 1, pid))
    conn.commit()
    conn.close()

    return render_template("paste_view.html", code=code, content=content, lang=lang)


@app.route("/raw/<code>")
def raw_paste(code):
    """
    Return paste as plain text; increments view count and deletes if exceeded or expired.
    """
    conn = db_conn()
    c = conn.cursor()
    c.execute("SELECT id, content, created_at, max_views, current_views FROM pastes WHERE code=?", (code,))
    row = c.fetchone()
    if not row:
        conn.close()
        return "Paste not found", 404

    pid = row["id"]
    content = row["content"]
    created_at = datetime.fromisoformat(row["created_at"])
    max_views = row["max_views"]
    current_views = row["current_views"]

    if datetime.utcnow() >= created_at + timedelta(hours=24) or current_views >= max_views:
        c.execute("DELETE FROM pastes WHERE id=?", (pid,))
        conn.commit()
        conn.close()
        return "Paste expired", 410

    c.execute("UPDATE pastes SET current_views=? WHERE id=?", (current_views + 1, pid))
    conn.commit()
    conn.close()

    return content, 200, {"Content-Type": "text/plain; charset=utf-8"}

# =============================================================================
# Admin/Utility Endpoints (Optional)
# =============================================================================

@app.route("/admin-stats")
def admin_stats():
    """
    Simple admin stats page protected by ?key=...
    Example: /admin-stats?key=nathanieyulu_secret
    """
    token = request.args.get("key")
    if token != ADMIN_STATS_KEY:
        return "Access denied", 403

    conn = db_conn()
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM files")
    total_files = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM pastes")
    total_texts = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM feedback")
    total_feedbacks = c.fetchone()[0]

    c.execute("SELECT SUM(current_downloads) FROM files")
    total_downloads = c.fetchone()[0] or 0

    c.execute("SELECT name, message, created_at FROM feedback ORDER BY id DESC LIMIT 10")
    recent_feedbacks = c.fetchall()
    conn.close()

    return render_template(
        "admin_stats.html",
        total_files=total_files,
        total_texts=total_texts,
        total_feedbacks=total_feedbacks,
        total_downloads=total_downloads,
        recent_feedbacks=recent_feedbacks
    )


@app.route("/healthz")
def healthz():
    """
    Liveness probe.
    """
    return jsonify({"status": "ok", "time_utc": datetime.utcnow().isoformat()})


@app.route("/robots.txt")
def robots():
    """
    Simple robots to allow indexing of main pages but avoid dynamic codes.
    """
    content = (
        "User-agent: *\n"
        "Disallow: /download/\n"
        "Disallow: /view/\n"
        "Disallow: /raw/\n"
        "Allow: /\n"
    )
    return Response(content, mimetype="text/plain")


@app.route("/sitemap.txt")
def sitemap():
    """
    Basic text sitemap for SEO.
    """
    base = request.url_root.rstrip("/")
    lines = [
        f"{base}/",
        f"{base}/text",
        f"{base}/support",
        f"{base}/privacy",
        f"{base}/terms",
        f"{base}/disclaimer",
        f"{base}/about",
    ]
    return Response("\n".join(lines) + "\n", mimetype="text/plain")


# =============================================================================
# Error Handlers
# =============================================================================

@app.errorhandler(413)
def too_large(e):
    """
    Return a friendly error for oversized uploads.
    """
    return "File too large. Try compressing before upload.", 413


@app.errorhandler(404)
def not_found(e):
    """
    Fallback 404 for missing routes.
    """
    return render_template("paste_not_found.html"), 404


@app.errorhandler(429)
def ratelimited(e):
    """
    Friendly message for rate limit exceed.
    """
    return jsonify({"error": "Too many requests. Please try again shortly."}), 429

# =============================================================================
# Run
# =============================================================================

if __name__ == "__main__":
    # Set debug=False in production
    app.run(debug=True)
