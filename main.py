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
        
        # Default Columns
        defaults = {
            "holes_played": "18", "gross_score": 0, "match_type": "Standard", "notes": "", "stableford_score": 0, "rp_earned": 0
        }
        for col, val in defaults.items():
            if col not in rounds.columns: rounds[col] = val
        
        # Type Conversion
        rounds["holes_played"] = rounds["holes_played"].fillna("18").astype(str)
        rounds["gross_score"] = rounds["gross_score"].fillna(0).astype(int)
        rounds["stableford_score"] = rounds["stableford_score"].fillna(0).astype(int)
        rounds["rp_earned"] = rounds["rp_earned"].fillna(0).astype(int)
        rounds["date"] = pd.to_datetime(rounds["date"], errors='coerce')
        
        return players, rounds
    except Exception:
        return pd.DataFrame(columns=["name", "handicap"]), pd.DataFrame()

def calculate_standard_rp(score, holes, is_clean, is_road, is_hio, group_data, current_player, player_rp_map):
    breakdown = []
    
    # 1. Base Participation & Performance
    is_9 = (str(holes) == "9")
    part_pts = 1 if is_9 else 2
    target = 18 if is_9 else 36
    
    diff = score - target
    perf_pts = diff * 2 if diff >= 0 else int(diff / 2)
    
    total = part_pts + perf_pts
    breakdown.append(f"Base({total})")
    
    # 2. Individual Bonuses
    if is_clean and not is_9:
        total += 2
        breakdown.append("Clean(+2)")
    if is_road:
        total += 2
        breakdown.append("Road(+2)")
    if is_hio:
        total += 10
        breakdown.append("HIO(+10)")
        
    # 3. Group Bonuses (Winner of Day)
    if group_data:
        best_score = max(p['score'] for p in group_data)
        if score == best_score:
            n_players = len(group_data)
            win_bonus = 0
            if n_players == 2: win_bonus = 2
            elif n_players == 3: win_bonus = 4
            elif n_players >= 4: win_bonus = 6
            
            if is_9: win_bonus = int(win_bonus / 2)
            
            if win_bonus > 0:
                total += win_bonus
                breakdown.append(f"Win(+{win_bonus})")
    
    # 4. Giant Slayer
    if group_data and current_player in player_rp_map:
        my_total_rank_pts = player_rp_map.get(current_player, 0)
        slayer_count = 0
        for opponent in group_data:
            opp_name = opponent['name']
            opp_score = opponent['score']
            if opp_name != current_player:
                if score > opp_score:
                    opp_rank_pts = player_rp_map.get(opp_name, 0)
                    if opp_rank_pts > my_total_rank_pts:
                        slayer_count += 1
        
        if slayer_count > 0:
            total += slayer_count
            breakdown.append(f"Slayer(+{slayer_count})")

    return total, ", ".join(breakdown)

def get_season(date_obj):
    if pd.isnull(date_obj): return "Unknown"
    y, d = date_obj.year, date_obj.date()
    if datetime.date(y, 1, 1) <= d <= datetime.date(y, 3, 31): return "Season 1"
    if datetime.date(y, 4, 1) <= d <= datetime.date(y, 6, 20): return "Season 2"
    return "Off-Season"

# --- APP START ---
conn = st.connection("gsheets", type=GSheetsConnection)
df_players, df_rounds = load_data(conn)
player_list = df_players["name"].tolist() if not df_players.empty else []

# --- 1. STATS CALCULATION ---
stats = df_players.copy().rename(columns={"name": "player_name"}).set_index("player_name")
for c in ["Tournament 1 Ranking Points", "Season 1", "Season 2", "Rounds", "Avg Score", "Best Gross", "1v1 Wins", "1v1 Losses", "Daily Wins"]: stats[c] = 0
stats["2v2 Record"] = "0-0-0"
current_rp_map = {}

