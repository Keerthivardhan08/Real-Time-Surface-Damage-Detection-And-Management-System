import streamlit as st
import pandas as pd
import sqlite3
import random
import math
import os
import smtplib

from datetime import datetime
from email.mime.text import MIMEText
from fpdf import FPDF

import folium
from folium.plugins import HeatMap

from streamlit_folium import st_folium
from ultralytics import YOLO
from PIL import Image
from streamlit_js_eval import get_geolocation
from geopy.geocoders import Nominatim

# ==================================================
# CONFIG & SESSION STATE
# ==================================================

st.set_page_config(
    page_title="ROAD DAMAGE DETECTION & MAINTENANCE SYSTEM",
    layout="wide"
)

# --- CHANGED: Added images folder creation ---
os.makedirs("reports", exist_ok=True)
os.makedirs("images", exist_ok=True)
# ---------------------------------------------

SENDER_EMAIL = "pvsnkeerthivardhan08@gmail.com"
APP_PASSWORD = "your_app_password"
AUTHORITY_EMAIL = "pvsnkeerthivardhan43@gmail.com"

# Initialize Session State for Authentication
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
    st.session_state["username"] = ""
    st.session_state["role"] = ""

# ==================================================
# LOAD MODEL
# ==================================================

@st.cache_resource
def load_model():
    try:
        model = YOLO("finalv4.pt")
        return model
    except Exception as e:
        st.error(f"Model Error: {e}")
        return None

model = load_model()

# ==================================================
# DATABASE
# ==================================================

