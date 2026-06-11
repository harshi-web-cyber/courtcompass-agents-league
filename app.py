import streamlit as st
import pandas as pd
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted
import plotly.express as px
import plotly.graph_objects as go
import time
import os
from io import StringIO

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="CourtCompass AI",
    page_icon="⚖️",
    layout="wide"
)

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
    df_main["courthall_shortfall"] = pd.to_numeric(
        df_main["courthall_shortfall"], errors="coerce"
    )

    df_ftc = df_ftc.rename(columns={
        "State/UT": "state",
        "Number of Fast Track Court": "ftc_count",
        "Number of Cases pending": "ftc_pending"
    })

    return df_main, df_hc, df_ftc, df_disp, df_tot, df_xlsx

df_main, df_hc, df_ftc, df_disp, df_tot, df_xlsx = load_data()

# ── Gemini setup ──────────────────────────────────────────────────────────────
def get_gemini_client(api_key):
    genai.configure(api_key=api_key)
    # gemini-1.5-flash has much higher free-tier RPM than gemini-2.0-flash
    return genai.GenerativeModel("gemini-1.5-flash")

# ── Retry wrapper ─────────────────────────────────────────────────────────────
def generate_with_retry(model, prompt, max_retries=3):
    """Call model.generate_content with exponential backoff on quota errors."""
    for attempt in range(max_retries):
        try:
            return model.generate_content(prompt)
        except ResourceExhausted:
            if attempt < max_retries - 1:
                wait_secs = 2 ** attempt * 5  # 5s → 10s → 20s
                st.toast(f"⏳ Rate limit hit — retrying in {wait_secs}s (attempt {attempt + 1}/{max_retries})...")
                time.sleep(wait_secs)
            else:
                raise  # re-raise after final attempt so the caller can handle it

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
        "courthall_shortfall": float(row["courthall_shortfall"]) if pd.notna(row["courthall_shortfall"]) else None,
        "nat_avg_shortfall": round(nat_shortfall, 1),
        "hc_clearance_rate": float(row["hc_clearance_rate"]),
        "lc_clearance_rate": float(row["lc_clearance_rate"]),
        "nat_avg_hc_clearance": round(nat_hc_clearance, 1),
        "nat_avg_lc_clearance": round(nat_lc_clearance, 1),
    }

    if not ftc_row.empty:
        signals["ftc_count"]   = int(ftc_row.iloc[0]["ftc_count"]) if pd.notna(ftc_row.iloc[0]["ftc_count"]) else 0
        signals["ftc_pending"] = int(ftc_row.iloc[0]["ftc_pending"]) if pd.notna(ftc_row.iloc[0]["ftc_pending"]) else 0
    else:
        signals["ftc_count"]   = 0
        signals["ftc_pending"] = 0

    signals["judge_shortage"]    = signals["pop_per_lc_judge"] > signals["nat_avg_pop_lc_judge"]
    signals["clearance_problem"] = signals["lc_clearance_rate"] < signals["nat_avg_lc_clearance"]
    signals["infra_shortage"]    = (signals["courthall_shortfall"] or 0) > signals["nat_avg_shortfall"]
    signals["underfunded"]       = signals["budget_per_capita"] < signals["nat_avg_budget"]

    return signals


def build_prompt(signals):
    return f"""You are CourtCompass AI, an expert judicial analytics reasoning agent for India.

You have been given structured data about the state of {signals['state']}. Your job is to:
1. Diagnose the TOP root causes of judicial backlog
2. Reason step-by-step through the evidence
3. Output a clear, actionable diagnosis

## Data for {signals['state']}:

JUDGE CAPACITY:
- Population per Lower Court Judge: {signals['pop_per_lc_judge']:,} (national avg: {signals['nat_avg_pop_lc_judge']:,})
- Population per High Court Judge: {signals['pop_per_hc_judge']:,} (national avg: {signals['nat_avg_pop_hc_judge']:,})
- Judge shortage flag: {'YES - above national average' if signals['judge_shortage'] else 'NO - within acceptable range'}

CASE CLEARANCE (efficiency proxy):
- Lower Court clearance rate: {signals['lc_clearance_rate']}% (national avg: {signals['nat_avg_lc_clearance']}%)
- High Court clearance rate: {signals['hc_clearance_rate']}% (national avg: {signals['nat_avg_hc_clearance']}%)
- Clearance problem flag: {'YES - below national average' if signals['clearance_problem'] else 'NO - performing adequately'}

INFRASTRUCTURE:
- Court hall shortfall: {signals['courthall_shortfall']}% (national avg: {signals['nat_avg_shortfall']}%)
- Infrastructure shortage flag: {'YES' if signals['infra_shortage'] else 'NO'}

BUDGET:
- Budget per capita on judiciary: Rs.{signals['budget_per_capita']} (national avg: Rs.{signals['nat_avg_budget']})
- Underfunded flag: {'YES - below national average' if signals['underfunded'] else 'NO'}

FAST TRACK COURTS:
- Number of Fast Track Courts: {signals['ftc_count']}
- Cases still pending in FTCs: {signals['ftc_pending']:,}

## Your task:
Reason through the data above and produce:

1. **One-line diagnosis** (the killer insight):
   Format: "Backlog in [State] is likely driven by [cause 1] combined with [cause 2]."

2. **Root Cause Analysis** (pick top 2-3 from: judge shortages, low clearance rates, infrastructure gaps, underfunding, adjournment patterns):
   For each cause: state the evidence from the data, explain why it contributes to backlog.

3. **Recommended Interventions** (2-3 specific, actionable suggestions)

4. **Confidence level**: High / Medium / Low

Be direct, data-backed, and concise. This is for policymakers and court administrators."""


