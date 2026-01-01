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
        if "match_type" not in rounds.columns: rounds["match_type"] = "Standard"
        if "winner_name" not in rounds.columns: rounds["winner_name"] = ""
        
        rounds["holes_played"] = rounds["holes_played"].fillna("18").astype(str)
        rounds["gross_score"] = rounds["gross_score"].fillna(0).astype(int)
        
        return players, rounds
    except Exception as e:
        # Graceful fallback for first run
        return pd.DataFrame(columns=["name", "handicap"]), pd.DataFrame(columns=["player_name", "rp_earned", "stableford_score", "date"])

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
conn = st.connection("gsheets", type=GSheetsConnection)
df_players, df_rounds = load_data(conn)
player_list = df_players["name"].tolist() if not df_players.empty else []

# --- GLOBAL CALCULATIONS (For Leaderboard & Trophies) ---
# Create a base Stats DataFrame with ALL players (Left Join)
stats = df_players.copy()
stats = stats.rename(columns={"name": "player_name"})

if not df_rounds.empty:
    # 1. Total RP and Rounds
    group_stats = df_rounds.groupby("player_name").agg({
        "rp_earned": "sum",
        "date": "count"
    }).reset_index()
    stats = stats.merge(group_stats, on="player_name", how="left")
    
    # 2. Avg Score & Best Round (18H Only)
    std_rounds = df_rounds[df_rounds["holes_played"] == "18"]
    if not std_rounds.empty:
        # Avg Score
        avg_scores = std_rounds.groupby("player_name")["stableford_score"].mean().reset_index()
        avg_scores.columns = ["player_name", "avg_score"]
        stats = stats.merge(avg_scores, on="player_name", how="left")
        
        # Best Gross (Lowest Strokes)
        best_gross = std_rounds[std_rounds["gross_score"] > 0].groupby("player_name")["gross_score"].min().reset_index()
        best_gross.columns = ["player_name", "best_gross"]
        stats = stats.merge(best_gross, on="player_name", how="left")
    
    # 3. 2v2 Record (Wins-Losses)
    # This is a simple approximation based on RP. >0 in Alliance = Win.
    alliance_rounds = df_rounds[df_rounds["match_type"] == "Alliance"]
    if not alliance_rounds.empty:
        wins = alliance_rounds[alliance_rounds["rp_earned"] > 0].groupby("player_name").size().reset_index(name="2v2_wins")
        losses = alliance_rounds[alliance_rounds["rp_earned"] < 0].groupby("player_name").size().reset_index(name="2v2_losses")
        stats = stats.merge(wins, on="player_name", how="left").merge(losses, on="player_name", how="left")

# Fill NaNs
stats["rp_earned"] = stats["rp_earned"].fillna(0).astype(int)
stats["date"] = stats["date"].fillna(0).astype(int)
stats["avg_score"] = stats["avg_score"].fillna(0.0).round(1)
stats["best_gross"] = stats["best_gross"].fillna(0).astype(int)
stats["2v2_wins"] = stats.get("2v2_wins", pd.Series([0]*len(stats))).fillna(0).astype(int)
stats["2v2_losses"] = stats.get("2v2_losses", pd.Series([0]*len(stats))).fillna(0).astype(int)

# Create "Record" String
stats["2v2 Record"] = stats["2v2_wins"].astype(str) + "-" + stats["2v2_losses"].astype(str) + "-0"

# Sort by Total RP
stats = stats.sort_values("rp_earned", ascending=False).reset_index(drop=True)

# --- HEADER ---
st.title("🏆 Fantasy Golf 2026")
st.markdown("*The Official League App.*")

# --- TABS LAYOUT (Correct Order) ---
tab_leaderboard, tab_trophy, tab_submit, tab_admin, tab_rules = st.tabs([
    "🌍 Leaderboard", 
    "🏆 Trophy Room", 
    "📝 Submit Round", 
    "⚙️ Admin & Players", 
    "📘 Rulebook"
])

# =========================================================
# TAB 1: LEADERBOARD (Full Grid)
# =========================================================
with tab_leaderboard:
    st.header("Live Standings")
    
    # Format for display
    display_df = stats[[
        "player_name", "rp_earned", "handicap", "best_gross", "date", "avg_score", "2v2 Record"
    ]].copy()
    
    # Add dummy cols for design match
    display_df["Daily Wins"] = 0 # Placeholder for now
    
    st.dataframe(
        display_df,
        column_config={
            "player_name": "Player",
            "rp_earned": st.column_config.ProgressColumn("Total RP", format="%d", min_value=-50, max_value=500),
            "handicap": "HCP",
            "best_gross": "Best Round (Gross)",
            "date": "Rounds",
            "avg_score": "Avg Score (18H)",
            "2v2 Record": "2v2 (W-L-D)",
            "Daily Wins": "Daily Wins"
        },
        use_container_width=True,
        hide_index=True
    )

