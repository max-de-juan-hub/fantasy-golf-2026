import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import datetime
import time
import math

# --- CONFIGURATION ---
st.set_page_config(
    page_title="Fantasy Golf 2026",
    page_icon="⛳",
    layout="wide"
)

# --- CONSTANTS ---
SPREADSHEET_NAME = "fantasy_golf_db"
MAX_PARTICIPATION_RP = 20  # Cap per season

# --- HELPER: NUMBER FORMATTING ---
def fmt_num(val):
    if pd.isnull(val) or val == 0: return "-"
    if isinstance(val, (int, float)):
        if val % 1 == 0: return f"{int(val)}"
        return f"{val:.2f}"
    return str(val)

# --- HELPER FUNCTIONS ---
def load_data(conn):
    st.cache_data.clear()
    try:
        players = conn.read(worksheet="players", spreadsheet=SPREADSHEET_NAME, ttl=0)
        rounds = conn.read(worksheet="rounds", spreadsheet=SPREADSHEET_NAME, ttl=0)
    except Exception as e:
        st.warning(f"Connection Note: {e}")
        return pd.DataFrame(), pd.DataFrame()
    
    if players.empty:
        players = pd.DataFrame(columns=["name", "handicap", "start_handicap"])
    
    for req in ["name", "handicap", "start_handicap"]:
        if req not in players.columns:
            if req == "name": players[req] = pd.Series(dtype='str')
            else: players[req] = 0.0

    defaults = {
        "holes_played": "18", "gross_score": 0, "match_type": "Standard", 
        "notes": "", "stableford_score": 0, "rp_earned": 0, "course": "Unknown",
        "date": str(datetime.date.today()), "match_id": "legacy", "part_rp": 0
    }
    
    if rounds.empty:
        rounds = pd.DataFrame(columns=list(defaults.keys()) + ["player_name"])

    for col, val in defaults.items():
        if col not in rounds.columns: rounds[col] = val

    rounds["holes_played"] = rounds["holes_played"].fillna("18").astype(str).str.replace(".0", "", regex=False)
    rounds["match_id"] = rounds["match_id"].astype(str).replace("nan", "legacy")
    
    for col in ["gross_score", "stableford_score", "rp_earned", "part_rp"]:
        rounds[col] = pd.to_numeric(rounds[col], errors='coerce').fillna(0).astype(int)

    rounds["date_parsed"] = pd.to_datetime(rounds["date"], dayfirst=True, errors='coerce')
    rounds["date"] = rounds["date_parsed"].fillna(pd.Timestamp.now())
    rounds = rounds.drop(columns=["date_parsed"])
    
    return players, rounds

def get_season(date_obj):
    if pd.isnull(date_obj): return "Unknown"
    y, d = date_obj.year, date_obj.date()
    if datetime.date(y, 1, 1) <= d <= datetime.date(y, 3, 31): return "Season 1"
    if datetime.date(y, 4, 1) <= d <= datetime.date(y, 6, 20): return "Season 2"
    return "Off-Season"

def calculate_new_handicap(current_hcp, score, holes="18"):
    # Normalize 9-hole scores
    is_9 = (str(holes) == "9")
    eff_score = score * 2 if is_9 else score
    current_hcp = float(current_hcp)
    
    # --- SANDBAGGER PROTOCOL (> 36.0) ---
    if current_hcp > 36.0:
        if eff_score > 36:
            # Drop 1.0 per point over 36, CAPPED at 10.0
            drop = float(eff_score - 36)
            actual_drop = min(drop, 10.0)
            return max(0.0, current_hcp - actual_drop)
        else:
            # For bad rounds > 36, apply standard bad day logic (+1.0)
            if eff_score <= 33: return current_hcp + 1.0 
            return current_hcp # 34-36 zone

    # --- STANDARD ADJUSTMENTS (<= 36.0) ---
    # God Day (45+)
    if eff_score >= 45: 
        return max(0.0, current_hcp - 5.0)
    
    # On Fire (40-44)
    elif eff_score >= 40: 
        return max(0.0, current_hcp - 2.0)
    
    # Good Day (37-39)
    elif eff_score >= 37: 
        return max(0.0, current_hcp - 1.0)
    
    # The Zone (34-36)
    elif eff_score >= 34: 
        return current_hcp
    
    # Bad Day (30-33)
    elif eff_score >= 30: 
        return current_hcp + 1.0
    
    # Disaster Day (< 30)
    else: 
        return current_hcp + 2.0

