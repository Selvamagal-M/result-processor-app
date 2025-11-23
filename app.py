# app.py
# Result Processor with role-based auth (admin/faculty/student),
# DB users, CSV bulk upload, hardcoded defaults, CGPA calc, modern UI.
import streamlit as st
import sqlite3
import pandas as pd
from io import BytesIO, StringIO
from datetime import datetime
import os
import hashlib
import traceback

# -------------------------
# Config & safety
# -------------------------
st.set_page_config(page_title="Result Processor (RBAC)", layout="wide", initial_sidebar_state="expanded")

DATA_DIR = "data"
DB_PATH = os.path.join(DATA_DIR, "results.db")
os.makedirs(DATA_DIR, exist_ok=True)

def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

# -------------------------
# Utilities
# -------------------------
def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()

def user_exists(username):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM users WHERE username=?", (username,))
    res = cur.fetchone()
    conn.close()
    return bool(res)

def create_default_users_if_missing():
    # Creates users table and adds default admin+faculty if no users exist
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password_hash TEXT,
        role TEXT,
        linked_roll TEXT
    )
    """)
    conn.commit()
    # check if empty
    cur.execute("SELECT count(*) FROM users")
    count = cur.fetchone()[0]
    if count == 0:
        # default credentials (changeable)
        defaults = [
            ("admin", "1234", "admin", None),
            ("faculty", "faculty123", "faculty", None)
        ]
        for u, p, r, roll in defaults:
            try:
                cur.execute("INSERT INTO users (username, password_hash, role, linked_roll) VALUES (?, ?, ?, ?)",
                            (u, hash_password(p), r, roll))
            except sqlite3.IntegrityError:
                pass
        conn.commit()
    conn.close()

# -------------------------
# Initialize application DB (tables for students, subjects, marks)
# -------------------------
def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS students (
        student_id INTEGER PRIMARY KEY AUTOINCREMENT,
        roll TEXT UNIQUE,
        name TEXT,
        program TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS subjects (
        subject_id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE,
        title TEXT,
        credits REAL
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS marks (
        mark_id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER,
        subject_id INTEGER,
        marks REAL,
        max_marks REAL,
        FOREIGN KEY(student_id) REFERENCES students(student_id),
        FOREIGN KEY(subject_id) REFERENCES subjects(subject_id)
    )
    """)
    conn.commit()
    conn.close()

# Create DB structure and default users
init_db()
create_default_users_if_missing()

# -------------------------
# Business logic (grading)
# -------------------------
def grade_from_percent(p):
    if p >= 90: return ("A+", 10.0)
    if p >= 80: return ("A", 9.0)
    if p >= 70: return ("B+", 8.0)
    if p >= 60: return ("B", 7.0)
    if p >= 50: return ("C", 6.0)
    if p >= 40: return ("D", 5.0)
    return ("F", 0.0)

def compute_student_report(student_id):
    conn = get_conn()
    q = """
    SELECT s.student_id, s.roll, s.name, sub.code, sub.title, sub.credits,
           m.marks, m.max_marks
    FROM students s
    JOIN marks m ON s.student_id = m.student_id
    JOIN subjects sub ON m.subject_id = sub.subject_id
    WHERE s.student_id = ?
    """
    df = pd.read_sql_query(q, conn, params=(student_id,))
    conn.close()
    if df.empty:
        return None

    df['percent'] = (df['marks'] / df['max_marks']) * 100
    df[['grade', 'grade_point']] = df['percent'].apply(lambda p: pd.Series(grade_from_percent(p)))
    df['credit_gp'] = df['credits'] * df['grade_point']

    total_credits = df['credits'].sum()
    total_credit_gp = df['credit_gp'].sum()
    cgpa = (total_credit_gp / total_credits) if total_credits > 0 else 0.0

    summary = {
        "roll": df.iloc[0]['roll'],
        "name": df.iloc[0]['name'],
        "total_credits": float(total_credits),
        "total_credit_gp": float(total_credit_gp),
        "cgpa": round(cgpa, 2),
        "generated_at": datetime.utcnow().isoformat() + "Z"
    }
    return df, summary

# -------------------------
# Data operations
# -------------------------
def add_student(roll, name, program=""):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO students (roll, name, program) VALUES (?, ?, ?)", (roll, name, program))
        conn.commit()
        return True, "Student added"
    except sqlite3.IntegrityError:
        return False, "Student with this roll already exists."
    finally:
        conn.close()

