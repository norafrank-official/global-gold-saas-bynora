# global-gold-saas-bynora


A brutalist, terminal-inspired fintech web application designed for real-time global precious metal analytics, predictive machine learning, and secure portfolio management.

![System Status](https://img.shields.io/badge/System-Online-00ff41?style=for-the-badge&logoColor=black)
![Python](https://img.shields.io/badge/Python-3.9+-black?style=for-the-badge&logo=python&logoColor=00ff41)
![Streamlit](https://img.shields.io/badge/Streamlit-Framework-black?style=for-the-badge&logo=streamlit&logoColor=00ff41)
![Supabase](https://img.shields.io/badge/Supabase-Cloud_DB-black?style=for-the-badge&logo=supabase&logoColor=00ff41)

## 📡 System Overview
The Asset Command Center is a full-stack SaaS application that breaks away from traditional, cluttered financial dashboards. It provides users with a distraction-free, highly secure terminal interface to track live XAU (Gold) markets, forecast short-term trends using machine learning, and securely manage personal assets in the cloud.

## ⚡ Core Architecture & Features
* **Live Market Telemetry:** Integrates with `GoldAPI.io` to fetch real-time 24K spot rates. Automatically calculates regional purities (e.g., 22K / 91.6%).
* **Geo-IP Tax Routing:** Automatically detects the user's country via IP tracing and applies the correct local tax laws (e.g., India's 3% GST vs. Saudi Arabia's 15% VAT).
* **Predictive ML Engine:** Utilizes `scikit-learn` (Linear Regression) to analyze 30-day trailing data and project 24-hour bullish/bearish market trends.
* **Encrypted Cloud Vaults:** Leverages **Supabase** (PostgreSQL) for secure, multi-tenant user authentication and portfolio database management.
* **Automated PDF Reporting:** Uses `fpdf2` to generate downloadable, terminal-styled financial procurement quotations on the fly.

## 🛠️ Technology Stack
* **Frontend/Framework:** Streamlit (Python)
* **Backend/Database:** Supabase (PostgreSQL, Auth)
* **Machine Learning:** Scikit-Learn, NumPy
* **Data Visualization:** Plotly Graph Objects
* **External APIs:** GoldAPI.io, IP-API

## 🚀 Local Deployment Protocol

### 1. Clone the Repository
```bash
git clone [https://github.com/norafrank-offcial/gold-saas-bynora.git](https://github.com/your-norafrank-offical/gold-saas-bynora.git)
cd gold-saas-bynora