def recalculate_all_handicaps(df_rounds, df_players):
    hcp_map = {}
    for idx, row in df_players.iterrows():
        hcp_map[row["name"]] = row["start_handicap"]
        
    if not df_rounds.empty:
        sorted_rounds = df_rounds.sort_values("date", ascending=True)
        for idx, row in sorted_rounds.iterrows():
            if row["match_type"] == "Standard":
                p_name = row["player_name"]
                score = row["stableford_score"]
                holes = row["holes_played"]
                if p_name in hcp_map:
                    old_hcp = hcp_map[p_name]
                    new_hcp = calculate_new_handicap(old_hcp, score, holes)
                    hcp_map[p_name] = new_hcp
    
    for idx, row in df_players.iterrows():
        if row["name"] in hcp_map:
            df_players.at[idx, "handicap"] = hcp_map[row["name"]]
    return df_players

def calculate_standard_rp(score, holes, is_clean, is_road, is_hio, group_data, current_player, player_rp_map, current_season_part_rp):
    breakdown = []
    is_9 = (str(holes) == "9")
    
    # --- 1. PARTICIPATION (WITH CAP) ---
    potential_part = 2 if is_9 else 4
    
    remaining_cap = MAX_PARTICIPATION_RP - current_season_part_rp
    actual_part = min(potential_part, max(0, remaining_cap))
    
    if actual_part > 0:
        breakdown.append(f"Part(+{actual_part})")
    elif potential_part > 0:
        breakdown.append("Part(Cap Reached)")
        
    # --- 2. PERFORMANCE ---
    target = 18 if is_9 else 36
    diff = score - target
    perf_pts = diff * 2 if diff >= 0 else int(diff / 2)
    breakdown.append(f"Perf({'+' if perf_pts>0 else ''}{perf_pts})")
    
    total = actual_part + perf_pts
    
    # --- 3. BONUSES ---
    if is_clean:
        cs_pts = 1 if is_9 else 3
        total += cs_pts
        breakdown.append(f"Clean(+{cs_pts})")
        
    if is_road: total += 2; breakdown.append("Road(+2)")
    if is_hio: total += 10; breakdown.append("HIO(+10)")
        
    if group_data:
        best_score = max(p['score'] for p in group_data)
        if score == best_score:
            winners_count = sum(1 for p in group_data if p['score'] == best_score)
            n_players = len(group_data)
            total_pot = 0
            if n_players == 2: total_pot = 2
            elif n_players == 3: total_pot = 4
            elif n_players >= 4: total_pot = 6
            if is_9: total_pot = total_pot / 2
            
            share = math.ceil(total_pot / winners_count)
            if share > 0:
                total += int(share)
                breakdown.append(f"Win(+{int(share)})")
    
    if group_data and current_player in player_rp_map:
        my_total = player_rp_map.get(current_player, 0)
        slayer = 0
        for opp in group_data:
            if opp['name'] != current_player and score > opp['score']:
                if player_rp_map.get(opp['name'], 0) > my_total: slayer += 1
        if slayer > 0: total += slayer; breakdown.append(f"Slayer(+{slayer})")

    return total, ", ".join(breakdown), actual_part

# --- APP START ---
conn = st.connection("gsheets", type=GSheetsConnection)
df_players, df_rounds = load_data(conn)
player_list = df_players["name"].tolist() if not df_players.empty else []

# --- 1. STATS ENGINE ---
if df_players.empty:
    stats = pd.DataFrame()
else:
    stats = df_players.copy().rename(columns={"name": "player_name"}).set_index("player_name")
    for c in ["Tournament 1 Ranking Points", "Season 1", "Season 2", "Bonus RP S1", "Bonus RP S2", "Rounds", "Avg Score", "Best Gross", "1v1 Wins", "1v1 Losses", "Daily Wins", "Part RP S1", "Part RP S2"]: 
        stats[c] = 0
    stats["2v2 Record"] = "0-0-0"

