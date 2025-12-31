import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import datetime

# --- CONFIGURATION ---
st.set_page_config(
    page_title="Fantasy Golf Manager",
    page_icon="⛳",
    layout="wide"
)

# --- CONSTANTS ---
SPREADSHEET_NAME = "fantasy_golf_db"  # <--- We explicitly tell it which sheet to find

# --- TITLE & HERO SECTION ---
st.title("🏆 Fantasy Golf 2026 Manager")
st.markdown("""
*The Official League App. Track scores, rankings, and rivalry history.*
""")

# --- CONNECT TO GOOGLE SHEETS ---
conn = st.connection("gsheets", type=GSheetsConnection)

# Load Data
# We explicitly pass the spreadsheet name here to avoid the ValueError
try:
    df_players = conn.read(worksheet="players", spreadsheet=SPREADSHEET_NAME, ttl=0)
    df_rounds = conn.read(worksheet="rounds", spreadsheet=SPREADSHEET_NAME, ttl=0)
except Exception as e:
    st.error(f"Could not load data. Ensure the Google Sheet is named '{SPREADSHEET_NAME}' exactly.")
    st.stop()

# --- DATA CLEANING ---
if "holes_played" not in df_rounds.columns:
    df_rounds["holes_played"] = 18
df_rounds["holes_played"] = df_rounds["holes_played"].fillna(18).astype(int)

# --- LOGIC FUNCTIONS ---
def calculate_rp(stableford_score, holes_played=18):
    if holes_played == 9:
        target_score = 18
        participation_rp = 1
    else:
        target_score = 36
        participation_rp = 2

    diff = stableford_score - target_score
    
    if diff >= 0:
        performance_rp = diff * 2
    else:
        performance_rp = int(diff / 2)

    return participation_rp + performance_rp

# --- SIDEBAR: PLAYER STATS ---
st.sidebar.header("📊 Player Card")
player_names = df_players["name"].unique() if not df_players.empty else []
selected_player = st.sidebar.selectbox("Select Player Profile", player_names)

if selected_player:
    player_rounds = df_rounds[df_rounds["player_name"] == selected_player]
    if not player_rounds.empty:
        total_rp = player_rounds["rp_earned"].sum()
        rounds_count = len(player_rounds)
        avg_score = player_rounds[player_rounds["holes_played"] == 18]["stableford_score"].mean()
        
        st.sidebar.metric("Total RP", f"{total_rp}")
        st.sidebar.metric("Rounds Played", f"{rounds_count}")
        if pd.notna(avg_score):
            st.sidebar.metric("Avg Score (18H)", f"{avg_score:.1f}")
    else:
        st.sidebar.write("No rounds played yet.")

# --- MAIN TAB LAYOUT ---
tab1, tab2, tab3 = st.tabs(["📝 Submit Round", "🌍 Leaderboard", "📜 Match History"])

# === TAB 1: SUBMIT ROUND ===
with tab1:
    st.subheader("Submit a New Scorecard")
    with st.form("add_round_form"):
        col1, col2 = st.columns(2)
        with col1:
            player_name = st.selectbox("Player", player_names)
            date_played = st.date_input("Date", datetime.date.today())
            course_name = st.text_input("Course Name")
        with col2:
            holes_played = st.radio("Holes Played", [18, 9], horizontal=True)
            stableford_score = st.number_input("Stableford Points", min_value=0, max_value=60, step=1)
            notes = st.text_area("Notes")
        
        submitted = st.form_submit_button("✅ Submit Round")
        
        if submitted:
            if not course_name:
                st.error("Please enter a course name.")
            else:
                rp_earned = calculate_rp(stableford_score, holes_played)
                
                new_round = pd.DataFrame([{
                    "date": str(date_played),
                    "course": course_name,
                    "player_name": player_name,
                    "holes_played": holes_played,
                    "stableford_score": stableford_score,
                    "rp_earned": rp_earned,
                    "notes": notes,
                    "match_group_id": f"{date_played}_{course_name.replace(' ', '')}"
                }])
                
                updated_rounds = pd.concat([df_rounds, new_round], ignore_index=True)
                
                # Update with explicit spreadsheet name
                conn.update(worksheet="rounds", data=updated_rounds, spreadsheet=SPREADSHEET_NAME)
                
                st.success(f"🎉 Round Saved! {player_name} earned {rp_earned} RP.")
                st.rerun()

# === TAB 2: LEADERBOARD ===
with tab2:
    st.subheader("🌍 Live Rankings")
    if not df_rounds.empty:
        leaderboard = df_rounds.groupby("player_name").agg({
            "rp_earned": "sum",
            "stableford_score": "mean",
            "date": "count"
        }).reset_index()
        leaderboard.columns = ["Player", "Total RP", "Avg Score", "Rounds"]
        
        # Merge with Handicap
        leaderboard = leaderboard.merge(df_players[["name", "handicap"]], left_on="Player", right_on="name", how="left")
        
        leaderboard = leaderboard.sort_values(by="Total RP", ascending=False).reset_index(drop=True)
        
        st.dataframe(
            leaderboard[["Player", "handicap", "Total RP", "Rounds"]],
            column_config={
                "handicap": "HCP",
                "Total RP": st.column_config.ProgressColumn("Total RP", format="%d", min_value=0, max_value=500),
            },
            use_container_width=True
        )
    else:
        st.info("No rounds recorded yet.")

# === TAB 3: HISTORY ===
with tab3:
    st.subheader("📜 Recent Matches")
    if not df_rounds.empty:
        st.dataframe(
            df_rounds.sort_values(by="date", ascending=False)[["date", "player_name", "course", "holes_played", "stableford_score", "rp_earned"]],
            use_container_width=True
        )
