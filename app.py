import streamlit as st
import pandas as pd
from supabase import create_client, Client
from postgrest.exceptions import APIError
from datetime import datetime, date, timedelta

# ==============================================================================
# 1. INITIALIZE GLOBAL APP CONFIGURATIONS & SUPABASE
# ==============================================================================
st.set_page_config(page_title="SubTracker", page_icon="🔑", layout="centered")

try:
    URL: str = st.secrets["SUPABASE_URL"]
    KEY: str = st.secrets["SUPABASE_KEY"]
except KeyError:
    st.error("Missing credentials! Please add SUPABASE_URL and SUPABASE_KEY to your Streamlit secrets.")
    st.stop()

@st.cache_resource
def get_supabase() -> Client:
    return create_client(URL, KEY)

supabase = get_supabase()

# Live Production Redirect Target URL
REDIRECT_URL = "https://subtracker.streamlit.app/"  

# ==============================================================================
# 2. SEAMLESS SINGLE-TAB OAUTH HANDSHAKE
# ==============================================================================
query_params = st.query_params

if "code" in query_params:
    auth_code = query_params["code"]
    try:
        session = supabase.auth.exchange_code_for_session({"auth_code": auth_code})
        st.session_state.user = session.user
        st.query_params.clear()
        st.rerun()
    except Exception as e:
        st.error(f"Handshake failed: {e}")

def get_google_auth_url():
    response = supabase.auth.sign_in_with_oauth({
        "provider": "google",
        "options": {
            "redirect_to": REDIRECT_URL
        }
    })
    return response.url

def logout():
    supabase.auth.sign_out()
    if "user" in st.session_state:
        del st.session_state.user
    st.rerun()

if "user" not in st.session_state:
    try:
        current_session = supabase.auth.get_session()
        if current_session and current_session.user:
            st.session_state.user = current_session.user
    except Exception:
        pass

# ==============================================================================
# 3. HELPER FUNCTION: ZERO-DEPENDENCY RENEWAL CALCULATION
# ==============================================================================
def calculate_next_renewal(start_date: date, cycle: str) -> date:
    """Calculates next billing date using Python standard library only."""
    if cycle == "Weekly":
        return start_date + timedelta(days=7)
    elif cycle == "Yearly":
        try:
            return start_date.replace(year=start_date.year + 1)
        except ValueError:  # Leap year fallback (Feb 29 -> Feb 28)
            return start_date + timedelta(days=365)
    elif cycle == "Monthly":
        month = start_date.month % 12 + 1
        year = start_date.year + (start_date.month // 12)
        day = min(
            start_date.day,
            [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
        )
        return date(year, month, day)
    
    return start_date

# ==============================================================================
# 4. APP VIEW ROUTER
# ==============================================================================
if "user" not in st.session_state:
    st.title("Welcome to SubTracker 🔑")
    st.write("Please sign in with Google to safely track and manage your subscriptions.")

    try:
        auth_url = get_google_auth_url()
        st.link_button("⚡ Login with Google", auth_url, use_container_width=True)
    except Exception as e:
        st.error(f"Could not build Google Auth URL: {e}")

else:
    user = st.session_state.user
    
    st.sidebar.title("SubTracker Dashboard")
    st.sidebar.write(f"Logged in as: **{user.email}**")
    if st.sidebar.button("Log Out", use_container_width=True):
        logout()

    st.title("Your Subscription Tracker")
    st.write("Manage your running services and upcoming billings below.")

    # ──── 1. SUMMARY METRICS MODULE ────
    today = date.today()
    full_date_str = today.strftime("%A, %d %B %Y")  # e.g., Tuesday, 21 July 2026
    current_month_str = today.strftime("%B %Y")      # e.g., July 2026
    current_year_str = today.strftime("%Y")          # e.g., 2026

    # Fetch subscriptions to compute real-time totals
    total_month_cost = 0.0
    total_year_cost = 0.0
    
    try:
        response = supabase.table("subscriptions").select("*").eq("email", user.email).execute()
        subscriptions = response.data or []
        
        for item in subscriptions:
            raw_start = item.get("start_date") or item.get("created_at")
            if raw_start:
                try:
                    # Parse start date (supports YYYY-MM-DD)
                    s_date = datetime.strptime(str(raw_start)[:10], "%Y-%m-%d").date()
                    item_cost = float(item.get("cost", 0))

                    # Cumulative sum for current year
                    if s_date.year == today.year:
                        total_year_cost += item_cost
                        
                        # Cumulative sum for current month & year
                        if s_date.month == today.month:
                            total_month_cost += item_cost
                except Exception:
                    pass
    except Exception:
        subscriptions = []

    # Display Metrics Banner
    st.caption(f"📅 **Today:** {full_date_str}")
    col1, col2 = st.columns(2)
    with col1:
        st.metric(
            label=f"Total Cost ({current_month_str})", 
            value=f"{total_month_cost:,.2f}"
        )
    with col2:
        st.metric(
            label=f"Total Cost ({current_year_str} YTD)", 
            value=f"{total_year_cost:,.2f}"
        )

    st.write("---")

    # ──── 2. DATA DISPLAY MODULE (Active Subscriptions) ────
    st.subheader("Active Subscriptions")
    
    if subscriptions:
        formatted_data = []
        for idx, item in enumerate(subscriptions, start=1):
            formatted_data.append({
                "S/N": idx,
                "Subscription": item.get("name", "N/A"),
                "Cost": f"{float(item.get('cost', 0)):,.2f}",
                "Currency": item.get("currency", "N/A"),
                "Cycle": item.get("cycle", "N/A"),
                "Start Date": item.get("start_date", item.get("created_at", "N/A")),
                "Renewal Date": item.get("next_renewal", "N/A")
            })
        
        df = pd.DataFrame(formatted_data)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No active subscriptions logged yet. Add one using the form below!")

    st.write("---")

    # ──── 3. FORM MODULE (Add Subscriptions) ────
    st.subheader("Add New Subscription")
    with st.form("add_subscription_form", clear_on_submit=True):
        name = st.text_input("Service Name (e.g., Netflix, Spotify)")
        cost = st.number_input("Cost", min_value=0.0, step=0.01)
        currency = st.selectbox("Currency", ["USD ($)", "NGN (₦)", "EUR (€)", "GBP (£)"])
        cycle = st.selectbox("Billing Cycle", ["Monthly", "Yearly", "Weekly"])
        
        current_sub_date = st.date_input("Current / Last Payment Date", value=datetime.today())
        
        submit_button = st.form_submit_button("Save Subscription")
        
        if submit_button:
            if not name:
                st.error("Please enter a service name.")
            else:
                computed_next_renewal = calculate_next_renewal(current_sub_date, cycle)

                new_row = {
                    "email": user.email,
                    "name": name,
                    "cost": cost,
                    "currency": currency.split()[0],
                    "cycle": cycle,
                    "start_date": str(current_sub_date),
                    "next_renewal": str(computed_next_renewal)
                }
                
                try:
                    supabase.table("subscriptions").insert(new_row).execute()
                    st.success(f"Added {name}! Next renewal set for {computed_next_renewal.strftime('%Y-%m-%d')}.")
                    st.rerun()
                except APIError as e:
                    st.error("Database policy block or schema structural mismatch.")
                    st.json(e.__dict__) 
                except Exception as e:
                    st.exception(e)
