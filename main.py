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
        return pd.DataFrame(columns=["name", "handicap"]), pd.DataFrame(columns=["player_name", "rp_earned", "stableford_score", "date"])

def calculate_rp(stableford, holes_played, clean_sheet=False, road_warrior=False, hio=False):
    is_9 = (str(holes_played) == "9")
    participation = 1 if is_9 else 2
    target = 18 if is_9 else 36
    
    diff = stableford - target
    if diff >= 0:
        perf = diff * 2
    else:
        perf = int(diff / 2)
        
    bonus = 0
    if clean_sheet: bonus += 2
    if road_warrior: bonus += 2
    if hio: bonus += 10
    
    return participation + perf + bonus

# --- APP START ---
conn = st.connection("gsheets", type=GSheetsConnection)
df_players, df_rounds = load_data(conn)
player_list = df_players["name"].tolist() if not df_players.empty else []

# --- 1. GLOBAL STATS CALCULATION (THE BRAIN) ---
stats = df_players.copy()
stats = stats.rename(columns={"name": "player_name"})
stats = stats.set_index("player_name")

# Init Columns
for col in ["Base RP", "Rounds", "Avg Score", "Best Gross", "1v1 Wins", "1v1 Losses", "2v2 Record", "Daily Wins"]:
    stats[col] = 0

if not df_rounds.empty:
    # Basic Aggregations
    # 1. Base RP (Sum from rounds)
    rp_sum = df_rounds.groupby("player_name")["rp_earned"].sum()
    stats["Base RP"] = stats["Base RP"].add(rp_sum, fill_value=0)
    
    # 2. Rounds Count
    r_count = df_rounds.groupby("player_name")["date"].count()
    stats["Rounds"] = stats["Rounds"].add(r_count, fill_value=0)
    
    # 3. Avg Score (18H Only)
    std_rounds = df_rounds[df_rounds["holes_played"] == "18"]
    if not std_rounds.empty:
        avg = std_rounds.groupby("player_name")["stableford_score"].mean()
        stats["Avg Score"] = stats["Avg Score"].add(avg, fill_value=0)
        
        # Best Gross (Sniper Candidate)
        gross_r = std_rounds[std_rounds["gross_score"] > 0]
        if not gross_r.empty:
            best = gross_r.groupby("player_name")["gross_score"].min()
            stats["Best Gross"] = stats["Best Gross"].add(best, fill_value=0)

    # 4. 1v1 Record
    duels = df_rounds[df_rounds["match_type"] == "Duel"]
    if not duels.empty:
        # Wins: Positive RP in a duel (since loser gets negative)
        d_wins = duels[duels["rp_earned"] > 0].groupby("player_name").size()
        d_loss = duels[duels["rp_earned"] < 0].groupby("player_name").size()
        stats["1v1 Wins"] = stats["1v1 Wins"].add(d_wins, fill_value=0)
        stats["1v1 Losses"] = stats["1v1 Losses"].add(d_loss, fill_value=0)

    # 5. 2v2 Record (Approximate)
    allies = df_rounds[df_rounds["match_type"] == "Alliance"]
    if not allies.empty:
        a_wins = allies[allies["rp_earned"] > 0].groupby("player_name").size()
        a_loss = allies[allies["rp_earned"] < 0].groupby("player_name").size()
        # Create string record
        for p in stats.index:
            w = a_wins.get(p, 0)
            l = a_loss.get(p, 0)
            stats.at[p, "2v2 Record"] = f"{w}-{l}-0"

# --- 2. TROPHY LOGIC (FLOATING POINTS) ---
# Holders
holder_rock = None
holder_sniper = None
holder_conq = None
# Rocket is manual/placeholder for now
holder_rocket = None 

# A. The Rock (+10 RP) - Best Avg, Min 5 Rounds
qualified_rock = stats[stats["Rounds"] >= 5].sort_values("Avg Score", ascending=False)
if not qualified_rock.empty:
    holder_rock = qualified_rock.index[0]
    stats.at[holder_rock, "Base RP"] += 10 # ADD BONUS

# B. The Sniper (+5 RP) - Lowest Gross, Min 1 Round
qualified_sniper = stats[(stats["Best Gross"] > 0)].sort_values("Best Gross", ascending=True)
if not qualified_sniper.empty:
    holder_sniper = qualified_sniper.index[0]
    stats.at[holder_sniper, "Base RP"] += 5 # ADD BONUS

