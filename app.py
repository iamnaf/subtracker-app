import streamlit as st
from supabase import create_client, Client

# Page configuration MUST be first
st.set_page_config(page_title="SubTracker", page_icon="🔑", layout="centered")

# ==============================================================================
# 1. INITIALIZE SUPABASE CLIENT
# ==============================================================================
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

# Automatically discover if the app is running locally or live on Streamlit Cloud
# This saves you from having to manually swap URLs back and forth!
if st.runtime.exists():
    # Fallback to local dev port if headers aren't fully resolved yet
    REDIRECT_URL = "http://localhost:8501"
else:
    REDIRECT_URL = "https://subtracker.streamlit.app/" # 💡 Change to your real Streamlit Cloud URL!

# ==============================================================================
# 2. SEAMLESS OAUTH CALLBACK CHECK
# ==============================================================================
# Look at the browser URL bar. If '?code=...' exists, exchange it immediately for a login session.
query_params = st.query_params

if "code" in query_params:
    auth_code = query_params["code"]
    try:
        session = supabase.auth.exchange_code_for_session({"auth_code": auth_code})
        st.session_state.user = session.user
        # Wipe the clean code from URL so refreshing the app doesn't trigger errors
        st.query_params.clear()
        st.rerun()
    except Exception as e:
        st.error(f"Failed to complete secure authentication handshake: {e}")

# Helper: Logout Cleanup
def logout():
    supabase.auth.sign_out()
    if "user" in st.session_state:
        del st.session_state.user
    st.rerun()

# ==============================================================================
# 3. ROUTER / UI RENDER
# ==============================================================================
# Double-check if a valid session is already active in memory
if "user" not in st.session_state:
    try:
        current_session = supabase.auth.get_session()
        if current_session and current_session.user:
            st.session_state.user = current_session.user
    except Exception:
        pass

# GATEKEEPER MODE: Render Login Button
if "user" not in st.session_state:
    st.title("Welcome to SubTracker 🔑")
    st.write("Please sign in with your Google account to safely track and manage your subscriptions.")
    
    # Generate direct authentication link targeting our dynamic REDIRECT_URL
    try:
        response = supabase.auth.sign_in_with_oauth({
            "provider": "google",
            "options": {
                "redirect_to": REDIRECT_URL
            }
        })
        # Standard link button that transitions smoothly in the same tab
        st.link_button("⚡ Login with Google", response.url, use_container_width=True)
    except Exception as e:
        st.error(f"Could not build Google Auth URL: {e}")

# DASHBOARD MODE: Authenticated Workspace
else:
    user = st.session_state.user
    
    st.sidebar.title("SubTracker Dashboard")
    st.sidebar.write(f"Logged in as: **{user.email}**")
    if st.sidebar.button("Log Out"):
        logout()

    st.title("Your Subscription Tracker")
    st.write("Manage your running services and upcoming billings below.")

    # ---- Add Subscription Form ----
    st.subheader("Add New Subscription")
    with st.form("add_subscription_form", clear_on_submit=True):
        name = st.text_input("Service Name (e.g., Netflix, Spotify)")
        cost = st.number_input("Monthly Cost ($)", min_value=0.0, step=0.01)
        billing_date = st.date_input("Next Billing Date")
        
        submit_button = st.form_submit_button("Save Subscription")
        
        if submit_button:
            if not name:
                st.error("Please enter a service name.")
            else:
                new_row = {
                    "user_id": user.id,
                    "name": name,
                    "cost": cost,
                    "billing_date": str(billing_date)
                }
                try:
                    supabase.table("subscriptions").insert(new_row).execute()
                    st.success(f"Added {name} successfully!")
                    st.rerun()
                except Exception as e:
                    st.error("Database policy error or schema mismatch.")
                    st.exception(e)

    # ---- View Active Subscriptions ----
    st.write("---")
    st.subheader("Active Subscriptions")
    try:
        subscriptions_response = supabase.table("subscriptions").select("*").execute()
        subscriptions = subscriptions_response.data
        if subscriptions:
            st.dataframe(subscriptions, use_container_width=True)
        else:
            st.info("No active subscriptions logged yet. Add one above!")
    except Exception as e:
        st.warning("Could not fetch subscriptions. Verify SELECT RLS policies.")
