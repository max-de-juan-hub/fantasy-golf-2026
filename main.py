import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import datetime

# --- CONFIGURATION ---
st.set_page_config(
    page_title="Fantasy Golf 2026",
    page_icon="⛳",
    layout="wide"
)

# --- CONSTANTS ---
SPREADSHEET_NAME = "fantasy_golf_db"

# --- HELPER FUNCTIONS ---
def load_data(conn):
    try:
        players = conn.read(worksheet="players", spreadsheet=SPREADSHEET_NAME, ttl=0)
        rounds = conn.read(worksheet="rounds", spreadsheet=SPREADSHEET_NAME, ttl=0)
        # Ensure correct types
        if "holes_played" not in rounds.columns: rounds["holes_played"] = 18
        rounds["holes_played"] = rounds["holes_played"].fillna(18).astype(str) # String to handle '2v2' labels if needed
        return players, rounds
    except Exception as e:
        st.error(f"Connection Error: {e}")
        st.stop()

def calculate_individual_rp(stableford_score, holes_played, is_nine_hole):
    # Rule: 9 Holes = Target 18, 18 Holes = Target 36
    if is_nine_hole:
        target = 18
        participation = 1
    else:
        target = 36
        participation = 2
    
    diff = stableford_score - target
    
    # Performance Logic
    if diff >= 0:
        performance = diff * 2 # Double Down
    else:
        performance = int(diff / 2) # Dampener
        
    return participation + performance

# --- APP START ---
st.title("🏆 Fantasy Golf 2026: The Official League")
st.markdown("*Track progress, fuel rivalry, and simulate the pressure of the professional tour.*")

conn = st.connection("gsheets", type=GSheetsConnection)
df_players, df_rounds = load_data(conn)
player_list = df_players["name"].tolist() if not df_players.empty else []

# --- TABS ---
tab_submit, tab_leaderboard, tab_trophy, tab_admin, tab_rules = st.tabs([
    "📝 Submit Match", 
    "🌍 Leaderboard", 
    "🏆 Trophy Room", 
    "⚙️ Admin & Players",
    "📘 Rulebook"
])