current_rp_map = {}

if not df_rounds.empty and not stats.empty:
    df_rounds["season"] = df_rounds["date"].apply(get_season)
    
    season_rp = df_rounds.groupby(["player_name", "season"])["rp_earned"].sum().unstack(fill_value=0)
    part_rp_sum = df_rounds.groupby(["player_name", "season"])["part_rp"].sum().unstack(fill_value=0)
    
    for s in ["Season 1", "Season 2"]:
        if s in season_rp.columns: 
            stats[s] = stats[s].add(season_rp[s], fill_value=0)
        if s in part_rp_sum.columns:
            target_col = "Part RP S1" if s == "Season 1" else "Part RP S2"
            stats[target_col] = stats[target_col].add(part_rp_sum[s], fill_value=0)

    rounds_count = df_rounds.groupby("player_name").size()
    stats["Rounds"] = stats["Rounds"].add(rounds_count, fill_value=0)

    std_matches = df_rounds[df_rounds["match_type"] == "Standard"]
    if not std_matches.empty:
        std_matches["norm_score"] = std_matches.apply(
            lambda r: r["stableford_score"] * 2 if r["holes_played"] == "9" else r["stableford_score"], axis=1
        )
        avg = std_matches.groupby("player_name")["norm_score"].mean()
        stats["Avg Score"] = stats["Avg Score"].add(avg, fill_value=0)

    curr = datetime.date.today()
    month_rnds = df_rounds[
        (df_rounds["date"].dt.month == curr.month) & 
        (df_rounds["date"].dt.year == curr.year) & 
        (df_rounds["holes_played"] == "18") &
        (df_rounds["match_type"].isin(["Standard", "Duel"])) &
        (df_rounds["gross_score"] > 0)
    ]
    if not month_rnds.empty:
        best_month = month_rnds.groupby("player_name")["gross_score"].min()
        for p, val in best_month.items():
            if p in stats.index: stats.at[p, "Best Gross"] = val

    if not std_matches.empty:
        for mid, group in std_matches.groupby("match_id"):
            max_s = group["stableford_score"].max()
            winners = group[group["stableford_score"] == max_s]["player_name"].unique()
            for w in winners:
                if w in stats.index: stats.at[w, "Daily Wins"] += 1
    
    non_std = df_rounds[df_rounds["match_type"].isin(["Duel", "Alliance"])]
    if not non_std.empty:
        winners = non_std[non_std["rp_earned"] > 0]["player_name"]
        for w in winners:
            if w in stats.index: stats.at[w, "Daily Wins"] += 1

    duels = df_rounds[df_rounds["match_type"] == "Duel"]
    if not duels.empty:
        w = duels[duels["rp_earned"] > 0].groupby("player_name").size()
        l = duels[duels["rp_earned"] < 0].groupby("player_name").size()
        stats["1v1 Wins"] = stats["1v1 Wins"].add(w, fill_value=0)
        stats["1v1 Losses"] = stats["1v1 Losses"].add(l, fill_value=0)

    allies = df_rounds[df_rounds["match_type"] == "Alliance"]
    if not allies.empty:
        w = allies[allies["rp_earned"] > 0].groupby("player_name").size()
        t = allies[allies["rp_earned"] == 0].groupby("player_name").size()
        l = allies[allies["rp_earned"] < 0].groupby("player_name").size()
        for p in stats.index:
            stats.at[p, "2v2 Record"] = f"{int(w.get(p,0))}-{int(t.get(p,0))}-{int(l.get(p,0))}"

# --- 2. TROPHY LOGIC ---
holder_rock, holder_sniper, holder_conq, holder_rocket = None, None, None, None

current_season = get_season(datetime.datetime.now())
current_season_col = "Bonus RP S1" if current_season == "Season 1" else "Bonus RP S2"
if current_season == "Off-Season": current_season_col = "Bonus RP S1" 

