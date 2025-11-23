# app.py
# Clean modern Result Processor with soft micro-animations (no 3D), login + CGPA calculator
import streamlit as st
import sqlite3
import pandas as pd
from io import BytesIO
from datetime import datetime
import os
import traceback

# -------------------------
# Configuration & safety
# -------------------------
st.set_page_config(page_title="Digital Result Processor", layout="wide", initial_sidebar_state="expanded")

# Wrap startup in try/except to avoid black screen on Streamlit Cloud
try:
    # -------------------------
    # Paths & DB initialization
    # -------------------------
    DATA_DIR = "data"
    DB_PATH = os.path.join(DATA_DIR, "results.db")
    os.makedirs(DATA_DIR, exist_ok=True)

    def get_conn():
        return sqlite3.connect(DB_PATH, check_same_thread=False)

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

    init_db()

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
            st.success("Student added")
        except sqlite3.IntegrityError:
            st.warning("Student with this roll already exists.")
        finally:
            conn.close()

    def add_subject(code, title, credits):
        conn = get_conn()
        cur = conn.cursor()
        try:
            cur.execute("INSERT INTO subjects (code, title, credits) VALUES (?, ?, ?)", (code, title, float(credits)))
            conn.commit()
            st.success("Subject added")
        except sqlite3.IntegrityError:
            st.warning("Subject with this code already exists.")
        finally:
            conn.close()

    def add_marks(roll, subject_code, marks, max_marks=100):
        conn = get_conn()
        cur = conn.cursor()
        try:
            cur.execute("SELECT student_id FROM students WHERE roll = ?", (roll,))
            s = cur.fetchone()
            if not s:
                st.error("Student roll not found.")
                return
            student_id = s[0]
            cur.execute("SELECT subject_id FROM subjects WHERE code = ?", (subject_code,))
            sub = cur.fetchone()
            if not sub:
                st.error("Subject code not found.")
                return
            subject_id = sub[0]

            cur.execute("SELECT mark_id FROM marks WHERE student_id = ? AND subject_id = ?", (student_id, subject_id))
            existing = cur.fetchone()

            if existing:
                cur.execute(
                    "UPDATE marks SET marks=?, max_marks=? WHERE mark_id=?",
                    (float(marks), float(max_marks), existing[0])
                )
            else:
                cur.execute(
                    "INSERT INTO marks (student_id, subject_id, marks, max_marks) VALUES (?, ?, ?, ?)",
                    (student_id, subject_id, float(marks), float(max_marks))
                )

            conn.commit()
            st.success("Marks saved")
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
    # Auth & session
    # -------------------------
    CREDENTIALS = {"admin": "1234"}  # hard-coded login

    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False

    # -------------------------
    # Styling
    # -------------------------
    st.markdown("""
    <style>
        body {
            background: linear-gradient(180deg,#f7fbff 0%, #eef6ff 100%);
            color: #0b2545;
        }
        .card {
            background: white;
            padding: 20px;
            border-radius: 12px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.08);
            transition: transform 0.2s ease;
        }
        .card:hover {
            transform: translateY(-4px);
        }
    </style>
    """, unsafe_allow_html=True)

    # -------------------------
    # Login UI
    # -------------------------
    def login_ui():
        st.markdown("<div class='card' style='max-width:450px;margin:auto;'>", unsafe_allow_html=True)
        st.markdown("<h3 style='text-align:center;'>Login</h3>", unsafe_allow_html=True)

        username = st.text_input("Username")
        password = st.text_input("Password", type="password")

        if st.button("Login"):
            if username in CREDENTIALS and CREDENTIALS[username] == password:
                st.session_state.logged_in = True
                st.experimental_rerun()
            else:
                st.error("Invalid credentials.")

        st.markdown("</div>", unsafe_allow_html=True)

    # -------------------------
    # Show login if not signed in
    # -------------------------
    if not st.session_state.logged_in:
        login_ui()
        st.stop()

    # -------------------------
    # Sidebar navigation
    # -------------------------
    pages = ["Dashboard", "Add Data", "Enter Marks", "Student Report", "Export"]
    choice = st.sidebar.radio("Navigation", pages)

    # -------------------------
    # PAGES
    # -------------------------

    if choice == "Dashboard":
        st.title("📘 Dashboard")
        st.write("Class summary")
        students = get_all_students_df()
        subjects = get_all_subjects_df()
        st.dataframe(students)
        st.dataframe(subjects)

    elif choice == "Add Data":
        st.title("Add Student / Subject")
        with st.form("add_student"):
            st.subheader("Add student")
            roll = st.text_input("Roll")
            name = st.text_input("Name")
            program = st.text_input("Program")
            if st.form_submit_button("Save Student"):
                add_student(roll, name, program)

        with st.form("add_subject"):
            st.subheader("Add subject")
            code = st.text_input("Code")
            title = st.text_input("Title")
            credits = st.number_input("Credits", min_value=0.0)
            if st.form_submit_button("Save Subject"):
                add_subject(code, title, credits)

    elif choice == "Enter Marks":
        st.title("Enter Marks")
        students = get_all_students_df()
        subjects = get_all_subjects_df()
        if students.empty or subjects.empty:
            st.warning("Add students and subjects first.")
        else:
            with st.form("marks_form"):
                roll = st.selectbox("Student Roll", students["roll"])
                subject = st.selectbox("Subject", subjects["code"])
                marks = st.number_input("Marks", min_value=0.0)
                max_marks = st.number_input("Max Marks", min_value=1.0, value=100.0)
                if st.form_submit_button("Save"):
                    add_marks(roll, subject, marks, max_marks)

    elif choice == "Student Report":
        st.title("Student Report")
        students = get_all_students_df()
        if students.empty:
            st.warning("No students found.")
        else:
            roll = st.selectbox("Choose Roll", students["roll"])
            sid = int(students[students["roll"] == roll]["student_id"].iloc[0])
            result = compute_student_report(sid)
            if not result:
                st.warning("No marks for this student.")
            else:
                df, summary = result
                st.metric("CGPA", summary["cgpa"])
                st.write(df)

    elif choice == "Export":
        st.title("Export Data")
        students = get_all_students_df()
        subjects = get_all_subjects_df()
        conn = get_conn()
        marks = pd.read_sql_query("""
        SELECT s.roll, s.name, sub.code, sub.title, sub.credits,
               m.marks, m.max_marks
        FROM marks m
        JOIN students s ON m.student_id = s.student_id
        JOIN subjects sub ON m.subject_id = sub.subject_id
        ORDER BY s.roll
        """, conn)
        conn.close()

        excel = export_df_to_excel_bytes({
            "students": students,
            "subjects": subjects,
            "marks": marks
        })

        st.download_button("Download Excel", excel, "all_results.xlsx")

except Exception:
    st.error("Startup error")
    st.code(traceback.format_exc())
