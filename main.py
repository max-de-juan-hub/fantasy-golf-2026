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

# --- SIDEBAR: FORCE RELOAD ---
if st.sidebar.button("🔄 Reload Data (Clear Cache)"):
    st.cache_data.clear()
    st.rerun()

# --- CONSTANTS ---
SPREADSHEET_NAME = "fantasy_golf_db"

# --- HELPER FUNCTIONS ---
def load_data(conn):
    # READ DATA NO CACHE (ttl=0)
    try:
        players = conn.read(worksheet="players", spreadsheet=SPREADSHEET_NAME, ttl=0)
        rounds = conn.read(worksheet="rounds", spreadsheet=SPREADSHEET_NAME, ttl=0)
    except Exception as e:
        st.error(f"Connection Error: {e}")
        return pd.DataFrame(), pd.DataFrame()
    
    # 1. Ensure Columns
    defaults = {
        "holes_played": "18", "gross_score": 0, "match_type": "Standard", 
        "notes": "", "stableford_score": 0, "rp_earned": 0, "course": "Unknown",
        "date": str(datetime.date.today())
    }
    for col, val in defaults.items():
        if col not in rounds.columns: 
            rounds[col] = val

    # 2. CLEAN UP NUMBERS (Force 0 instead of crash)
    rounds["holes_played"] = rounds["holes_played"].fillna("18").astype(str)
    
    for col in ["gross_score", "stableford_score", "rp_earned"]:
        # Coerce errors to NaN, then fill with 0
        rounds[col] = pd.to_numeric(rounds[col], errors='coerce').fillna(0).astype(int)

    # 3. CLEAN UP DATES (The likely culprit)
    # dayfirst=True handles 31/01/2026 correctly. errors='coerce' turns bad dates into NaT
    rounds["date"] = pd.to_datetime(rounds["date"], dayfirst=True, errors='coerce')
    
    # Remove rows where date is completely broken (NaT), but keep everything else
    rounds = rounds.dropna(subset=["date"])
    
    return players, rounds

def calculate_new_handicap(current_hcp, score):
    current_hcp = float(current_hcp)
    score = int(score)
    if current_hcp > 36.0:
        if score > 36: return max(0.0, current_hcp - float(score - 36))
        else: return current_hcp if score >= 27 else current_hcp + 1.0
    else:
        if score >= 40: return max(0.0, current_hcp - 2.0)
        elif score >= 37: return max(0.0, current_hcp - 1.0)
        elif score < 27: return current_hcp + 1.0
        else: return current_hcp

def calculate_standard_rp(score, holes, is_clean, is_road, is_hio, group_data, current_player, player_rp_map):
    breakdown = []
    is_9 = (str(holes) == "9")
    part_pts = 1 if is_9 else 2
    
    target = 18 if is_9 else 36
    diff = score - target
    perf_pts = diff * 2 if diff >= 0 else int(diff / 2)
    
    breakdown.append(f"Part(+{part_pts})")
    breakdown.append(f"Perf({'+' if perf_pts>0 else ''}{perf_pts})")
    
    total = part_pts + perf_pts
    
    if is_clean and not is_9: total += 2; breakdown.append("Clean(+2)")
    if is_road: total += 2; breakdown.append("Road(+2)")
    if is_hio: total += 10; breakdown.append("HIO(+10)")
        
    if group_data:
        best_score = max(p['score'] for p in group_data)
        if score == best_score:
            n = len(group_data)
            wb = 0
            if n == 2: wb = 2
            elif n == 3: wb = 4
            elif n >= 4: wb = 6
            if is_9: wb = int(wb / 2)
            if wb > 0: total += wb; breakdown.append(f"Win(+{wb})")
    
    if group_data and current_player in player_rp_map:
        my_total = player_rp_map.get(current_player, 0)
        slayer = 0
        for opp in group_data:
            if opp['name'] != current_player and score > opp['score']:
                if player_rp_map.get(opp['name'], 0) > my_total: slayer += 1
        if slayer > 0: total += slayer; breakdown.append(f"Slayer(+{slayer})")

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