def resolve_tie(cand, metric):
    if len(cand) == 1: return cand.index[0]
    is_gross = (metric == "Best Gross")
    if is_gross:
        cand = cand[cand[metric] > 0]
        if cand.empty: return None
        best_val = cand[metric].min()
    else:
        best_val = cand[metric].max()
    tied = cand[cand[metric] == best_val]
    if len(tied) == 1: return tied.index[0]
    best_wins = tied["Daily Wins"].max()
    tied_wins = tied[tied["Daily Wins"] == best_wins]
    return tied_wins.index[0] if len(tied_wins) == 1 else "Tied"

def award_bonus(holder, points):
    if holder and holder != "Tied" and holder in stats.index:
        stats.at[holder, current_season_col] += points

if not stats.empty:
    q_rock = stats[stats["Rounds"] >= 3]
    if not q_rock.empty:
        holder_rock = resolve_tie(q_rock, "Avg Score")
        award_bonus(holder_rock, 10)

    stats["HCP Reduction"] = stats.apply(lambda row: df_players.loc[df_players["name"]==row.name, "start_handicap"].values[0] - row["handicap"] if row.name in df_players["name"].values else 0, axis=1)
    q_rocket = stats[stats["Rounds"] >= 3]
    if not q_rocket.empty:
        q_rocket = q_rocket[q_rocket["HCP Reduction"] > 0]
        if not q_rocket.empty:
            holder_rocket = resolve_tie(q_rocket, "HCP Reduction")
            award_bonus(holder_rocket, 10)

    q_sniper = stats[stats["Best Gross"] > 0]
    if not q_sniper.empty:
        holder_sniper = resolve_tie(q_sniper, "Best Gross")
        award_bonus(holder_sniper, 5)

    q_conq = stats[stats["Rounds"] >= 3]
    if not q_conq.empty:
        holder_conq = resolve_tie(q_conq, "Daily Wins")
        award_bonus(holder_conq, 10)

    stats["Tournament 1 Ranking Points"] = stats["Season 1"] + stats["Bonus RP S1"] + stats["Season 2"] + stats["Bonus RP S2"]
    
    for p, val in stats["Tournament 1 Ranking Points"].items(): current_rp_map[p] = val

    stats = stats.sort_values("Tournament 1 Ranking Points", ascending=False).reset_index()
    def decorate(row):
        n, i = row["player_name"], ""
        if n == holder_rock: i += " 🪨"
        if n == holder_sniper: i += " 🎯"
        if n == holder_conq: i += " 👑"
        if n == holder_rocket: i += " 🚀"
        return f"{n}{i}"
    stats["Player"] = stats.apply(decorate, axis=1)

# --- UI ---
st.title("🏆 Fantasy Golf 2026")
tab_leaderboard, tab_trophy, tab_submit, tab_history, tab_admin, tab_rules = st.tabs(["🌍 Leaderboard", "🏆 Trophy Room", "📝 Submit Round", "📜 History", "⚙️ Admin", "📘 Rulebook"])

with tab_leaderboard:
    st.header("Live Standings")
    if stats.empty:
        st.info("👋 Welcome! No players found. Go to the 'Admin' tab to add players.")
    else:
        v = stats.copy()
        v["1v1 Record"] = v["1v1 Wins"].astype(int).astype(str) + "-" + v["1v1 Losses"].astype(int).astype(str)
        v = v.rename(columns={"handicap": "Handicap", "Best Gross": "Best Round", "Avg Score": "Average Stableford", "Rounds": "Rounds Played", "Season 1": "Season 1 RP", "Season 2": "Season 2 RP"})
        
        curr_part_col = "Part RP S1" if current_season == "Season 1" else "Part RP S2"
        if current_season == "Off-Season": curr_part_col = "Part RP S1"
        
        v["Part. Cap (20)"] = v[curr_part_col].astype(int).astype(str) + "/20"

        cols_order = ["Player", "Tournament 1 Ranking Points", "Handicap", "Daily Wins", "Best Round", "Average Stableford", "Rounds Played", "Part. Cap (20)", "1v1 Record", "2v2 Record", "Season 1 RP", "Bonus RP S1", "Season 2 RP", "Bonus RP S2"]
        final_cols = [c for c in cols_order if c in v.columns]
        v = v[final_cols]

        for col in v.columns:
            if col not in ["Player", "1v1 Record", "2v2 Record", "Part. Cap (20)"]:
                v[col] = v[col].apply(fmt_num)

        def color_row(row):
            if row.name == 0: return ['background-color: #FFA500; color: black'] * len(row)
            if 1 <= row.name <= 3: return ['background-color: #FFFFE0; color: black'] * len(row)
            return [''] * len(row)

        st.dataframe(
            v.style.apply(color_row, axis=1), 
            use_container_width=True, 
            hide_index=True,
            column_config={
                "Player": st.column_config.TextColumn("Player", width="medium")
            }
        )
        st.caption("🔶 **Orange:** Leader | 🟡 **Yellow:** Top 4 | 🏆 **Bonuses:** 🪨 Rock(+10) 🎯 Sniper(+5) 👑 Conqueror(+10) 🚀 Rocket(+10)")