if not df_rounds.empty:
    for i, r in df_rounds.iterrows():
        p, rp = r["player_name"], r["rp_earned"]
        if p in stats.index and pd.notnull(r["date"]):
            stats.at[p, "Tournament 1 Ranking Points"] += rp
            current_rp_map[p] = stats.at[p, "Tournament 1 Ranking Points"]
            
            s = get_season(r["date"])
            if s in stats.columns: stats.at[p, s] += rp
            
            if r["match_type"] in ["Standard", "Duel"]:
                stats.at[p, "Rounds"] += 1

    # Avg & Best Gross (Standard OR Duel, 18H)
    valid_18 = df_rounds[
        (df_rounds["holes_played"] == "18") & 
        (df_rounds["match_type"].isin(["Standard", "Duel"]))
    ]
    if not valid_18.empty:
        # Avg (Stableford) - Only Standard usually counts for Avg, but user said 1v1 counts for sniper. Keeping Avg to Standard/Duel is safer.
        # Actually user said "Sniper... from standard and 1v1". He didn't specify Avg. Usually Avg is Standard only.
        # Let's keep Avg to Standard+Duel to be consistent with "Rounds Played"
        avg = valid_18.groupby("player_name")["stableford_score"].mean()
        stats["Avg Score"] = stats["Avg Score"].add(avg, fill_value=0)
        
        # Best Gross
        gross_recs = valid_18[valid_18["gross_score"] > 0]
        if not gross_recs.empty:
            best = gross_recs.groupby("player_name")["gross_score"].min()
            for p, val in best.items():
                if p in stats.index: stats.at[p, "Best Gross"] = val

    # Records
    duels = df_rounds[df_rounds["match_type"] == "Duel"]
    if not duels.empty:
        stats["1v1 Wins"] = stats["1v1 Wins"].add(duels[duels["rp_earned"] > 0].groupby("player_name").size(), fill_value=0)
        stats["1v1 Losses"] = stats["1v1 Losses"].add(duels[duels["rp_earned"] < 0].groupby("player_name").size(), fill_value=0)
    
    allies = df_rounds[df_rounds["match_type"] == "Alliance"]
    if not allies.empty:
        w = allies[allies["rp_earned"] > 0].groupby("player_name").size()
        t = allies[allies["rp_earned"] == 0].groupby("player_name").size()
        l = allies[allies["rp_earned"] < 0].groupby("player_name").size()
        for p in stats.index:
            stats.at[p, "2v2 Record"] = f"{int(w.get(p,0))}-{int(t.get(p,0))}-{int(l.get(p,0))}"
    
    # Daily Wins
    # Standard
    std_only = df_rounds[df_rounds["match_type"] == "Standard"]
    for (d, c), g in std_only.groupby(["date", "course"]):
        if not g.empty:
            m = g["stableford_score"].max()
            for winner in g[g["stableford_score"] == m]["player_name"].unique():
                if winner in stats.index: stats.at[winner, "Daily Wins"] += 1
    # Duels
    for winner in duels[duels["rp_earned"] > 0]["player_name"]:
        if winner in stats.index: stats.at[winner, "Daily Wins"] += 1

# --- 2. TROPHY LOGIC (UPDATED RULES) ---
holder_rock, holder_sniper, holder_conq = None, None, None

# Rock: Best Avg (Min 3 Rounds)
q_rock = stats[stats["Rounds"] >= 3].sort_values("Avg Score", ascending=False)
if not q_rock.empty:
    holder_rock = q_rock.index[0]
    stats.at[holder_rock, "Tournament 1 Ranking Points"] += 10

# Sniper: Lowest Gross (Month) - Standard OR Duel (18H)
curr = datetime.date.today()
m_rnds = df_rounds[
    (df_rounds["date"].dt.month == curr.month) & 
    (df_rounds["date"].dt.year == curr.year) & 
    (df_rounds["gross_score"] > 0) & 
    (df_rounds["holes_played"] == "18") &
    (df_rounds["match_type"].isin(["Standard", "Duel"]))
]
if not m_rnds.empty:
    min_g = m_rnds["gross_score"].min()
    s_list = m_rnds[m_rnds["gross_score"] == min_g]["player_name"].unique()
    if len(s_list) > 0:
        holder_sniper = s_list[0]
        stats.at[holder_sniper, "Tournament 1 Ranking Points"] += 5

