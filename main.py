import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import datetime
from datetime import date

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
        
        rounds["holes_played"] = rounds["holes_played"].fillna("18").astype(str)
        rounds["gross_score"] = rounds["gross_score"].fillna(0).astype(int)
        rounds["stableford_score"] = rounds["stableford_score"].fillna(0).astype(int)
        rounds["rp_earned"] = rounds["rp_earned"].fillna(0).astype(int)
        rounds["date"] = pd.to_datetime(rounds["date"])
        
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

def get_season(date_obj):
    # Season 1: Jan 1 - Mar 31
    # Season 2: Apr 1 - Jun 20
    year = date_obj.year
    d = date_obj.date()
    
    s1_start = datetime.date(year, 1, 1)
    s1_end = datetime.date(year, 3, 31)
    s2_start = datetime.date(year, 4, 1)
    s2_end = datetime.date(year, 6, 20)
    
    if s1_start <= d <= s1_end: return "Season 1"
    if s2_start <= d <= s2_end: return "Season 2"
    return "Off-Season"

# --- APP START ---
conn = st.connection("gsheets", type=GSheetsConnection)
df_players, df_rounds = load_data(conn)
player_list = df_players["name"].tolist() if not df_players.empty else []

# --- 1. GLOBAL STATS CALCULATION ---
stats = df_players.copy()
stats = stats.rename(columns={"name": "player_name"})
stats = stats.set_index("player_name")

# Init Columns
for col in ["Tournament 1 Ranking Points", "Season 1", "Season 2", "Rounds", "Avg Score", "Best Gross", "1v1 Wins", "1v1 Losses", "2v2 Record", "Daily Wins"]:
    stats[col] = 0

if not df_rounds.empty:
    # A. Ranking Points (Split by Season)
    for idx, row in df_rounds.iterrows():
        p = row["player_name"]
        rp = row["rp_earned"]
        season = get_season(row["date"])
        
        # Add to Total
        if p in stats.index:
            stats.at[p, "Tournament 1 Ranking Points"] += rp
            # Add to Season Bucket
            if season in stats.columns:
                stats.at[p, season] += rp

    # B. Rounds Count
    r_count = df_rounds.groupby("player_name")["date"].count()
    stats["Rounds"] = stats["Rounds"].add(r_count, fill_value=0)
    
    # C. Avg Score (18H Only)
    std_rounds = df_rounds[df_rounds["holes_played"] == "18"]
    if not std_rounds.empty:
        avg = std_rounds.groupby("player_name")["stableford_score"].mean()
        stats["Avg Score"] = stats["Avg Score"].add(avg, fill_value=0)
        
        # Best Gross (Valid rounds only)
        gross_r = std_rounds[std_rounds["gross_score"] > 0]
        if not gross_r.empty:
            # We want MIN score, but fill_value=0 in add messes min up. Direct update is safer.
            best = gross_r.groupby("player_name")["gross_score"].min()
            for p, score in best.items():
                if p in stats.index:
                    stats.at[p, "Best Gross"] = score

    # D. 1v1 Record
    duels = df_rounds[df_rounds["match_type"] == "Duel"]
    if not duels.empty:
        d_wins = duels[duels["rp_earned"] > 0].groupby("player_name").size()
        d_loss = duels[duels["rp_earned"] < 0].groupby("player_name").size()
        stats["1v1 Wins"] = stats["1v1 Wins"].add(d_wins, fill_value=0)
        stats["1v1 Losses"] = stats["1v1 Losses"].add(d_loss, fill_value=0)

    # E. 2v2 Record (W-T-L)
    allies = df_rounds[df_rounds["match_type"] == "Alliance"]
    if not allies.empty:
        a_wins = allies[allies["rp_earned"] > 0].groupby("player_name").size()
        a_ties = allies[allies["rp_earned"] == 0].groupby("player_name").size() # Usually 0 RP implies tie if participation wasn't logged
        a_loss = allies[allies["rp_earned"] < 0].groupby("player_name").size()
        
        for p in stats.index:
            w = a_wins.get(p, 0)
            t = a_ties.get(p, 0)
            l = a_loss.get(p, 0)
            stats.at[p, "2v2 Record"] = f"{w}-{t}-{l}"
            
    # F. Daily Wins
    # Group by Date + Course -> Find Max Score -> Assign Win
    match_groups = std_rounds.groupby(["date", "course"])
    for _, group in match_groups:
        if not group.empty:
            max_s = group["stableford_score"].max()
            winners = group[group["stableford_score"] == max_s]["player_name"].unique()
            for w in winners:
                if w in stats.index:
                    stats.at[w, "Daily Wins"] += 1

