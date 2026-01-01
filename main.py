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
        
        # Ensure correct types and handle missing columns
        if "holes_played" not in rounds.columns: rounds["holes_played"] = "18"
        if "gross_score" not in rounds.columns: rounds["gross_score"] = 0
        
        rounds["holes_played"] = rounds["holes_played"].fillna("18").astype(str)
        rounds["gross_score"] = rounds["gross_score"].fillna(0).astype(int)
        
        return players, rounds
    except Exception as e:
        st.error(f"Connection Error: {e}")
        st.stop()

def calculate_rp(stableford, holes_played, clean_sheet=False, road_warrior=False, hio=False):
    # Base Participation
    is_9 = (str(holes_played) == "9")
    participation = 1 if is_9 else 2
    target = 18 if is_9 else 36
    
    # Performance
    diff = stableford - target
    if diff >= 0:
        perf = diff * 2
    else:
        perf = int(diff / 2)
        
    # Bonuses
    bonus = 0
    if clean_sheet: bonus += 2
    if road_warrior: bonus += 2
    if hio: bonus += 10
    
    return participation + perf + bonus

# --- APP START ---
st.title("🏆 Fantasy Golf 2026: The Official League")
st.markdown("*Track progress, fuel rivalry, and simulate the pressure of the professional tour.*")

conn = st.connection("gsheets", type=GSheetsConnection)
df_players, df_rounds = load_data(conn)
player_list = df_players["name"].tolist() if not df_players.empty else []

# --- GLOBAL CALCULATIONS (Fixes NameError) ---
# We calculate stats HERE so they are available for all tabs
stats = pd.DataFrame()
if not df_rounds.empty:
    # 1. Total RP and Matches
    stats = df_rounds.groupby("player_name").agg({
        "rp_earned": "sum",
        "date": "count"
    }).reset_index()
    
    # 2. Average Score (18H Only)
    std_rounds = df_rounds[df_rounds["holes_played"] == "18"]
    if not std_rounds.empty:
        avg_scores = std_rounds.groupby("player_name")["stableford_score"].mean().reset_index()
        avg_scores.columns = ["player_name", "avg_score"]
        stats = stats.merge(avg_scores, on="player_name", how="left")
    else:
        stats["avg_score"] = 0.0

    # 3. Merge Handicaps
    stats = stats.merge(df_players, left_on="player_name", right_on="name", how="left")
    stats = stats.sort_values("rp_earned", ascending=False).reset_index(drop=True)
    stats["avg_score"] = stats["avg_score"].fillna(0).round(1)

# --- TABS LAYOUT (Reordered) ---
tab_leaderboard, tab_trophy, tab_submit, tab_admin, tab_rules = st.tabs([
    "🌍 Leaderboard", 
    "🏆 Trophy Room", 
    "📝 Submit Round", 
    "⚙️ Admin & Players", 
    "📘 Rulebook"
])

# =========================================================
# TAB 1: LEADERBOARD
# =========================================================
with tab_leaderboard:
    st.header("🌍 The Standings")
    if not stats.empty:
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
    else:
        st.info("No matches played yet.")

# =========================================================
# TAB 2: TROPHY ROOM
# =========================================================
with tab_trophy:
    st.header("🏆 The Hall of Fame")
    
    # -- Calculation Logic --
    rock_winner = "Unclaimed"
    sniper_winner = "Unclaimed"
    conq_winner = "Unclaimed"
    
    if not df_rounds.empty and not stats.empty:
        # The Rock (Best Avg)
        eligible_rock = stats[stats["date"] >= 5].sort_values("avg_score", ascending=False)
        if not eligible_rock.empty:
            rock_winner = f"{eligible_rock.iloc[0]['name']} ({eligible_rock.iloc[0]['avg_score']})"
            
        # The Sniper (Lowest Gross Score - requires gross_score column)
        # If gross_score is 0 (not entered), we skip. Filter > 0.
        valid_gross = df_rounds[(df_rounds["holes_played"] == "18") & (df_rounds["gross_score"] > 0)]
        if not valid_gross.empty:
            best_gross = valid_gross.sort_values("gross_score", ascending=True).iloc[0]
            sniper_winner = f"{best_gross['player_name']} ({best_gross['gross_score']})"
            
        # The Conqueror (Leader)
        if not stats.empty:
            conq_winner = f"{stats.iloc[0]['name']}"

    # -- Display --
    col1, col2, col3 = st.columns(3)
    with col1:
        st.error(f"🪨 **The Rock**\n\n*Best Avg Score (Min 5)*\n\n**{rock_winner}**")
    with col2:
        st.warning(f"🎯 **The Sniper**\n\n*Lowest Gross Score*\n\n**{sniper_winner}**")
    with col3:
        st.success(f"👑 **The Conqueror**\n\n*League Leader*\n\n**{conq_winner}**")