# Conqueror: Most Wins (Min 3 Rounds)
# Filter for Min 3 Rounds first
eligible_conq = stats[stats["Rounds"] >= 3]
if not eligible_conq.empty:
    q_conq = eligible_conq.sort_values(["Daily Wins", "Tournament 1 Ranking Points"], ascending=False)
    if not q_conq.empty and q_conq.iloc[0]["Daily Wins"] > 0:
        holder_conq = q_conq.index[0]
        stats.at[holder_conq, "Tournament 1 Ranking Points"] += 10

# Final Formatting
stats["Avg Score"] = stats["Avg Score"].round(1)
stats = stats.sort_values("Tournament 1 Ranking Points", ascending=False).reset_index()
def decorate(row):
    n, i = row["player_name"], ""
    if n == holder_rock: i += " 🪨"
    if n == holder_sniper: i += " 🎯"
    if n == holder_conq: i += " 👑"
    return f"{n}{i}"
stats["Player"] = stats.apply(decorate, axis=1)

# --- UI START ---
st.title("🏆 Fantasy Golf 2026")

tab_leaderboard, tab_trophy, tab_submit, tab_history, tab_admin, tab_rules = st.tabs([
    "🌍 Leaderboard", "🏆 Trophy Room", "📝 Submit Round", "📜 History", "⚙️ Admin", "📘 Rulebook"
])

# =========================================================
# TAB 1: LEADERBOARD
# =========================================================
with tab_leaderboard:
    st.header("Live Standings")
    v = stats[["Player", "Tournament 1 Ranking Points", "Season 1", "Season 2", "handicap", "Best Gross", "Rounds", "Avg Score", "1v1 Wins", "1v1 Losses", "2v2 Record", "Daily Wins"]].copy()
    v["1v1 Record"] = v["1v1 Wins"].astype(int).astype(str) + "-" + v["1v1 Losses"].astype(int).astype(str)
    v = v.drop(columns=["1v1 Wins", "1v1 Losses"]).rename(columns={"handicap": "Handicap", "Best Gross": "Best Round"})
    
    def color_row(row):
        if row.name == 0: return ['background-color: #FFA500; color: black'] * len(row)
        if 1 <= row.name <= 3: return ['background-color: #FFFFE0; color: black'] * len(row)
        return [''] * len(row)

    st.dataframe(v.style.apply(color_row, axis=1).format({"Handicap": "{:.0f}"}), use_container_width=True, hide_index=True)
    st.caption("🔶 **Orange:** Leader | 🟡 **Yellow:** Top 4 | 🏆 **Bonuses:** 🪨 Rock(+10) 🎯 Sniper(+5) 👑 Conqueror(+10)")

