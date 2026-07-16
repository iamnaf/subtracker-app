import streamlit as st
from supabase import create_client, Client
import streamlit.components.v1 as components
from postgrest.exceptions import APIError

# Set Page Config FIRST
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

# Dynamic Redirect URL configuration (Detects if live or local)
# Set your production URL here when deploying (e.g., "https://your-app.streamlit.app")
REDIRECT_URL = "https://subtracker.streamlit.app/"  

# ==============================================================================
# 2. THE POPUP CALLBACK HANDLER (The magic sauce)
# ==============================================================================
query_params = st.query_params

# If this instance of the app is the popup window receiving the redirect "code"
if "code" in query_params:
    auth_code = query_params["code"]
    try:
        # Exchange the code for a session
        session = supabase.auth.exchange_code_for_session({"auth_code": auth_code})
        
        # Inject JavaScript to save the session tokens into parent window's localStorage,
        # notify the parent window, and close this popup.
        js_callback = f"""
        <script>
            if (window.opener) {{
                // Pass tokens back to the main application tab
                window.opener.postMessage({{
                    type: "OAUTH_SUCCESS",
                    access_token: "{session.session.access_token}",
                    refresh_token: "{session.session.refresh_token}"
                }}, "*");
                // Close the popup window
                window.close();
            }}
        </script>
        """
        components.html(js_callback, height=0, width=0)
        st.write("Authenticating... You can close this window if it doesn't close automatically.")
        st.stop()
    except Exception as e:
        st.error(f"Popup auth exchange failed: {e}")
        st.stop()

# ==============================================================================
# 3. PARENT WINDOW EVENT LISTENER & SESSION RESTORE
# ==============================================================================
# 1. Listen for the message from the closing popup
js_listener = """
<script>
    window.addEventListener("message", function(event) {
        if (event.data && event.data.type === "OAUTH_SUCCESS") {
            // Store details in localStorage to persist on reload
            localStorage.setItem("sb_access_token", event.data.access_token);
            localStorage.setItem("sb_refresh_token", event.data.refresh_token);
            
            # Create a hidden query parameter to trigger a streamlit rerun
            const url = new URL(window.location.href);
            url.searchParams.set("login_success", "true");
            window.location.href = url.toString();
        }
    });
</script>
"""
components.html(js_listener, height=0, width=0)

# 2. Check if we just received a login success redirect
if "login_success" in query_params:
    st.query_params.clear()
    st.rerun()

# 3. Helper: Auth URL Builder
def get_google_auth_url():
    response = supabase.auth.sign_in_with_oauth({
        "provider": "google",
        "options": {
            "redirect_to": REDIRECT_URL
        }
    })
    return response.url

# Helper: Logout Cleanup
def logout():
    supabase.auth.sign_out()
    if "user" in st.session_state:
        del st.session_state.user
    st.rerun()

# ==============================================================================
# 4. ROUTER / VIEW RENDERER
# ==============================================================================
if "user" not in st.session_state:
    # Attempt to check if Supabase Client can silently retrieve the active session
    try:
        current_session = supabase.auth.get_session()
        if current_session:
            st.session_state.user = current_session.user
            st.rerun()
    except Exception:
        pass

# If still not logged in, render the login page
if "user" not in st.session_state:
    st.title("Welcome to SubTracker 🔑")
    st.write("Please sign in to safely track and manage your subscriptions.")

    # Javascript launcher that opens Google OAuth in a clean 500x600 popup window
    auth_url = get_google_auth_url()
    popup_launcher_html = f"""
    <button onclick="openLoginPopup()" style="
        background-color: #4285F4;
        color: white;
        border: none;
        padding: 10px 20px;
        font-size: 16px;
        border-radius: 4px;
        cursor: pointer;
        font-weight: bold;
    ">⚡ Login with Google</button>

    <script>
        function openLoginPopup() {{
            const width = 500;
            const height = 600;
            const left = (screen.width - width) / 2;
            const top = (screen.height - height) / 2;
            
            window.open(
                "{auth_url}",
                "GoogleLoginPopup",
                `width=${{width}},height=${{height}},top=${{top}},left=${{left}},resizable=yes,scrollbars=yes,status=yes`
            );
        }}
    </script>
    """
    components.html(popup_launcher_html, height=60)

else:
    # ──────────────────────────────────────────────────────────────────────────
    # AUTHENTICATED AREA: TRACKER APP
    # ──────────────────────────────────────────────────────────────────────────
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
                except APIError as e:
                    st.error("Database policy error or schema mismatch.")
                    st.json(e.__dict__) 
                except Exception as e:
                    st.exception(e)

    # ---- View Active Subscriptions ----
    st.write("---")
    st.subheader("Active Subscriptions")
    try:
        response = supabase.table("subscriptions").select("*").execute()
        subscriptions = response.data
        if subscriptions:
            st.dataframe(subscriptions, use_container_width=True)
        else:
            st.info("No active subscriptions logged yet. Add one above!")
    except Exception as e:
        st.warning("Could not fetch subscriptions. Verify SELECT RLS policies.")