# =========================================================
# TAB 3: SUBMIT ROUND
# =========================================================
with tab_submit:
    st.subheader("Choose Game Mode")
    
    game_mode = st.radio("Select Format:", 
        ["🏌️ Standard Round", "⚔️ The Duel (1v1)", "🛡️ The Alliance (2v2)"], 
        horizontal=True
    )
    
    # --- MODE A: STANDARD ROUND (Multi-Player) ---
    if game_mode == "🏌️ Standard Round":
        st.info("Submit scores for one or more players.")
        
        with st.form("standard_form"):
            # 1. Global Details
            c1, c2, c3 = st.columns(3)
            date_play = c1.date_input("Date", datetime.date.today())
            course = c2.text_input("Course Name")
            holes = c3.radio("Length", ["18", "9"], horizontal=True)
            
            # 2. Select Players
            selected_players = st.multiselect("Select Players in Group", player_list)
            
            # 3. Dynamic Input for each player
            player_data = []
            if selected_players:
                st.divider()
                for p in selected_players:
                    st.markdown(f"**{p}**")
                    col_a, col_b, col_c, col_d = st.columns(4)
                    
                    score = col_a.number_input(f"Stableford Pts ({p})", min_value=0, step=1, key=f"sf_{p}")
                    gross = col_b.number_input(f"Gross Strokes ({p})", min_value=0, step=1, key=f"gr_{p}")
                    
                    # Bonuses
                    is_clean = col_c.checkbox("Clean Sheet (+2)", key=f"cs_{p}")
                    is_road = col_c.checkbox("New Course (+2)", key=f"rw_{p}")
                    is_hio = col_d.checkbox("Hole-in-One (+10)", key=f"hio_{p}")
                    
                    player_data.append({
                        "name": p, "score": score, "gross": gross, 
                        "clean": is_clean, "road": is_road, "hio": is_hio
                    })
                st.divider()

            submitted = st.form_submit_button("✅ Submit All Scorecards")
            
            if submitted:
                if not selected_players:
                    st.error("Please select at least one player.")
                else:
                    new_rows = []
                    for p_dat in player_data:
                        # Calculate RP
                        rp = calculate_rp(p_dat['score'], holes, p_dat['clean'], p_dat['road'], p_dat['hio'])
                        
                        # Note String
                        note_parts = []
                        if p_dat['clean']: note_parts.append("Clean Sheet")
                        if p_dat['road']: note_parts.append("Road Warrior")
                        if p_dat['hio']: note_parts.append("Hole-in-One")
                        
                        new_rows.append({
                            "date": str(date_play), 
                            "course": course, 
                            "player_name": p_dat['name'],
                            "holes_played": holes, 
                            "stableford_score": p_dat['score'],
                            "gross_score": p_dat['gross'],
                            "rp_earned": rp, 
                            "notes": ", ".join(note_parts), 
                            "match_type": "Standard"
                        })
                    
                    updated_df = pd.concat([df_rounds, pd.DataFrame(new_rows)], ignore_index=True)
                    conn.update(worksheet="rounds", data=updated_df, spreadsheet=SPREADSHEET_NAME)
                    st.success(f"Saved rounds for {len(selected_players)} players!")
                    st.rerun()

    # --- MODE B: THE DUEL (1v1) ---
    elif game_mode == "⚔️ The Duel (1v1)":
        st.warning("⚠️ **High Stakes:** Winner steals RP from Loser.")
        with st.form("duel_form"):
            c1, c2 = st.columns(2)
            winner = c1.selectbox("Winner", player_list)
            loser = c2.selectbox("Loser", player_list, index=1 if len(player_list)>1 else 0)
            
            c3, c4 = st.columns(2)
            course = c3.text_input("Course")
            date_play = c4.date_input("Date")
            
            stake = st.radio("Stakes:", ["Standard (Fav Wins: +5/-5)", "Upset (Underdog Wins: +10/-5)"])
            
            if st.form_submit_button("Submit Duel"):
                win_pts = 10 if "Upset" in stake else 5
                
                rows = [
                    {"date": str(date_play), "course": course, "player_name": winner, "holes_played": "Duel", "stableford_score": 0, "rp_earned": win_pts, "notes": f"Defeated {loser}", "match_type": "Duel"},
                    {"date": str(date_play), "course": course, "player_name": loser, "holes_played": "Duel", "stableford_score": 0, "rp_earned": -5, "notes": f"Lost to {winner}", "match_type": "Duel"}
                ]
                updated_df = pd.concat([df_rounds, pd.DataFrame(rows)], ignore_index=True)
                conn.update(worksheet="rounds", data=updated_df, spreadsheet=SPREADSHEET_NAME)
                st.success("Duel Recorded!")
                st.rerun()

    # --- MODE C: THE ALLIANCE (2v2) ---
    elif game_mode == "🛡️ The Alliance (2v2)":
        st.info("Winners steal 5 RP from Losers.")
        with st.form("alliance_form"):
            col1, col2 = st.columns(2)
            st.markdown("**🏆 Winning Duo**")
            w1 = col1.selectbox("Winner 1", player_list, key="w1")
            w2 = col2.selectbox("Winner 2", player_list, key="w2")
            w_holes = col1.number_input("Holes Won (Winners)", min_value=0, max_value=18)
            
            st.divider()
            st.markdown("**💀 Losing Duo**")
            l1 = col1.selectbox("Loser 1", player_list, key="l1")
            l2 = col2.selectbox("Loser 2", player_list, key="l2")
            l_holes = col2.number_input("Holes Won (Losers)", min_value=0, max_value=18)
            
            course = st.text_input("Course")
            date_play = st.date_input("Date")
            
            if st.form_submit_button("Submit 2v2 Match"):
                rows = []
                match_note = f"Result: Winners {w_holes} - {l_holes} Losers"
                
                # Winners (+5)
                for p in [w1, w2]:
                    rows.append({"date": str(date_play), "course": course, "player_name": p, "holes_played": "2v2", "stableford_score": 0, "rp_earned": 5, "notes": match_note, "match_type": "Alliance"})
                # Losers (-5)
                for p in [l1, l2]:
                    rows.append({"date": str(date_play), "course": course, "player_name": p, "holes_played": "2v2", "stableford_score": 0, "rp_earned": -5, "notes": match_note, "match_type": "Alliance"})
                
                updated_df = pd.concat([df_rounds, pd.DataFrame(rows)], ignore_index=True)
                conn.update(worksheet="rounds", data=updated_df, spreadsheet=SPREADSHEET_NAME)
                st.success("Alliance Match Recorded!")
                st.rerun()