def add_subject(code, title, credits):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO subjects (code, title, credits) VALUES (?, ?, ?)", (code, title, float(credits)))
        conn.commit()
        return True, "Subject added"
    except sqlite3.IntegrityError:
        return False, "Subject with this code already exists."
    finally:
        conn.close()

def add_marks(roll, subject_code, marks, max_marks=100):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT student_id FROM students WHERE roll = ?", (roll,))
        s = cur.fetchone()
        if not s:
            return False, "Student roll not found."
        student_id = s[0]
        cur.execute("SELECT subject_id FROM subjects WHERE code = ?", (subject_code,))
        sub = cur.fetchone()
        if not sub:
            return False, "Subject code not found."
        subject_id = sub[0]
        cur.execute("SELECT mark_id FROM marks WHERE student_id = ? AND subject_id = ?", (student_id, subject_id))
        existing = cur.fetchone()
        if existing:
            cur.execute("UPDATE marks SET marks=?, max_marks=? WHERE mark_id=?", (float(marks), float(max_marks), existing[0]))
        else:
            cur.execute("INSERT INTO marks (student_id, subject_id, marks, max_marks) VALUES (?, ?, ?, ?)",
                        (student_id, subject_id, float(marks), float(max_marks)))
        conn.commit()
        return True, "Marks saved"
    finally:
        conn.close()

def get_all_students_df():
    conn = get_conn()
    df = pd.read_sql_query("SELECT student_id, roll, name, program FROM students ORDER BY roll", conn)
    conn.close()
    return df

def get_all_subjects_df():
    conn = get_conn()
    df = pd.read_sql_query("SELECT subject_id, code, title, credits FROM subjects ORDER BY code", conn)
    conn.close()
    return df

def export_df_to_excel_bytes(dfs: dict):
    with BytesIO() as b:
        with pd.ExcelWriter(b, engine="openpyxl") as writer:
            for sheet_name, df in dfs.items():
                df.to_excel(writer, sheet_name=sheet_name[:31], index=False)
        return b.getvalue()

# -------------------------
# User management (DB)
# -------------------------
def create_user_db(username, password, role, linked_roll=None):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO users (username, password_hash, role, linked_roll) VALUES (?, ?, ?, ?)",
                    (username, hash_password(password), role, linked_roll))
        conn.commit()
        return True, "User created"
    except sqlite3.IntegrityError:
        return False, "Username exists"
    finally:
        conn.close()

def validate_user(username, password):
    # first try DB
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT password_hash, role, linked_roll FROM users WHERE username=?", (username,))
    row = cur.fetchone()
    conn.close()
    if row:
        stored_hash, role, linked_roll = row
        if stored_hash == hash_password(password):
            return True, role, linked_roll
        else:
            return False, None, None
    # fallback: check hardcoded defaults (shouldn't be necessary because defaults are in DB)
    hardcoded = {"admin": ("1234", "admin"), "faculty": ("faculty123", "faculty")}
    if username in hardcoded and hardcoded[username][0] == password:
        return True, hardcoded[username][1], None
    return False, None, None

def list_users_df():
    conn = get_conn()
    df = pd.read_sql_query("SELECT user_id, username, role, linked_roll FROM users ORDER BY username", conn)
    conn.close()
    return df

def bulk_create_users_from_csv(contents):
    # contents: bytes or string
    if isinstance(contents, (bytes, bytearray)):
        s = contents.decode("utf-8")
    else:
        s = contents
    df = pd.read_csv(StringIO(s))
    added = 0
    skipped = 0
    messages = []
    for idx, row in df.iterrows():
        try:
            username = str(row.get("username") or row.get("user") or "").strip()
            password = str(row.get("password") or "").strip()
            role = str(row.get("role") or "").strip()
            linked_roll = str(row.get("roll") or row.get("linked_roll") or "").strip() or None
            if not username or not password or not role:
                skipped += 1
                messages.append(f"Row {idx+1}: missing fields")
                continue
            ok, msg = create_user_db(username, password, role, linked_roll)
            if ok:
                added += 1
            else:
                skipped += 1
                messages.append(f"Row {idx+1}: {msg}")
        except Exception as e:
            skipped += 1
            messages.append(f"Row {idx+1}: error {e}")
    return added, skipped, messages