# =========================================================
# TAB 1: SUBMIT MATCH (The Brain)
# =========================================================
with tab_submit:
    st.subheader("Choose Game Mode")
    
    game_mode = st.radio("Select Format:", 
        ["🏌️ Individual Round (Standard)", "⚔️ The Duel (1v1)", "🛡️ The Alliance (2v2)"], 
        horizontal=True
    )
    
    # --- MODE A: INDIVIDUAL (Standard) ---
    if game_mode == "🏌️ Individual Round (Standard)":
        st.info("Log a standard scorecard for yourself or a friend.")
        with st.form("individual_form"):
            col1, col2 = st.columns(2)
            with col1:
                p_name = st.selectbox("Player", player_list)
                course = st.text_input("Course Name")
                date_play = st.date_input("Date", datetime.date.today())
            with col2:
                holes = st.radio("Length", ["18 Holes", "9 Holes"], horizontal=True)
                score = st.number_input("Stableford Score", min_value=0, max_value=60, step=1)
                notes = st.text_area("Notes")

            submitted = st.form_submit_button("✅ Submit Scorecard")
            
            if submitted:
                is_9 = (holes == "9 Holes")
                rp = calculate_individual_rp(score, 18 if not is_9 else 9, is_9)
                
                new_row = pd.DataFrame([{
                    "date": str(date_play), "course": course, "player_name": p_name,
                    "holes_played": 9 if is_9 else 18, "stableford_score": score, 
                    "rp_earned": rp, "notes": notes, "match_type": "Standard"
                }])
                updated_df = pd.concat([df_rounds, new_row], ignore_index=True)
                conn.update(worksheet="rounds", data=updated_df, spreadsheet=SPREADSHEET_NAME)
                st.success(f"Score saved! {p_name} earned {rp} RP.")
                st.rerun()

    # --- MODE B: THE DUEL (1v1) ---
    elif game_mode == "⚔️ The Duel (1v1)":
        st.warning("⚠️ **High Stakes:** Winner steals RP from Loser. Gross Score only (No Handicap).")
        with st.form("duel_form"):
            col1, col2 = st.columns(2)
            winner = col1.selectbox("🏆 The Winner", player_list)
            loser = col2.selectbox("💀 The Loser", player_list, index=1 if len(player_list)>1 else 0)
            
            course = st.text_input("Course Name")
            date_play = st.date_input("Date")
            
            # Logic: Determine stakes based on handicap (Simple version: User selects stake)
            stake_type = st.radio("Stakes Rule:", 
                ["Standard Defense (Favorite Wins: Winner +5, Loser -5)", 
                 "The Upset (Underdog Wins: Winner +10, Loser -5)"],
                horizontal=True
            )
            
            submitted_duel = st.form_submit_button("⚔️ Record Duel Results")
            
            if submitted_duel:
                if winner == loser:
                    st.error("Winner and Loser cannot be the same person.")
                else:
                    win_pts = 10 if "Upset" in stake_type else 5
                    lose_pts = -5
                    
                    # Create TWO rows
                    row1 = {"date": str(date_play), "course": course, "player_name": winner, "holes_played": "Duel", "stableford_score": 0, "rp_earned": win_pts, "notes": f"Won Duel vs {loser}", "match_type": "Duel"}
                    row2 = {"date": str(date_play), "course": course, "player_name": loser, "holes_played": "Duel", "stableford_score": 0, "rp_earned": lose_pts, "notes": f"Lost Duel vs {winner}", "match_type": "Duel"}
                    
                    updated_df = pd.concat([df_rounds, pd.DataFrame([row1, row2])], ignore_index=True)
                    conn.update(worksheet="rounds", data=updated_df, spreadsheet=SPREADSHEET_NAME)
                    st.success(f"Duel Recorded! {winner} stole points from {loser}.")
                    st.rerun()

    # --- MODE C: THE ALLIANCE (2v2) ---
    elif game_mode == "🛡️ The Alliance (2v2)":
        st.info("Texas Scramble / Match Play. Winners steal 5 RP from Losers.")
        with st.form("alliance_form"):
            col1, col2 = st.columns(2)
            st.markdown("**🏆 Winning Duo**")
            w1 = col1.selectbox("Winner 1", player_list, key="w1")
            w2 = col2.selectbox("Winner 2", player_list, key="w2")
            
            st.divider()
            st.markdown("**💀 Losing Duo**")
            l1 = col1.selectbox("Loser 1", player_list, key="l1")
            l2 = col2.selectbox("Loser 2", player_list, key="l2")
            
            course = st.text_input("Course")
            date_play = st.date_input("Date")
            
            submitted_ally = st.form_submit_button("🛡️ Record 2v2 Match")
            
            if submitted_ally:
                # Create FOUR rows
                rows = []
                for p in [w1, w2]:
                    rows.append({"date": str(date_play), "course": course, "player_name": p, "holes_played": "2v2", "stableford_score": 0, "rp_earned": 5, "notes": "Won 2v2", "match_type": "Alliance"})
                for p in [l1, l2]:
                    rows.append({"date": str(date_play), "course": course, "player_name": p, "holes_played": "2v2", "stableford_score": 0, "rp_earned": -5, "notes": "Lost 2v2", "match_type": "Alliance"})
                
                updated_df = pd.concat([df_rounds, pd.DataFrame(rows)], ignore_index=True)
                conn.update(worksheet="rounds", data=updated_df, spreadsheet=SPREADSHEET_NAME)
                st.success("Alliance Match Recorded. Points stolen!")
                st.rerun()


# =========================================================
# TAB 2: LEADERBOARD
# =========================================================
with tab_leaderboard:
    st.header("🌍 The Standings")
    if not df_rounds.empty:
        # Group by player
        stats = df_rounds.groupby("player_name").agg({
            "rp_earned": "sum",
            "date": "count"
        }).reset_index()
        
        # Calculate Average Score (Only for standard 18H rounds)
        avg_scores = df_rounds[df_rounds["holes_played"].astype(str) == "18"].groupby("player_name")["stableford_score"].mean().reset_index()
        avg_scores.columns = ["player_name", "avg_score"]
        
        # Merge
        stats = stats.merge(df_players, left_on="player_name", right_on="name", how="left")
        stats = stats.merge(avg_scores, on="player_name", how="left")
        
        # Sort and Clean
        stats = stats.sort_values("rp_earned", ascending=False).reset_index(drop=True)
        stats["avg_score"] = stats["avg_score"].fillna(0).round(1)
        
        st.dataframe(
            stats[["name", "handicap", "rp_earned", "date", "avg_score"]],
            column_config={
                "name": "Player",
                "handicap": "HCP",
                "rp_earned": st.column_config.ProgressColumn("Total RP", format="%d", min_value=-50, max_value=500),
                "date": "Matches Played",
                "avg_score": "Avg Score (18H)"
            },
            use_container_width=True
        )


