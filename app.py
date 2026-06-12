import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import google.generativeai as genai
from io import StringIO

st.set_page_config(page_title="CourtCompass AI", page_icon="⚖️", layout="wide")

# ── DATA LOAD ─────────────────────────────
@st.cache_data
def load_data():
    df_main = pd.read_csv("data/Pendency of Court Cases in India.csv")
    df_hc   = pd.read_csv("data/RS_Session_259_AU_119_1.csv")
    df_ftc  = pd.read_csv("data/RS_Session_254_AU_419.A.csv")
    df_disp = pd.read_csv("data/RS_Session_256_AU_4038_4.csv")
    df_tot  = pd.read_csv("data/RS_Session_256_AU_3321_A_to_D.csv")

    df_xlsx = pd.read_excel("data/Report (4).xlsx", skiprows=1)
    df_xlsx.columns = ["Years", "Institution", "Disposal"]
    df_xlsx = df_xlsx.dropna(subset=["Years"])
    df_xlsx["Years"] = df_xlsx["Years"].astype(int)

    df_main = df_main.rename(columns={
        "State/UT": "state",
        "Budget per capita on judiciary (₹) (2020–21)": "budget_per_capita",
        "Population per High Court Judge (2022)": "pop_per_hc_judge",
        "Population per Lower Court Judge (2022)": "pop_per_lc_judge",
        "Courthall shortfall (%) (2022)": "courthall_shortfall",
        "Case clearance rate of High Court (2022)": "hc_clearance_rate",
        "Case clearance rate of Lower Court (2022)": "lc_clearance_rate",
    })

    df_main["courthall_shortfall"] = pd.to_numeric(df_main["courthall_shortfall"], errors="coerce")

    df_ftc = df_ftc.rename(columns={
        "State/UT": "state",
        "Number of Fast Track Court": "ftc_count",
        "Number of Cases pending": "ftc_pending"
    })

    return df_main, df_hc, df_ftc, df_disp, df_tot, df_xlsx

df_main, df_hc, df_ftc, df_disp, df_tot, df_xlsx = load_data()

# ── GEMINI FIXED CONFIG ─────────────────────────────
def generate_with_gemini(api_key, prompt):
    genai.configure(api_key=api_key)

    # ✅ FIXED MODEL NAME (this was your error)
    model = genai.GenerativeModel("gemini-1.5-pro")

    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Gemini error: {e}"

# ── LOGIC ─────────────────────────────
def diagnose_state(state_name, df_main, df_ftc):
    state_row = df_main[df_main["state"].str.lower() == state_name.lower()]
    ftc_row = df_ftc[df_ftc["state"].str.lower() == state_name.lower()]

    if state_row.empty:
        return None

    row = state_row.iloc[0]

    nat = df_main[df_main["state"] != "India"]

    signals = {
        "state": row["state"],
        "budget_per_capita": float(row["budget_per_capita"]),
        "pop_per_lc_judge": float(row["pop_per_lc_judge"]),
        "lc_clearance_rate": float(row["lc_clearance_rate"]),
        "hc_clearance_rate": float(row["hc_clearance_rate"]),
        "courthall_shortfall": float(row["courthall_shortfall"]) if pd.notna(row["courthall_shortfall"]) else 0,
        "nat_budget": nat["budget_per_capita"].mean(),
        "nat_pop_lc": nat["pop_per_lc_judge"].mean(),
        "nat_clearance": nat["lc_clearance_rate"].mean(),
    }

    return signals

# ── PROMPT ─────────────────────────────
def build_prompt(s):
    return f"""
You are CourtCompass AI.

State: {s['state']}

DATA:
- Budget: {s['budget_per_capita']} vs {s['nat_budget']}
- Judges: {s['pop_per_lc_judge']} vs {s['nat_pop_lc']}
- Clearance: {s['lc_clearance_rate']} vs {s['nat_clearance']}
- Infra shortfall: {s['courthall_shortfall']}

Give:
1. One-line diagnosis
2. Causes
3. Fixes
4. Confidence
"""

# ── UI ─────────────────────────────
st.title("⚖️ CourtCompass AI")

with st.sidebar:
    api_key = st.text_input("Gemini API Key", type="password")

tab1, tab2, tab3 = st.tabs(["State", "National", "Trends"])

with tab1:
    states = sorted(df_main[df_main["state"] != "India"]["state"].tolist())
    state = st.selectbox("Select State", states)

    if st.button("Diagnose"):
        if not api_key:
            st.error("Add API key")
        else:
            s = diagnose_state(state, df_main, df_ftc)
            if s:
                prompt = build_prompt(s)
                result = generate_with_gemini(api_key, prompt)

                st.subheader("AI Diagnosis")
                st.write(result)