# -------------------------
# Auth UI & session
# -------------------------
if "auth" not in st.session_state:
    st.session_state.auth = {"logged_in": False, "username": None, "role": None, "linked_roll": None}

def do_logout():
    st.session_state.auth = {"logged_in": False, "username": None, "role": None, "linked_roll": None}
    st.rerun()

def login_form_ui():
    st.markdown("<div style='max-width:700px;margin:auto;'>", unsafe_allow_html=True)
    st.markdown("<h2 style='text-align:center;'>Sign in</h2>", unsafe_allow_html=True)
    with st.form("login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")
        if submitted:
            ok, role, linked_roll = validate_user(username.strip(), password)
            if ok:
                st.session_state.auth = {"logged_in": True, "username": username.strip(), "role": role, "linked_roll": linked_roll}
                st.success("Logged in")
                st.rerun()
            else:
                st.error("Invalid username or password.")
    st.markdown("</div>", unsafe_allow_html=True)

# -------------------------
# Styling: soft animations
# -------------------------
st.markdown("""
<style>
:root{ --bg: linear-gradient(180deg,#f7fbff 0%, #eef6ff 100%); }
body { background: linear-gradient(180deg,#f7fbff 0%, #eef6ff 100%); color: #0b2545; }
.block-container{ max-width:1400px; padding:1rem 2rem; }
.card { background: #ffffff; border-radius:12px; padding:18px; border:1px solid rgba(11,37,69,0.06); box-shadow: 0 6px 24px rgba(11,37,69,0.04); transition: transform 0.18s ease, box-shadow 0.18s ease; }
.card:hover { transform: translateY(-6px); box-shadow: 0 12px 40px rgba(11,37,69,0.08); }
.small-muted{ color:#3a5a82; font-size:13px; }
.logo-box{ width:56px; height:56px; border-radius:12px; display:flex; align-items:center; justify-content:center; background:linear-gradient(135deg,#4b7bec,#7b61ff); color:white; font-weight:700; box-shadow:0 8px 24px rgba(75,123,236,0.12); }
.fade-in { animation: fadeIn 0.36s ease both; }
@keyframes fadeIn { from { opacity:0; transform: translateY(6px);} to { opacity:1; transform: translateY(0);} }
</style>
""", unsafe_allow_html=True)