with tab_trophy:
    st.header("🏆 The Hall of Fame")
    if stats.empty:
        st.info("Add players to see awards.")
    else:
        def txt(h, v, l): 
            if h == "Tied": return "TIED\n*(Head-to-Head)*"
            return f"{h}\n\n*({fmt_num(v)} {l})*" if h else "Unclaimed"
        
        def get_val(holder, metric):
            if not holder or holder == "Tied": return 0
            val = stats.loc[stats["player_name"] == holder, metric]
            return val.values[0] if not val.empty else 0

        rv = get_val(holder_rock, "Avg Score")
        sv = get_val(holder_sniper, "Best Gross")
        cv = get_val(holder_conq, "Daily Wins")
        rkv = get_val(holder_rocket, "HCP Reduction")
        
        st.markdown("""<style>.trophy-card { background-color: #262730; padding: 20px; border-radius: 10px; border: 1px solid #4B4B4B; text-align: center; } .t-icon { font-size: 40px; } .t-head { font-size: 18px; font-weight: bold; color: #FFD700; margin-top: 5px; } .t-sub { font-size: 12px; color: #A0A0A0; margin-bottom: 10px; } .t-name { font-size: 20px; font-weight: bold; color: white; } .t-bonus { color: #00FF00; font-weight: bold; font-size: 14px; margin-top: 5px; }</style>""", unsafe_allow_html=True)
        def card(c, i, t, d, w, b, r): 
            c.markdown(f"""<div class="trophy-card"><div class="t-icon">{i}</div><div class="t-head">{t}</div><div class="t-sub">{d}<br><i>{r}</i></div><div class="t-name">{w}</div><div class="t-bonus">{b}</div></div>""", unsafe_allow_html=True)

        c1, c2, c3, c4 = st.columns(4)
        card(c1, "🪨", "The Rock", "Best Avg", txt(holder_rock, rv, "Avg"), "+10", "Min 3 Rounds")
        card(c2, "🚀", "The Rocket", "Biggest HCP Drop", txt(holder_rocket, rkv, "Drop"), "+10", "Min 3 Rounds")
        card(c3, "🎯", "The Sniper", "Best Gross (Month)", txt(holder_sniper, sv, "Strks"), "+5", "Std or 1v1 (18H)")
        card(c4, "👑", "The Conqueror", "Most Wins", txt(holder_conq, cv, "Wins"), "+10", "Min 3 Rounds")