# --- 2. TROPHY LOGIC (LIVE & SEASONAL) ---
holder_rock = None
holder_sniper = None
holder_conq = None
holder_rocket = None # Manual

# A. The Rock (+10 RP) - Best Avg
qualified_rock = stats[stats["Rounds"] >= 5].sort_values("Avg Score", ascending=False)
if not qualified_rock.empty:
    holder_rock = qualified_rock.index[0]
    stats.at[holder_rock, "Tournament 1 Ranking Points"] += 10 # ADD BONUS

# B. The Sniper (+5 RP) - Lowest Gross CURRENT MONTH
current_month = datetime.date.today().month
current_year = datetime.date.today().year
month_rounds = df_rounds[
    (df_rounds["date"].dt.month == current_month) & 
    (df_rounds["date"].dt.year == current_year) &
    (df_rounds["gross_score"] > 0) &
    (df_rounds["holes_played"] == "18")
]

if not month_rounds.empty:
    # Find lowest score
    best_month_score = month_rounds["gross_score"].min()
    # Find player(s) with that score
    snipers = month_rounds[month_rounds["gross_score"] == best_month_score]["player_name"].unique()
    if len(snipers) > 0:
        holder_sniper = snipers[0] # Tie-breaker: first logged (or add logic)
        if holder_sniper in stats.index:
            stats.at[holder_sniper, "Tournament 1 Ranking Points"] += 5 # ADD BONUS

# C. The Conqueror (+10 RP) - Most Daily Wins
# If ties, goes to most RP
conq_sort = stats.sort_values(["Daily Wins", "Tournament 1 Ranking Points"], ascending=False)
if not conq_sort.empty and conq_sort.iloc[0]["Daily Wins"] > 0:
    holder_conq = conq_sort.index[0]
    stats.at[holder_conq, "Tournament 1 Ranking Points"] += 10 # ADD BONUS

# Clean Up
stats["Avg Score"] = stats["Avg Score"].round(1)
stats = stats.sort_values("Tournament 1 Ranking Points", ascending=False)
stats = stats.reset_index()

def decorate_name(row):
    name = row["player_name"]
    icons = ""
    if name == holder_rock: icons += " 🪨"
    if name == holder_sniper: icons += " 🎯"
    if name == holder_conq: icons += " 👑"
    return f"{name}{icons}"

stats["Player"] = stats.apply(decorate_name, axis=1)

# --- UI ---
st.title("🏆 Fantasy Golf 2026")

tab_leaderboard, tab_trophy, tab_submit, tab_history, tab_admin, tab_rules = st.tabs([
    "🌍 Leaderboard", "🏆 Trophy Room", "📝 Submit Round", "📜 History (Edit)", "⚙️ Admin", "📘 Rulebook"
])

# =========================================================
# TAB 1: LEADERBOARD
# =========================================================
with tab_leaderboard:
    st.header("Live Standings")
    
    lb_data = stats.copy()
    lb_data["1v1 Record"] = lb_data["1v1 Wins"].astype(int).astype(str) + "-" + lb_data["1v1 Losses"].astype(int).astype(str)
    
    view = lb_data[[
        "Player", "Tournament 1 Ranking Points", "Season 1", "Season 2", "handicap", 
        "Best Gross", "Rounds", "Avg Score", "1v1 Record", "2v2 Record", "Daily Wins"
    ]]
    
    view = view.rename(columns={"handicap": "Handicap", "Best Gross": "Best Round Strokes"})

    def highlight_rows(row):
        if row.name == 0:
            return ['background-color: #FFA500; color: black'] * len(row) # Orange Leader
        elif 1 <= row.name <= 3:
            return ['background-color: #FFFFE0; color: black'] * len(row) # Yellow Top 4
        return [''] * len(row)

    st.dataframe(
        view.style.apply(highlight_rows, axis=1).format({"Handicap": "{:.0f}"}), # Int formatting
        use_container_width=True,
        hide_index=True
    )
    
    st.caption("🔶 **Orange:** League Leader | 🟡 **Yellow:** Top 4 (Qualify for King's Cup)")
    st.caption("🏆 **Active Bonuses:** 🪨 The Rock (+10) | 🎯 The Sniper (+5) | 👑 The Conqueror (+10)")

