import streamlit as st
import pandas as pd
import requests
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
# 3. HELPER FUNCTIONS: DATES & LIVE EXCHANGE RATES
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

@st.cache_data(ttl=3600)  # Cache rates for 1 hour
def fetch_exchange_rates():
    """Fetches live USD-based conversion rates from open.er-api.com."""
    try:
        url = "https://open.er-api.com/v6/latest/USD"
        res = requests.get(url, timeout=5)
        data = res.json()
        if data.get("result") == "success":
            return data.get("rates", {})
    except Exception:
        pass
    # Fallback default static matrix in case network API is unreachable
    return {"USD": 1.0, "NGN": 1500.0, "EUR": 0.92, "GBP": 0.78}

def convert_currency(amount: float, from_curr: str, to_curr: str, rates: dict) -> float:
    """Converts amount from one currency to target currency using USD baseline rates."""
    if from_curr == to_curr or amount == 0:
        return amount
    
    # Strip symbolic wrappers if present (e.g. "USD ($)" -> "USD")
    clean_from = str(from_curr).split()[0]
    clean_to = str(to_curr).split()[0]
    
    rate_from = rates.get(clean_from, 1.0)
    rate_to = rates.get(clean_to, 1.0)
    
    # Convert source amount to USD, then from USD to target currency
    amount_in_usd = amount / rate_from
    return amount_in_usd * rate_to

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
    live_rates = fetch_exchange_rates()
    
    # Sidebar Module
    st.sidebar.title("SubTracker Settings")
    st.sidebar.write(f"Logged in as: **{user.email}**")
    
    # Default Currency Selection
    currency_options = ["USD ($)", "NGN (₦)", "EUR (€)", "GBP (£)"]
    default_currency = st.sidebar.selectbox("Default Preferred Currency", currency_options, index=0)
    target_currency_code = default_currency.split()[0]
    
    st.sidebar.write("---")
    if st.sidebar.button("Log Out", use_container_width=True):
        logout()

    st.title("Your Subscription Tracker")
    st.write("Manage your running services and upcoming billings below.")

    # ──── 1. SUMMARY METRICS MODULE ────
    today = date.today()
    full_date_str = today.strftime("%A, %d %B %Y")
    current_month_str = today.strftime("%B %Y")
    current_year_str = today.strftime("%Y")

    total_month_cost = 0.0
    total_year_cost = 0.0
    
    try:
        response = supabase.table("subscriptions").select("*").eq("email", user.email).execute()
        subscriptions = response.data or []
        
        for item in subscriptions:
            raw_start = item.get("start_date") or item.get("created_at")
            if raw_start:
                try:
                    s_date = datetime.strptime(str(raw_start)[:10], "%Y-%m-%d").date()
                    item_cost = float(item.get("cost", 0))
                    item_curr = item.get("currency", "USD")

                    # Convert original item cost to chosen user default currency
                    converted_item_cost = convert_currency(item_cost, item_curr, target_currency_code, live_rates)

                    if s_date.year == today.year:
                        total_year_cost += converted_item_cost
                        
                        if s_date.month == today.month:
                            total_month_cost += converted_item_cost
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
            value=f"{target_currency_code} {total_month_cost:,.2f}"
        )
    with col2:
        st.metric(
            label=f"Total Cost ({current_year_str} YTD)", 
            value=f"{target_currency_code} {total_year_cost:,.2f}"
        )

    st.write("---")

    # ──── 2. EDITABLE ACTIVE SUBSCRIPTIONS & ONE-CLICK ACTIONS ────
    st.subheader(f"Active Subscriptions (In {target_currency_code})")
    
    if subscriptions:
        # Construct DataFrame for st.data_editor
        table_rows = []
        for idx, item in enumerate(subscriptions, start=1):
            raw_cost = float(item.get('cost', 0))
            raw_curr = item.get("currency", "USD")
            
            # Compute live converted cost for reference
            converted_val = convert_currency(raw_cost, raw_curr, target_currency_code, live_rates)

            # Standardize start_date format
            s_date_str = str(item.get("start_date") or item.get("created_at") or today)[:10]

            table_rows.append({
                "id": item.get("id"),
                "S/N": idx,
                "Service Name": item.get("name", "N/A"),
                "Cost": raw_cost,
                "Currency": raw_curr,
                "Converted Cost": f"{target_currency_code} {converted_val:,.2f}",
                "Cycle": item.get("cycle", "Monthly"),
                "Start Date": s_date_str,
                "Renewal Date": item.get("next_renewal", "N/A")
            })
        
        df = pd.DataFrame(table_rows)

        # Render Interactive Table
        edited_df = st.data_editor(
            df,
            column_config={
                "id": None,  # Hide internal primary key column
                "S/N": st.column_config.NumberColumn("S/N", disabled=True, width="small"),
                "Service Name": st.column_config.TextColumn("Service Name", required=True),
                "Cost": st.column_config.NumberColumn("Cost", min_value=0.0, format="%.2f", required=True),
                "Currency": st.column_config.SelectboxColumn("Currency", options=["USD", "NGN", "EUR", "GBP"], required=True),
                "Converted Cost": st.column_config.TextColumn(f"Cost ({target_currency_code})", disabled=True),
                "Cycle": st.column_config.SelectboxColumn("Cycle", options=["Monthly", "Yearly", "Weekly"], required=True),
                "Start Date": st.column_config.TextColumn("Start Date", required=True),
                "Renewal Date": st.column_config.TextColumn("Renewal Date", disabled=True),
            },
            use_container_width=True,
            hide_index=True,
            key="subscriptions_editor"
        )

        # Save inline table edits button
        if st.button("💾 Save Table Changes", use_container_width=True):
            try:
                for idx, row in edited_df.iterrows():
                    # Recalculate next renewal based on edited start date and cycle
                    parsed_start = datetime.strptime(str(row["Start Date"])[:10], "%Y-%m-%d").date()
                    updated_next_renewal = calculate_next_renewal(parsed_start, row["Cycle"])

                    supabase.table("subscriptions").update({
                        "name": row["Service Name"],
                        "cost": float(row["Cost"]),
                        "currency": str(row["Currency"]).split()[0],
                        "cycle": row["Cycle"],
                        "start_date": str(parsed_start),
                        "next_renewal": str(updated_next_renewal)
                    }).eq("id", row["id"]).execute()

                st.success("Changes saved successfully!")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to update table records: {e}")

        # Quick Actions Drawer (One-Click Renew & Delete)
        with st.expander("⚡ Row Actions (Renew / Delete Subscription)"):
            sub_names = {row["id"]: f"{row['Service Name']} ({row['Currency']} {row['Cost']:,.2f})" for _, row in df.iterrows()}
            selected_sub_id = st.selectbox("Select Subscription", options=list(sub_names.keys()), format_func=lambda x: sub_names[x])

            act_col1, act_col2 = st.columns(2)
            
            # One-Click Renew
            with act_col1:
                if st.button("⚡ One-Click Renew", use_container_width=True):
                    sub_item = next((item for item in subscriptions if item["id"] == selected_sub_id), None)
                    if sub_item:
                        try:
                            # Use existing renewal date as the new start date
                            prev_renewal_str = sub_item.get("next_renewal") or str(today)
                            new_start = datetime.strptime(prev_renewal_str[:10], "%Y-%m-%d").date()
                            new_next_renewal = calculate_next_renewal(new_start, sub_item.get("cycle", "Monthly"))

                            supabase.table("subscriptions").update({
                                "start_date": str(new_start),
                                "next_renewal": str(new_next_renewal)
                            }).eq("id", selected_sub_id).execute()

                            st.success(f"Renewed {sub_item['name']}! Next renewal set for {new_next_renewal}.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Could not renew subscription: {e}")

            # Delete Subscription
            with act_col2:
                if st.button("🗑️ Delete Subscription", type="secondary", use_container_width=True):
                    try:
                        supabase.table("subscriptions").delete().eq("id", selected_sub_id).execute()
                        st.success("Subscription deleted!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to delete subscription: {e}")

    else:
        st.info("No active subscriptions logged yet. Add one using the form below!")

    st.write("---")

    # ──── 3. FORM MODULE (Add Subscriptions) ────
    st.subheader("Add New Subscription")
    with st.form("add_subscription_form", clear_on_submit=True):
        name = st.text_input("Service Name (e.g., Netflix, Spotify)")
        cost = st.number_input("Cost", min_value=0.0, step=0.01)
        currency = st.selectbox("Currency", currency_options)
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