# =========================================================
# TAB 4: ADMIN
# =========================================================
with tab_admin:
    st.header("⚙️ Player Management")
    with st.form("add_player"):
        new_p = st.text_input("New Player Name")
        new_h = st.number_input("Starting Handicap", min_value=0.0, step=0.1)
        if st.form_submit_button("Add Player"):
            new_row = pd.DataFrame([{"name": new_p, "handicap": new_h}])
            updated_p = pd.concat([df_players, new_row], ignore_index=True)
            conn.update(worksheet="players", data=updated_p, spreadsheet=SPREADSHEET_NAME)
            st.success(f"Added {new_p}")
            st.rerun()
            
    st.divider()
    st.write("Edit Player Database:")
    edited_df = st.data_editor(df_players, num_rows="dynamic")
    if st.button("Save Changes"):
        conn.update(worksheet="players", data=edited_df, spreadsheet=SPREADSHEET_NAME)
        st.success("Database Updated")

# =========================================================
# TAB 5: RULEBOOK
# =========================================================
with tab_rules:
    st.header("📘 Official Rulebook 2026")
    st.markdown("""
    ### 1. Scoring (Stableford)
    * **Target Score:** 36 Points (18H) | 18 Points (9H)
    * **Positive Score:** (Score - Target) x 2 = **RP Gained**.
    * **Negative Score:** (Score - Target) / 2 = **RP Lost** (Dampened).
    
    ### 2. Match Bonuses
    * **Participation:** +2 RP (18H), +1 RP (9H).
    * **Clean Sheet:** +2 RP (No wipes).
    * **Road Warrior:** +2 RP (New Course).
    * **Hole-in-One:** +10 RP.

    ### 3. Rivalry Challenges
    * **The Alliance (2v2):** Winner takes 5 RP from Loser.
    * **The Duel (1v1):** * **Standard:** Favorite wins (+5 RP), Loser (-5 RP).
        * **Upset:** Underdog wins (+10 RP), Favorite (-5 RP).
    """)