# ── Cached diagnosis (prevents redundant API calls for same state) ─────────────
@st.cache_data(ttl=3600, show_spinner=False)
def run_diagnosis_cached(state_name, api_key, df_main_json, df_ftc_json):
    """
    Cache diagnosis results for 1 hour per (state, api_key) pair.
    DataFrames are passed as JSON strings so they are hashable by st.cache_data.
    """
    df_main_local = pd.read_json(StringIO(df_main_json))
    df_ftc_local  = pd.read_json(StringIO(df_ftc_json))

    signals = diagnose_state(state_name, df_main_local, df_ftc_local)
    if not signals:
        return None, None

    model    = get_gemini_client(api_key)
    prompt   = build_prompt(signals)
    response = generate_with_retry(model, prompt)
    return signals, response.text


def run_diagnosis(state_name, api_key, df_main, df_ftc):
    """Public entry point — serialises DataFrames and delegates to cached fn."""
    return run_diagnosis_cached(
        state_name,
        api_key,
        df_main.to_json(),
        df_ftc.to_json(),
    )


# ── UI ────────────────────────────────────────────────────────────────────────
st.title("⚖️ CourtCompass AI")
st.caption("Reasoning agent for judicial backlog diagnosis · Microsoft Agents League Hackathon 2026")

with st.sidebar:
    st.header("🔑 Configuration")
    api_key = st.text_input("Gemini API Key", type="password", placeholder="AIza...")
    st.divider()
    st.markdown("**📊 Datasets loaded:**")
    st.success(f"✅ State judiciary indicators — {len(df_main)-1} states")
    st.success(f"✅ High Court pendency — {len(df_hc)} courts")
    st.success(f"✅ Fast Track Courts — {len(df_ftc)-1} states")
    st.success(f"✅ HC disposal trends — {len(df_disp)} courts")
    st.success(f"✅ Institution vs disposal — {len(df_xlsx)} years")
    st.divider()
    total_pending = df_tot["Number of Cases pending"].sum()
    st.metric("Total pending cases in India", f"{total_pending/1e7:.2f} Cr")

tab1, tab2, tab3 = st.tabs(["🔍 Diagnose a State", "📊 National Overview", "📈 Trends"])

# ── Tab 1 ─────────────────────────────────────────────────────────────────────
with tab1:
    st.subheader("Ask CourtCompass")
    st.markdown("Select any Indian state to get a data-backed diagnosis of why pendency is high.")

    states = sorted(df_main[df_main["state"] != "India"]["state"].dropna().tolist())
    col1, col2 = st.columns([3, 1])
    with col1:
        selected_state = st.selectbox("Select a State/UT", states)
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        diagnose_btn = st.button("🧠 Diagnose", use_container_width=True)

    if diagnose_btn:
        if not api_key:
            st.error("Please enter your Gemini API key in the sidebar.")
        else:
            with st.spinner(f"Analysing {selected_state}..."):
                try:
                    signals, diagnosis = run_diagnosis(selected_state, api_key, df_main, df_ftc)
                except ResourceExhausted:
                    st.error(
                        "⚠️ **Gemini API quota exceeded.** "
                        "The free tier rate limit was hit even after retrying. "
                        "Please wait a minute and try again, or use a different API key."
                    )
                    st.stop()
                except Exception as e:
                    st.error(f"⚠️ An unexpected error occurred: {e}")
                    st.stop()

            if signals is None:
                st.error("State not found in dataset.")
            else:
                st.markdown("### 📋 Data Signals")
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Pop per LC Judge", f"{signals['pop_per_lc_judge']:,.0f}",
                          delta=f"Nat avg: {signals['nat_avg_pop_lc_judge']:,.0f}", delta_color="inverse")
                m2.metric("LC Clearance Rate", f"{signals['lc_clearance_rate']}%",
                          delta=f"Nat avg: {signals['nat_avg_lc_clearance']}%")
                m3.metric("Court Hall Shortfall", f"{signals['courthall_shortfall']}%",
                          delta=f"Nat avg: {signals['nat_avg_shortfall']}%", delta_color="inverse")
                m4.metric("Budget per Capita", f"Rs.{signals['budget_per_capita']}",
                          delta=f"Nat avg: Rs.{signals['nat_avg_budget']}")

                st.markdown("### 🚩 Root Cause Flags")
                f1, f2, f3, f4 = st.columns(4)
                f1.error("🔴 Judge Shortage") if signals["judge_shortage"] else f1.success("🟢 Judge Capacity OK")
                f2.error("🔴 Clearance Problem") if signals["clearance_problem"] else f2.success("🟢 Clearance OK")
                f3.error("🔴 Infra Shortage") if signals["infra_shortage"] else f3.success("🟢 Infra OK")
                f4.error("🔴 Underfunded") if signals["underfunded"] else f4.success("🟢 Budget OK")

                st.markdown("### 🧠 AI Diagnosis")
                st.markdown(diagnosis)

                if signals["ftc_count"] > 0:
                    st.info(f"ℹ️ {selected_state} has {signals['ftc_count']} Fast Track Courts with {signals['ftc_pending']:,} cases still pending.")