# -------------------------
# Main UI
# -------------------------
try:
    if not st.session_state.auth["logged_in"]:
        # show login methods and info
        st.sidebar.title("Result Processor")
        st.sidebar.markdown("**Login methods available:** DB users, default admin/faculty, CSV bulk-upload (admin).")
        login_form_ui()
        st.stop()

    # now logged in
    username = st.session_state.auth["username"]
    role = st.session_state.auth["role"]
    linked_roll = st.session_state.auth.get("linked_roll")

    # top header
    col1, col2 = st.columns([4,1])
    with col1:
        st.markdown(f"<div style='display:flex;gap:12px;align-items:center'><div class='logo-box'>RP</div><div><h2 style='margin:0;padding:0'>Result Processor</h2><div class='small-muted'>Role: <strong>{role}</strong> — Signed in as <strong>{username}</strong></div></div></div>", unsafe_allow_html=True)
    with col2:
        if st.button("Logout"):
            do_logout()

    st.sidebar.markdown("---")
    st.sidebar.write(f"Signed in: **{username}** ({role})")
    # role-based nav
    if role == "admin":
        pages = ["Dashboard", "Users", "Add Data", "Enter Marks", "Student Report", "Export", "Admin"]
    elif role == "faculty":
        pages = ["Dashboard", "Add Data", "Enter Marks", "Student Report", "Export"]
    else:  # student
        pages = ["My Report", "Export"]

    page = st.sidebar.selectbox("Navigation", pages)

    # ---- Pages implementation ----
    if page == "Dashboard":
        st.markdown("<div class='card fade-in'>", unsafe_allow_html=True)
        st.header("Class Summary")
        students = get_all_students_df()
        subjects = get_all_subjects_df()
        st.write(f"Total students: {len(students)} — Total subjects: {len(subjects)}")
        st.dataframe(students)
        st.dataframe(subjects)
        # quick CGPA leaderboard
        if st.button("Compute CGPA for all students"):
            out = []
            for sid in students['student_id'].tolist():
                result = compute_student_report(sid)
                if result:
                    df, summ = result
                    out.append({"roll": summ['roll'], "name": summ['name'], "cgpa": summ['cgpa'], "total_credits": summ['total_credits']})
            if out:
                st.subheader("CGPA Leaderboard")
                st.dataframe(pd.DataFrame(out).sort_values(["cgpa"], ascending=False))
            else:
                st.info("No marks present yet.")
        st.markdown("</div>", unsafe_allow_html=True)

    elif page == "Users":
        # Admin-only
        if role != "admin":
            st.error("Access denied.")
        else:
            st.markdown("<div class='card fade-in'>", unsafe_allow_html=True)
            st.header("User Management (Admin)")
            # create user
            with st.form("create_user"):
                st.subheader("Create user")
                u = st.text_input("Username")
                pw = st.text_input("Password", type="password")
                r = st.selectbox("Role", ["admin", "faculty", "student"])
                linked_roll_field = st.text_input("Linked student roll (optional for student accounts)")
                if st.form_submit_button("Create"):
                    ok, msg = create_user_db(u.strip(), pw, r, linked_roll_field.strip() or None)
                    if ok:
                        st.success(msg)
                    else:
                        st.warning(msg)
            st.markdown("---")

            # bulk upload CSV
            st.subheader("Bulk upload users (CSV)")
            st.markdown("CSV columns: username,password,role,roll (roll optional).")
            uploaded = st.file_uploader("Upload CSV", type=["csv"])
            if uploaded:
                contents = uploaded.getvalue()
                added, skipped, messages = bulk_create_users_from_csv(contents)
                st.success(f"Added: {added}, Skipped: {skipped}")
                for m in messages[:10]:
                    st.write("-", m)
            st.markdown("---")
            # list users
            st.subheader("Existing users")
            st.dataframe(list_users_df())
            st.markdown("</div>", unsafe_allow_html=True)

    elif page == "Add Data":
        st.markdown("<div class='card fade-in'>", unsafe_allow_html=True)
        st.header("Add Students & Subjects")
        with st.form("student_form"):
            st.subheader("Add student")
            roll = st.text_input("Roll (unique)")
            name = st.text_input("Name")
            program = st.text_input("Program / Course (optional)")
            if st.form_submit_button("Add student"):
                ok, msg = add_student(roll.strip(), name.strip(), program.strip())
                if ok:
                    st.success(msg)
                else:
                    st.warning(msg)
        st.markdown("---")
        with st.form("subject_form"):
            st.subheader("Add subject")
            code = st.text_input("Subject code (unique)", key="sc")
            title = st.text_input("Title", key="st")
            credits = st.number_input("Credits", min_value=0.0, value=3.0, step=0.5, key="scr")
            if st.form_submit_button("Add subject"):
                ok, msg = add_subject(code.strip(), title.strip(), credits)
                if ok:
                    st.success(msg)
                else:
                    st.warning(msg)
        st.markdown("</div>", unsafe_allow_html=True)

    elif page == "Enter Marks":
        st.markdown("<div class='card fade-in'>", unsafe_allow_html=True)
        st.header("Enter / Update Marks")
        students = get_all_students_df()
        subs = get_all_subjects_df()
        if students.empty or subs.empty:
            st.info("Add at least one student and subject first.")
        else:
            with st.form("marks_form"):
                roll = st.selectbox("Student (by roll)", students['roll'].tolist())
                subject_code = st.selectbox("Subject code", subs['code'].tolist())
                marks = st.number_input("Marks obtained", min_value=0.0)
                max_marks = st.number_input("Max marks (for percent)", min_value=1.0, value=100.0)
                if st.form_submit_button("Save marks"):
                    ok, msg = add_marks(roll, subject_code, marks, max_marks)
                    if ok:
                        st.success(msg)
                    else:
                        st.error(msg)
        st.markdown("</div>", unsafe_allow_html=True)

    elif page == "Student Report":
        st.markdown("<div class='card fade-in'>", unsafe_allow_html=True)
        st.header("Generate Student Report")
        students = get_all_students_df()
        if students.empty:
            st.info("No students yet.")
        else:
            roll_selected = st.selectbox("Choose student", students['roll'].tolist())
            sid = int(students[students['roll'] == roll_selected]['student_id'].iloc[0])
            res = compute_student_report(sid)
            if not res:
                st.warning("No marks recorded for this student yet.")
            else:
                df, summary = res
                st.subheader(f"{summary['name']} — {summary['roll']}")
                st.metric("CGPA", summary['cgpa'])
                display_df = df[['code','title','credits','marks','max_marks','percent','grade','grade_point']]
                st.dataframe(display_df.style.format({"percent":"{:.2f}","grade_point":"{:.2f}"}), height=300)
                csv_bytes = display_df.to_csv(index=False).encode('utf-8')
                st.download_button("Download CSV", csv_bytes, file_name=f"report_{summary['roll']}.csv", mime="text/csv")
                bytes_xl = export_df_to_excel_bytes({"report": display_df})
                st.download_button("Download Excel", bytes_xl, file_name=f"report_{summary['roll']}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        st.markdown("</div>", unsafe_allow_html=True)

    elif page == "My Report":
        # Student view (linked_roll must be set)
        st.markdown("<div class='card fade-in'>", unsafe_allow_html=True)
        if role != "student":
            st.error("Access denied.")
        else:
            if linked_roll:
                conn = get_conn()
                df_student = pd.read_sql_query("SELECT student_id, roll, name FROM students WHERE roll=?", conn, params=(linked_roll,))
                conn.close()
                if df_student.empty:
                    st.warning("Your roll is not found in students table.")
                else:
                    sid = int(df_student.iloc[0]['student_id'])
                    res = compute_student_report(sid)
                    if not res:
                        st.warning("No marks recorded for you yet.")
                    else:
                        df, summary = res
                        st.subheader(f"{summary['name']} — {summary['roll']}")
                        st.metric("CGPA", summary['cgpa'])
                        display_df = df[['code','title','credits','marks','max_marks','percent','grade','grade_point']]
                        st.dataframe(display_df.style.format({"percent":"{:.2f}","grade_point":"{:.2f}"}), height=300)
                        csv_bytes = display_df.to_csv(index=False).encode('utf-8')
                        st.download_button("Download CSV", csv_bytes, file_name=f"report_{summary['roll']}.csv", mime="text/csv")
            else:
                st.warning("Your student roll is not linked to your account.")
        st.markdown("</div>", unsafe_allow_html=True)

    elif page == "Export":
        st.markdown("<div class='card fade-in'>", unsafe_allow_html=True)
        st.header("Export All Data")
        students = get_all_students_df()
        subjects = get_all_subjects_df()
        conn = get_conn()
        marks_df = pd.read_sql_query("""
        SELECT s.roll, s.name, sub.code, sub.title, sub.credits,
               m.marks, m.max_marks
        FROM marks m
        JOIN students s ON m.student_id = s.student_id
        JOIN subjects sub ON m.subject_id = sub.subject_id
        ORDER BY s.roll
        """, conn)
        conn.close()
        st.subheader("Students")
        st.dataframe(students)
        st.subheader("Subjects")
        st.dataframe(subjects)
        st.subheader("Marks")
        st.dataframe(marks_df)
        if st.button("Export All to Excel"):
            bytes_xl = export_df_to_excel_bytes({"students": students, "subjects": subjects, "marks": marks_df})
            st.download_button("Download Excel", bytes_xl, file_name="all_results.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        st.markdown("</div>", unsafe_allow_html=True)

    elif page == "Admin":
        # admin only destructive tools
        if role != "admin":
            st.error("Access denied.")
        else:
            st.markdown("<div class='card fade-in'>", unsafe_allow_html=True)
            st.header("Admin Tools")
            st.markdown("**Reset DB** — drops students/subjects/marks (users kept). Use carefully.")
            if st.button("Reset ALL data (drop tables)"):
                if st.checkbox("I understand this will erase ALL student/subject/mark data. Confirm to reset database.", key="confirm_reset"):
                    conn = get_conn()
                    cur = conn.cursor()
                    cur.execute("DROP TABLE IF EXISTS marks")
                    cur.execute("DROP TABLE IF EXISTS subjects")
                    cur.execute("DROP TABLE IF EXISTS students")
                    conn.commit()
                    conn.close()
                    init_db()
                    st.success("Database reset (students/subjects/marks).")
            st.markdown("</div>", unsafe_allow_html=True)

except Exception:
    st.error("An unexpected error occurred. See details below.")
    st.code(traceback.format_exc())