# C. The Conqueror (+10 RP) - Most Base RP (Leader)
# We calculate this based on RP *before* the Conqueror bonus to avoid recursion loop, 
# or just give it to the person with most Daily Wins. Let's use Daily Wins if available, else Max RP.
# For now, simplest is: Leader in RP gets it.
if not stats.empty and stats["Rounds"].sum() > 0:
    temp_rank = stats.sort_values("Base RP", ascending=False)
    holder_conq = temp_rank.index[0]
    stats.at[holder_conq, "Base RP"] += 10 # ADD BONUS

# Clean Up Stats for Display
stats["Avg Score"] = stats["Avg Score"].round(1)
stats = stats.sort_values("Base RP", ascending=False)
stats = stats.reset_index()

# Add Icons to Names
def decorate_name(row):
    name = row["player_name"]
    icons = ""
    if name == holder_rock: icons += " 🪨"
    if name == holder_sniper: icons += " 🎯"
    if name == holder_conq: icons += " 👑"
    return f"{name}{icons}"

stats["Player"] = stats.apply(decorate_name, axis=1)

# --- UI LAYOUT ---
st.title("🏆 Fantasy Golf 2026")

tab_leaderboard, tab_trophy, tab_submit, tab_admin, tab_rules = st.tabs([
    "🌍 Leaderboard", "🏆 Trophy Room", "📝 Submit Round", "⚙️ Admin", "📘 Rulebook"
])

# =========================================================
# TAB 1: LEADERBOARD (Styled)
# =========================================================
with tab_leaderboard:
    st.header("Live Standings")
    
    # Prepare Columns
    lb_data = stats.copy()
    lb_data["1v1 Record"] = lb_data["1v1 Wins"].astype(int).astype(str) + "-" + lb_data["1v1 Losses"].astype(int).astype(str)
    
    # Add Placeholder Seasons
    lb_data["Season 1"] = 0
    lb_data["Season 2"] = 0
    
    # Final View
    final_view = lb_data[[
        "Player", "Base RP", "Season 1", "Season 2", "handicap", 
        "Best Gross", "Rounds", "Avg Score", "1v1 Record", "2v2 Record"
    ]]
    
    final_view = final_view.rename(columns={
        "Base RP": "Tournament 1 Ranking Points",
        "handicap": "HCP",
        "Best Gross": "Best Round Strokes"
    })

    # Styling function
    def highlight_rows(row):
        # We need the original index to determine rank
        if row.name == 0:
            return ['background-color: #FFD700; color: black'] * len(row) # Gold for 1st
        elif 1 <= row.name <= 3:
            return ['background-color: #FFFACD; color: black'] * len(row) # Light Yellow for 2-4
        else:
            return [''] * len(row)

    if not final_view.empty:
        st.dataframe(
            final_view.style.apply(highlight_rows, axis=1),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Tournament 1 Ranking Points": st.column_config.NumberColumn(format="%d"),
                "Rounds": st.column_config.NumberColumn(format="%d"),
            }
        )
        
        st.caption("🔶 **Gold:** The King (Leader) | 🟡 **Yellow:** The Princes (Qualify for King's Cup)")
        st.caption("🏆 **Bonuses Active:** 🪨 The Rock (+10) | 🎯 The Sniper (+5) | 👑 The Conqueror (+10)")

    else:
        st.info("Season has not started yet.")

# =========================================================
# TAB 2: TROPHY ROOM
# =========================================================
with tab_trophy:
    st.header("🏆 The Hall of Fame")
    
    # Text Generators
    def get_holder_text(holder, val, metric_name):
        if holder:
            return f"{holder}\n\n*({val} {metric_name})*"
        return "Unclaimed"

    # Rock Text
    rock_val = stats[stats["player_name"] == holder_rock]["Avg Score"].values[0] if holder_rock else 0
    rock_txt = get_holder_text(holder_rock, rock_val, "Avg")
    
    # Sniper Text
    snip_val = stats[stats["player_name"] == holder_sniper]["Best Gross"].values[0] if holder_sniper else 0
    snip_txt = get_holder_text(holder_sniper, snip_val, "Strokes")
    
    # Conq Text
    conq_txt = holder_conq if holder_conq else "Unclaimed"

    # Cards
    st.markdown("""
    <style>
    .trophy-card { background-color: #262730; padding: 20px; border-radius: 10px; border: 1px solid #4B4B4B; text-align: center; }
    .t-icon { font-size: 40px; }
    .t-head { font-size: 18px; font-weight: bold; color: #FFD700; margin-top: 5px; }
    .t-sub { font-size: 12px; color: #A0A0A0; margin-bottom: 10px; }
    .t-name { font-size: 20px; font-weight: bold; color: white; }
    .t-bonus { color: #00FF00; font-weight: bold; font-size: 14px; margin-top: 5px; }
    </style>
    """, unsafe_allow_html=True)

    c1, c2, c3, c4 = st.columns(4)
    
    def card(col, icon, title, desc, winner, bonus, cond):
        col.markdown(f"""
        <div class="trophy-card">
            <div class="t-icon">{icon}</div>
            <div class="t-head">{title}</div>
            <div class="t-sub">{desc}<br><i>{cond}</i></div>
            <div class="t-name">{winner}</div>
            <div class="t-bonus">{bonus} RP</div>
        </div>
        """, unsafe_allow_html=True)

    card(c1, "🪨", "The Rock", "Best Scoring Average", rock_txt, "+10", "Min 5 Rounds")
    card(c2, "🚀", "The Rocket", "Biggest HCP Drop", "Unclaimed", "+10", "Manual Award")
    card(c3, "🎯", "The Sniper", "Lowest Gross Score", snip_txt, "+5", "Monthly")
    card(c4, "👑", "The Conqueror", "League Leader", conq_txt, "+10", "Most Daily Wins")