with tab_submit:
    st.subheader("Choose Game Mode")
    if player_list:
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
                        batch_id = f"{dt.strftime('%Y%m%d')}_{int(time.time())}"
                        group_scores = [{'name': d['name'], 'score': d['score']} for d in input_data]
                        
                        # --- PRE-CALC PARTICIPATION CAPS ---
                        current_season_part_map = {}
                        if not stats.empty:
                            target_col = "Part RP S1" if current_season == "Season 1" else "Part RP S2"
                            if current_season == "Off-Season": target_col = "Part RP S1"
                            for _, row in stats.iterrows():
                                current_season_part_map[row["player_name"]] = row[target_col]

                        new_rows = []
                        for d in input_data:
                            curr_part = current_season_part_map.get(d['name'], 0)
                            
                            rp, note, actual_part_earned = calculate_standard_rp(d['score'], hl, d['cl'], d['rw'], d['ho'], group_scores, d['name'], current_rp_map, curr_part)
                            
                            curr_hcp = df_players.loc[df_players["name"] == d['name'], "handicap"].values[0]
                            new_hcp = calculate_new_handicap(curr_hcp, d['score'], hl)
                            df_players.loc[df_players["name"] == d['name'], "handicap"] = new_hcp
                            
                            new_rows.append({
                                "date": str(dt), "course": crs, "player_name": d['name'], 
                                "holes_played": hl, "stableford_score": d['score'], 
                                "gross_score": d['gross'], "rp_earned": rp, 
                                "notes": note, "match_type": "Standard", "match_id": batch_id,
                                "part_rp": actual_part_earned
                            })
                        
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
                        batch_id = f"{dt.strftime('%Y%m%d')}_{int(time.time())}"
                        win_p, lose_p = winner, (p2 if winner == p1 else p1)
                        steal = 10 if "Upset" in stake else 5
                        w_note = f"Duel Win(+{steal})"
                        l_note = f"Duel Loss(-{steal})"
                        rows = [{"date":str(dt), "course":crs, "player_name":win_p, "holes_played":hl, "gross_score":(g1 if win_p==p1 else g2), "rp_earned": steal, "notes":w_note, "match_type":"Duel", "match_id": batch_id, "part_rp": 0}, {"date":str(dt), "course":crs, "player_name":lose_p, "holes_played":hl, "gross_score":(g2 if win_p==p1 else g1), "rp_earned": -steal, "notes":l_note, "match_type":"Duel", "match_id": batch_id, "part_rp": 0}]
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
                    batch_id = f"{dt.strftime('%Y%m%d')}_{int(time.time())}"
                    def is_debut(p): return len(df_rounds[(df_rounds["player_name"]==p) & (df_rounds["match_type"]=="Alliance")]) == 0
                    for p in [w1, w2]: 
                        bonus = 5 if is_debut(p) else 0
                        note = f"Win ({wh}-{lh})"
                        if bonus: note += ", Duo Debut(+5)"
                        rows.append({"date":str(dt), "course":crs, "player_name":p, "holes_played":"18", "rp_earned": 5+bonus, "notes":note, "match_type":"Alliance", "match_id": batch_id, "part_rp": 0})
                    for p in [l1, l2]:
                        bonus = 5 if is_debut(p) else 0
                        note = f"Loss ({wh}-{lh})"
                        if bonus: note += ", Duo Debut(+5)"
                        rows.append({"date":str(dt), "course":crs, "player_name":p, "holes_played":"18", "rp_earned": -5+bonus, "notes":note, "match_type":"Alliance", "match_id": batch_id, "part_rp": 0})
                    conn.update(worksheet="rounds", data=pd.concat([df_rounds, pd.DataFrame(rows)], ignore_index=True), spreadsheet=SPREADSHEET_NAME)
                    st.cache_data.clear()
                    st.success("Alliance Saved!")
                    st.rerun()
    else:
        st.warning("Please add players in the Admin tab to start submitting scores.")