# =========================================================
# TAB 2: TROPHY ROOM (Visual Upgrades)
# =========================================================
with tab_trophy:
    st.header("🏆 The Hall of Fame")
    
    # -- Logic --
    # Rock: Best Avg (Min 5 rounds)
    rock_cand = stats[stats["date"] >= 5].sort_values("avg_score", ascending=False)
    rock_txt = f"{rock_cand.iloc[0]['player_name']} ({rock_cand.iloc[0]['avg_score']})" if not rock_cand.empty else "Unclaimed"
    
    # Rocket: Most Improved (Placeholder logic - needs historic tracking, currently showing Leader)
    rocket_txt = "Unclaimed"
    
    # Sniper: Lowest Gross
    sniper_cand = stats[stats["best_gross"] > 0].sort_values("best_gross", ascending=True)
    sniper_txt = f"{sniper_cand.iloc[0]['player_name']} ({sniper_cand.iloc[0]['best_gross']})" if not sniper_cand.empty else "Unclaimed"
    
    # Conqueror: Most RP
    conq_txt = f"{stats.iloc[0]['player_name']}" if not stats.empty else "Unclaimed"

    # -- Visual Cards --
    # CSS for cards
    st.markdown("""
    <style>
    .trophy-card {
        background-color: #262730;
        padding: 20px;
        border-radius: 10px;
        border: 1px solid #4B4B4B;
        text-align: center;
        margin-bottom: 10px;
    }
    .trophy-icon { font-size: 40px; }
    .trophy-title { font-size: 18px; font-weight: bold; color: #FFD700; margin-top: 10px;}
    .trophy-desc { font-size: 12px; color: #A0A0A0; }
    .trophy-winner { font-size: 20px; font-weight: bold; margin-top: 10px; color: #FFFFFF;}
    </style>
    """, unsafe_allow_html=True)

    c1, c2, c3, c4 = st.columns(4)
    
    def card(col, icon, title, desc, winner):
        col.markdown(f"""
        <div class="trophy-card">
            <div class="trophy-icon">{icon}</div>
            <div class="trophy-title">{title}</div>
            <div class="trophy-desc">{desc}</div>
            <div class="trophy-winner">{winner}</div>
        </div>
        """, unsafe_allow_html=True)

    card(c1, "🪨", "The Rock", "Best Avg Score", rock_txt)
    card(c2, "🚀", "The Rocket", "Most Improved HCP", rocket_txt)
    card(c3, "🎯", "The Sniper", "Lowest Gross Score", sniper_txt)
    card(c4, "👑", "The Conqueror", "League Leader", conq_txt)