# =========================================================
# TAB 2: TROPHY ROOM
# =========================================================
with tab_trophy:
    st.header("🏆 The Hall of Fame")
    
    def get_text(holder, val, label):
        return f"{holder}\n\n*({val} {label})*" if holder else "Unclaimed"

    rock_val = stats[stats["player_name"] == holder_rock]["Avg Score"].values[0] if holder_rock else 0
    
    # Sniper val needs to come from month logic
    snip_val = best_month_score if holder_sniper else 0
    
    conq_val = stats[stats["player_name"] == holder_conq]["Daily Wins"].values[0] if holder_conq else 0

    # CSS Cards
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
    def card(col, i, t, d, w, b):
        col.markdown(f"""<div class="trophy-card"><div class="t-icon">{i}</div><div class="t-head">{t}</div><div class="t-sub">{d}</div><div class="t-name">{w}</div><div class="t-bonus">{b}</div></div>""", unsafe_allow_html=True)

    card(c1, "🪨", "The Rock", "Best Avg (Min 5 Rnds)", get_text(holder_rock, rock_val, "Avg"), "+10 RP")
    card(c2, "🚀", "The Rocket", "Biggest HCP Drop", "Unclaimed", "+10 RP")
    card(c3, "🎯", "The Sniper", "Best Gross (This Month)", get_text(holder_sniper, snip_val, "Strks"), "+5 RP")
    card(c4, "👑", "The Conqueror", "Most Daily Wins", get_text(holder_conq, conq_val, "Wins"), "+10 RP")