# --- 1. STATS ENGINE ---
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
            if r["match_type"] in ["Standard", "Duel"]: stats.at[p, "Rounds"] += 1

    # Avg (Standard Only)
    std_18 = df_rounds[(df_rounds["holes_played"] == "18") & (df_rounds["match_type"] == "Standard")]
    if not std_18.empty:
        avg = std_18.groupby("player_name")["stableford_score"].mean()
        stats["Avg Score"] = stats["Avg Score"].add(avg, fill_value=0)
    
    # Best (Standard + Duel)
    valid_gross = df_rounds[(df_rounds["holes_played"] == "18") & (df_rounds["match_type"].isin(["Standard", "Duel"])) & (df_rounds["gross_score"] > 0)]
    if not valid_gross.empty:
        best = valid_gross.groupby("player_name")["gross_score"].min()
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
        for p in stats.index: stats.at[p, "2v2 Record"] = f"{int(w.get(p,0))}-{int(t.get(p,0))}-{int(l.get(p,0))}"
    
    # Daily Wins (Standard + Duel)
    for (d, c), g in std_18.groupby(["date", "course"]):
        if not g.empty:
            m = g["stableford_score"].max()
            for w in g[g["stableford_score"] == m]["player_name"].unique():
                if w in stats.index: stats.at[w, "Daily Wins"] += 1
    for w in duels[duels["rp_earned"] > 0]["player_name"]:
        if w in stats.index: stats.at[w, "Daily Wins"] += 1

# --- 2. TROPHY LOGIC ---
holder_rock, holder_sniper, holder_conq = None, None, None

def resolve_tie(cand, metric):
    if len(cand) == 1: return cand.index[0]
    best_val = cand[metric].max() if metric != "Best Gross" else cand[metric].min()
    tied = cand[cand[metric] == best_val]
    if len(tied) == 1: return tied.index[0]
    best_wins = tied["Daily Wins"].max()
    tied_wins = tied[tied["Daily Wins"] == best_wins]
    return tied_wins.index[0] if len(tied_wins) == 1 else "Tied"

q_rock = stats[stats["Rounds"] >= 3]
if not q_rock.empty:
    holder_rock = resolve_tie(q_rock, "Avg Score")
    if holder_rock != "Tied" and holder_rock: stats.at[holder_rock, "Tournament 1 Ranking Points"] += 10

curr = datetime.date.today()
m_rnds = df_rounds[(df_rounds["date"].dt.month == curr.month) & (df_rounds["date"].dt.year == curr.year) & (df_rounds["gross_score"] > 0) & (df_rounds["holes_played"] == "18") & (df_rounds["match_type"].isin(["Standard", "Duel"]))]
if not m_rnds.empty:
    min_g = m_rnds["gross_score"].min()
    s_list = m_rnds[m_rnds["gross_score"] == min_g]["player_name"].unique()
    if len(s_list) == 1: holder_sniper = s_list[0]
    else: 
        s_stats = stats[stats.index.isin(s_list)]
        holder_sniper = resolve_tie(s_stats, "Daily Wins")
    if holder_sniper != "Tied" and holder_sniper in stats.index: stats.at[holder_sniper, "Tournament 1 Ranking Points"] += 5

q_conq = stats[stats["Rounds"] >= 3]
if not q_conq.empty:
    holder_conq = resolve_tie(q_conq, "Daily Wins")
    if holder_conq != "Tied" and holder_conq: stats.at[holder_conq, "Tournament 1 Ranking Points"] += 10

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