def init_db():
    conn = sqlite3.connect("municipal_operationsv4.db", check_same_thread=False)
    c = conn.cursor()

    # Tickets Table
    c.execute("""
    CREATE TABLE IF NOT EXISTS tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id TEXT UNIQUE,
        email TEXT,
        date TEXT,
        lat REAL,
        lon REAL,
        zone TEXT,
        potholes INTEGER,
        transverse INTEGER,
        longitudinal INTEGER,
        alligator INTEGER,
        pci INTEGER,
        condition TEXT,
        priority TEXT,
        action TEXT,
        status TEXT,
        contractor TEXT,
        deadline TEXT,
        user_feedback TEXT
    )
    """)

    # Users Table for Auth
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        role TEXT
    )
    """)

    # Insert default users if table is empty
    users_count = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if users_count == 0:
        default_users = [
            ("admin", "admin123", "Admin"),
            ("Team Alpha", "alpha123", "Contractor"),
            ("Team Bravo", "bravo123", "Contractor"),
            ("Team Charlie", "charlie123", "Contractor")
        ]
        c.executemany("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", default_users)

    conn.commit()
    return conn, c

conn, c = init_db()

# ==================================================
# DUPLICATE DETECTION
# ==================================================

def is_duplicate(lat, lon):
    rows = c.execute("""
        SELECT ticket_id, lat, lon
        FROM tickets
        WHERE status != 'Resolved'
    """).fetchall()

    for row in rows:
        existing_ticket = row[0]
        old_lat = row[1]
        old_lon = row[2]

        distance = math.sqrt((lat - old_lat) ** 2 + (lon - old_lon) ** 2) * 111000

        if distance < 50:
            return True, existing_ticket
    return False, None

# ==================================================
# SEVERITY ENGINE
# ==================================================

def get_severity(confidence):
    if confidence >= 0.50: return "High"
    elif confidence >= 0.30: return "Medium"
    return "Low"

# ==================================================
# MAINTENANCE RECOMMENDATION ENGINE
# ==================================================

def recommend_maintenance(counts):
    if counts["alligator"] > 0:
        return ("Full Depth Reconstruction", "Priority 1", "Critical Structural Failure")
    elif counts["potholes"] >= 3:
        return ("Full Depth Patching", "Priority 2", "Multiple Potholes Detected")
    elif counts["potholes"] > 0:
        return ("Pothole Repair", "Priority 3", "Localized Damage")
    elif counts["transverse"] > 2:
        return ("Crack Sealing", "Priority 4", "Thermal Cracking")
    elif counts["longitudinal"] > 2:
        return ("Joint Sealing", "Priority 5", "Linear Cracking")
    
    return ("Routine Monitoring", "Priority 6", "Road Condition Acceptable")

# ==================================================
# ADVANCED PCI ENGINE
# ==================================================

def calculate_engineering_metrics(counts, severity_counts):
    pci = 100 - (
        counts['longitudinal'] * 5 +
        counts['transverse'] * 8 +
        counts['potholes'] * 18 +
        counts['alligator'] * 30
    )
    pci = max(0, pci)

    if pci >= 85: condition = "Excellent"
    elif pci >= 70: condition = "Good"
    elif pci >= 55: condition = "Fair"
    elif pci >= 40: condition = "Poor"
    elif pci >= 20: condition = "Very Poor"
    else: condition = "Failed"

    dispatch_required = "No"

    # OVERRIDE RULES
    if counts["alligator"] >= 1:
        priority = "Critical"
        action = "Immediate Structural Rehabilitation Required"
        dispatch_required = "Yes"
        repair_rank = "Priority 1"
        repair_reason = "Critical Structural Failure"
    elif counts["potholes"] >= 1:
        priority = "High"
        action = "Immediate Pothole Repair Required"
        dispatch_required = "Yes"
        repair_rank = "Priority 2"
        repair_reason = "Potholes Detected"
    else:
        if pci < 40:
            priority = "High"
            action = "Major Rehabilitation Required"
            repair_rank = "Priority 3"
            repair_reason = "Low PCI Score"
        elif pci < 60:
            priority = "Medium"
            action = "Preventive Maintenance Required"
            repair_rank = "Priority 4"
            repair_reason = "Moderate Degradation"
        else:
            priority = "Low"
            action = "Routine Monitoring"
            repair_rank = "Priority 6"
            repair_reason = "Condition Acceptable"

    return (pci, condition, priority, action, repair_rank, repair_reason)

# ==================================================
# EMAIL SYSTEM
# ==================================================

def send_email(to_email, subject, body):
    if not to_email: return
    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(SENDER_EMAIL, APP_PASSWORD)
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = SENDER_EMAIL
        msg["To"] = to_email
        server.sendmail(SENDER_EMAIL, to_email, msg.as_string())
        server.quit()
    except Exception as e:
        print(e)

# ==================================================
# PDF REPORT
# ==================================================

def generate_ticket_pdf(ticket_id, pci, condition, priority, repair):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=14)
    pdf.cell(200, 10, txt="Municipal Infrastructure Report", ln=True)
    pdf.ln(10)
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt=f"Ticket ID : {ticket_id}", ln=True)
    pdf.cell(200, 10, txt=f"PCI : {pci}", ln=True)
    pdf.cell(200, 10, txt=f"Condition : {condition}", ln=True)
    pdf.cell(200, 10, txt=f"Priority : {priority}", ln=True)
    pdf.multi_cell(0, 10, txt=f"Recommended Repair : {repair}")
    file_path = f"reports/{ticket_id}.pdf"
    pdf.output(file_path)
    return file_path

# ==================================================
# AUTHENTICATION UI
# ==================================================

if not st.session_state["logged_in"]:
    st.title("Municipal Infrastructure AI Access")
    
    tab_login, tab_register = st.tabs(["Login", "Citizen Registration"])

    with tab_login:
        l_user = st.text_input("Username")
        l_pass = st.text_input("Password", type="password")
        
        if st.button("Secure Login"):
            user_data = c.execute("SELECT role FROM users WHERE username=? AND password=?", (l_user, l_pass)).fetchone()
            if user_data:
                st.session_state["logged_in"] = True
                st.session_state["username"] = l_user
                st.session_state["role"] = user_data[0]
                st.rerun()
            else:
                st.error("Invalid credentials. Please try again.")

    with tab_register:
        r_user = st.text_input("Choose Username", key="reg_user")
        r_pass = st.text_input("Choose Password", type="password", key="reg_pass")
        
        if st.button("Register as Citizen"):
            if r_user and r_pass:
                try:
                    c.execute("INSERT INTO users (username, password, role) VALUES (?, ?, 'Citizen')", (r_user, r_pass))
                    conn.commit()
                    st.success("Registration successful! You may now log in.")
                except sqlite3.IntegrityError:
                    st.error("Username already exists. Choose another.")
            else:
                st.warning("Please provide a username and password.")

# ==================================================
# MAIN APPLICATION LOGIC (Requires Login)
# ==================================================
else:
    # Sidebar logout & identity
    st.sidebar.title("System Access")
    st.sidebar.write(f"**Logged in as:** {st.session_state['username']}")
    st.sidebar.write(f"**Role:** {st.session_state['role']}")
    
    if st.sidebar.button("Logout"):
        st.session_state["logged_in"] = False
        st.session_state["username"] = ""
        st.session_state["role"] = ""
        st.rerun()

    app_mode = st.session_state["role"]

    # ==================================================
    # CITIZEN PORTAL
    # ==================================================
    if app_mode == "Citizen":
        st.title("Road Damage Reporting System")
        col1, col2 = st.columns(2)

        with col1:
            img_file = st.file_uploader("Upload Road Image", type=["jpg", "jpeg", "png"])
            cam_file = st.camera_input("Capture Road Image")

        with col2:
            email_in = st.text_input("Email Address")
            zone_in = st.selectbox("Municipal Zone", ["North", "South", "East", "West", "Central"])

        lat_in = 12.9716
        lon_in = 77.5946

        st.subheader("Location")
        location_mode = st.radio("Location Method", ["GPS", "Landmark", "Pin on Map"])

        if location_mode == "GPS":
            loc = get_geolocation()
            if loc and "coords" in loc:
                lat_in = loc["coords"]["latitude"]
                lon_in = loc["coords"]["longitude"]
                st.success(f"GPS Locked: {lat_in:.5f}, {lon_in:.5f}")

        elif location_mode == "Landmark":
            landmark = st.text_input("Enter Landmark")
            if landmark:
                try:
                    geolocator = Nominatim(user_agent="municipal_ai")
                    location = geolocator.geocode(landmark)
                    if location:
                        lat_in = location.latitude
                        lon_in = location.longitude
                        st.success(location.address)
                except:
                    pass

        elif location_mode == "Pin on Map":
            st.info("Click on the map to mark the road damage location.")
            pin_map = folium.Map(location=[lat_in, lon_in], zoom_start=12)
            map_data = st_folium(pin_map, width=700, height=400, key="road_damage_pin")

            if map_data and map_data.get("last_clicked"):
                lat_in = map_data["last_clicked"]["lat"]
                lon_in = map_data["last_clicked"]["lng"]
            st.success(f"Location Selected: {lat_in:.6f}, {lon_in:.6f}")

        if st.button("Analyze & Generate Ticket"):
            img_source = cam_file if cam_file else img_file

            if img_source is None:
                st.error("Upload an image first.")
            elif model is None:
                st.error("Model not loaded.")
            else:
                img = Image.open(img_source)
                img.save("temp.jpg")
                results = model("temp.jpg")

                counts = {"potholes": 0, "transverse": 0, "longitudinal": 0, "alligator": 0}
                severity_counts = {
                    "pothole_high": 0, "pothole_medium": 0, "pothole_low": 0,
                    "transverse_high": 0, "transverse_medium": 0, "transverse_low": 0,
                    "longitudinal_high": 0, "longitudinal_medium": 0, "longitudinal_low": 0,
                    "alligator_high": 0, "alligator_medium": 0, "alligator_low": 0
                }

                for box in results[0].boxes:
                    conf = float(box.conf[0])
                    if conf < 0.20: continue

                    cls_id = int(box.cls[0])
                    label = model.names[cls_id].lower()
                    severity = get_severity(conf)

                    if "pothole" in label:
                        counts["potholes"] += 1
                        severity_counts[f"pothole_{severity.lower()}"] += 1
                    elif "transverse" in label:
                        counts["transverse"] += 1
                        severity_counts[f"transverse_{severity.lower()}"] += 1
                    elif "longitudinal" in label:
                        counts["longitudinal"] += 1
                        severity_counts[f"longitudinal_{severity.lower()}"] += 1
                    elif "alligator" in label or "aligator" in label:
                        counts["alligator"] += 1
                        severity_counts[f"alligator_{severity.lower()}"] += 1

                pci, condition, priority, repair, repair_rank, repair_reason = calculate_engineering_metrics(counts, severity_counts)

                duplicate, existing = is_duplicate(lat_in, lon_in)
                if duplicate:
                    st.warning(f"Possible Duplicate Complaint Found: {existing}")

                # --- CHANGED: ID generation and Image Saving logic moved here ---
                ticket_id = "TKT" + str(random.randint(10000, 99999))
                
                # Extract the AI-drawn image from YOLO (BGR format) and convert to RGB
                res_image = results[0].plot()
                annotated_image = Image.fromarray(res_image[..., ::-1])
                
                # Save it permanently in the images folder using the Ticket ID
                img_path = f"images/{ticket_id}.jpg"
                annotated_image.save(img_path)
                # ----------------------------------------------------------------

                c.execute("""
                    INSERT INTO tickets
                    (ticket_id, email, date, lat, lon, zone, potholes, transverse, longitudinal, alligator, pci, condition, priority, action, status)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (ticket_id, email_in, datetime.now().strftime("%d-%m-%Y"), lat_in, lon_in, zone_in, counts["potholes"], counts["transverse"], counts["longitudinal"], counts["alligator"], pci, condition, priority, repair, "Pending Review"))
                conn.commit()

                pdf_file = generate_ticket_pdf(ticket_id, pci, condition, priority, repair)
                
                # --- ADDED: Send "Complaint Received" Email to Citizen ---
                if email_in:
                   subject = f"Complaint Received: {ticket_id}"
                   body = f"Hello,\n\nWe have successfully received your road damage report. Your ticket ID is {ticket_id}.\n\nOur AI system has analyzed the image and assigned an initial Pavement Condition Index (PCI) of {pci}. The priority is currently marked as {priority}.\n\nYou will receive another email as soon as an Admin assigns this ticket to a contractor for repair.\n\nThank you for helping improve municipal infrastructure!"
        
                   send_email(email_in, subject, body)
                # ---------------------------------------------------------

                st.success(f"Ticket Generated: {ticket_id}")
                st.image(annotated_image) # Display the RGB converted image directly

                st.metric("PCI Score", pci)
                st.write(f"Condition : {condition}")
                st.write(f"Priority : {priority}")
                st.write(f"Repair : {repair}")
                st.write(f"Reason : {repair_reason}")

                with open(pdf_file, "rb") as file:
                    st.download_button("Download Report", data=file, file_name=f"{ticket_id}.pdf")

        st.divider()
        st.header("Citizen Services")
        service_tab1, service_tab2 = st.tabs(["Track Complaint", "AI Feedback"])

        with service_tab1:
            track_id = st.text_input("Enter Ticket ID")
            if st.button("Track Status"):
                result = pd.read_sql(f"SELECT ticket_id, zone, pci, condition, priority, status, contractor, deadline FROM tickets WHERE ticket_id='{track_id}'", conn)
                if not result.empty:
                    st.dataframe(result, use_container_width=True)
                else:
                    st.warning("Ticket Not Found")

        with service_tab2:
            feedback_ticket = st.text_input("Ticket ID")
            feedback_text = st.text_area("AI Misclassification Feedback")
            if st.button("Submit Feedback"):
                exists = c.execute("SELECT ticket_id FROM tickets WHERE ticket_id=?", (feedback_ticket,)).fetchone()
                if exists:
                    c.execute("UPDATE tickets SET user_feedback=? WHERE ticket_id=?", (feedback_text, feedback_ticket))
                    conn.commit()
                    st.success("Feedback Submitted")
                else:
                    st.error("Ticket Not Found")

    # ==================================================
    # ADMIN DASHBOARD
    # ==================================================
    elif app_mode == "Admin":
        st.title("Municipal Operations Dashboard")

        df = pd.read_sql("SELECT * FROM tickets", conn)
        if df.empty:
            st.info("No complaints available.")
        else:
            st.subheader("System Overview")
            col1, col2, col3, col4 = st.columns(4)
            with col1: st.metric("Total Complaints", len(df))
            with col2: st.metric("Average PCI", round(df["pci"].mean(), 2))
            with col3: st.metric("Critical Roads", len(df[df["priority"] == "Critical"]))
            with col4: st.metric("Resolved", len(df[df["status"] == "Resolved"]))

            st.divider()

            # GIS Map
            st.subheader("Road Defect GIS Map")
            center_lat, center_lon = df.iloc[-1]["lat"], df.iloc[-1]["lon"]
            m = folium.Map(location=[center_lat, center_lon], zoom_start=12)

            for _, row in df.iterrows():
                color = "red" if row["priority"] == "Critical" else "orange" if row["priority"] == "High" else "green"
                popup_text = f"Ticket: {row['ticket_id']}<br>PCI: {row['pci']}<br>Status: {row['status']}<br>Zone: {row['zone']}"
                folium.CircleMarker(location=[row["lat"], row["lon"]], radius=8, color=color, fill=True, fill_color=color, popup=popup_text).add_to(m)

            st_folium(m, width=1200, height=500)
            st.divider()

            # Heatmap
            st.subheader("Road Damage Heatmap")
            heatmap = folium.Map(location=[center_lat, center_lon], zoom_start=12)
            heat_data = [[row["lat"], row["lon"]] for _, row in df.iterrows()]
            HeatMap(heat_data, radius=20, blur=15).add_to(heatmap)
            st_folium(heatmap, width=1200, height=500, key="heatmap")
            st.divider()

            # Analytics
            st.subheader("Zone Analytics")
            zone_summary = df.groupby("zone").agg(complaints=("ticket_id", "count"), avg_pci=("pci", "mean")).reset_index()
            st.dataframe(zone_summary, use_container_width=True)

            # Assign Orders
            st.subheader("Assign Contractor")
            assign_ticket = st.selectbox("Ticket", df["ticket_id"], key="assign_ticket")
            contractor = st.selectbox("Contractor", ["Team Alpha", "Team Bravo", "Team Charlie"])
            deadline = st.date_input("Deadline")

            if st.button("Assign Work Order"):
                # 1. Update the database
                 c.execute("UPDATE tickets SET contractor=?, deadline=?, status='Assigned' WHERE ticket_id=?", (contractor, deadline.strftime("%Y-%m-%d"), assign_ticket))
                 conn.commit()
    
                 # 2. Fetch the citizen's email for this specific ticket
                 citizen_email = c.execute("SELECT email FROM tickets WHERE ticket_id=?", (assign_ticket,)).fetchone()
    
                 # 3. Send the email if an address exists
                 if citizen_email and citizen_email[0]:
                    subject = f"Update on Your Road Complaint: {assign_ticket}"
                    body = f"Hello,\n\nYour complaint ({assign_ticket}) has been reviewed by the Municipal Admin. It has been assigned to {contractor} for repair.\n\nThe estimated completion deadline is {deadline.strftime('%Y-%m-%d')}.\n\nThank you for helping keep our roads safe!"
        
                    send_email(citizen_email[0], subject, body)

                 # 4. Notify the admin and refresh
                 st.success("Work Order Assigned & Citizen Notified")
                 st.rerun()

            st.subheader("All Complaints")
            st.dataframe(df, use_container_width=True)

            # --- CHANGED: Added Evidence Inspection Logic ---
            st.divider()
            st.subheader("Inspect AI Output & Engineering Reports")
            
            # Select a ticket from the dataframe
            inspect_ticket = st.selectbox("Select Ticket to View Evidence", df["ticket_id"])
            
            col_img, col_pdf = st.columns(2)
            
            with col_img:
                img_path = f"images/{inspect_ticket}.jpg"
                if os.path.exists(img_path):
                    st.image(img_path, caption=f"AI Analysis for {inspect_ticket}", use_container_width=True)
                else:
                    st.warning("Image no longer available on server.")
            
            with col_pdf:
                pdf_path = f"reports/{inspect_ticket}.pdf"
                if os.path.exists(pdf_path):
                    with open(pdf_path, "rb") as file:
                        st.download_button(
                            label="Download Engineering Report (PDF)", 
                            data=file, 
                            file_name=f"{inspect_ticket}.pdf", 
                            key=f"admin_pdf_{inspect_ticket}"
                        )
            # ------------------------------------------------

    # ==================================================
    # CONTRACTOR PORTAL
    # ==================================================
    elif app_mode == "Contractor":
        st.title(f"{st.session_state['username']} Operations Portal")

        # Query includes lat and lon for the map
        contractor_df = pd.read_sql(f"""
            SELECT ticket_id, zone, action, deadline, status, lat, lon
            FROM tickets
            WHERE contractor='{st.session_state['username']}'
        """, conn)

        st.subheader("Assigned Work Orders")
        # Displaying df without coordinates to avoid visual clutter
        st.dataframe(contractor_df.drop(columns=['lat', 'lon'], errors='ignore'), use_container_width=True)

        st.divider()
        st.subheader("Work Order Location Map")

        if not contractor_df.empty:
            map_center_lat = contractor_df.iloc[0]["lat"]
            map_center_lon = contractor_df.iloc[0]["lon"]

            contractor_map = folium.Map(location=[map_center_lat, map_center_lon], zoom_start=12)

            for _, row in contractor_df.iterrows():
                marker_color = "green" if row["status"] == "Resolved" else "red"
                folium.Marker(
                    location=[row["lat"], row["lon"]],
                    popup=f"Ticket: {row['ticket_id']} | Status: {row['status']} | Deadline: {row['deadline']}",
                    icon=folium.Icon(color=marker_color)
                ).add_to(contractor_map)

            st_folium(contractor_map, width=1200, height=450, key="contractor_map")
        else:
            st.info("No mapped locations to display.")

        st.divider()

        st.subheader("Close Work Order")
        pending_tasks = contractor_df[contractor_df["status"] != "Resolved"]

        if not pending_tasks.empty:
            selected_task = st.selectbox("Select Ticket", pending_tasks["ticket_id"])
            
            # --- CHANGED: Show the AI image to the contractor ---
            img_path = f"images/{selected_task}.jpg"
            if os.path.exists(img_path):
                st.image(img_path, caption=f"Damage Location for {selected_task}", width=500)
            else:
                st.info("Reference image not available.")
            # ----------------------------------------------------

            repair_photo = st.file_uploader("Upload Repair Photo", type=["jpg", "jpeg", "png"])
            completion_notes = st.text_area("Completion Notes")

            if st.button("Mark as Resolved"):
                c.execute("UPDATE tickets SET status='Resolved' WHERE ticket_id=?", (selected_task,))
                conn.commit()

                citizen_email = c.execute("SELECT email FROM tickets WHERE ticket_id=?", (selected_task,)).fetchone()
                if citizen_email:
                    send_email(citizen_email[0], "Road Repair Completed", f"Your complaint {selected_task} has been resolved.\n\nNotes:\n{completion_notes}")

                st.success("Work Order Closed")
                st.rerun()
        else:
            st.success("No Pending Tasks")