# =========================================================
# TAB 2: TROPHY ROOM
# =========================================================
with tab_trophy:
    st.header("🏆 The Hall of Fame")
    def txt(h, v, l): return f"{h}\n\n*({v} {l})*" if h else "Unclaimed"
    rv = stats[stats["player_name"] == holder_rock]["Avg Score"].values[0] if holder_rock else 0
    sv = min_g if holder_sniper else 0
    cv = stats[stats["player_name"] == holder_conq]["Daily Wins"].values[0] if holder_conq else 0

    st.markdown("""<style>.trophy-card { background-color: #262730; padding: 20px; border-radius: 10px; border: 1px solid #4B4B4B; text-align: center; } .t-icon { font-size: 40px; } .t-head { font-size: 18px; font-weight: bold; color: #FFD700; margin-top: 5px; } .t-sub { font-size: 12px; color: #A0A0A0; margin-bottom: 10px; } .t-name { font-size: 20px; font-weight: bold; color: white; } .t-bonus { color: #00FF00; font-weight: bold; font-size: 14px; margin-top: 5px; }</style>""", unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    def card(c, i, t, d, w, b, r): c.markdown(f"""<div class="trophy-card"><div class="t-icon">{i}</div><div class="t-head">{t}</div><div class="t-sub">{d}<br><i>{r}</i></div><div class="t-name">{w}</div><div class="t-bonus">{b}</div></div>""", unsafe_allow_html=True)
    card(c1, "🪨", "The Rock", "Best Avg", txt(holder_rock, rv, "Avg"), "+10", "Min 3 Rounds")
    card(c2, "🚀", "The Rocket", "Biggest HCP Drop", "Unclaimed", "+10", "Min 3 Rounds")
    card(c3, "🎯", "The Sniper", "Best Gross (Month)", txt(holder_sniper, sv, "Strks"), "+5", "Std or 1v1 (18H)")
    card(c4, "👑", "The Conqueror", "Most Wins", txt(holder_conq, cv, "Wins"), "+10", "Min 3 Rounds")

# =========================================================
# TAB 3: SUBMIT ROUND
# =========================================================
with tab_submit:
    st.subheader("Choose Game Mode")
    mode = st.radio("Format:", ["Standard Round", "The Duel (1v1)", "The Alliance (2v2)"], horizontal=True, label_visibility="collapsed")
    
    if mode == "Standard Round":
        st.info("Submit scores for the group.")
        
        # --- FIX: MULTISELECT OUTSIDE FORM TO PREVENT DISAPPEARING INPUTS ---
        selected_players = st.multiselect("Select Players", player_list)
        
        with st.form("std_form"):
            st.divider()
            c1, c2, c3 = st.columns(3)
            dt = c1.date_input("Date", datetime.date.today())
            crs = c2.text_input("Course", "Chinderah")
            hl = c3.radio("Length", ["18", "9"], horizontal=True)
            
            input_data = []
            if selected_players:
                for p in selected_players:
                    st.markdown(f"**{p}**")
                    ca, cb, cc = st.columns([1, 1, 2])
                    sf = ca.number_input(f"Stableford ({p})", 0, 60, key=f"s_{p}")
                    gr = cb.number_input(f"Gross ({p})", 0, 150, key=f"g_{p}")
                    
                    bon = cc.columns(3)
                    cl = bon[0].checkbox("Clean?", key=f"c_{p}")
                    rw = bon[1].checkbox("New Crs?", key=f"r_{p}")
                    ho = bon[2].checkbox("HIO?", key=f"h_{p}")
                    input_data.append({'name':p, 'score':sf, 'gross':gr, 'cl':cl, 'rw':rw, 'ho':ho})
            
            if st.form_submit_button("Submit Scorecards"):
                if not selected_players:
                    st.error("Select players first.")
                else:
                    group_scores = [{'name': d['name'], 'score': d['score']} for d in input_data]
                    new_rows = []
                    for d in input_data:
                        rp, note = calculate_standard_rp(d['score'], hl, d['cl'], d['rw'], d['ho'], group_scores, d['name'], current_rp_map)
                        new_rows.append({
                            "date": str(dt), "course": crs, "player_name": d['name'], "holes_played": hl,
                            "stableford_score": d['score'], "gross_score": d['gross'],
                            "rp_earned": rp, "notes": note, "match_type": "Standard"
                        })
                    conn.update(worksheet="rounds", data=pd.concat([df_rounds, pd.DataFrame(new_rows)], ignore_index=True), spreadsheet=SPREADSHEET_NAME)
                    st.success(f"Saved!")
                    st.rerun()

    elif mode == "The Duel (1v1)":
        with st.form("duel_form"):
            st.warning("⚔️ **1v1 STAKES**")
            c1, c2 = st.columns(2)
            p1 = c1.selectbox("P1", player_list)
            p2 = c2.selectbox("P2", player_list, index=1)
            winner = st.radio("Winner:", [p1, p2], horizontal=True)
            
            c3, c4, c5 = st.columns(3)
            dt = c3.date_input("Date")
            crs = c4.text_input("Course", "Chinderah")
            hl = c5.radio("L", ["18", "9"], horizontal=True)
            
            st.divider()
            c6, c7 = st.columns(2)
            g1 = c6.number_input(f"{p1} Gross", 0)
            g2 = c7.number_input(f"{p2} Gross", 0)
            stake = st.radio("Type", ["Standard (+5/-5)", "Upset (+10/-10)"])
            
            if st.form_submit_button("Record Duel"):
                if p1 == p2: st.error("Same player selected.")
                else:
                    win_p, lose_p = winner, (p2 if winner == p1 else p1)
                    steal = 10 if "Upset" in stake else 5
                    base = 1 if hl=="9" else 2
                    w_note = f"Base(+{base}), Duel Win(+{steal})"
                    l_note = f"Base(+{base}), Duel Loss(-{steal})"
                    rows = [
                        {"date":str(dt), "course":crs, "player_name":win_p, "holes_played":hl, "gross_score":(g1 if win_p==p1 else g2), "rp_earned": base+steal, "notes":w_note, "match_type":"Duel"},
                        {"date":str(dt), "course":crs, "player_name":lose_p, "holes_played":hl, "gross_score":(g2 if win_p==p1 else g1), "rp_earned": base-steal, "notes":l_note, "match_type":"Duel"}
                    ]
                    conn.update(worksheet="rounds", data=pd.concat([df_rounds, pd.DataFrame(rows)], ignore_index=True), spreadsheet=SPREADSHEET_NAME)
                    st.success("Duel Saved!")
                    st.rerun()

    elif mode == "The Alliance (2v2)":
        with st.form("ally_form"):
            c1, c2 = st.columns(2)
            w1 = c1.selectbox("Win 1", player_list, key="w1")
            w2 = c1.selectbox("Win 2", player_list, key="w2")
            wh = c1.number_input("Holes", 0, 18, key="wh")
            l1 = c2.selectbox("Lose 1", player_list, key="l1")
            l2 = c2.selectbox("Lose 2", player_list, key="l2")
            lh = c2.number_input("Holes", 0, 18, key="lh")
            
            dt = st.date_input("Date")
            crs = st.text_input("Course")
            
            if st.form_submit_button("Submit 2v2"):
                rows = []
                def is_debut(p):
                    # Check if player has any Alliance matches before today
                    past = df_rounds[(df_rounds["player_name"]==p) & (df_rounds["match_type"]=="Alliance")]
                    return len(past) == 0

                for p in [w1, w2]: 
                    bonus = 5 if is_debut(p) else 0
                    note = f"Win ({wh}-{lh})"
                    if bonus: note += ", Duo Debut(+5)"
                    rows.append({"date":str(dt), "course":crs, "player_name":p, "holes_played":"18", "rp_earned": 5+bonus, "notes":note, "match_type":"Alliance"})
                
                for p in [l1, l2]:
                    bonus = 5 if is_debut(p) else 0
                    note = f"Loss ({wh}-{lh})"
                    if bonus: note += ", Duo Debut(+5)"
                    rows.append({"date":str(dt), "course":crs, "player_name":p, "holes_played":"18", "rp_earned": -5+bonus, "notes":note, "match_type":"Alliance"})
                
                conn.update(worksheet="rounds", data=pd.concat([df_rounds, pd.DataFrame(rows)], ignore_index=True), spreadsheet=SPREADSHEET_NAME)
                st.success("Alliance Saved!")
                st.rerun()

# =========================================================
# TAB 4: HISTORY
# =========================================================
with tab_history:
    st.header("📜 League History")
    if not df_rounds.empty:
        df_show = df_rounds.copy()
        df_show['d_str'] = df_show['date'].dt.strftime('%Y-%m-%d')
        df_show = df_show.sort_values("date", ascending=False)
        groups = df_show.groupby(['d_str', 'course', 'match_type'], sort=False)
        
        for (d, c, t), g in groups:
            with st.expander(f"📅 {d} | {c} | {t} ({len(g)} Players)"):
                edited = st.data_editor(
                    g[["player_name", "stableford_score", "gross_score", "rp_earned", "notes"]],
                    key=f"e_{d}_{c}_{t}",
                    use_container_width=True,
                    num_rows="dynamic"
                )
                
                col_s, col_d = st.columns([1, 4])
                if col_s.button("Save", key=f"s_{d}_{c}_{t}"):
                    # Drop old by index
                    df_rounds = df_rounds.drop(g.index)
                    # Create new from edited
                    save_df = edited.copy()
                    save_df["date"] = pd.to_datetime(d)
                    save_df["course"] = c
                    save_df["match_type"] = t
                    save_df["holes_played"] = g.iloc[0]["holes_played"]
                    
                    df_rounds = pd.concat([df_rounds, save_df], ignore_index=True)
                    conn.update(worksheet="rounds", data=df_rounds, spreadsheet=SPREADSHEET_NAME)
                    st.success("Updated!")
                    st.rerun()
                    
                if col_d.button("Delete Match", key=f"d_{d}_{c}_{t}"):
                    df_rounds = df_rounds.drop(g.index)
                    conn.update(worksheet="rounds", data=df_rounds, spreadsheet=SPREADSHEET_NAME)
                    st.error("Deleted!")
                    st.rerun()

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
        if st.form_submit_button("Delete"):
            conn.update(worksheet="players", data=df_players[df_players["name"]!=d], spreadsheet=SPREADSHEET_NAME)
            st.rerun()

# =========================================================
# TAB 6: RULEBOOK
# =========================================================
with tab_rules:
    st.header("📘 Official Rulebook 2026")
    with st.expander("1. HOW WE PLAY (STABLEFORD)", expanded=True):
        st.markdown("""
        **Stableford Scoring:**
        * **Golden Rule:** Play against your "Personal Par" (Net Par).
        * **Points:** Albatross (5), Eagle (4), Birdie (3), Par (2), Bogey (1), Double+ (0).
        * *No Gimmes.*
        """)
    with st.expander("2. THE CALENDAR"):
        st.markdown("""
        * **Tournament 1:** Jan 1 - Jun 20. (Top 4 -> King's Cup).
        * **Tournament 2:** Jul 1 - Dec 20. (Grand Finals).
        """)
    with st.expander("3. PERFORMANCE RANKING (RP)"):
        st.markdown("""
        **Target: 36 Pts (18H) | 18 Pts (9H)**
        * **Positive (>36):** (Score - 36) * 2 = RP Gained.
        * **Negative (<36):** (Score - 36) / 2 = RP Lost.
        * **9-Hole:** Participation +1 RP.
        """)
    with st.expander("4. BONUSES & AWARDS"):
        st.markdown("""
        **Match Bonuses:**
        * **Participation:** +2 (18H) | +1 (9H).
        * **Winner of Day:** +2 (2p), +4 (3p), +6 (4p+). (Halved for 9H).
        * **Giant Slayer:** +1 per higher-ranked opponent beaten.
        * **Clean Sheet:** +2 (No wipes).
        * **Road Warrior:** +2 (New Course).
        * **Duo Debut:** +5 (First 2v2).
        * **HIO:** +10.
        
        **Seasonal Awards (Floating):**
        * 🪨 **The Rock (+10):** Best Avg.
        * 🚀 **The Rocket (+10):** HCP Drop.
        * 🎯 **The Sniper (+5):** Low Gross (Month).
        * 👑 **The Conqueror (+10):** Most Wins.
        """)
    with st.expander("5. RIVALRY CHALLENGES"):
        st.markdown("""
        **Alliance (2v2):** Winners +5, Losers -5.
        **Duel (1v1):** Winner +5/+10, Loser -5/-10.
        """)
    with st.expander("6. LIVE HANDICAPS"):
        st.markdown("""
        * **40+ pts:** -2.0
        * **37-39 pts:** -1.0
        * **<27 pts:** +1.0
        * **Away Game:** +3 to +7 shots.
        """)
