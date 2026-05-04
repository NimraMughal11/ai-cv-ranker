import streamlit as st
from groq import Groq
import pdfplumber
import docx
import sqlite3
import json
import re
import pandas as pd
import time

# =========================
# 🗄 DATABASE
# =========================
def get_db():
    conn = sqlite3.connect("hr_saas.db", check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

conn = get_db()
c = conn.cursor()
c.execute("""CREATE TABLE IF NOT EXISTS candidates(
    id INTEGER PRIMARY KEY AUTOINCREMENT, 
    file_name TEXT, name TEXT, email TEXT, phone TEXT,
    job_role TEXT, score INTEGER, decision TEXT, 
    strengths TEXT, missing TEXT, summary TEXT, suggestions TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)""")
conn.commit()

# =========================
# 📄 FILE READERS
# =========================
def read_pdf(file):
    text = ""
    try:
        with pdfplumber.open(file) as pdf:
            for page in pdf.pages:
                if page.extract_text():
                    text += page.extract_text() + "\n"
    except:
        text = ""
    return text.strip()

def read_docx(file):
    try:
        doc = docx.Document(file)
        return "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
    except:
        return ""

# =========================
# 🔍 SMART EXTRACTORS
# =========================
def get_name_from_file(file_name):
    name = re.sub(r'\.(pdf|docx|doc)$', '', file_name, flags=re.IGNORECASE)
    name = re.sub(r'[_\-\.\s]+', ' ', name).strip()
    name = ' '.join(word.capitalize() for word in name.split())
    return name if name else "Unknown Candidate"

def extract_contact_info(text):
    email_match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
    email = email_match.group(0) if email_match else "Not Found"
    phone_match = re.search(r'(\+\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}', text)
    phone = phone_match.group(0).strip() if phone_match else "Not Found"
    return email, phone

def extract_local_skills(text):
    common_tech = ["python", "javascript", "react", "node", "sql", "machine learning", "aws", "docker", "java", "c++", "html", "css", "tensorflow", "fastapi", "flask", "django"]
    found_skills = [skill for skill in common_tech if re.search(rf'\b{skill}\b', text, re.IGNORECASE)]
    return found_skills

# =========================
# 🤖 AI ENGINE (Now using GROQ)
# =========================
def clean_json(text):
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*", "", text)
    text = text.strip()
    start, end = text.find("{"), text.rfind("}")
    return text[start:end+1] if start != -1 and end != -1 else text

def analyze_cv(cv_text, file_name, job_role):
    name = get_name_from_file(file_name)
    email, phone = extract_contact_info(cv_text)
    local_skills = extract_local_skills(cv_text)

    if not st.session_state.get("api_key"):
        return {"name": name, "email": email, "phone": phone, "score": 0, "decision": "No API Key", "strengths": local_skills, "missing_skills": ["Add API Key"], "summary": "No API Key provided", "suggestions": "Get key from groq.com"}

    try:
        # Initialize Groq Client
        client = Groq(api_key=st.session_state.api_key)
        
        prompt = f"""Analyze this CV for a {job_role} role.
Return ONLY a JSON object strictly in this format:
{{
    "score": 85,
    "decision": "Hire",
    "strengths": ["point 1", "point 2"],
    "missing_skills": ["skill 1"],
    "summary": "3 lines summary",
    "suggestions": "2 lines suggestion"
}}
Rules: score 0-100, decision ONLY "Hire", "Maybe", or "Reject".

CV:
{cv_text[:6000]}"""

        # Using Llama-3 model (Free & Powerful)
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile", # This is a top-tier free model
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        
        data = json.loads(clean_json(chat_completion.choices[0].message.content))
        
        score = int(float(str(data.get("score", 0)).replace('%', '').strip())) if data.get("score") else 0
        decision = data.get("decision", "Maybe") if data.get("decision") in ["Hire", "Maybe", "Reject"] else "Maybe"
        
        return {
            "name": name, "email": email, "phone": phone,
            "score": max(0, min(100, score)), "decision": decision, 
            "strengths": data.get("strengths", local_skills), 
            "missing_skills": data.get("missing_skills", []),
            "summary": data.get("summary", "AI summary failed."), 
            "suggestions": data.get("suggestions", "")
        }
    except Exception as e:
        return {
            "name": name, "email": email, "phone": phone,
            "score": 0, "decision": "AI Error", 
            "strengths": local_skills, "missing_skills": ["Analysis failed"],
            "summary": f"Error: {str(e)[:100]}", "suggestions": "Check API Key."
        }

# =========================
# 🎨 UI
# =========================
st.set_page_config(page_title="AI HR Tool (Groq)", page_icon="💼", layout="wide")

st.sidebar.title("💼 AI HR Tool")
st.sidebar.markdown("### 🔐 Enter Groq API Key")
st.sidebar.markdown("[🔗 Get a FREE Groq API Key here](https://console.groq.com/keys)")

if "api_key" not in st.session_state:
    st.session_state.api_key = ""

api_key_input = st.sidebar.text_input("API Key", type="password", value=st.session_state.api_key)
st.session_state.api_key = api_key_input.strip()

if st.session_state.api_key:
    st.sidebar.success("✅ API key loaded")
else:
    st.sidebar.warning("⚠️ Please enter your Groq API key.")

st.sidebar.divider()
menu = st.sidebar.radio("Menu", ["📄 New Analysis & Ranking", "🏆 Scores Dashboard", "📝 Detailed Reports", "🗑️ Clear Data"], label_visibility="collapsed")

if menu == "📄 New Analysis & Ranking":
    st.title("📄 Upload Multiple CVs for Comparison")
    job_role = st.selectbox("🎯 Select Job Role", ["Frontend Developer", "Backend Developer", "Full Stack Developer", "Data Analyst", "Data Scientist", "AI/ML Engineer", "DevOps Engineer"])
    files = st.file_uploader("Attach CVs (PDF/DOCX)", type=["pdf", "docx"], accept_multiple_files=True)

    if files and st.button("🚀 Analyze & Rank CVs", type="primary", use_container_width=True):
        if not st.session_state.api_key:
            st.error("🔑 Please enter your Groq API key in the sidebar.")
        else:
            bar = st.progress(0, text="Reading CVs...")
            results = []
            for i, file in enumerate(files):
                bar.progress((i / len(files)), text=f"🔍 Analyzing: {file.name}")
                text = read_pdf(file) if file.name.endswith(".pdf") else read_docx(file)
                if text:
                    ai = analyze_cv(text, file.name, job_role)
                    results.append(ai)
                    c.execute("""INSERT INTO candidates(file_name, name, email, phone, job_role, score, decision, strengths, missing, summary, suggestions) 
                                VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (
                        file.name, ai["name"], ai["email"], ai["phone"], job_role, ai["score"], ai["decision"],
                        json.dumps(ai["strengths"]), json.dumps(ai["missing_skills"]), ai["summary"], ai["suggestions"]
                    ))
                    conn.commit()
                time.sleep(0.2)
            bar.progress(1.0, text="✅ Analysis Complete!")
            
            if results:
                results.sort(key=lambda x: x["score"], reverse=True)
                st.divider()
                st.subheader(f"📊 Results for: {job_role}")
                
                best = results[0]
                if best["score"] > 0:
                    st.success(f"🥇 **BEST FIT:** {best['name']} ({best['score']}%)")
                else:
                    st.warning("⚠️ AI faced issues. Check errors below.")
                
                comp_data = [{"Rank": f"#{idx}", "Name": res['name'], "Score": f"{res['score']}%", "Decision": res['decision'], "Top Strength": res['strengths'][0] if res['strengths'] else "N/A"} for idx, res in enumerate(results, 1)]
                st.dataframe(pd.DataFrame(comp_data), use_container_width=True, hide_index=True)
                
                st.subheader("📝 Individual Analysis")
                for idx, res in enumerate(results, 1):
                    with st.expander(f"Rank #{idx}: {res['name']} ({res['score']}%)"):
                        c1, c2 = st.columns(2)
                        with c1:
                            st.write("**✅ Strengths:**")
                            for s in res["strengths"]: st.markdown(f"- {s}")
                        with c2:
                            st.write("**❌ Missing Skills:**")
                            for m in res["missing_skills"]: st.markdown(f"- {m}")
                        st.info(res["summary"])

elif menu == "🏆 Scores Dashboard":
    st.title("🏆 All Time Scores")
    df = pd.read_sql("SELECT * FROM candidates WHERE decision != 'AI Error' ORDER BY score DESC", conn)
    if not df.empty:
        st.dataframe(df[["name", "job_role", "score", "decision"]], use_container_width=True, hide_index=True)
    else:
        st.info("No data yet.")

elif menu == "📝 Detailed Reports":
    st.title("📝 Detailed Reports")
    df = pd.read_sql("SELECT * FROM candidates ORDER BY score DESC", conn)
    if not df.empty:
        for _, r in df.iterrows():
            with st.expander(f"{r['name']} — {r['score']}%"):
                st.write(f"**Email:** {r['email']} | **Phone:** {r['phone']}")
                st.info(f"**Summary:** {r['summary']}")
                st.warning(f"**Suggestions:** {r['suggestions']}")
    else:
        st.info("No reports yet.")

elif menu == "🗑️ Clear Data":
    st.title("🗑️ Manage Database")
    if st.button("Delete All Data"):
        c.execute("DELETE FROM candidates")
        conn.commit()
        st.success("Data cleared!")
        st.rerun()
