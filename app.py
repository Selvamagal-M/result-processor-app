import streamlit as st
import pandas as pd
import os
import sqlite3
from datetime import datetime

# ------------------------------
#  SAFETY: Create data directory
# ------------------------------
DATA_DIR = "data"
DB_PATH = os.path.join(DATA_DIR, "results.db")

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# ------------------------------
#  DATABASE INITIALIZATION
# ------------------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            register_no TEXT,
            score INTEGER,
            uploaded_at TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ------------------------------
#  LOGIN SYSTEM
# ------------------------------
def check_login(username, password):
    return username == "admin" and password == "1234"

def login_screen():
    st.markdown("<h2 style='text-align:center;'>🔐 Login to Continue</h2>", unsafe_allow_html=True)
    user = st.text_input("Username")
    pwd = st.text_input("Password", type="password")
    if st.button("Login"):
        if check_login(user, pwd):
            st.session_state["logged_in"] = True
            st.success("Login successful!")
        else:
            st.error("Invalid username or password.")

# ------------------------------
#  UI STYLING
# ------------------------------
st.markdown("""
    <style>
        .main {
            background-color: #F5F7FA;
        }
        .stButton>button {
            width: 100%;
            border-radius: 10px;
            background-color: #4B7BEC;
            color: white;
            height: 45px;
        }
        .stTextInput>div>div>input {
            border-radius: 8px;
        }
    </style>
""", unsafe_allow_html=True)

# ------------------------------
#  DATA FUNCTIONS
# ------------------------------
def insert_result(name, reg_no, score):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO results (name, register_no, score, uploaded_at) VALUES (?, ?, ?, ?)",
              (name, reg_no, score, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

def fetch_results():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM results", conn)
    conn.close()
    return df

# ------------------------------
#  MAIN APP
# ------------------------------
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    login_screen()
else:
    st.markdown("<h1 style='text-align:center;'>📊 Result Processor Dashboard</h1>", unsafe_allow_html=True)

    menu = st.sidebar.radio("Navigation", ["Upload Result", "View Results"])

    if menu == "Upload Result":
        st.subheader("📥 Upload New Result")

        name = st.text_input("Student Name")
        reg_no = st.text_input("Register Number")
        score = st.number_input("Score", min_value=0, max_value=100)

        if st.button("Save Result"):
            if name and reg_no:
                insert_result(name, reg_no, score)
                st.success("Result saved successfully!")
            else:
                st.warning("Please fill all fields.")

    elif menu == "View Results":
        st.subheader("📄 All Results")
        df = fetch_results()
        st.dataframe(df, use_container_width=True)

        # Download as CSV
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Download CSV",
            data=csv,
            file_name="results.csv",
            mime="text/csv"
        )
