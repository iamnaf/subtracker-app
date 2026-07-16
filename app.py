import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import re

# Set page config
st.set_page_config(page_title="SubTrackr", page_icon="📱", layout="centered")

# --- INITIALIZE SUPABASE CONNECTION ---
# This safely handles our database queries via streamlit secrets
conn = st.connection("supabase", type=SupabaseConnection)

# --- SMTP EMAIL HELPER ---
def send_notification_email(recipient_email, sub_name, days_left, cost, currency):
    try:
        sender_email = st.secrets["SENDER_EMAIL"]
        sender_password = st.secrets["SENDER_PASSWORD"]
        smtp_server = st.secrets["SMTP_SERVER"]
        smtp_port = st.secrets["SMTP_PORT"]

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"⏰ Subscription Alert: {sub_name} is renewing soon!"
        msg["From"] = f"SubTrackr <{sender_email}>"
        msg["To"] = recipient_email

        html = f"""
        <html>
          <body style="font-family: Arial, sans-serif; background-color: #f4f4f5; padding: 20px;">
            <div style="max-width: 500px; margin: 0 auto; background: #ffffff; padding: 30px; border-radius: 12px; border: 1px solid #e4e4e7;">
              <h2 style="color: #10b981; margin-top: 0;">SubTrackr Reminder</h2>
              <p>Hello,</p>
              <p>This is a quick reminder that your subscription for <strong>{sub_name}</strong> is renewing in <strong>{days_left} days</strong>.</p>
              <div style="background-color: #f4f4f5; padding: 15px; border-radius: 8px; margin: 20px 0;">
                <p style="margin: 5px 0;"><strong>Subscription:</strong> {sub_name}</p>
                <p style="margin: 5px 0;"><strong>Cost:</strong> {cost} {currency}</p>
              </div>
              <p style="font-size: 13px; color: #71717a;">Make sure to review this subscription before the renewal date!</p>
              <hr style="border: none; border-top: 1px solid #e4e4e7; margin: 20px 0;" />
              <p style="font-size: 11px; color: #a1a1aa; text-align: center;">Sent automatically by your SubTrackr App.</p>
            </div>
          </body>
        </html>
        """
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, recipient_email, msg.as_string())
        return True
    except Exception as e:
        st.error(f"Email system is not fully configured yet in Streamlit Secrets. (Error: {e})")
        return False

def is_valid_email(email):
    pattern = r'^[\w\.-]+@[\w\.-]+\.\w+$'
    return re.match(pattern, email) is not None

# --- INITIALIZE USER SESSION ---
if "user_email" not in st.session_state:
    st.session_state.user_email = None

# --- LOGIN SCREEN ---
if st.session_state.user_email is None:
    st.title("SubTrackr 📱")
    st.write("Track your subscriptions and sync across devices simply using your email address.")
    
    tab1, tab2 = st.tabs(["Log In", "Sign Up"])
    
    with tab1:
        login_email = st.text_input("Enter your Email Address", key="login_email_input").lower().strip()
        if st.button("Log In"):
            if is_valid_email(login_email):
                st.session_state.user_email = login_email
                st.rerun()
            else:
                st.error("Please enter a valid email address.")
                
    with tab2:
        signup_email = st.text_input("Enter your Email Address", key="signup_email_input").lower().strip()
        if st.button("Create Account"):
            if is_valid_email(signup_email):
                st.session_state.user_email = signup_email
                st.success("Account created successfully!")
                st.rerun()
            else:
                st.error("Please enter a valid email address.")
                
    st.stop()

# --- ACTIVE SESSION ---
user_email = st.session_state.user_email

with st.sidebar:
    st.write(f"Logged in as:")
    st.info(user_email)
    if st.button("Log Out"):
        st.session_state.user_email = None
        st.rerun()

st.title("My Subscriptions 📱")

# --- FETCH USER DATA FROM SUPABASE ---
# We query the 'subscriptions' table filtering by the logged-in email
response = conn.table("subscriptions").select("id, name, cost, currency, cycle, next_renewal").eq("email", user_email).execute()

# Convert returned data to a pandas DataFrame
if response.data:
    user_df = pd.DataFrame(response.data)
else:
    user_df = pd.DataFrame(columns=["id", "name", "cost", "currency", "cycle", "next_renewal"])

# --- EXPIRATION ALERTS ENGINE ---
if not user_df.empty:
    user_df["next_renewal"] = pd.to_datetime(user_df["next_renewal"]).dt.date
    today = datetime.date.today()
    
    imminent_alerts = []
    for idx, row in user_df.iterrows():
        days_left = (row["next_renewal"] - today).days
        if 0 < days_left <= 3:
            imminent_alerts.append((row["name"], days_left, row["cost"], row["currency"]))
            
    if imminent_alerts:
        st.warning("⚠️ You have upcoming renewals!")
        for name, days, cost, currency in imminent_alerts:
            st.write(f"• **{name}** is renewing in **{days} days**.")
            
            # Simple session-level email sending guard
            email_key = f"sent_{name}_{user_email}_{today}"
            if email_key not in st.session_state:
                sent = send_notification_email(user_email, name, days, cost, currency)
                if sent:
                    st.session_state[email_key] = True
                    st.success(f"Notification email sent to {user_email}!")

    # Display clean table (hide 'id')
    st.dataframe(user_df.drop(columns=["id"]), use_container_width=True)
else:
    st.info("You haven't added any subscriptions yet! Add one below.")

# --- ADD NEW SUBSCRIPTION FORM ---
with st.form("add_sub_form", clear_on_submit=True):
    st.write("### Add New Subscription")
    name = st.text_input("Subscription Name")
    cost = st.number_input("Cost", min_value=0.0, step=0.01)
    currency = st.selectbox("Currency", ["USD", "EUR", "GBP", "NGN"])
    cycle = st.selectbox("Billing Cycle", ["Weekly", "Monthly", "Annual"])
    next_renewal = st.date_input("Next Renewal Date", min_value=datetime.date.today())
    
    submit = st.form_submit_button("Save Subscription")
    
    if submit:
        if name and cost > 0:
            # Prepare payload for Supabase insert
            new_row = {
                "email": user_email,
                "name": name,
                "cost": cost,
                "currency": currency,
                "cycle": cycle,
                "next_renewal": next_renewal.strftime("%Y-%m-%d")
            }
            
            # Execute insert query
            conn.table("subscriptions").insert(new_row).execute()
            
            st.success(f"Added {name} successfully!")
            st.rerun()
        else:
            st.error("Please enter a valid name and cost.")
