import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime

# --- CONNECTION SETUP ---
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

def get_client():
    """Connects to Google Sheets using secrets."""
    try:
        # Load the dictionary from secrets
        creds_dict = st.secrets["gcp_service_account"]
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
        # Make sure this matches your Sheet Name EXACTLY
        return client.open("fantasy_golf_db") 
    return None

# --- READ DATA ---
def load_players():
    sh = get_db()
    worksheet = sh.worksheet("players")
    data = worksheet.get_all_records()
    df = pd.DataFrame(data)
    # Ensure columns exist even if sheet is empty
    if df.empty:
        return pd.DataFrame(columns=["name", "handicap", "total_rp", "rounds_played", "wins"])
    return df

def load_history():
    sh = get_db()
    worksheet = sh.worksheet("rounds")
    data = worksheet.get_all_records()
    df = pd.DataFrame(data)
    if df.empty:
        return pd.DataFrame(columns=["date", "course", "player_name", "stableford_score", "rp_earned", "notes"])
    return df

# --- WRITE DATA ---
def update_player_stats(player_name, new_hcp, rp_gained, is_win=False):
    sh = get_db()
    ws = sh.worksheet("players")
    
    # Get all data to find the row index
    data = ws.get_all_records()
    
    # Find the row number for the player (Google Sheets is 1-indexed, +1 for header)
    row_idx = None
    for i, row in enumerate(data):
        if row['name'] == player_name:
            row_idx = i + 2  # +2 because enumerate starts at 0, and sheets starts at 1, plus header
            current_rp = float(row['total_rp'])
            current_rounds = int(row['rounds_played'])
            current_wins = int(row['wins'])
            break
    
    if row_idx:
        # UPDATE EXISTING PLAYER
        ws.update_cell(row_idx, 2, new_hcp)  # Col 2: Handicap
        ws.update_cell(row_idx, 3, current_rp + rp_gained) # Col 3: RP
        ws.update_cell(row_idx, 4, current_rounds + 1) # Col 4: Rounds
        if is_win:
            ws.update_cell(row_idx, 5, current_wins + 1) # Col 5: Wins
    else:
        # CREATE NEW PLAYER (If they don't exist yet)
        wins = 1 if is_win else 0
        new_row = [player_name, new_hcp, rp_gained, 1, wins]
        ws.append_row(new_row)

def log_round(date, course, player_name, stbl, rp, notes, match_id):
    sh = get_db()
    ws = sh.worksheet("rounds")
    # Append the round data
    row = [str(date), course, player_name, stbl, rp, notes, match_id]
    ws.append_row(row)