# ── Tab 2 ─────────────────────────────────────────────────────────────────────
with tab2:
    st.subheader("National Overview")
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Population per Lower Court Judge by State**")
        df_plot = df_main[df_main["state"] != "India"].sort_values("pop_per_lc_judge", ascending=True)
        fig = px.bar(df_plot.tail(15), x="pop_per_lc_judge", y="state", orientation="h",
                     color="pop_per_lc_judge", color_continuous_scale="Reds",
                     labels={"pop_per_lc_judge": "Population per Judge", "state": ""})
        fig.update_layout(showlegend=False, height=450, coloraxis_showscale=False)
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.markdown("**Lower Court Clearance Rate by State**")
        df_plot2 = df_main[df_main["state"] != "India"].sort_values("lc_clearance_rate", ascending=True)
        fig2 = px.bar(df_plot2.tail(15), x="lc_clearance_rate", y="state", orientation="h",
                      color="lc_clearance_rate", color_continuous_scale="RdYlGn",
                      labels={"lc_clearance_rate": "Clearance Rate (%)", "state": ""})
        fig2.add_vline(x=100, line_dash="dash", line_color="gray", annotation_text="100% line")
        fig2.update_layout(showlegend=False, height=450, coloraxis_showscale=False)
        st.plotly_chart(fig2, use_container_width=True)

    st.markdown("**Court Hall Shortfall % by State**")
    df_short = df_main[df_main["state"] != "India"][["state", "courthall_shortfall"]].dropna()
    fig3 = px.bar(df_short.sort_values("courthall_shortfall", ascending=False),
                  x="state", y="courthall_shortfall", color="courthall_shortfall",
                  color_continuous_scale="RdYlGn_r",
                  labels={"courthall_shortfall": "Shortfall (%)", "state": "State"})
    fig3.update_layout(height=350, coloraxis_showscale=False)
    st.plotly_chart(fig3, use_container_width=True)

# ── Tab 3 ─────────────────────────────────────────────────────────────────────
with tab3:
    st.subheader("Institution vs Disposal Trends (All India)")

    fig4 = go.Figure()
    fig4.add_trace(go.Scatter(x=df_xlsx["Years"], y=df_xlsx["Institution"],
                              name="Cases Filed", line=dict(color="#EF553B", width=2),
                              fill="tozeroy", fillcolor="rgba(239,85,59,0.1)"))
    fig4.add_trace(go.Scatter(x=df_xlsx["Years"], y=df_xlsx["Disposal"],
                              name="Cases Disposed", line=dict(color="#00CC96", width=2),
                              fill="tozeroy", fillcolor="rgba(0,204,150,0.1)"))
    fig4.update_layout(height=400, xaxis_title="Year", yaxis_title="Number of Cases",
                       hovermode="x unified",
                       legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    st.plotly_chart(fig4, use_container_width=True)
    st.caption("Gap between filed and disposed = growing backlog. Note the 2020 COVID dip in disposals.")

    st.markdown("**High Court Pendency (2022)**")
    df_hc_plot = df_hc[df_hc["Name of the High Court"] != "Total"].sort_values(
        "Pendency as on 31-12-2022", ascending=True)
    fig5 = px.bar(df_hc_plot, x="Pendency as on 31-12-2022", y="Name of the High Court",
                  orientation="h", color="Pendency as on 31-12-2022",
                  color_continuous_scale="Reds",
                  labels={"Pendency as on 31-12-2022": "Pending Cases", "Name of the High Court": ""})
    fig5.update_layout(height=500, coloraxis_showscale=False)
    st.plotly_chart(fig5, use_container_width=True)