# =========================================================
# TAB 3: SUBMIT ROUND
# =========================================================
with tab_submit:
    st.subheader("Choose Game Mode")
    mode = st.radio("Format:", ["Standard Round", "The Duel (1v1)", "The Alliance (2v2)"], horizontal=True, label_visibility="collapsed")
    
    if mode == "Standard Round":
        st.info("Submit scores for one or more players.")
        players = st.multiselect("Select Players", player_list)
        if players:
            with st.form("std_form"):
                c1, c2, c3 = st.columns(3)
                dt = c1.date_input("Date", datetime.date.today())
                crs = c2.text_input("Course", "Chinderah")
                hl = c3.radio("Length", ["18", "9"], horizontal=True)
                
                new_rows = []
                for p in players:
                    st.markdown(f"**{p}**")
                    ca, cb, cc = st.columns([1, 1, 2])
                    sf = ca.number_input(f"Stableford ({p})", 0, 60, step=1)
                    gr = cb.number_input(f"Gross ({p})", 0, 150, step=1)
                    cl = cc.checkbox("Clean Sheet", key=f"c{p}")
                    rw = cc.checkbox("New Course", key=f"r{p}")
                    ho = cc.checkbox("Hole-in-One", key=f"h{p}")
                    
                    rp = calculate_rp(sf, hl, cl, rw, ho)
                    n = []
                    if cl: n.append("Clean Sheet")
                    if rw: n.append("Road Warrior")
                    if ho: n.append("HIO")
                    
                    new_rows.append({
                        "date": str(dt), "course": crs, "player_name": p,
                        "holes_played": hl, "stableford_score": sf, "gross_score": gr,
                        "rp_earned": rp, "notes": ", ".join(n), "match_type": "Standard"
                    })
                
                if st.form_submit_button("Submit Scorecards"):
                    conn.update(worksheet="rounds", data=pd.concat([df_rounds, pd.DataFrame(new_rows)], ignore_index=True), spreadsheet=SPREADSHEET_NAME)
                    st.success("Saved!")
                    st.rerun()

    elif mode == "The Duel (1v1)":
        with st.form("duel_form"):
            st.warning("⚔️ **1v1 STAKES**")
            c1, c2 = st.columns(2)
            p1 = c1.selectbox("Player 1", player_list)
            p2 = c2.selectbox("Player 2", player_list, index=1)
            
            st.divider()
            winner_name = st.radio("🏆 THE WINNER IS:", [p1, p2], horizontal=True)
            
            c3, c4 = st.columns(2)
            dt = c3.date_input("Date")
            hl = c4.radio("Length", ["18", "9"], horizontal=True)
            stake = st.radio("Stakes Rule:", ["Standard (Winner +5, Loser -5)", "Upset (Winner +10, Loser -10)"])
            
            if st.form_submit_button("Record Duel"):
                if p1 == p2:
                    st.error("Select different players.")
                else:
                    win_p = winner_name
                    lose_p = p2 if win_p == p1 else p1
                    part = 1 if hl == "9" else 2
                    steal = 10 if "Upset" in stake else 5
                    
                    rows = [
                        {"date": str(dt), "course": "Duel", "player_name": win_p, "holes_played": hl, "gross_score": 0, "rp_earned": part + steal, "notes": f"Won Duel vs {lose_p}", "match_type": "Duel"},
                        {"date": str(dt), "course": "Duel", "player_name": lose_p, "holes_played": hl, "gross_score": 0, "rp_earned": part - steal, "notes": f"Lost Duel vs {win_p}", "match_type": "Duel"}
                    ]
                    conn.update(worksheet="rounds", data=pd.concat([df_rounds, pd.DataFrame(rows)], ignore_index=True), spreadsheet=SPREADSHEET_NAME)
                    st.success("Duel Saved!")
                    st.rerun()

    elif mode == "The Alliance (2v2)":
        with st.form("ally_form"):
            c1, c2 = st.columns(2)
            w1 = c1.selectbox("Winner 1", player_list, key="w1")
            w2 = c1.selectbox("Winner 2", player_list, key="w2")
            l1 = c2.selectbox("Loser 1", player_list, key="l1")
            l2 = c2.selectbox("Loser 2", player_list, key="l2")
            dt = st.date_input("Date")
            
            if st.form_submit_button("Submit 2v2"):
                rows = []
                for p in [w1, w2]: rows.append({"date":str(dt), "course":"Alliance", "player_name":p, "holes_played":"18", "rp_earned": 7, "notes":"Win", "match_type":"Alliance"})
                for p in [l1, l2]: rows.append({"date":str(dt), "course":"Alliance", "player_name":p, "holes_played":"18", "rp_earned": -3, "notes":"Loss", "match_type":"Alliance"})
                conn.update(worksheet="rounds", data=pd.concat([df_rounds, pd.DataFrame(rows)], ignore_index=True), spreadsheet=SPREADSHEET_NAME)
                st.success("Alliance Saved!")
                st.rerun()