# =========================================================
# TAB 3: SUBMIT ROUND
# =========================================================
with tab_submit:
    st.subheader("Choose Game Mode")
    
    game_mode = st.radio("Select Format:", 
        ["🏌️ Standard Round", "⚔️ The Duel (1v1)", "🛡️ The Alliance (2v2)"], 
        horizontal=True
    )
    
    # --- MODE A: STANDARD ---
    if game_mode == "🏌️ Standard Round":
        st.info("Log scores for yourself or the group.")
        
        # 1. SELECT PLAYERS OUTSIDE THE FORM
        selected_players = st.multiselect("Select Players in Group", player_list)
        
        if selected_players:
            with st.form("standard_form"):
                # Global Settings
                c1, c2, c3 = st.columns(3)
                date_play = c1.date_input("Date", datetime.date.today())
                course = c2.text_input("Course Name", value="Chinderah")
                holes = c3.radio("Length", ["18", "9"], horizontal=True)
                
                # Dynamic Inputs
                st.subheader("Scorecards")
                player_data = []
                for p in selected_players:
                    st.markdown(f"**{p}**")
                    ca, cb, cc, cd = st.columns(4)
                    
                    s_score = ca.number_input(f"Stableford ({p})", min_value=0, max_value=60, step=1, key=f"sf_{p}")
                    g_score = cb.number_input(f"Gross Strokes ({p})", min_value=0, max_value=150, step=1, key=f"gr_{p}")
                    
                    clean = cc.checkbox(f"Clean Sheet? ({p})", key=f"cs_{p}")
                    road = cc.checkbox(f"New Course? ({p})", key=f"rw_{p}")
                    hio = cd.checkbox(f"HOLE IN ONE? ({p})", key=f"hio_{p}")
                    
                    player_data.append({
                        "name": p, "score": s_score, "gross": g_score, 
                        "clean": clean, "road": road, "hio": hio
                    })
                    st.divider()
                
                submitted = st.form_submit_button("✅ Submit All Scorecards")
                
                if submitted:
                    new_rows = []
                    for p_dat in player_data:
                        rp = calculate_rp(p_dat['score'], holes, p_dat['clean'], p_dat['road'], p_dat['hio'])
                        
                        notes = []
                        if p_dat['clean']: notes.append("Clean Sheet")
                        if p_dat['road']: notes.append("Road Warrior")
                        if p_dat['hio']: notes.append("Hole-in-One")
                        
                        new_rows.append({
                            "date": str(date_play), "course": course, "player_name": p_dat['name'],
                            "holes_played": holes, "stableford_score": p_dat['score'], "gross_score": p_dat['gross'],
                            "rp_earned": rp, "notes": ", ".join(notes), "match_type": "Standard"
                        })
                    
                    updated_df = pd.concat([df_rounds, pd.DataFrame(new_rows)], ignore_index=True)
                    conn.update(worksheet="rounds", data=updated_df, spreadsheet=SPREADSHEET_NAME)
                    st.success("Rounds Saved!")
                    st.rerun()

    # --- MODE B: 1v1 DUEL ---
    elif game_mode == "⚔️ The Duel (1v1)":
        st.markdown("**Stakes:** Standard (Winner +5 RP, Loser -5 RP) | Upset (Winner +10 RP, Loser -5 RP)")
        
        with st.form("duel_form"):
            c1, c2 = st.columns(2)
            winner = c1.selectbox("🏆 Winner", player_list, key="d_win")
            loser = c2.selectbox("💀 Loser", player_list, index=1 if len(player_list)>1 else 0, key="d_lose")
            
            st.divider()
            
            c3, c4, c5 = st.columns(3)
            date_play = c3.date_input("Date")
            course = c4.text_input("Course")
            holes = c5.radio("Length", ["18", "9"], horizontal=True)
            
            c6, c7 = st.columns(2)
            w_gross = c6.number_input("Winner Gross Score", min_value=0)
            l_gross = c7.number_input("Loser Gross Score", min_value=0)
            
            stake_type = st.radio("Win Type", ["Standard Win (Favorite Won)", "Upset Win (Underdog Won)"])
            
            if st.form_submit_button("⚔️ Record Duel"):
                if winner == loser:
                    st.error("Select different players.")
                else:
                    # Participation RP (+2 or +1)
                    part_rp = 1 if holes == "9" else 2
                    
                    # Theft RP
                    steal_win = 10 if "Upset" in stake_type else 5
                    steal_lose = -5
                    
                    # Total RP
                    w_rp = part_rp + steal_win
                    l_rp = part_rp + steal_lose
                    
                    rows = [
                        {"date": str(date_play), "course": course, "player_name": winner, "holes_played": holes, "gross_score": w_gross, "stableford_score": 0, "rp_earned": w_rp, "notes": f"Won Duel vs {loser}", "match_type": "Duel"},
                        {"date": str(date_play), "course": course, "player_name": loser, "holes_played": holes, "gross_score": l_gross, "stableford_score": 0, "rp_earned": l_rp, "notes": f"Lost Duel vs {winner}", "match_type": "Duel"}
                    ]
                    updated_df = pd.concat([df_rounds, pd.DataFrame(rows)], ignore_index=True)
                    conn.update(worksheet="rounds", data=updated_df, spreadsheet=SPREADSHEET_NAME)
                    st.success(f"Duel Recorded! {winner} (+{w_rp}), {loser} ({l_rp})")
                    st.rerun()

    # --- MODE C: 2v2 ALLIANCE ---
    elif game_mode == "🛡️ The Alliance (2v2)":
        with st.form("alliance_form"):
            st.subheader("Match Details")
            c_meta1, c_meta2 = st.columns(2)
            date_play = c_meta1.date_input("Date")
            course = c_meta2.text_input("Course")
            
            st.divider()
            
            col_win, col_lose = st.columns(2)
            
            with col_win:
                st.success("🏆 THE WINNERS (+5 RP)")
                w1 = st.selectbox("Partner 1", player_list, key="w1")
                w2 = st.selectbox("Partner 2", player_list, key="w2")
                w_holes = st.number_input("Holes Won", min_value=0, max_value=18, key="wh")
            
            with col_lose:
                st.error("💀 THE LOSERS (-5 RP)")
                l1 = st.selectbox("Partner 1", player_list, key="l1")
                l2 = st.selectbox("Partner 2", player_list, key="l2")
                l_holes = st.number_input("Holes Won", min_value=0, max_value=18, key="lh")
            
            if st.form_submit_button("Submit Alliance Match"):
                rows = []
                note = f"Result: {w_holes}-{l_holes}"
                # Participation (+2) + Win/Loss
                part = 2
                
                for p in [w1, w2]:
                    rows.append({"date": str(date_play), "course": course, "player_name": p, "holes_played": "18", "rp_earned": part + 5, "notes": note, "match_type": "Alliance"})
                for p in [l1, l2]:
                    rows.append({"date": str(date_play), "course": course, "player_name": p, "holes_played": "18", "rp_earned": part - 5, "notes": note, "match_type": "Alliance"})
                
                updated_df = pd.concat([df_rounds, pd.DataFrame(rows)], ignore_index=True)
                conn.update(worksheet="rounds", data=updated_df, spreadsheet=SPREADSHEET_NAME)
                st.success("Alliance Recorded!")
                st.rerun()