# =========================================================
# TAB 3: SUBMIT ROUND
# =========================================================
with tab_submit:
    st.subheader("Choose Game Mode")
    mode = st.radio("Format:", ["Standard Round", "The Duel (1v1)", "The Alliance (2v2)"], horizontal=True, label_visibility="collapsed")
    
    # --- STANDARD ---
    if mode == "Standard Round":
        st.info("Submit scores for one or more players.")
        players = st.multiselect("Select Players", player_list)
        if players:
            with st.form("std_form"):
                c1, c2, c3 = st.columns(3)
                dt = c1.date_input("Date", datetime.date.today())
                crs = c2.text_input("Course", "Chinderah")
                hl = c3.radio("Length", ["18", "9"], horizontal=True)
                
                rows = []
                for p in players:
                    st.markdown(f"**{p}**")
                    ca, cb, cc = st.columns([1, 1, 2])
                    sf = ca.number_input(f"Stableford ({p})", 0, 60, step=1)
                    gr = cb.number_input(f"Gross ({p})", 0, 150, step=1)
                    
                    c_bon = cc.columns(3)
                    cl = c_bon[0].checkbox("Clean Sheet", key=f"c{p}")
                    rw = c_bon[1].checkbox("New Course", key=f"r{p}")
                    ho = c_bon[2].checkbox("Hole-in-One", key=f"h{p}")
                    
                    rows.append({"p":p, "s":sf, "g":gr, "cl":cl, "rw":rw, "ho":ho})
                    st.divider()
                
                if st.form_submit_button("Submit Scorecards"):
                    new_data = []
                    for r in rows:
                        rp = calculate_rp(r['s'], hl, r['cl'], r['rw'], r['ho'])
                        n = []
                        if r['cl']: n.append("Clean Sheet")
                        if r['rw']: n.append("Road Warrior")
                        if r['ho']: n.append("HIO")
                        
                        new_data.append({
                            "date": str(dt), "course": crs, "player_name": r['p'],
                            "holes_played": hl, "stableford_score": r['s'], "gross_score": r['g'],
                            "rp_earned": rp, "notes": ", ".join(n), "match_type": "Standard"
                        })
                    
                    conn.update(worksheet="rounds", data=pd.concat([df_rounds, pd.DataFrame(new_data)], ignore_index=True), spreadsheet=SPREADSHEET_NAME)
                    st.success("Saved!")
                    st.rerun()

    # --- DUEL (1v1) ---
    elif mode == "The Duel (1v1)":
        st.warning("⚔️ **1v1 STAKES**")
        with st.form("duel_form"):
            c1, c2 = st.columns(2)
            p1 = c1.selectbox("Player 1", player_list)
            p2 = c2.selectbox("Player 2", player_list, index=1 if len(player_list)>1 else 0)
            
            st.divider()
            # Winner Selector
            winner_radio = st.radio("🏆 Who Won?", [p1, p2], horizontal=True)
            
            c3, c4, c5 = st.columns(3)
            dt = c3.date_input("Date")
            crs = c4.text_input("Course")
            hl = c5.radio("Length", ["18", "9"], horizontal=True)
            
            c6, c7 = st.columns(2)
            s1 = c6.number_input(f"{p1} Gross", 0)
            s2 = c7.number_input(f"{p2} Gross", 0)
            
            stake = st.radio("Stakes Rule:", ["Standard (Winner +5, Loser -5)", "Upset (Winner +10, Loser -10)"])
            
            if st.form_submit_button("Record Duel"):
                if p1 == p2:
                    st.error("Select different players.")
                else:
                    win_p = winner_radio
                    lose_p = p2 if win_p == p1 else p1
                    
                    # Scores
                    win_gross = s1 if win_p == p1 else s2
                    lose_gross = s2 if win_p == p1 else s1
                    
                    # Math
                    part = 1 if hl == "9" else 2
                    steal = 10 if "Upset" in stake else 5
                    
                    rows = [
                        {"date": str(dt), "course": crs, "player_name": win_p, "holes_played": hl, "gross_score": win_gross, "stableford_score": 0, "rp_earned": part + steal, "notes": f"Won Duel vs {lose_p}", "match_type": "Duel"},
                        {"date": str(dt), "course": crs, "player_name": lose_p, "holes_played": hl, "gross_score": lose_gross, "stableford_score": 0, "rp_earned": part - steal, "notes": f"Lost Duel vs {win_p}", "match_type": "Duel"}
                    ]
                    conn.update(worksheet="rounds", data=pd.concat([df_rounds, pd.DataFrame(rows)], ignore_index=True), spreadsheet=SPREADSHEET_NAME)
                    st.success(f"Duel Recorded! {win_p} steals {steal} RP from {lose_p}.")
                    st.rerun()

    # --- ALLIANCE (2v2) ---
    elif mode == "The Alliance (2v2)":
        with st.form("ally_form"):
            col_w, col_l = st.columns(2)
            with col_w:
                st.success("Winners (+5)")
                w1 = st.selectbox("W1", player_list, key="w1")
                w2 = st.selectbox("W2", player_list, key="w2")
                wh = st.number_input("Holes Won", 0, 18, key="wh")
            with col_l:
                st.error("Losers (-5)")
                l1 = st.selectbox("L1", player_list, key="l1")
                l2 = st.selectbox("L2", player_list, key="l2")
                lh = st.number_input("Holes Won", 0, 18, key="lh")
            
            dt = st.date_input("Date")
            crs = st.text_input("Course")
            
            if st.form_submit_button("Submit 2v2"):
                d = []
                note = f"Result: {wh}-{lh}"
                for p in [w1, w2]: d.append({"date":str(dt), "course":crs, "player_name":p, "holes_played":"18", "rp_earned": 7, "notes":note, "match_type":"Alliance"})
                for p in [l1, l2]: d.append({"date":str(dt), "course":crs, "player_name":p, "holes_played":"18", "rp_earned": -3, "notes":note, "match_type":"Alliance"})
                
                conn.update(worksheet="rounds", data=pd.concat([df_rounds, pd.DataFrame(d)], ignore_index=True), spreadsheet=SPREADSHEET_NAME)
                st.success("Alliance Recorded!")
                st.rerun()