# =========================================================
# TAB 3: TROPHY ROOM
# =========================================================
with tab_trophy:
    st.header("🏆 The Hall of Fame")
    st.markdown("### Seasonal Glory")
    
    col1, col2, col3 = st.columns(3)
    
    # CALCULATIONS
    # 1. The Rock (Best Avg, min 5 rounds)
    rock_winner = "Unclaimed"
    if not df_rounds.empty:
        std_rounds = df_rounds[df_rounds["holes_played"].astype(str) == "18"]
        counts = std_rounds["player_name"].value_counts()
        eligible = counts[counts >= 5].index
        if not eligible.empty:
            best_avg = std_rounds[std_rounds["player_name"].isin(eligible)].groupby("player_name")["stableford_score"].mean().sort_values(ascending=False)
            if not best_avg.empty:
                rock_winner = f"{best_avg.index[0]} ({best_avg.iloc[0]:.1f})"

    # 2. The Sniper (Best Single Round)
    sniper_winner = "Unclaimed"
    if not df_rounds.empty:
        best_r = df_rounds[df_rounds["holes_played"].astype(str) == "18"].sort_values("stableford_score", ascending=False).iloc[0]
        sniper_winner = f"{best_r['player_name']} ({best_r['stableford_score']} pts)"
        
    # 3. The Conqueror (Most Wins - Placeholder logic: most RP)
    conq_winner = "Unclaimed" # Requires 'Win' flags in DB, simpler to use Top RP for now
    if not stats.empty:
        conq_winner = f"{stats.iloc[0]['name']}"

    # DISPLAY CARDS
    with col1:
        st.error(f"🪨 **The Rock**\n\n*Highest Avg Score*\n\n**{rock_winner}**")
    with col2:
        st.warning(f"🚀 **The Rocket**\n\n*Most Improved HCP*\n\n**Unclaimed**")
    with col3:
        st.success(f"👑 **The Conqueror**\n\n*League Leader*\n\n**{conq_winner}**")

    st.divider()
    st.markdown("### Monthly Awards")
    c1, c2 = st.columns(2)
    with c1:
        st.info(f"🎯 **The Sniper**\n\n*Best Round of Month*\n\n**{sniper_winner}**")
    with c2:
        st.info(f"🛡️ **Clean Sheet**\n\n*Round with No Wipes*\n\n**(Tracked in App)**")


# =========================================================
# TAB 4: ADMIN
# =========================================================
with tab_admin:
    st.header("⚙️ Player Management")
    
    # Add Player
    with st.form("add_player"):
        new_p = st.text_input("New Player Name")
        new_h = st.number_input("Starting Handicap", min_value=0.0, step=0.1)
        if st.form_submit_button("Add Player"):
            new_player_row = pd.DataFrame([{"name": new_p, "handicap": new_h}])
            updated_players = pd.concat([df_players, new_player_row], ignore_index=True)
            conn.update(worksheet="players", data=updated_players, spreadsheet=SPREADSHEET_NAME)
            st.success(f"Added {new_p}")
            st.rerun()

    st.divider()
    st.subheader("Edit Database")
    # Editable Dataframe
    edited_df = st.data_editor(df_players, num_rows="dynamic")
    if st.button("Save Changes to Players"):
        conn.update(worksheet="players", data=edited_df, spreadsheet=SPREADSHEET_NAME)
        st.success("Player database updated!")


# =========================================================
# TAB 5: RULES
# =========================================================
with tab_rules:
    st.header("📘 Official Rulebook 2026")
    st.markdown("""
    ### 1. Scoring (Stableford)
    * **The Golden Rule:** You play against your **Personal Par** (Net Par).
    * **Handicap:** If you get a stroke, a Gross 5 becomes a Net 4 (Par).
    * **Points:**
        * Albatross: 5 pts
        * Eagle: 4 pts
        * Birdie: 3 pts
        * **Par: 2 pts**
        * Bogey: 1 pt
        * Double Bogey+: 0 pts

    ### 2. Performance Ranking (RP)
    * **Target Score:** 36 Points.
    * **Positive Score:** (Score - 36) x 2 = **RP Gained**.
    * **Negative Score:** (Score - 36) / 2 = **RP Lost** (Dampened).
    * **9-Hole Rounds:** Target 18 pts. Participation +1 RP.
    
    ### 3. Match Bonuses
    * **Participation:** +2 RP (18H), +1 RP (9H).
    * **Winner of the Day:** +2 to +6 RP depending on group size.
    * **Giant Slayer:** +1 RP per higher-ranked player beaten.
    * **Clean Sheet:** +2 RP (No wipes).
    * **Road Warrior:** +2 RP (New Course).

    ### 4. Rivalry Challenges
    * **The Alliance (2v2):** * Texas Scramble / Match Play.
        * Winner takes 5 RP from Loser.
    * **The Duel (1v1):** * Gross Stroke Play (No Handicap).
        * **Standard:** Favorite wins (+5 RP), Loser (-5 RP).
        * **Upset:** Underdog wins (+10 RP), Favorite (-5 RP).
    """)