# =========================================================
# TAB 4: HISTORY (NEW!)
# =========================================================
with tab_history:
    st.header("📜 Round History Management")
    st.info("Expand a round to view details, edit scores, or delete entries.")
    
    if not df_rounds.empty:
        # Sort by date descending
        history_df = df_rounds.sort_values("date", ascending=False).reset_index(drop=True)
        
        for i, row in history_df.iterrows():
            # Create a label for the expander
            label = f"{row['date'].strftime('%Y-%m-%d')} | {row['player_name']} | {row['course']} | {row['rp_earned']} RP"
            
            with st.expander(label):
                with st.form(f"edit_{i}"):
                    c1, c2, c3 = st.columns(3)
                    new_score = c1.number_input("Stableford", value=int(row['stableford_score']), key=f"ns_{i}")
                    new_gross = c2.number_input("Gross", value=int(row['gross_score']), key=f"ng_{i}")
                    new_notes = c3.text_input("Notes", value=str(row['notes']), key=f"nn_{i}")
                    
                    col_up, col_del = st.columns(2)
                    update = col_up.form_submit_button("Update Round")
                    delete = col_del.form_submit_button("🗑️ DELETE ROUND", type="primary")
                    
                    if update:
                        # Find original index in main DF to update
                        # This works because we iterate, but safer to match by all fields if possible. 
                        # Since we don't have IDs, we assume chronological sort holds or reload.
                        # Simplified: We reload, find the row, update.
                        # Recalculate RP
                        new_rp = calculate_rp(new_score, row['holes_played'], "Clean" in new_notes, "Road" in new_notes, "HIO" in new_notes)
                        
                        # Update logic (Matching by timestamp/player/course is safest without ID)
                        mask = (df_rounds['date'] == row['date']) & (df_rounds['player_name'] == row['player_name']) & (df_rounds['course'] == row['course'])
                        df_rounds.loc[mask, 'stableford_score'] = new_score
                        df_rounds.loc[mask, 'gross_score'] = new_gross
                        df_rounds.loc[mask, 'notes'] = new_notes
                        df_rounds.loc[mask, 'rp_earned'] = new_rp
                        
                        conn.update(worksheet="rounds", data=df_rounds, spreadsheet=SPREADSHEET_NAME)
                        st.success("Updated!")
                        st.rerun()
                        
                    if delete:
                        mask = (df_rounds['date'] == row['date']) & (df_rounds['player_name'] == row['player_name']) & (df_rounds['course'] == row['course'])
                        df_rounds = df_rounds[~mask]
                        conn.update(worksheet="rounds", data=df_rounds, spreadsheet=SPREADSHEET_NAME)
                        st.error("Deleted!")
                        st.rerun()
    else:
        st.write("No history available.")

# =========================================================
# TAB 5: ADMIN
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

