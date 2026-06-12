import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import time
import google.generativeai as genai
from io import StringIO

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="CourtCompass AI", page_icon="⚖️", layout="wide")

# ── Load data ─────────────────────────────────────────────────────────────────
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

# ── GEMINI CONFIG ─────────────────────────────────────────────────────────────
def generate_with_gemini(api_key, prompt):
    genai.configure(api_key=api_key)

    model = genai.GenerativeModel("gemini-1.5-flash")

    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        raise RuntimeError(f"Gemini failed: {e}")

# ── Reasoning engine ──────────────────────────────────────────────────────────
def diagnose_state(state_name, df_main, df_ftc):
    state_row = df_main[df_main["state"].str.lower() == state_name.lower()]
    ftc_row   = df_ftc[df_ftc["state"].str.lower() == state_name.lower()]

    if state_row.empty:
        return None

    row = state_row.iloc[0]

    nat_lc_clearance = df_main[df_main["state"] != "India"]["lc_clearance_rate"].mean()
    nat_hc_clearance = df_main[df_main["state"] != "India"]["hc_clearance_rate"].mean()
    nat_pop_lc_judge = df_main[df_main["state"] != "India"]["pop_per_lc_judge"].mean()
    nat_pop_hc_judge = df_main[df_main["state"] != "India"]["pop_per_hc_judge"].mean()
    nat_shortfall    = df_main[df_main["state"] != "India"]["courthall_shortfall"].mean()
    nat_budget       = df_main[df_main["state"] != "India"]["budget_per_capita"].mean()

    signals = {
        "state": row["state"],
        "budget_per_capita": float(row["budget_per_capita"]),
        "nat_avg_budget": round(nat_budget, 1),
        "pop_per_hc_judge": float(row["pop_per_hc_judge"]),
        "nat_avg_pop_hc_judge": round(nat_pop_hc_judge),
        "pop_per_lc_judge": float(row["pop_per_lc_judge"]),
        "nat_avg_pop_lc_judge": round(nat_pop_lc_judge),
        "courthall_shortfall": float(row["courthall_shortfall"]) if pd.notna(row["courthall_shortfall"]) else 0,
        "nat_avg_shortfall": round(nat_shortfall, 1),
        "hc_clearance_rate": float(row["hc_clearance_rate"]),
        "lc_clearance_rate": float(row["lc_clearance_rate"]),
        "nat_avg_hc_clearance": round(nat_hc_clearance, 1),
        "nat_avg_lc_clearance": round(nat_lc_clearance, 1),
    }

    if not ftc_row.empty:
        signals["ftc_count"] = int(ftc_row.iloc[0]["ftc_count"]) if pd.notna(ftc_row.iloc[0]["ftc_count"]) else 0
        signals["ftc_pending"] = int(ftc_row.iloc[0]["ftc_pending"]) if pd.notna(ftc_row.iloc[0]["ftc_pending"]) else 0
    else:
        signals["ftc_count"] = 0
        signals["ftc_pending"] = 0

    signals["judge_shortage"] = signals["pop_per_lc_judge"] > signals["nat_avg_pop_lc_judge"]
    signals["clearance_problem"] = signals["lc_clearance_rate"] < signals["nat_avg_lc_clearance"]
    signals["infra_shortage"] = signals["courthall_shortfall"] > signals["nat_avg_shortfall"]
    signals["underfunded"] = signals["budget_per_capita"] < signals["nat_avg_budget"]

    return signals

# ── Prompt ─────────────────────────────────────────────────────────────────────
def build_prompt(signals):
    return f"""
You are CourtCompass AI.

State: {signals['state']}

DATA:
- Judge capacity: {signals['pop_per_lc_judge']} vs avg {signals['nat_avg_pop_lc_judge']}
- Clearance: {signals['lc_clearance_rate']} vs avg {signals['nat_avg_lc_clearance']}
- Infra shortfall: {signals['courthall_shortfall']}
- Budget: {signals['budget_per_capita']}

TASK:
1. One-line diagnosis
2. Top 2–3 causes with evidence
3. 2–3 interventions
4. Confidence level
"""

# ── UI ────────────────────────────────────────────────────────────────────────
st.title("⚖️ CourtCompass AI")

with st.sidebar:
    api_key = st.text_input("Gemini API Key", type="password", placeholder="AIza...")

tab1, tab2, tab3 = st.tabs(["State", "National", "Trends"])

with tab1:
    states = sorted(df_main[df_main["state"] != "India"]["state"].tolist())
    state = st.selectbox("State", states)

    if st.button("Diagnose"):
        if not api_key:
            st.error("Enter Gemini API key")
        else:
            signals = diagnose_state(state, df_main, df_ftc)

            if signals:
                prompt = build_prompt(signals)
                result = generate_with_gemini(api_key, prompt)

                st.subheader("Diagnosis")
                st.write(result)