with tab_history:
    st.header("📜 League History")
    if not df_rounds.empty:
        df_show = df_rounds.copy()
        df_show['d_str'] = df_show['date'].dt.strftime('%Y-%m-%d')
        df_show = df_show.sort_values("date", ascending=False)
        modern = df_show[df_show["match_id"] != "legacy"]
        legacy = df_show[df_show["match_id"] == "legacy"]
        groups = []
        if not modern.empty:
            for m_id, g in modern.groupby("match_id"):
                first = g.iloc[0]
                groups.append({"key": m_id, "label": f"📅 {first['d_str']} | {first['course']} | {first['match_type']} ({len(g)} Players)", "data": g, "sort_val": first['date']})
        if not legacy.empty:
            for (d_str, crs, mtype), g in legacy.groupby(['d_str', 'course', 'match_type']):
                groups.append({"key": f"{d_str}_{crs}", "label": f"📅 {d_str} | {crs} | {mtype} (Legacy)", "data": g, "sort_val": g.iloc[0]['date']})
        groups.sort(key=lambda x: x['sort_val'], reverse=True)
        for grp in groups:
            with st.expander(grp["label"]):
                g = grp["data"]
                edited = st.data_editor(g[["player_name", "stableford_score", "gross_score", "rp_earned", "notes"]], key=f"e_{grp['key']}", use_container_width=True, num_rows="dynamic")
                col_s, col_d = st.columns([1, 4])
                if col_s.button("Save Changes", key=f"s_{grp['key']}"):
                    df_rounds = df_rounds.drop(g.index)
                    save_df = edited.copy()
                    t = g.iloc[0]
                    for c in ["date", "course", "match_type", "holes_played", "match_id", "part_rp"]: 
                        if c in t: save_df[c] = t[c]
                        else: save_df[c] = 0
                    
                    new_rounds_db = pd.concat([df_rounds, save_df], ignore_index=True)
                    conn.update(worksheet="rounds", data=new_rounds_db, spreadsheet=SPREADSHEET_NAME)
                    
                    recalc_players = recalculate_all_handicaps(new_rounds_db, df_players)
                    conn.update(worksheet="players", data=recalc_players, spreadsheet=SPREADSHEET_NAME)
                    
                    st.cache_data.clear()
                    st.success("Updated & Handicaps Recalculated!")
                    st.rerun()
                    
                if col_d.button("Delete Match", key=f"d_{grp['key']}"):
                    new_rounds_db = df_rounds.drop(g.index)
                    conn.update(worksheet="rounds", data=new_rounds_db, spreadsheet=SPREADSHEET_NAME)
                    
                    recalc_players = recalculate_all_handicaps(new_rounds_db, df_players)
                    conn.update(worksheet="players", data=recalc_players, spreadsheet=SPREADSHEET_NAME)
                    
                    st.cache_data.clear()
                    st.error("Deleted & Handicaps Recalculated!")
                    st.rerun()

with tab_admin:
    st.header("⚙️ Admin")
    with st.expander("⚠️ Danger Zone (Reset)"):
        st.warning("Use this to wipe ALL rounds and reset handicaps to their original start value (Day 1 Reset).")
        confirm_reset = st.text_input("Type 'RESET LEAGUE' to wipe everything:")
        if st.button("☢️ Factory Reset League"):
            if confirm_reset == "RESET LEAGUE":
                empty_rounds = pd.DataFrame(columns=["date", "course", "player_name", "holes_played", "gross_score", "stableford_score", "rp_earned", "notes", "match_type", "match_id", "part_rp"])
                conn.update(worksheet="rounds", data=empty_rounds, spreadsheet=SPREADSHEET_NAME)
                df_players["handicap"] = df_players["start_handicap"]
                conn.update(worksheet="players", data=df_players, spreadsheet=SPREADSHEET_NAME)
                st.cache_data.clear()
                st.success("League Reset Complete!")
                st.rerun()
            else:
                st.error("Type 'RESET LEAGUE' exactly.")

    with st.expander("🚀 Season Management (New Season)"):
        st.warning("Use this when Season 1 ends (e.g., July 1). It locks current handicaps as the new baseline.")
        confirm = st.text_input("Type 'NEW SEASON' to confirm:")
        if st.button("🚀 Start New Season"):
            if confirm == "NEW SEASON":
                df_players["start_handicap"] = df_players["handicap"]
                conn.update(worksheet="players", data=df_players, spreadsheet=SPREADSHEET_NAME)
                st.cache_data.clear()
                st.success("New Season Started!")
                st.rerun()

    st.write("### 🔍 Debug Data")
    with st.expander("Show Raw Data"):
        st.write(df_rounds)
        st.write(df_players)
    st.divider()
    with st.form("add_p"):
        n = st.text_input("Name")
        h = st.number_input("Handicap", 0.0)
        if st.form_submit_button("Add"):
            conn.update(worksheet="players", data=pd.concat([df_players, pd.DataFrame([{"name":n, "handicap":h, "start_handicap":h}])], ignore_index=True), spreadsheet=SPREADSHEET_NAME)
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
    with st.expander("6. LIVE HANDICAPS"): st.markdown(f"""* **God Day (+45pts):** -5.0 \n* **On Fire (40-44pts):** -2.0\n* **Good Day (37-39pts):** -1.0\n* **The Zone (34-36pts):** No Change\n* **Bad Day (30-33pts):** +1.0\n* **Disaster Day (<30pts):** +2.0""")
