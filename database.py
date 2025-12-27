import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import json

# --- CONNECTION SETUP ---
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

def get_client():
    """Connects to Google Sheets using secrets."""
    try:
        # Check for the "Easy Trick" format (JSON String)
        if "service_account_info" in st.secrets:
            creds_dict = json.loads(st.secrets["service_account_info"])
        # Check for the "Standard" format (TOML)
        elif "gcp_service_account" in st.secrets:
            creds_dict = st.secrets["gcp_service_account"]
        else:
            st.error("Secrets not found! Please check Streamlit settings.")
            return None

        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        st.error(f"Error connecting to Google Sheets: {e}")
        return None

def get_db():
    """Returns the Spreadsheet object."""
    client = get_client()
    if client:
        try:
            return client.open("fantasy_golf_db")
        except gspread.exceptions.SpreadsheetNotFound:
            st.error("Could not find Google Sheet named 'fantasy_golf_db'. Check spelling and sharing permissions.")
            return None
    return None

# --- READ DATA ---
def load_players():
    sh = get_db()
    if not sh: return pd.DataFrame()
    
    try:
        worksheet = sh.worksheet("players")
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)
        if df.empty:
            return pd.DataFrame(columns=["name", "handicap", "total_rp", "rounds_played", "wins"])
        return df
    except gspread.exceptions.WorksheetNotFound:
        st.error("Tab 'players' not found in Google Sheet.")
        return pd.DataFrame()

def load_history():
    sh = get_db()
    if not sh: return pd.DataFrame()
    
    try:
        worksheet = sh.worksheet("rounds")
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)
        if df.empty:
            return pd.DataFrame(columns=["date", "course", "player_name", "stableford_score", "rp_earned", "notes"])
        return df
    except gspread.exceptions.WorksheetNotFound:
        st.error("Tab 'rounds' not found in Google Sheet.")
        return pd.DataFrame()

# --- WRITE DATA ---
def update_player_stats(player_name, new_hcp, rp_gained, is_win=False):
    sh = get_db()
    if not sh: return

    ws = sh.worksheet("players")
    data = ws.get_all_records()
    
    # Find the row number for the player
    row_idx = None
    for i, row in enumerate(data):
        if row['name'] == player_name:
            # +2 because enumerate starts at 0, and sheets starts at 1, plus header
            row_idx = i + 2  
            current_rp = float(row['total_rp']) if row['total_rp'] != '' else 0.0
            current_rounds = int(row['rounds_played']) if row['rounds_played'] != '' else 0
            current_wins = int(row['wins']) if row['wins'] != '' else 0
            break
    
    if row_idx:
        # UPDATE EXISTING PLAYER
        ws.update_cell(row_idx, 2, new_hcp)
        ws.update_cell(row_idx, 3, current_rp + rp_gained)
        ws.update_cell(row_idx, 4, current_rounds + 1)
        if is_win:
            ws.update_cell(row_idx, 5, current_wins + 1)
    else:
        # CREATE NEW PLAYER
        wins = 1 if is_win else 0
        new_row = [player_name, new_hcp, rp_gained, 1, wins]
        ws.append_row(new_row)

def log_round(date, course, player_name, stbl, rp, notes, match_id):
    sh = get_db()
    if not sh: return
    
    ws = sh.worksheet("rounds")
    row = [str(date), course, player_name, stbl, rp, notes, match_id]
    ws.append_row(row)