# =========================================================
# TAB 4: ADMIN
# =========================================================
with tab_admin:
    st.header("⚙️ Admin")
    with st.form("add_p"):
        n = st.text_input("Name")
        h = st.number_input("Handicap", 0.0)
        if st.form_submit_button("Add"):
            conn.update(worksheet="players", data=pd.concat([df_players, pd.DataFrame([{"name":n, "handicap":h}])], ignore_index=True), spreadsheet=SPREADSHEET_NAME)
            st.rerun()
            
    with st.form("del_p"):
        d = st.selectbox("Delete", player_list)
        if st.form_submit_button("Delete Player"):
            conn.update(worksheet="players", data=df_players[df_players["name"]!=d], spreadsheet=SPREADSHEET_NAME)
            st.rerun()

    st.data_editor(df_players, num_rows="dynamic")

# =========================================================
# TAB 5: RULEBOOK (COMPLETE)
# =========================================================
with tab_rules:
    st.header("📘 Official Fantasy Golf 2026 Rulebook")
    
    with st.expander("1. HOW WE PLAY (STABLEFORD)", expanded=True):
        st.markdown("""
        **We use Stableford Scoring.**
        * **The Golden Rule:** "Your Personal Par". Forget the "Course Par." In this league, you play against your Personal Par (Net Par).
        * **Handicap:** Your handicap gives you extra shots on difficult holes.
        * **Example:** If you get 1 handicap stroke on a Par 4, your "Personal Par" becomes 5. If you shoot a 5, that counts as a Par (2 points).
        
        **Points System:**
        * **Albatross (3 under Personal Par):** 5 Points
        * **Eagle (2 under Personal Par):** 4 Points
        * **Birdie (1 under Personal Par):** 3 Points
        * **Par (Level with Personal Par):** 2 Points
        * **Bogey (1 over Personal Par):** 1 Point
        * **Double Bogey or worse:** 0 Points
        
        *Note: No "gimmes". Finish your hole.*
        """)

    with st.expander("2. THE CALENDAR & STRUCTURE"):
        st.markdown("""
        **Tournament 1: The Road to the King (Jan - Jun)**
        * **Season 1 (Summer):** Jan 1 - Mar 31
        * **Season 2 (Fall):** Apr 1 - Jun 20
        * **Special Event:** The King's Cup (June 21 - 30). *Qualification: Top 4 Ranking.*
        
        **Tournament 2: The Road to Glory (Jul - Dec)**
        * *League Points Reset to 0.*
        * **Season 3 (Winter):** Jul 1 - Sep 30
        * **Season 4 (Spring):** Oct 1 - Dec 20
        * **Grand Finals:** Dec 21 - 31. *Qualification: Top from T1 & T2 + King's Cup Champ.*
        """)

    with st.expander("3. PERFORMANCE RANKING (RP)"):
        st.markdown("""
        **Target Score:** 36 Points (18H) | 18 Points (9H)
        
        **1. Positive Score (Score > 36) - The "Double Down" Rule**
        * Formula: `(Your Score - 36) x 2 = RP Earned`
        * *Example: Score 40 pts -> (40-36)*2 = +8 RP.*
        
        **2. Negative Score (Score < 36)**
        * Formula: `(Your Score - 36) / 2 = RP Deducted`
        * *Example: Score 27 pts -> -9 diff / 2 = -5 RP.*
        
        **3. The Sprint Protocol (9-Hole Rounds)**
        * Goal: 18 Pts.
        * Participation: +1 RP.
        * *Restrictions: Not eligible for Clean Sheet or Sniper.*
        """)

    with st.expander("4. MATCH BONUSES & AWARDS"):
        st.markdown("""
        **Match Bonuses**
        * **Participation:** +2 RP (18H), +1 RP (9H).
        * **Winner of the Day:** +2 to +6 RP (Depends on group size).
        * **Giant Slayer:** +1 RP per higher-ranked player beaten.
        * **Clean Sheets:** +2 RP (No "0 pt" holes).
        * **Road Warrior:** +2 RP (New Course).
        * **Hole-in-One:** +10 RP.
        
        **Seasonal Awards (Floating Trophies)**
        *Held by the current leader. If you lose the lead, you lose the points.*
        * 🪨 **The Rock (+10 RP):** Best Scoring Average (Min 5 rounds).
        * 🚀 **The Rocket (+10 RP):** Biggest Handicap reduction.
        * 👑 **The Conqueror (+10 RP):** League Leader (Most Wins).
        * 🎯 **The Sniper (+5 RP):** Best Gross Score of the Month.
        
        **The Checkpoint Podium**
        * At end of Season 1, Top 5 receive permanent RP injection:
        * 1st (+15), 2nd (+10), 3rd (+7), 4th (+4), 5th (+2).
        """)

    with st.expander("5. RIVALRY CHALLENGES"):
        st.markdown("""
        **The Alliance (2v2)**
        * **Format:** Texas Scramble / Match Play.
        * **Scoring:** Winners steal points from Losers.
        * **Victory:** +5 RP per player.
        * **Defeat:** -5 RP per player.
        * *Note: 2v2 scores do NOT count for handicap.*
        
        **The Duel (1v1 Scratch)**
        * **Format:** Gross Stroke Play (No Handicaps).
        * **Standard Stakes:** Favorite Wins (+5 RP), Loser (-5 RP).
        * **Upset Stakes:** Underdog Wins (+10 RP), Loser (-10 RP).
        * *Note: Duel scores DO count for handicap.*
        """)

    with st.expander("6. LIVE HANDICAPS"):
        st.markdown("""
        **Automatic Adjustments (HCP <= 36)**
        * **40+ pts:** -2.0
        * **37-39 pts:** -1.0
        * **27-36 pts:** No Change
        * **<27 pts:** +1.0
        
        **Sandbagger Protocol (HCP > 36)**
        * Cut by 1.0 stroke for every single point scored over 36.
        
        **Away Game Protocol**
        * Par 70+ courses allow handicap boosts:
        * HCP 0-10: +3 Shots
        * HCP 11-20: +5 Shots
        * HCP 21+: +7 Shots
        """)
