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

# --- TITLE & HERO SECTION ---
st.title("🏆 Fantasy Golf 2026 Manager")
st.markdown("""
*The Official League App. Track scores, rankings, and rivalry history.*
""")

# --- CONNECT TO GOOGLE SHEETS ---
conn = st.connection("gsheets", type=GSheetsConnection)

# Load Data
# ttl=0 ensures we don't cache old data; we want fresh scores every reload
df_players = conn.read(worksheet="players", ttl=0)
df_rounds = conn.read(worksheet="rounds", ttl=0)

# --- DATA CLEANING (PREVENTS CRASHES) ---
# If 'holes_played' column is missing or empty in old rows, fill with 18
if "holes_played" not in df_rounds.columns:
    df_rounds["holes_played"] = 18
df_rounds["holes_played"] = df_rounds["holes_played"].fillna(18).astype(int)

# --- LOGIC FUNCTIONS ---

def calculate_rp(stableford_score, holes_played=18):
    """
    Calculates Ranking Points (RP) based on league rules.
    18 Holes: Target 36, Participation 2 RP.
    9 Holes:  Target 18, Participation 1 RP.
    """
    if holes_played == 9:
        target_score = 18
        participation_rp = 1
    else:
        target_score = 36
        participation_rp = 2

    # Performance Logic: Difference from Target
    diff = stableford_score - target_score
    
    if diff >= 0:
        performance_rp = diff * 2  # Double Down (Gain)
    else:
        performance_rp = int(diff / 2)  # Dampener (Loss halved)

    return participation_rp + performance_rp

# --- SIDEBAR: PLAYER STATS ---
st.sidebar.header("📊 Player Card")
selected_player = st.sidebar.selectbox("Select Player Profile", df_players["name"].unique())

if selected_player:
    # Filter stats for this player
    player_rounds = df_rounds[df_rounds["player_name"] == selected_player]
    
    if not player_rounds.empty:
        total_rp = player_rounds["rp_earned"].sum()
        rounds_count = len(player_rounds)
        avg_score = player_rounds[player_rounds["holes_played"] == 18]["stableford_score"].mean() # Only avg 18 hole rounds
        
        st.sidebar.metric("Total RP (Rank)", f"{total_rp}")
        st.sidebar.metric("Rounds Played", f"{rounds_count}")
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
            player_name = st.selectbox("Player", df_players["name"].tolist())
            date_played = st.date_input("Date", datetime.date.today())
            course_name = st.text_input("Course Name")
        
        with col2:
            holes_played = st.radio("Holes Played", [18, 9], horizontal=True)
            stableford_score = st.number_input("Stableford Points", min_value=0, max_value=60, step=1)
            notes = st.text_area("Notes (e.g. 'Eagle on 18th')")
        
        submitted = st.form_submit_button("✅ Submit Round")
        
        if submitted:
            if not course_name:
                st.error("Please enter a course name.")
            else:
                # 1. Calculate RP
                rp_earned = calculate_rp(stableford_score, holes_played)
                
                # 2. Prepare Data Row
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
                
                # 3. Update 'rounds' Worksheet
                updated_rounds = pd.concat([df_rounds, new_round], ignore_index=True)
                conn.update(worksheet="rounds", data=updated_rounds)
                
                # 4. Optional: Update 'players' totals (Simple aggregation)
                # We usually just recalculate leaderboard dynamically, but if you want to save stats:
                # (Skipping complex write-back to 'players' sheet to avoid sync errors. We rely on 'rounds' data)

                st.success(f"🎉 Round Saved! {player_name} earned {rp_earned} RP.")
                st.balloons()
                st.rerun() # Refresh page to show new data

# === TAB 2: LEADERBOARD ===
with tab2:
    st.subheader("🌍 Live Rankings")
    
    # Calculate Live Stats from the Rounds Data
    # 1. Group by player
    leaderboard = df_rounds.groupby("player_name").agg({
        "rp_earned": "sum",
        "stableford_score": "mean",
        "date": "count"
    }).reset_index()
    
    # 2. Rename columns
    leaderboard.columns = ["Player", "Total RP", "Avg Score (Raw)", "Rounds"]
    
    # 3. Merge with Handicap from Players sheet
    leaderboard = leaderboard.merge(df_players[["name", "handicap"]], left_on="Player", right_on="name", how="left")
    
    # 4. Clean up and Sort
    leaderboard = leaderboard[["Player", "handicap", "Total RP", "Rounds"]] # Select columns to show
    leaderboard = leaderboard.sort_values(by="Total RP", ascending=False).reset_index(drop=True)
    
    # 5. Display
    st.dataframe(
        leaderboard,
        column_config={
            "handicap": "HCP",
            "Total RP": st.column_config.ProgressColumn("Total RP", format="%d", min_value=0, max_value=500),
        },
        use_container_width=True
    )

# === TAB 3: HISTORY ===
with tab3:
    st.subheader("📜 Recent Matches")
    
    # Show latest rounds first
    history_view = df_rounds.sort_values(by="date", ascending=False)
    
    st.dataframe(
        history_view[["date", "player_name", "course", "holes_played", "stableford_score", "rp_earned", "notes"]],
        use_container_width=True
    )
