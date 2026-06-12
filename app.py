import streamlit as st
import pandas as pd
import google.generativeai as genai

# ── PAGE ─────────────────────────────
st.set_page_config(page_title="CourtCompass AI", page_icon="⚖️", layout="wide")

# ── DATA ─────────────────────────────
@st.cache_data
def load_data():
    df_main = pd.read_csv("data/Pendency of Court Cases in India.csv")

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

    return df_main

df_main = load_data()

# ── GEMINI ───────────────────────────
def setup_gemini(api_key):
    genai.configure(api_key=api_key)
    return genai.GenerativeModel("models/gemini-1.5-flash-latest")


def generate(model, prompt):
    try:
        res = model.generate_content(prompt)
        return res.text
    except Exception as e:
        return f"ERROR: {str(e)}"


# ── ANALYSIS ─────────────────────────
def analyze(state):
    row = df_main[df_main["state"].str.lower() == state.lower()]
    if row.empty:
        return None

    row = row.iloc[0]

    nat_lc = df_main["lc_clearance_rate"].mean()
    nat_pop = df_main["pop_per_lc_judge"].mean()
    nat_budget = df_main["budget_per_capita"].mean()

    return {
        "state": state,
        "lc_clearance_rate": float(row["lc_clearance_rate"]),
        "pop_per_lc_judge": float(row["pop_per_lc_judge"]),
        "budget_per_capita": float(row["budget_per_capita"]),
        "courthall_shortfall": float(row["courthall_shortfall"] or 0),
        "nat_lc": round(nat_lc, 2),
        "nat_pop": round(nat_pop, 0),
        "nat_budget": round(nat_budget, 0),
    }


# ── PROMPT ───────────────────────────
def build_prompt(s):
    return f"""
You are CourtCompass AI (judicial analytics agent).

STATE: {s['state']}

DATA:
- Clearance rate: {s['lc_clearance_rate']} vs national {s['nat_lc']}
- Judge load: {s['pop_per_lc_judge']} vs national {s['nat_pop']}
- Budget: {s['budget_per_capita']} vs national {s['nat_budget']}
- Infra gap: {s['courthall_shortfall']}

TASK:
1. One-line diagnosis
2. Top 2 causes with evidence
3. 2 solutions
4. Confidence level
"""


# ── UI ───────────────────────────────
st.title("⚖️ CourtCompass AI")

api_key = st.sidebar.text_input("Gemini API Key", type="password")

states = sorted(df_main["state"].dropna().unique())
state = st.selectbox("Select State", states)

if st.button("Diagnose"):
    if not api_key:
        st.error("Enter API key")
    else:
        model = setup_gemini(api_key)
        data = analyze(state)

        if data is None:
            st.error("State not found")
        else:
            prompt = build_prompt(data)
            result = generate(model, prompt)

            st.subheader("AI Diagnosis")
            st.write(result)