# =========================================================
# TAB 4: ADMIN
# =========================================================
with tab_admin:
    st.header("⚙️ Admin")
    
    col_add, col_del = st.columns(2)
    
    with col_add:
        st.subheader("Add Player")
        with st.form("add_p"):
            n = st.text_input("Name")
            h = st.number_input("Handicap", min_value=0.0)
            if st.form_submit_button("Create"):
                new = pd.DataFrame([{"name": n, "handicap": h}])
                conn.update(worksheet="players", data=pd.concat([df_players, new], ignore_index=True), spreadsheet=SPREADSHEET_NAME)
                st.rerun()
                
    with col_del:
        st.subheader("Danger Zone: Delete Player")
        with st.form("del_p"):
            to_del = st.selectbox("Select Player to DELETE", player_list)
            confirm = st.text_input("Type 'DELETE' to confirm")
            if st.form_submit_button("Permanently Delete"):
                if confirm == "DELETE":
                    # Remove from players DF
                    clean_players = df_players[df_players["name"] != to_del]
                    conn.update(worksheet="players", data=clean_players, spreadsheet=SPREADSHEET_NAME)
                    st.error(f"Deleted {to_del}")
                    st.rerun()
                else:
                    st.warning("You must type DELETE to confirm.")

    st.divider()
    st.subheader("Database Editor")
    edited = st.data_editor(df_players, num_rows="dynamic")
    if st.button("Save Edits"):
        conn.update(worksheet="players", data=edited, spreadsheet=SPREADSHEET_NAME)
        st.success("Saved!")

# =========================================================
# TAB 5: RULEBOOK
# =========================================================
with tab_rules:
    st.header("📘 Official Rulebook 2026")
    st.markdown("""
    ### 1. HOW WE PLAY (STABLEFORD)
    We use Stableford Scoring.
    * **The Golden Rule:** "Your Personal Par". Forget the "Course Par."
    * **Calculation:** If you get 1 handicap stroke on a Par 4, your "Personal Par" is 5. If you shoot 5, that is a Par (2 pts).
    * **Points:** Albatross (5), Eagle (4), Birdie (3), Par (2), Bogey (1), Double+ (0).

    ### 2. THE CALENDAR
    * **Tournament 1:** The Road to the King (Jan - Jun)
    * **Special Event:** The King's Cup (June). Top 4 Qualify.
    * **Tournament 2:** The Road to Glory (Jul - Dec)
    * **Grand Finals:** Dec 21-31. Top qualifiers from T1 & T2 + King's Cup Champ.

    ### 3. PERFORMANCE RANKING (RP)
    **Target Score:** 36 Points (18H) | 18 Points (9H)
    
    * **Positive Score (>36):** (Score - 36) x 2 = RP Gained.
    * **Negative Score (<36):** (Score - 36) / 2 = RP Lost.
    * **9-Hole Rounds:** Participation +1 RP. Performance relative to 18 pts.

    ### 4. BONUSES
    * **Participation:** +2 RP (18H), +1 RP (9H).
    * **Winner of the Day:** +2 to +6 RP (Group size dependent).
    * **Giant Slayer:** +1 RP per higher-ranked player beaten.
    * **Clean Sheet:** +2 RP (No wipes).
    * **Road Warrior:** +2 RP (New Course).
    * **Hole-in-One:** +10 RP.

    ### 5. RIVALRY CHALLENGES
    **The Alliance (2v2)**
    * Format: Texas Scramble / Match Play.
    * Result: Winners steal 5 RP from Losers.
    
    **The Duel (1v1)**
    * Format: Gross Stroke Play (No Handicaps).
    * **Standard Stakes:** Favorite Wins (+5 RP), Loser (-5 RP).
    * **Upset Stakes:** Underdog Wins (+10 RP), Favorite (-5 RP).
    """)
