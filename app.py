import streamlit as st
from supabase import create_client, Client
from postgrest.exceptions import APIError

# ==============================================================================
# 1. INITIALIZE SUPABASE CLIENT
# ==============================================================================
# Ensure SUPABASE_URL and SUPABASE_KEY are defined at the root level of secrets
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

# Define where Google should send users back after authenticating.
# Change this to your production URL when deploying (e.g., "https://your-app.streamlit.app")
REDIRECT_URL = "http://localhost:8501" 

# ==============================================================================
# 2. HANDLE OAUTH CALLBACK (PKCE FLOW)
# ==============================================================================
# If Google redirects back with a code parameter, exchange it for a session
query_params = st.query_params

if "code" in query_params:
    auth_code = query_params["code"]
    try:
        session = supabase.auth.exchange_code_for_session({"auth_code": auth_code})
        st.session_state.user = session.user
        # Clear the code from the URL bar to keep things clean
        st.query_params.clear() 
        st.rerun()
    except Exception as e:
        st.error(f"Authentication failed: {e}")

# Auth Helper Functions
def login_with_google():
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

# ==============================================================================
# 3. APP UI ROUTER
# ==============================================================================
if "user" not in st.session_state:
    # ──────────────────────────────────────────────────────────────────────────
    # GATEKEEPER: LOGIN SCREEN
    # ──────────────────────────────────────────────────────────────────────────
    st.title("Welcome to SubTracker 🔑")
    st.write("Please sign in with Google to safely track and manage your subscriptions.")
    
    # Generate the authorization URL and present the login button
    google_login_url = login_with_google()
    st.link_button("⚡ Login with Google", google_login_url)

else:
    # ──────────────────────────────────────────────────────────────────────────
    # MAIN APP: AUTHENTICATED ZONE
    # ──────────────────────────────────────────────────────────────────────────
    user = st.session_state.user
    
    # Sidebar Navigation / Logout
    st.sidebar.title("SubTracker Dashboard")
    st.sidebar.write(f"Logged in as: **{user.email}**")
    if st.sidebar.button("Log Out"):
        logout()

    st.title("Your Subscription Tracker")
    st.write("Manage your running services and upcoming billings below.")

    # ──── Form to Add a New Subscription ────
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
                # Structure row explicitly, linking it to the logged-in user's UUID
                new_row = {
                    "user_id": user.id,          # Automatically captured from active Google session
                    "name": name,
                    "cost": cost,
                    "billing_date": str(billing_date)
                }
                
                # Execute Insert Query with debug block for quick RLS/Schema isolation
                try:
                    supabase.table("subscriptions").insert(new_row).execute()
                    st.success(f"Added {name} successfully!")
                    st.rerun()
                except APIError as e:
                    st.error("Database policy error or schema mismatch encountered.")
                    # Keep this active while verifying your RLS settings match the user.id link!
                    st.json(e.__dict__) 
                except Exception as e:
                    st.exception(e)

    # ──── View Existing Subscriptions ────
    st.write("---")
    st.subheader("Active Subscriptions")
    
    try:
        # Fetching data dynamically based on your RLS rule (auth.uid() = user_id)
        response = supabase.table("subscriptions").select("*").execute()
        subscriptions = response.data
        
        if subscriptions:
            st.dataframe(subscriptions, use_container_width=True)
        else:
            st.info("No active subscriptions logged yet. Add one above!")
            
    except Exception as e:
        st.warning("Could not fetch active subscriptions list. Verify your SELECT RLS policies.")