# =========================================================
# TAB 6: RULEBOOK
# =========================================================
with tab_rules:
    [cite_start]st.header("📘 Official Rulebook [cite: 1]")
    
    with st.expander("1. HOW WE PLAY (STABLEFORD)", expanded=True):
        st.markdown("""
        [cite_start]**We use Stableford Scoring. [cite: 9, 10]**
        * **The Golden Rule:** "Your Personal Par". Forget the "Course Par." [cite_start]You play against your Personal Par (Net Par). [cite: 11, 12]
        * [cite_start]**Handicap:** Gives you extra shots on difficult holes. [cite: 13]
        * [cite_start]**Example:** 1 handicap stroke on a Par 4 = Personal Par 5. Shooting a 5 = Par (2 pts). [cite: 14]
        
        [cite_start]**Points System: [cite: 16, 17]**
        * **Albatross (3 under):** 5 Points
        * **Eagle (2 under):** 4 Points
        * **Birdie (1 under):** 3 Points
        * **Par (Level):** 2 Points
        * **Bogey (1 over):** 1 Point
        * **Double Bogey or worse:** 0 Points
        
        *Note: No "gimmes". [cite_start]Finish your hole. [cite: 18]*
        """)

    [cite_start]with st.expander("2. THE CALENDAR [cite: 19]"):
        st.markdown("""
        [cite_start]**Tournament 1: The Road to the King (Jan - Jun) [cite: 20]**
        * [cite_start]**Season 1 (Summer):** Jan 1 - Mar 31 [cite: 21]
        * [cite_start]**Season 2 (Fall):** Apr 1 - Jun 20 [cite: 21]
        * **Special Event:** The King's Cup (June 21 - 30). [cite_start]*Qualification: Top 4.* [cite: 22, 23]
        
        [cite_start]**Tournament 2: The Road to Glory (Jul - Dec) [cite: 24]**
        * [cite_start]*League Points Reset to 0.* [cite: 25]
        * [cite_start]**Season 3 (Winter):** Jul 1 - Sep 30 [cite: 27]
        * [cite_start]**Season 4 (Spring):** Oct 1 - Dec 20 [cite: 28]
        * [cite_start]**Grand Finals:** Dec 21 - 31. *Qualification: Top from T1 & T2 + King's Cup Champ.* [cite: 29, 30]
        """)

    [cite_start]with st.expander("3. PERFORMANCE RANKING (RP) [cite: 31]"):
        st.markdown("""
        [cite_start]**Target Score:** 36 Points (18H) | 18 Points (9H) [cite: 32, 47]
        
        **1. [cite_start]Positive Score (Score > 36) - "Double Down" [cite: 34]**
        * [cite_start]Formula: `(Score - 36) x 2 = RP Earned` [cite: 35]
        * [cite_start]*Example: 40 pts -> +8 RP.* [cite: 38]
        
        **2. [cite_start]Negative Score (Score < 36) [cite: 39]**
        * [cite_start]Formula: `(Score - 36) / 2 = RP Deducted` [cite: 40]
        * [cite_start]*Example: 27 pts -> -5 RP.* [cite: 43]
        
        **3. [cite_start]The Sprint Protocol (9-Hole Rounds) [cite: 44]**
        * [cite_start]Goal: 18 Pts. [cite: 47]
        * [cite_start]Participation: +1 RP. [cite: 48]
        * [cite_start]*Restrictions: No Clean Sheet or Sniper.* [cite: 49]
        """)

    [cite_start]with st.expander("4. BONUSES & AWARDS [cite: 50]"):
        st.markdown("""
        [cite_start]**Match Bonuses [cite: 51]**
        * [cite_start]**Participation:** +2 RP (18H), +1 RP (9H). [cite: 54]
        * [cite_start]**Winner of the Day:** +2 to +6 RP (Group size dependent). [cite: 55]
        * [cite_start]**Giant Slayer:** +1 RP per higher-ranked player beaten. [cite: 56]
        * [cite_start]**Clean Sheets:** +2 RP (No "0 pt" holes). [cite: 57]
        * [cite_start]**Road Warrior:** +2 RP (New Course). [cite: 58]
        * [cite_start]**Hole-in-One:** +10 RP. [cite: 59]
        
        [cite_start]**Seasonal Awards [cite: 60]**
        * [cite_start]**The Rock (+10 RP):** Best Scoring Average (Min 5 rounds). [cite: 63]
        * [cite_start]**The Rocket (+10 RP):** Biggest Handicap reduction. [cite: 64]
        * [cite_start]**The Conqueror (+10 RP):** League Leader. [cite: 65]
        * [cite_start]**The Sniper (+5 RP):** Best Gross Score (Monthly). [cite: 66]
        
        [cite_start]**The Checkpoint Podium [cite: 67]**
        * [cite_start]End of Season 1 Top 5 Bonus: 1st (+15), 2nd (+10), 3rd (+7), 4th (+4), 5th (+2). [cite: 70]
        """)

    [cite_start]with st.expander("5. RIVALRY CHALLENGES [cite: 71]"):
        st.markdown("""
        [cite_start]**The Alliance (2v2) [cite: 73]**
        * [cite_start]**Format:** Texas Scramble / Match Play. [cite: 74]
        * [cite_start]**Scoring:** Winners steal points. [cite: 77]
        * [cite_start]**Victory:** +5 RP per player. [cite: 79]
        * [cite_start]**Defeat:** -5 RP per player. [cite: 80]
        
        [cite_start]**The Duel (1v1 Scratch) [cite: 84]**
        * [cite_start]**Format:** Gross Stroke Play (No Handicaps). [cite: 85]
        * [cite_start]**Standard Stakes:** Favorite Wins (+5 RP), Loser (-5 RP). [cite: 89]
        * [cite_start]**Upset Stakes:** Underdog Wins (+10 RP). [cite: 90]
        """)

    [cite_start]with st.expander("6. LIVE HANDICAPS [cite: 92]"):
        st.markdown("""
        [cite_start]**Automatic Adjustments (HCP <= 36) [cite: 97]**
        * [cite_start]**40+ pts:** -2.0 [cite: 98]
        * [cite_start]**37-39 pts:** -1.0 [cite: 99]
        * [cite_start]**27-36 pts:** No Change [cite: 100]
        * [cite_start]**<27 pts:** +1.0 [cite: 101]
        
        [cite_start]**Sandbagger Protocol (HCP > 36) [cite: 102]**
        * Cut 1.0 stroke per point over 36.
        
        [cite_start]**Away Game Protocol [cite: 103]**
        * Par 70+ courses:
        * [cite_start]HCP 0-10: +3 Shots [cite: 107]
        * [cite_start]HCP 11-20: +5 Shots [cite: 107]
        * [cite_start]HCP 21+: +7 Shots [cite: 108]
        """)
