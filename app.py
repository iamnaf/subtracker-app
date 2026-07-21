import streamlit as st
from supabase import create_client, Client
from postgrest.exceptions import APIError

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

# When returning from Google, exchange the URL 'code' for a valid Supabase user session
if "code" in query_params:
    auth_code = query_params["code"]
    try:
        session = supabase.auth.exchange_code_for_session({"auth_code": auth_code})
        st.session_state.user = session.user
        # Clean the temporary code out of the browser URL bar
        st.query_params.clear()
        st.rerun()
    except Exception as e:
        st.error(f"Handshake failed: {e}")

# Helper: Generate Google OAuth Link
def get_google_auth_url():
    response = supabase.auth.sign_in_with_oauth({
        "provider": "google",
        "options": {
            "redirect_to": REDIRECT_URL
        }
    })
    return response.url

# Helper: Logout
def logout():
    supabase.auth.sign_out()
    if "user" in st.session_state:
        del st.session_state.user
    st.rerun()

# Check for existing background active session
if "user" not in st.session_state:
    try:
        current_session = supabase.auth.get_session()
        if current_session and current_session.user:
            st.session_state.user = current_session.user
    except Exception:
        pass

# ==============================================================================
# 3. APP VIEW ROUTER
# ==============================================================================
if "user" not in st.session_state:
    # ──────────────────────────────────────────────────────────────────────────
    # ACCESS GATEKEEPER LAYER
    # ──────────────────────────────────────────────────────────────────────────
    st.title("Welcome to SubTracker 🔑")
    st.write("Please sign in with Google to safely track and manage your subscriptions.")

    # Native Streamlit Link Button for standard full-tab redirect
    try:
        auth_url = get_google_auth_url()
        st.link_button("⚡ Login with Google", auth_url, use_container_width=True)
    except Exception as e:
        st.error(f"Could not build Google Auth URL: {e}")

else:
    # ──────────────────────────────────────────────────────────────────────────
    # AUTHENTICATED CORE DASHBOARD
    # ──────────────────────────────────────────────────────────────────────────
    user = st.session_state.user
    
    # Persistent Sidebar Module
    st.sidebar.title("SubTracker Dashboard")
    st.sidebar.write(f"Logged in as: **{user.email}**")
    if st.sidebar.button("Log Out", use_container_width=True):
        logout()

    st.title("Your Subscription Tracker")
    st.write("Manage your running services and upcoming billings below.")

    # ──── 1. TOP MODULE: Data Display (Active Subscriptions) ────
    st.subheader("Active Subscriptions")
    
    try:
        # Filter subscriptions strictly belonging to the logged-in user's email
        response = supabase.table("subscriptions").select("*").eq("email", user.email).execute()
        subscriptions = response.data
        
        if subscriptions:
            st.dataframe(subscriptions, use_container_width=True)
        else:
            st.info("No active subscriptions logged yet. Add one using the form below!")
    except Exception as e:
        st.warning("Could not pull data. Verify active SELECT schema rules.")

    st.write("---")

    # ──── 2. BOTTOM MODULE: Form block (Add Subscriptions) ────
    st.subheader("Add New Subscription")
    with st.form("add_subscription_form", clear_on_submit=True):
        name = st.text_input("Service Name (e.g., Netflix, Spotify)")
        cost = st.number_input("Cost", min_value=0.0, step=0.01)
        currency = st.selectbox("Currency", ["USD ($)", "NGN (₦)", "EUR (€)", "GBP (£)"])
        cycle = st.selectbox("Billing Cycle", ["Monthly", "Yearly", "Weekly"])
        next_renewal = st.date_input("Next Renewal Date")
        
        submit_button = st.form_submit_button("Save Subscription")
        
        if submit_button:
            if not name:
                st.error("Please enter a service name.")
            else:
                new_row = {
                    "email": user.email,
                    "name": name,
                    "cost": cost,
                    "currency": currency.split()[0],
                    "cycle": cycle,
                    "next_renewal": str(next_renewal)
                }
                
                try:
                    supabase.table("subscriptions").insert(new_row).execute()
                    st.success(f"Added {name} successfully!")
                    st.rerun()
                except APIError as e:
                    st.error("Database policy block or schema structural mismatch.")
                    st.json(e.__dict__) 
                except Exception as e:
                    st.exception(e)