with tab_trophy:
    st.header("🏆 The Hall of Fame")
    def txt(h, v, l): return "TIED\n*(Requires Head-to-Head)*" if h == "Tied" else (f"{h}\n\n*({v} {l})*" if h else "Unclaimed")
    rv = stats[stats["player_name"] == holder_rock]["Avg Score"].values[0] if holder_rock and holder_rock != "Tied" else 0
    sv = min_g if holder_sniper and holder_sniper != "Tied" else 0
    cv = stats[stats["player_name"] == holder_conq]["Daily Wins"].values[0] if holder_conq and holder_conq != "Tied" else 0
    st.markdown("""<style>.trophy-card { background-color: #262730; padding: 20px; border-radius: 10px; border: 1px solid #4B4B4B; text-align: center; } .t-icon { font-size: 40px; } .t-head { font-size: 18px; font-weight: bold; color: #FFD700; margin-top: 5px; } .t-sub { font-size: 12px; color: #A0A0A0; margin-bottom: 10px; } .t-name { font-size: 20px; font-weight: bold; color: white; } .t-bonus { color: #00FF00; font-weight: bold; font-size: 14px; margin-top: 5px; }</style>""", unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    def card(c, i, t, d, w, b, r): c.markdown(f"""<div class="trophy-card"><div class="t-icon">{i}</div><div class="t-head">{t}</div><div class="t-sub">{d}<br><i>{r}</i></div><div class="t-name">{w}</div><div class="t-bonus">{b}</div></div>""", unsafe_allow_html=True)
    card(c1, "🪨", "The Rock", "Best Avg", txt(holder_rock, rv, "Avg"), "+10", "Min 3 Rounds")
    card(c2, "🚀", "The Rocket", "Biggest HCP Drop", "Unclaimed", "+10", "Min 3 Rounds")
    card(c3, "🎯", "The Sniper", "Best Gross (Month)", txt(holder_sniper, sv, "Strks"), "+5", "Std or 1v1 (18H)")
    card(c4, "👑", "The Conqueror", "Most Wins", txt(holder_conq, cv, "Wins"), "+10", "Min 3 Rounds")

with tab_submit:
    st.subheader("Choose Game Mode")
    mode = st.radio("Format:", ["Standard Round", "The Duel (1v1)", "The Alliance (2v2)"], horizontal=True, label_visibility="collapsed")
    
    if mode == "Standard Round":
        st.info("Submit scores for the group.")
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
                    cl = bon[0].checkbox("Clean Sheet", key=f"c_{p}")
                    rw = bon[1].checkbox("New Course", key=f"r_{p}")
                    ho = bon[2].checkbox("Hole in One", key=f"h_{p}")
                    input_data.append({'name':p, 'score':sf, 'gross':gr, 'cl':cl, 'rw':rw, 'ho':ho})
            if st.form_submit_button("Submit Scorecards"):
                if not selected_players: st.error("Select players first.")
                else:
                    group_scores = [{'name': d['name'], 'score': d['score']} for d in input_data]
                    new_rows = []
                    for d in input_data:
                        rp, note = calculate_standard_rp(d['score'], hl, d['cl'], d['rw'], d['ho'], group_scores, d['name'], current_rp_map)
                        curr_hcp = df_players.loc[df_players["name"] == d['name'], "handicap"].values[0]
                        new_hcp = calculate_new_handicap(curr_hcp, d['score'])
                        df_players.loc[df_players["name"] == d['name'], "handicap"] = new_hcp
                        new_rows.append({"date": str(dt), "course": crs, "player_name": d['name'], "holes_played": hl, "stableford_score": d['score'], "gross_score": d['gross'], "rp_earned": rp, "notes": note, "match_type": "Standard"})
                    conn.update(worksheet="rounds", data=pd.concat([df_rounds, pd.DataFrame(new_rows)], ignore_index=True), spreadsheet=SPREADSHEET_NAME)
                    conn.update(worksheet="players", data=df_players, spreadsheet=SPREADSHEET_NAME)
                    st.cache_data.clear()
                    st.success(f"Saved {len(selected_players)} rounds! Handicaps updated.")
                    st.rerun()

    elif mode == "The Duel (1v1)":
        c1, c2 = st.columns(2)
        p1 = c1.selectbox("P1", player_list)
        p2 = c2.selectbox("P2", player_list, index=1 if len(player_list)>1 else 0)
        with st.form("duel_form"):
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
                    w_note = f"Part(+{base}), Duel Win(+{steal})"
                    l_note = f"Part(+{base}), Duel Loss(-{steal})"
                    rows = [{"date":str(dt), "course":crs, "player_name":win_p, "holes_played":hl, "gross_score":(g1 if win_p==p1 else g2), "rp_earned": base+steal, "notes":w_note, "match_type":"Duel"}, {"date":str(dt), "course":crs, "player_name":lose_p, "holes_played":hl, "gross_score":(g2 if win_p==p1 else g1), "rp_earned": base-steal, "notes":l_note, "match_type":"Duel"}]
                    conn.update(worksheet="rounds", data=pd.concat([df_rounds, pd.DataFrame(rows)], ignore_index=True), spreadsheet=SPREADSHEET_NAME)
                    st.cache_data.clear()
                    st.success("Duel Saved!")
                    st.rerun()

    elif mode == "The Alliance (2v2)":
        c1, c2 = st.columns(2)
        w1 = c1.selectbox("Win 1", player_list, key="w1")
        w2 = c1.selectbox("Win 2", player_list, key="w2")
        l1 = c2.selectbox("Lose 1", player_list, key="l1")
        l2 = c2.selectbox("Lose 2", player_list, key="l2")
        with st.form("ally_form"):
            c_h1, c_h2 = st.columns(2)
            wh = c_h1.number_input("Win Holes", 0, 18)
            lh = c_h2.number_input("Lose Holes", 0, 18)
            dt = st.date_input("Date")
            crs = st.text_input("Course")
            if st.form_submit_button("Submit 2v2"):
                rows = []
                def is_debut(p): return len(df_rounds[(df_rounds["player_name"]==p) & (df_rounds["match_type"]=="Alliance")]) == 0
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
                st.cache_data.clear()
                st.success("Alliance Saved!")
                st.rerun()

with tab_history:
    st.header("📜 League History")
    if not df_rounds.empty:
        df_show = df_rounds.copy()
        df_show['d_str'] = df_show['date'].dt.strftime('%Y-%m-%d')
        df_show = df_show.sort_values("date", ascending=False)
        groups = df_show.groupby(['d_str', 'course', 'match_type'], sort=False)
        for (d, c, t), g in groups:
            with st.expander(f"📅 {d} | {c} | {t} ({len(g)} Players)"):
                edited = st.data_editor(g[["player_name", "stableford_score", "gross_score", "rp_earned", "notes"]], key=f"e_{d}_{c}_{t}", use_container_width=True, num_rows="dynamic")
                col_s, col_d = st.columns([1, 4])
                if col_s.button("Save", key=f"s_{d}_{c}_{t}"):
                    df_rounds = df_rounds.drop(g.index)
                    save_df = edited.copy()
                    save_df["date"] = pd.to_datetime(d)
                    save_df["course"] = c
                    save_df["match_type"] = t
                    save_df["holes_played"] = g.iloc[0]["holes_played"]
                    conn.update(worksheet="rounds", data=pd.concat([df_rounds, save_df], ignore_index=True), spreadsheet=SPREADSHEET_NAME)
                    st.cache_data.clear()
                    st.success("Updated!")
                    st.rerun()
                if col_d.button("Delete Match", key=f"d_{d}_{c}_{t}"):
                    df_rounds = df_rounds.drop(g.index)
                    conn.update(worksheet="rounds", data=df_rounds, spreadsheet=SPREADSHEET_NAME)
                    st.cache_data.clear()
                    st.error("Deleted!")
                    st.rerun()

with tab_admin:
    st.header("⚙️ Admin")
    st.write("### 🔍 Debug Data (Raw from Google Sheets)")
    with st.expander("Show Raw Dataframes"):
        st.write("#### Rounds Data", df_rounds)
        st.write("#### Players Data", df_players)
    
    st.divider()
    with st.form("add_p"):
        n = st.text_input("Name")
        h = st.number_input("Handicap", 0.0)
        if st.form_submit_button("Add"):
            conn.update(worksheet="players", data=pd.concat([df_players, pd.DataFrame([{"name":n, "handicap":h}])], ignore_index=True), spreadsheet=SPREADSHEET_NAME)
            st.cache_data.clear()
            st.rerun()
    with st.form("del_p"):
        d = st.selectbox("Delete", player_list)
        if st.form_submit_button("Delete"):
            conn.update(worksheet="players", data=df_players[df_players["name"]!=d], spreadsheet=SPREADSHEET_NAME)
            st.cache_data.clear()
            st.rerun()

with tab_rules:
    st.header("📘 Official Rulebook 2026")
    with st.expander("1. HOW WE PLAY (STABLEFORD)", expanded=True):
        st.markdown("**Stableford Scoring:**\n* **Golden Rule:** Play against your 'Personal Par' (Net Par).\n* **Points:** Albatross (5), Eagle (4), Birdie (3), Par (2), Bogey (1), Double+ (0).")
    with st.expander("2. THE CALENDAR"): st.markdown("* **Tournament 1:** Jan 1 - Jun 20.\n* **Tournament 2:** Jul 1 - Dec 20.")
    with st.expander("3. PERFORMANCE RANKING (RP)"): st.markdown("**Target: 36 Pts (18H) | 18 Pts (9H)**\n* **Positive (>36):** (Score - 36) * 2 = RP Gained.\n* **Negative (<36):** (Score - 36) / 2 = RP Lost.")
    with st.expander("4. BONUSES & AWARDS"): st.markdown("**Match Bonuses:**\n* Part(+2), Win(+2-6), Slayer(+1), Clean(+2), Road(+2), HIO(+10).\n**Seasonal Awards:** Rock, Rocket, Sniper, Conqueror.")
    with st.expander("5. RIVALRY CHALLENGES"): st.markdown("**Alliance (2v2):** +/-5.\n**Duel (1v1):** +/-5 or +/-10.")
    with st.expander("6. LIVE HANDICAPS"): st.markdown("* **40+ pts:** -2.0\n* **37-39 pts:** -1.0\n* **<27 pts:** +1.0\n* **Away Game:** +3 to +7 shots.")
