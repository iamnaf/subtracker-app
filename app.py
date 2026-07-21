import streamlit as st
from supabase import create_client, Client
import streamlit.components.v1 as components
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
# 2. POPUP WINDOW CALLBACK HANDLER (PKCE EXCHANGE INTERCEPTOR)
# ==============================================================================
query_params = st.query_params

# If this specific thread execution is running inside the temporary popup window
if "code" in query_params:
    auth_code = query_params["code"]
    try:
        # Exchange the single-use code for a full authenticated web session
        session = supabase.auth.exchange_code_for_session({"auth_code": auth_code})
        
        # Package tokens and broadcast them back out to the parent tab, then self-terminate
        js_callback = f"""
        <script>
            if (window.opener) {{
                window.opener.postMessage({{
                    type: "OAUTH_SUCCESS",
                    access_token: "{session.session.access_token}",
                    refresh_token: "{session.session.refresh_token}"
                }}, "*");
                window.close();
            }}
        </script>
        """
        components.html(js_callback, height=0, width=0)
        st.info("Authentication complete! Processing session...")
        st.stop()
    except Exception as e:
        st.error(f"Handshake interception failed: {e}")
        st.stop()

# ==============================================================================
# 3. PARENT APPLICATION EVENT LISTENER & PERSISTENCE
# ==============================================================================
# Injects a listener into the main tab to watch for messages arriving from the popup
js_listener = """
<script>
    window.addEventListener("message", function(event) {
        if (event.data && event.data.type === "OAUTH_SUCCESS") {
            // Log tokens to local state context
            localStorage.setItem("sb_access_token", event.data.access_token);
            localStorage.setItem("sb_refresh_token", event.data.refresh_token);
            
            // Inject reload param to break out of frame loops
            const url = new URL(window.location.href);
            url.searchParams.set("login_success", "true");
            window.location.href = url.toString();
        }
    });
</script>
"""
components.html(js_listener, height=0, width=0)

# Catch the reload event param, clean the address bar, and update interface state
if "login_success" in query_params:
    st.query_params.clear()
    st.invalidate_pages()
    st.rerun()

# Auth Helpers
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

# Check for existing background active sessions
if "user" not in st.session_state:
    try:
        current_session = supabase.auth.get_session()
        if current_session and current_session.user:
            st.session_state.user = current_session.user
    except Exception:
        pass

# ==============================================================================
# 4. APP VIEW ROUTER
# ==============================================================================
if "user" not in st.session_state:
    # ──────────────────────────────────────────────────────────────────────────
    # ACCESS GATEKEEPER LAYER
    # ──────────────────────────────────────────────────────────────────────────
    st.title("Welcome to SubTracker 🔑")
    st.write("Please sign in with Google to safely track and manage your subscriptions.")

    # HTML Engine launching Google OAuth inside an isolated, dimensioned modal layout
    auth_url = get_google_auth_url()
    popup_launcher_html = f"""
    <button onclick="openLoginPopup()" style="
        background-color: #4285F4;
        color: white;
        border: none;
        padding: 12px 24px;
        font-size: 16px;
        border-radius: 6px;
        cursor: pointer;
        font-weight: bold;
        display: inline-flex;
        align-items: center;
        box-shadow: 0 2px 4px rgba(0,0,0,0.2);
    ">⚡ Login with Google</button>

    <script>
        function openLoginPopup() {{
            const width = 520;
            const height = 650;
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
    components.html(popup_launcher_html, height=70)

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

    # ──── Form block: Add Subscriptions ────
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
                    "user_id": user.id,  # Link the record to the active authenticated profile
                    "name": name,
                    "cost": cost,
                    "billing_date": str(billing_date)
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

    # ──── Visualization block: Data Display ────
    st.write("---")
    st.subheader("Active Subscriptions")
    
    try:
        # Pull records passing through RLS filtering layers (auth.uid() = user_id)
        response = supabase.table("subscriptions").select("*").execute()
        subscriptions = response.data
        
        if subscriptions:
            st.dataframe(subscriptions, use_container_width=True)
        else:
            st.info("No active subscriptions logged yet. Add one above!")
    except Exception as e:
        st.warning("Could not pull data. Verify active SELECT schema rules.")
