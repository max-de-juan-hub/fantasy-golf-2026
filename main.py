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
SPREADSHEET_NAME = "fantasy_golf_db"

# --- TITLE ---
st.title("🏆 Fantasy Golf 2026 Manager")
st.markdown("*The Official League App. Track progress, fuel rivalry, and simulate the pressure.*")

# --- CONNECT TO GOOGLE SHEETS ---
conn = st.connection("gsheets", type=GSheetsConnection)

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
    # Logic: 9 holes = Target 18 (1 RP part). 18 holes = Target 36 (2 RP part).
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

# --- MAIN LAYOUT (5 TABS) ---
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📝 Submit Round", 
    "🌍 Leaderboard", 
    "📜 Match History", 
    "🏆 Trophy Room", 
    "📘 Rules"
])

# === TAB 1: SUBMIT ROUND ===
with tab1:
    st.subheader("Submit a New Scorecard")
    player_names = df_players["name"].tolist() if not df_players.empty else []
    
    with st.form("add_round_form"):
        col1, col2 = st.columns(2)
        with col1:
            player_name = st.selectbox("Player", player_names)
            date_played = st.date_input("Date", datetime.date.today())
            course_name = st.text_input("Course Name")
        
        with col2:
            # THE NEW 9-HOLE FEATURE
            holes_played = st.radio("Holes Played", [18, 9], horizontal=True)
            stableford_score = st.number_input("Stableford Points", min_value=0, max_value=60, step=1)
            notes = st.text_area("Notes (e.g. 'Eagle on 18th')")
        
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
                conn.update(worksheet="rounds", data=updated_rounds, spreadsheet=SPREADSHEET_NAME)
                
                st.success(f"🎉 Round Saved! {player_name} earned {rp_earned} RP.")
                st.rerun()

# === TAB 2: LEADERBOARD ===
with tab2:
    st.subheader("🌍 Live Rankings")
    if not df_rounds.empty:
        # Calculate stats
        leaderboard = df_rounds.groupby("player_name").agg({
            "rp_earned": "sum",
            "stableford_score": "mean",
            "date": "count"
        }).reset_index()
        leaderboard.columns = ["Player", "Total RP", "Avg Score", "Rounds"]
        
        # Merge Handicap
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
    st.subheader("📜 Match History")
    if not df_rounds.empty:
        st.dataframe(
            df_rounds.sort_values(by="date", ascending=False)[["date", "player_name", "course", "holes_played", "stableford_score", "rp_earned", "notes"]],
            use_container_width=True
        )
    else:
        st.info("No matches played yet.")

# === TAB 4: TROPHY ROOM ===
with tab4:
    st.header("🏆 The Hall of Fame")
    st.markdown("Track the Monthly and Seasonal Awards.")

    if not df_rounds.empty:
        col_a, col_b = st.columns(2)
        
        # 1. THE SNIPER (Highest Stableford Score in a single round)
        # We filter for 18 holes only for the big records usually
        full_rounds = df_rounds[df_rounds["holes_played"] == 18]
        if not full_rounds.empty:
            best_round = full_rounds.loc[full_rounds["stableford_score"].idxmax()]
            
            with col_a:
                st.success(f"🎯 **The Sniper** (Best 18H Round)")
                st.metric(label=best_round['player_name'], value=f"{best_round['stableford_score']} pts", delta=best_round['course'])
        
        # 2. THE GRINDER (Most Rounds Played)
        most_rounds_player = df_rounds['player_name'].mode()[0]
        count_rounds = df_rounds[df_rounds['player_name'] == most_rounds_player].shape[0]
        
        with col_b:
            st.info(f"🚜 **The Grinder** (Most Rounds)")
            st.metric(label=most_rounds_player, value=f"{count_rounds} rounds")

    else:
        st.write("Play more rounds to unlock trophies!")

# === TAB 5: RULES ===
with tab5:
    st.subheader("📘 League Rules")
    st.markdown("""
    **1. Scoring (RP System)**
    * **Participation:** +2 RP (18 Holes), +1 RP (9 Holes).
    * **Performance:** Beat the target (36 or 18) -> Gain 2x the difference.
    * **Penalty:** Miss the target -> Lose 0.5x the difference.

    **2. The Trophies**
    * **The Sniper:** Highest Stableford score of the month.
    * **The Rock:** Highest Average Score (min 5 rounds).
    * **Giant Slayer:** Beating the league leader.
    """)
