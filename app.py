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
        cur.execute(\"\"\"
        CREATE TABLE IF NOT EXISTS students (
            student_id INTEGER PRIMARY KEY AUTOINCREMENT,
            roll TEXT UNIQUE,
            name TEXT,
            program TEXT
        )
        \"\"\")
        cur.execute(\"\"\"
        CREATE TABLE IF NOT EXISTS subjects (
            subject_id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            title TEXT,
            credits REAL
        )
        \"\"\")
        cur.execute(\"\"\"
        CREATE TABLE IF NOT EXISTS marks (
            mark_id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            subject_id INTEGER,
            marks REAL,
            max_marks REAL,
            FOREIGN KEY(student_id) REFERENCES students(student_id),
            FOREIGN KEY(subject_id) REFERENCES subjects(subject_id)
        )
        \"\"\")
        conn.commit()
        conn.close()

    init_db()

    # -------------------------
    # Business logic (grading)
    # -------------------------
    def grade_from_percent(p):
        if p >= 90: return (\"A+\", 10.0)
        if p >= 80: return (\"A\", 9.0)
        if p >= 70: return (\"B+\", 8.0)
        if p >= 60: return (\"B\", 7.0)
        if p >= 50: return (\"C\", 6.0)
        if p >= 40: return (\"D\", 5.0)
        return (\"F\", 0.0)

    def compute_student_report(student_id):
        conn = get_conn()
        q = \"\"\"
        SELECT s.student_id, s.roll, s.name, sub.code, sub.title, sub.credits, m.marks, m.max_marks
        FROM students s
        JOIN marks m ON s.student_id = m.student_id
        JOIN subjects sub ON m.subject_id = sub.subject_id
        WHERE s.student_id = ?
        \"\"\"
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
            \"roll\": df.iloc[0]['roll'],
            \"name\": df.iloc[0]['name'],
            \"total_credits\": float(total_credits),
            \"total_credit_gp\": float(total_credit_gp),
            \"cgpa\": round(cgpa, 2),
            \"generated_at\": datetime.utcnow().isoformat() + \"Z\"
        }
        return df, summary

    # -------------------------
    # Data operations
    # -------------------------
    def add_student(roll, name, program=\"\"):
        conn = get_conn()
        cur = conn.cursor()
        try:
            cur.execute(\"INSERT INTO students (roll, name, program) VALUES (?, ?, ?)\", (roll, name, program))
            conn.commit()
            st.success(\"Student added\")
        except sqlite3.IntegrityError:
            st.warning(\"Student with this roll already exists.\")
        finally:
            conn.close()

    def add_subject(code, title, credits):
        conn = get_conn()
        cur = conn.cursor()
        try:
            cur.execute(\"INSERT INTO subjects (code, title, credits) VALUES (?, ?, ?)\", (code, title, float(credits)))
            conn.commit()
            st.success(\"Subject added\")
        except sqlite3.IntegrityError:
            st.warning(\"Subject with this code already exists.\")
        finally:
            conn.close()

    def add_marks(roll, subject_code, marks, max_marks=100):
        conn = get_conn()
        cur = conn.cursor()
        try:
            cur.execute(\"SELECT student_id FROM students WHERE roll = ?\", (roll,))
            s = cur.fetchone()
            if not s:
                st.error(\"Student roll not found.\")
                return
            student_id = s[0]
            cur.execute(\"SELECT subject_id FROM subjects WHERE code = ?\", (subject_code,))
            sub = cur.fetchone()
            if not sub:
                st.error(\"Subject code not found.\")
                return
            subject_id = sub[0]
            cur.execute(\"SELECT mark_id FROM marks WHERE student_id = ? AND subject_id = ?\", (student_id, subject_id))
            existing = cur.fetchone()
            if existing:
                cur.execute(\"UPDATE marks SET marks=?, max_marks=? WHERE mark_id=?\", (float(marks), float(max_marks), existing[0]))
            else:
                cur.execute(\"INSERT INTO marks (student_id, subject_id, marks, max_marks) VALUES (?, ?, ?, ?)\",
                            (student_id, subject_id, float(marks), float(max_marks)))
            conn.commit()
            st.success(\"Marks saved\")
        finally:
            conn.close()

    def get_all_students_df():
        conn = get_conn()
        df = pd.read_sql_query(\"SELECT student_id, roll, name, program FROM students ORDER BY roll\", conn)
        conn.close()
        return df

    def get_all_subjects_df():
        conn = get_conn()
        df = pd.read_sql_query(\"SELECT subject_id, code, title, credits FROM subjects ORDER BY code\", conn)
        conn.close()
        return df

    def export_df_to_excel_bytes(dfs: dict):
        with BytesIO() as b:
            with pd.ExcelWriter(b, engine=\"openpyxl\") as writer:
                for sheet_name, df in dfs.items():
                    df.to_excel(writer, sheet_name=sheet_name[:31], index=False)
            return b.getvalue()

    # -------------------------
    # Auth & session (hard-coded)
    # -------------------------
    CREDENTIALS = {\"admin\": \"1234\"}  # change this map to add users

    if \"logged_in\" not in st.session_state:
        st.session_state.logged_in = False
    if \"username\" not in st.session_state:
        st.session_state.username = None
    if \"nav\" not in st.session_state:
        st.session_state.nav = \"Dashboard\"

    def login_ui():
        st.markdown(\"<div style='max-width:700px;margin:auto;'>\", unsafe_allow_html=True)
        st.markdown(\"<h2 style='text-align:center;margin:0;color:#0b2545;'>Welcome — Sign in</h2>\", unsafe_allow_html=True)
        st.markdown(\"<p style='text-align:center;color:#3a5a82;margin-top:6px;'>Enter your username and password to continue.</p>\", unsafe_allow_html=True)
        with st.form(\"login_form\", clear_on_submit=False):
            cols = st.columns([1,1])
            with cols[0]:
                username = st.text_input(\"Username\", value=\"\", placeholder=\"admin\")
            with cols[1]:
                password = st.text_input(\"Password\", type=\"password\", placeholder=\"1234\")
            submitted = st.form_submit_button(\"Sign in\")
            if submitted:
                if username in CREDENTIALS and CREDENTIALS[username] == password:
                    st.session_state.logged_in = True
                    st.session_state.username = username
                    st.success(\"Login successful.\")
                    st.experimental_rerun()
                else:
                    st.error(\"Invalid username or password.\")
        st.markdown(\"</div>\", unsafe_allow_html=True)

    # -------------------------
    # Styling: modern minimal + soft micro-animations
    # -------------------------
    st.markdown(\"\"\"
    <style>
    :root{ --bg: linear-gradient(180deg,#f7fbff 0%, #eef6ff 100%); }
    body { background: linear-gradient(180deg,#f7fbff 0%, #eef6ff 100%); color: #0b2545; }
    .block-container{ max-width:1400px; padding:1rem 2rem; }
    .card { background: #ffffff; border-radius:12px; padding:18px; border:1px solid rgba(11,37,69,0.06); box-shadow: 0 6px 24px rgba(11,37,69,0.04); transition: transform 0.18s ease, box-shadow 0.18s ease; }
    .card:hover { transform: translateY(-6px); box-shadow: 0 12px 40px rgba(11,37,69,0.08); }
    .small-muted{ color:#3a5a82; font-size:13px; }
    .top-row { display:flex; gap:12px; align-items:center; justify-content:space-between; }
    .logo-box{ width:56px; height:56px; border-radius:12px; display:flex; align-items:center; justify-content:center; background:linear-gradient(135deg,#4b7bec,#7b61ff); color:white; font-weight:700; box-shadow:0 8px 24px rgba(75,123,236,0.12); }
    .stButton>button { border-radius:10px; height:44px; transition: transform 0.12s ease; }
    .stButton>button:hover { transform: translateY(-3px); }
    .metric { font-weight:700; font-size:20px; color:#0b2545; }
    .fade-in { animation: fadeIn 0.36s ease both; }
    @keyframes fadeIn { from { opacity:0; transform: translateY(6px);} to { opacity:1; transform: translateY(0);} }
    </style>
    \"\"\", unsafe_allow_html=True)

    # -------------------------
    # Header
    # -------------------------
    col1, col2 = st.columns([4,1])
    with col1:
        st.markdown(\"<div class='top-row'><div style='display:flex;gap:12px;align-items:center'><div class='logo-box'>RP</div><div><h2 style='margin:0;padding:0'>Result Processor</h2><div class='small-muted'>Clean UI • Reliable CGPA • Soft micro-animations</div></div></div></div>\", unsafe_allow_html=True)
    with col2:
        if st.session_state.logged_in:
            st.markdown(f\"<div style='text-align:right' class='small-muted'>Signed in as <strong>{st.session_state.username}</strong></div>\", unsafe_allow_html=True)
            if st.button(\"Logout\", key=\"logout_btn\"):
                st.session_state.logged_in = False
                st.session_state.username = None
                st.experimental_rerun()

    # -------------------------
    # Login handling
    # -------------------------
    if not st.session_state.logged_in:
        st.markdown(\"<div class='card fade-in' style='max-width:900px;margin:16px auto;'>\", unsafe_allow_html=True)
        login_ui()
        st.markdown(\"</div>\", unsafe_allow_html=True)
        st.stop()

    # -------------------------
    # Sidebar navigation (after login)
    # -------------------------
    st.sidebar.markdown(\"---\")
    st.sidebar.markdown(\"### Navigation\")
    st.session_state.nav = st.sidebar.selectbox(\"\", [\"Dashboard\", \"Add Data\", \"Enter Marks\", \"Student Report\", \"Export\", \"Admin\"], index=[\"Dashboard\",\"Add Data\",\"Enter Marks\",\"Student Report\",\"Export\",\"Admin\"].index(st.session_state.nav) if st.session_state.nav in [\"Dashboard\",\"Add Data\",\"Enter Marks\",\"Student Report\",\"Export\",\"Admin\"] else 0)
    st.sidebar.markdown(\"---\")
    st.sidebar.write(f\"Logged in as **{st.session_state.username}**\")
    st.sidebar.markdown(\"---\")
    st.sidebar.caption(\"Built with ❤️ — clean UI\")

    # -------------------------
    # Pages
    # -------------------------
    menu = st.session_state.nav

    if menu == \"Dashboard\":
        st.markdown(\"<div class='card fade-in'>\", unsafe_allow_html=True)
        st.header(\"Class Summary\")
        students = get_all_students_df()
        subjects = get_all_subjects_df()
        colA, colB, colC = st.columns([2,1,1])
        with colA:
            st.subheader(\"Students\")
            st.write(f\"Total students: {len(students)}\")
            st.dataframe(students, use_container_width=True)
        with colB:
            st.subheader(\"Subjects\")
            st.write(f\"Total subjects: {len(subjects)}\")
            st.dataframe(subjects, use_container_width=True)
        with colC:
            cgpa_vals = []
            for sid in students['student_id'].tolist():
                result = compute_student_report(sid)
                if result:
                    cgpa_vals.append(result[1]['cgpa'])
            avg_cgpa = round(sum(cgpa_vals)/len(cgpa_vals),2) if cgpa_vals else \"—\"
            st.markdown(\"<div class='metric'>Class Avg. CGPA</div>\", unsafe_allow_html=True)
            st.markdown(f\"<h2 style='margin-top:6px'>{avg_cgpa}</h2>\", unsafe_allow_html=True)
        st.markdown(\"</div>\", unsafe_allow_html=True)

        st.markdown(\"<div class='card fade-in' style='margin-top:16px'>\", unsafe_allow_html=True)
        if st.button(\"Compute CGPA for all students\"):
            out = []
            for sid in students['student_id'].tolist():
                result = compute_student_report(sid)
                if result:
                    df, summ = result
                    out.append({\"roll\": summ['roll'], \"name\": summ['name'], \"cgpa\": summ['cgpa'], \"total_credits\": summ['total_credits']})
            if out:
                st.subheader(\"CGPA Leaderboard\")
                st.dataframe(pd.DataFrame(out).sort_values([\"cgpa\"], ascending=False), use_container_width=True)
            else:
                st.info(\"No marks present yet.\")
        st.markdown(\"</div>\", unsafe_allow_html=True)

    elif menu == \"Add Data\":
        st.markdown(\"<div class='card fade-in'>\", unsafe_allow_html=True)
        st.header(\"Add Students & Subjects\")
        with st.form(\"student_form\"):
            st.subheader(\"Add student\")
            roll = st.text_input(\"Roll (unique)\", value=\"\")
            name = st.text_input(\"Name\")
            program = st.text_input(\"Program / Course (optional)\")
            submitted = st.form_submit_button(\"Add student\")
            if submitted:
                if roll.strip() == \"\" or name.strip() == \"\":
                    st.error(\"Fill roll and name.\")
                else:
                    add_student(roll.strip(), name.strip(), program.strip())

        st.markdown(\"---\")
        with st.form(\"subject_form\"):
            st.subheader(\"Add subject\")
            code = st.text_input(\"Subject code (unique)\", value=\"\", key=\"scode\")
            title = st.text_input(\"Title\", key=\"stitle\")
            credits = st.number_input(\"Credits\", min_value=0.0, value=3.0, step=0.5, key=\"scredit\")
            submitted2 = st.form_submit_button(\"Add subject\")
            if submitted2:
                if code.strip() == \"\" or title.strip() == \"\":
                    st.error(\"Fill code and title.\")
                else:
                    add_subject(code.strip(), title.strip(), float(credits))
        st.markdown(\"</div>\", unsafe_allow_html=True)

    elif menu == \"Enter Marks\":
        st.markdown(\"<div class='card fade-in'>\", unsafe_allow_html=True)
        st.header(\"Enter / Update Marks\")
        students = get_all_students_df()
        subs = get_all_subjects_df()
        if students.empty or subs.empty:
            st.info(\"You need to add at least one student and one subject first.\")
        else:
            with st.form(\"marks_form\"):
                roll = st.selectbox(\"Student (by roll)\", students['roll'].tolist())
                subject_code = st.selectbox(\"Subject code\", subs['code'].tolist())
                marks = st.number_input(\"Marks obtained\", min_value=0.0, value=0.0)
                max_marks = st.number_input(\"Max marks (for percent)\", min_value=1.0, value=100.0)
                submitted3 = st.form_submit_button(\"Save marks\")
                if submitted3:
                    add_marks(roll, subject_code, marks, max_marks)
        st.markdown(\"</div>\", unsafe_allow_html=True)

    elif menu == \"Student Report\":
        st.markdown(\"<div class='card fade-in'>\", unsafe_allow_html=True)
        st.header(\"Generate Student Report\")
        students = get_all_students_df()
        if students.empty:
            st.info(\"No students yet.\")
        else:
            roll_selected = st.selectbox(\"Choose student\", students['roll'].tolist())
            sid = int(students[students['roll']==roll_selected]['student_id'].iloc[0])
            res = compute_student_report(sid)
            if not res:
                st.warning(\"No marks recorded for this student yet.\")
            else:
                df, summary = res
                st.subheader(f\"{summary['name']} — {summary['roll']}\")
                st.metric(\"CGPA\", summary['cgpa'])
                st.write(\"Detailed marks / grades\")
                display_df = df[['code','title','credits','marks','max_marks','percent','grade','grade_point']]
                st.dataframe(display_df.style.format({\"percent\":\"{:.2f}\",\"grade_point\":\"{:.2f}\"}), height=300)

                csv_bytes = display_df.to_csv(index=False).encode('utf-8')
                st.download_button(\"Download CSV\", csv_bytes, file_name=f\"report_{summary['roll']}.csv\", mime=\"text/csv\")

                if st.button(\"Export Excel for this student\"):
                    bytes_xl = export_df_to_excel_bytes({\"report\": display_df})
                    st.download_button(\"Download Excel\", bytes_xl, file_name=f\"report_{summary['roll']}.xlsx\", mime=\"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\")
        st.markdown(\"</div>\", unsafe_allow_html=True)

    elif menu == \"Export\":
        st.markdown(\"<div class='card fade-in'>\", unsafe_allow_html=True)
        st.header(\"Export All Data\")
        students = get_all_students_df()
        subjects = get_all_subjects_df()

        conn = get_conn()
        marks_df = pd.read_sql_query(\"\"\"
        SELECT s.roll, s.name, sub.code AS subject_code, sub.title AS subject_title, sub.credits,
               m.marks, m.max_marks
        FROM marks m
        JOIN students s ON m.student_id = s.student_id
        JOIN subjects sub ON m.subject_id = sub.subject_id
        ORDER BY s.roll
        \"\"\", conn)
        conn.close()

        st.write(\"Students\")
        st.dataframe(students)
        st.write(\"Subjects\")
        st.dataframe(subjects)
        st.write(\"Marks\")
        st.dataframe(marks_df)

        if st.button(\"Export All to Excel\"):
            bytes_xl = export_df_to_excel_bytes({
                \"students\": students,
                \"subjects\": subjects,
                \"marks\": marks_df
            })
            st.download_button(\"Download Excel\", bytes_xl, file_name=\"all_results.xlsx\", mime=\"application/vnd.openxmlformats-officedocument-spreadsheetml.sheet\")
        st.markdown(\"</div>\", unsafe_allow_html=True)

    elif menu == \"Admin\":
        st.markdown(\"<div class='card fade-in'>\", unsafe_allow_html=True)
        st.header(\"Admin / DB Tools\")
        if st.button(\"Reset ALL data (drop tables)\"):
            if st.checkbox(\"I understand this will erase ALL data. Confirm to reset database.\", key=\"confirm_reset\"):
                conn = get_conn()
                cur = conn.cursor()
                cur.execute(\"DROP TABLE IF EXISTS marks\")
                cur.execute(\"DROP TABLE IF EXISTS subjects\")
                cur.execute(\"DROP TABLE IF EXISTS students\")
                conn.commit()
                conn.close()
                init_db()
                st.success(\"Database reset.\")
        st.markdown(\"Use this to backup the DB file (`data/results.db`) before destructive operations.\")
        st.markdown(\"</div>\", unsafe_allow_html=True)

    # footer
    st.sidebar.markdown(\"---\")
    st.sidebar.write(\"Built with ❤️ using Streamlit\")
except Exception as e:
    st.exception(\"Startup error — see traceback below:\")
    st.text(traceback.format_exc())