# ==================================================
# STYLES (Applies to all)
# ==================================================
st.markdown("""
<style>
.stApp { background: linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 25%, #dbeafe 50%, #ede9fe 100%); }
[data-testid="stSidebar"] { background: linear-gradient(180deg, #0f172a, #1e293b); }
[data-testid="stSidebar"] * { color: white !important; }
h1 { background: linear-gradient(90deg, #2563eb, #06b6d4, #10b981); -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-size: 3rem; font-weight: 800; }
h2, h3 { color: #1e3a8a; }
div[data-testid="stVerticalBlock"] > div { border-radius: 15px; }
.stButton > button { background: linear-gradient(90deg, #2563eb, #06b6d4); color: white; border: none; border-radius: 12px; padding: 10px 20px; font-weight: 700; transition: 0.3s; }
.stButton > button:hover { transform: scale(1.03); background: linear-gradient(90deg, #1d4ed8, #0891b2); }
[data-testid="metric-container"] { background: white; border-radius: 15px; padding: 15px; box-shadow: 0 4px 12px rgba(0,0,0,0.12); border-left: 6px solid #2563eb; }
[data-testid="stDataFrame"], [data-testid="stFileUploader"] { background: white; border-radius: 15px; padding: 10px; box-shadow: 0 4px 12px rgba(0,0,0,0.10); }
[data-testid="stFileUploader"] { border: 2px dashed #3b82f6; }
</style>
""", unsafe_allow_html=True)