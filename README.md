# ⚖️ CourtCompass AI

> **Microsoft Agents League Hackathon 2026 · Reasoning Agents Track**

An AI-powered reasoning agent that diagnoses the root causes of judicial backlog in Indian courts — and recommends targeted interventions.

---

## 🧠 What it does

CourtCompass doesn't just show you a dashboard. It **reasons** through multiple data signals to produce a diagnosis like:

> *"Backlog in Uttar Pradesh is likely driven by a severe judge shortage (93,021 population per lower court judge vs national avg 71,224) combined with a low case clearance rate of 72%, well below the national average of 89%."*

### The 3 root causes it checks:
1. **Judge & staff shortages** — population per judge vs national average
2. **Low clearance rates** — cases disposed vs cases filed
3. **Infrastructure gaps** — court hall shortfall %, budget per capita

---

## 📊 Datasets

| File | What it contains |
|------|-----------------|
| `Pendency_of_Court_Cases_in_India.csv` | State-wise judge ratios, clearance rates, infrastructure, budget |
| `RS_Session_259_AU_119_1.csv` | High Court pendency 2022 |
| `RS_Session_254_AU_419_A.csv` | Fast Track Courts by state |
| `RS_Session_256_AU_4038_4.csv` | High Court disposal trends 2017–2021 |
| `RS_Session_256_AU_3321_A_to_D.csv` | Total pendency snapshot |
| `Report__4_.xlsx` | All-India institution vs disposal 2018–2026 |

---

## 🏗️ Architecture

```
Judicial Datasets (CSV/XLSX)
        ↓
Data Layer (Pandas — cleaning, merging, signal extraction)
        ↓
Reasoning Layer (Google Gemini 1.5 Flash / Azure AI Foundry*)
        ↓
Streamlit UI (diagnosis + visualizations)
        ↓
Deployed on Streamlit Cloud
```

*Azure AI Foundry is the intended production deployment target.

---

## 🚀 Run locally

```bash
git clone https://github.com/harshi-web-cyber/courtcompass
cd courtcompass
pip install -r requirements.txt
streamlit run app.py
```

Add your Gemini API key in the sidebar when the app opens.

---

## 🛠️ Tech Stack

- Python · Pandas · Streamlit · Plotly
- Google Gemini 1.5 Flash (LLM reasoning layer)
- GitHub

---

## 🏆 Hackathon

**Microsoft Agents League Hackathon 2026**
Track: Reasoning Agents
Built by: Shri Harshidaa · Avinashilingam Institute, Coimbatore

---

## ⚠️ Disclaimer

CourtCompass is for analytical and educational purposes only. It does not provide legal advice or predict judicial outcomes.
