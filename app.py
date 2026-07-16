import streamlit as st
import datetime
from dateutil.relativedelta import relativedelta

# --- APP CONFIGURATION ---
st.set_page_config(page_title="SubTrackr", page_icon="🚦", layout="centered")

# Custom CSS to make it look like a premium, dark-mode native mobile app
st.markdown("""
    <style>
        .block-container { padding-top: 1.5rem; max-width: 450px; }
        [data-testid="stMetricValue"] { font-size: 1.8rem !important; font-weight: 800; }
        .stButton button { width: 100%; border-radius: 12px; }
    </style>
""", unsafe_allow_html=True)

# --- IN-MEMORY DATABASE FAILSAFE ---
# Streamlit uses session_state to store data locally during the user's active browser session
if "subscriptions" not in st.session_state:
    st.session_state.subscriptions = []

# Exchange rates relative to USD base
RATES = {"USD": 1.0, "EUR": 0.92, "GBP": 0.78, "NGN": 1500.0}
SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "NGN": "₦"}

# --- UTILITY: PREDICTIVE DATE MATH ---
def calculate_next_renewal(day, month_idx, year, cycle):
    today = datetime.date.today()
    try:
        start_date = datetime.date(year, month_idx, day)
    except ValueError:
        # Handle end-of-month date overflows (e.g. Feb 31st defaults to Feb 28th)
        start_date = datetime.date(year, month_idx, 28)
        
    next_date = start_date

    # Increment date until it is equal to or in the future of today
    while next_date < today:
        if cycle == "Weekly":
            next_date += datetime.timedelta(weeks=1)
        elif cycle == "Bi-weekly":
            next_date += datetime.timedelta(weeks=2)
        elif cycle == "Monthly":
            next_date += relativedelta(months=1)
        elif cycle == "Quarterly":
            next_date += relativedelta(months=3)
        elif cycle == "Bi-annually":
            next_date += relativedelta(months=6)
        elif cycle == "Annual":
            next_date += relativedelta(years=1)
            
    return next_date

# --- HEADER & GLOBAL BASE CURRENCY ---
st.title("🚦 SubTrackr")
base_currency = st.selectbox("Global Base Currency", options=["USD", "EUR", "GBP", "NGN"])
symbol = SYMBOLS[base_currency]

# --- METRICS CALCULATOR ---
total_monthly_spend = 0.0
cash_7_days = 0.0
cash_30_days = 0.0
active_count = len(st.session_state.subscriptions)
today = datetime.date.today()

# Process metrics
processed_subs = []
for sub in st.session_state.subscriptions:
    renewal_date = calculate_next_renewal(sub["day"], sub["month_idx"], sub["year"], sub["cycle"])
    days_left = (renewal_date - today).days
    
    # Currency conversion
    cost_in_usd = sub["cost"] / RATES[sub["currency"]]
    cost_in_base = cost_in_usd * RATES[base_currency]
    
    # Normalize billing cycles to monthly cost
    cycle_factor = 1.0
    if sub["cycle"] == "Weekly": cycle_factor = 52 / 12
    elif sub["cycle"] == "Bi-weekly": cycle_factor = 26 / 12
    elif sub["cycle"] == "Quarterly": cycle_factor = 1 / 3
    elif sub["cycle"] == "Bi-annually": cycle_factor = 1 / 6
    elif sub["cycle"] == "Annual": cycle_factor = 1 / 12
    
    total_monthly_spend += (cost_in_base * cycle_factor)
    
    # Cash runways
    if days_left <= 7:
        cash_7_days += cost_in_base
    if days_left <= 30:
        cash_30_days += cost_in_base
        
    processed_subs.append({
        "id": sub["id"],
        "name": sub["name"],
        "cost_display": f"{symbol}{cost_in_base:.2f}",
        "raw_cost": f"{sub['cost']:.2f} {sub['currency']}",
        "renewal": renewal_date.strftime("%d-%b-%Y"),
        "days_left": days_left,
        "cycle": sub["cycle"]
    })

# --- UI: MAIN DASHBOARD SUMMARY ---
col1, col2 = st.columns(2)
col1.metric("Monthly Spend", f"{symbol}{total_monthly_spend:.2f}")
col2.metric("Active Subs", active_count)

col3, col4 = st.columns(2)
col3.metric("Next 7 Days", f"{symbol}{cash_7_days:.2f}")
col4.metric("Next 30 Days", f"{symbol}{cash_30_days:.2f}")

st.markdown("---")

# --- UI: SUBSCRIPTION CARDS LIST ---
st.subheader("My Subscriptions")
if not processed_subs:
    st.info("No active subscriptions. Tap the section below to add one!")
else:
    for sub in processed_subs:
        # Dynamic alert indicator logic based on cycle length
        limit_red, limit_orange = (2, 4) if sub["cycle"] in ["Weekly", "Bi-weekly"] else (5, 10) if sub["cycle"] in ["Monthly", "Quarterly"] else (14, 30)
        
        if sub["days_left"] <= limit_red:
            urgency_emoji = "🔴"
        elif sub["days_left"] <= limit_orange:
            urgency_emoji = "🟡"
        else:
            urgency_emoji = "🟢"
            
        with st.container():
            # Card Layout
            c_left, c_right = st.columns([3, 1])
            c_left.markdown(f"**{urgency_emoji} {sub['name']}** ` {sub['cycle']} `")
            c_left.caption(f"Due: {sub['renewal']} ({sub['days_left']}d left)")
            
            c_right.markdown(f"**{sub['cost_display']}**")
            c_right.caption(sub["raw_cost"])
            
            if c_right.button("🗑️", key=f"del_{sub['id']}"):
                st.session_state.subscriptions = [s for s in st.session_state.subscriptions if s["id"] != sub["id"]]
                st.rerun()
            st.markdown("<div style='border-bottom: 1px solid #334155; margin: 8px 0;'></div>", unsafe_allow_html=True)

# --- UI: ADD SUBSCRIPTION (COLLAPSIBLE DRAWER) ---
with st.expander("➕ Add New Subscription", expanded=False):
    with st.form("add_form", clear_on_submit=True):
        name = st.text_input("Subscription Name", placeholder="Netflix, Spotify")
        
        col_cost, col_curr = st.columns([2, 1])
        cost = col_cost.number_input("Cost", min_value=0.0, step=0.01)
        currency = col_curr.selectbox("Currency", options=["USD", "EUR", "GBP", "NGN"])
        
        cycle = st.selectbox("Billing Cycle", options=["Weekly", "Bi-weekly", "Monthly", "Quarterly", "Bi-annually", "Annual"], index=2)
        
        st.write("Start Date (Mobile Wheel Dropdowns)")
        col_d, col_m, col_y = st.columns(3)
        day = col_d.selectbox("Day", options=list(range(1, 32)), index=datetime.date.today().day - 1)
        month = col_m.selectbox("Month", options=["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], index=datetime.date.today().month - 1)
        year = col_y.selectbox("Year", options=list(range(2024, 2031)), index=2) # Default to 2026
        
        submitted = st.form_submit_button("Save Subscription")
        if submitted and name:
            month_idx = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"].indexOf(month) + 1 if hasattr(list, "indexOf") else ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"].index(month) + 1
            new_sub = {
                "id": datetime.datetime.now().timestamp(),
                "name": name,
                "cost": cost,
                "currency": currency,
                "cycle": cycle,
                "day": day,
                "month_idx": month_idx,
                "year": year
            }
            st.session_state.subscriptions.append(new_sub)
            st.success(f"{name} added successfully!")
            st.rerun()
