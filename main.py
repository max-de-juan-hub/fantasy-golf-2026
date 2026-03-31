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

# --- CONSTANTS & MANUAL OVERRIDES ---
SPREADSHEET_NAME = "fantasy_golf_db"
MAX_PARTICIPATION_RP = 20  # Cap per season

# 🏆 PAST CHAMPIONS LOCK-IN 🏆
# The app will permanently award them +10 points and display them in the Trophy Room.
PAST_CHAMPIONS = {
    "Season 1": {
        "Rock": "Max De Juan (± 6.18)",
        "Rocket": "Jokin (8.0 Drop)",
        "Conqueror": "Max De Juan (4 Wins)"
    }
}

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

    # --- STRICT ISO DATE PARSING ---
    rounds["date"] = rounds["date"].astype(str)
    rounds["_date_obj"] = pd.to_datetime(rounds["date"], errors='coerce')
    rounds["_date_obj"] = rounds["_date_obj"].fillna(pd.Timestamp.now())
    rounds["display_date"] = rounds["_date_obj"].dt.strftime("%d-%b-%Y")
    
    return players, rounds

def get_season(date_obj):
    if pd.isnull(date_obj): return "Unknown"
    y, d = date_obj.year, date_obj.date()
    if datetime.date(y, 1, 1) <= d <= datetime.date(y, 3, 31): return "Season 1"
    if datetime.date(y, 4, 1) <= d <= datetime.date(y, 6, 30): return "Season 2"
    if datetime.date(y, 7, 1) <= d <= datetime.date(y, 9, 30): return "Season 3"
    if datetime.date(y, 10, 1) <= d <= datetime.date(y, 12, 31): return "Season 4"
    return "Off-Season"

def calculate_new_handicap(current_hcp, score, holes="18"):
    is_9 = (str(holes) == "9")
    eff_score = score * 2 if is_9 else score
    current_hcp = float(current_hcp)
    
    if current_hcp > 36.0:
        if eff_score > 36:
            drop = float(eff_score - 36)
            actual_drop = min(drop, 10.0)
            return max(0.0, current_hcp - actual_drop)
        else:
            if eff_score <= 33: return current_hcp + 1.0 
            return current_hcp 

    if eff_score >= 45: return max(0.0, current_hcp - 5.0)
    elif eff_score >= 40: return max(0.0, current_hcp - 2.0)
    elif eff_score >= 37: return max(0.0, current_hcp - 1.0)
    elif eff_score >= 34: return current_hcp
    elif eff_score >= 30: return current_hcp + 1.0
    else: return current_hcp + 2.0

def recalculate_all_handicaps(df_rounds, df_players):
    hcp_map = {}
    for idx, row in df_players.iterrows():
        hcp_map[row["name"]] = row["start_handicap"]
        
    if not df_rounds.empty:
        sorted_rounds = df_rounds.sort_values("_date_obj", ascending=True)
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

# --- DYNAMIC START HANDICAP CALCULATION ---
def get_start_handicaps_for_season(df_rounds, df_players, target_season):
    """Calculates what everyone's handicap was at the BEGINNING of the target season."""
    hcp_map = {}
    # 1. Initialize with original day-1 handicaps
    for idx, row in df_players.iterrows():
        hcp_map[row["name"]] = row["start_handicap"]
        
    if not df_rounds.empty:
        # 2. Play through rounds chronologically
        sorted_rounds = df_rounds.sort_values("_date_obj", ascending=True)
        for idx, row in sorted_rounds.iterrows():
            season_of_round = get_season(row["_date_obj"])
            
            # 3. Stop calculating once we reach the target season
            # (Because we only want to know the handicap BEFORE this season started)
            if season_of_round == target_season:
                continue # We don't apply this round's adjustments to the baseline
                
            if row["match_type"] == "Standard":
                p_name = row["player_name"]
                score = row["stableford_score"]
                holes = row["holes_played"]
                if p_name in hcp_map:
                    old_hcp = hcp_map[p_name]
                    new_hcp = calculate_new_handicap(old_hcp, score, holes)
                    hcp_map[p_name] = new_hcp
                    
    return hcp_map

def calculate_standard_rp(score, holes, is_clean, is_road, is_hio, group_data, current_player, player_rp_map, current_season_part_rp):
    breakdown = []
    is_9 = (str(holes) == "9")
    potential_part = 2 if is_9 else 4
    remaining_cap = MAX_PARTICIPATION_RP - current_season_part_rp
    actual_part = min(potential_part, max(0, remaining_cap))
    
    if actual_part > 0: breakdown.append(f"Part(+{actual_part})")
    elif potential_part > 0: breakdown.append("Part(Cap Reached)")
        
    target = 18 if is_9 else 36
    diff = score - target
    perf_pts = diff * 2 if diff >= 0 else int(diff / 2)
    breakdown.append(f"Perf({'+' if perf_pts>0 else ''}{perf_pts})")
    total = actual_part + perf_pts
    
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

current_season = get_season(datetime.datetime.now())

# --- 1. STATS ENGINE ---
if df_players.empty:
    stats = pd.DataFrame()
else:
    stats = df_players.copy().rename(columns={"name": "player_name"}).set_index("player_name")
    cols = ["Total RP", "Season 1", "Season 2", "Season 3", "Season 4", "Bonus RP S1", "Bonus RP S2", "Bonus RP S3", "Bonus RP S4", "Rounds (S)", "Total Rounds", "Avg Score", "Best Gross", "1v1 Wins", "1v1 Losses", "Daily Wins", "Part RP S1", "Part RP S2", "Part RP S3", "Part RP S4", "Gross Consistency"]
    for c in cols: stats[c] = 0
    stats["2v2 Record"] = "0-0-0"

current_rp_map = {}

if not df_rounds.empty and not stats.empty:
    df_rounds["season"] = df_rounds["_date_obj"].apply(get_season)
    
    season_rp = df_rounds.groupby(["player_name", "season"])["rp_earned"].sum().unstack(fill_value=0)
    part_rp_sum = df_rounds.groupby(["player_name", "season"])["part_rp"].sum().unstack(fill_value=0)
    
    for s in ["Season 1", "Season 2", "Season 3", "Season 4"]:
        if s in season_rp.columns: 
            stats[s] = stats[s].add(season_rp[s], fill_value=0)
        if s in part_rp_sum.columns:
            s_num = s.split(" ")[1]
            target_col = f"Part RP S{s_num}"
            stats[target_col] = stats[target_col].add(part_rp_sum[s], fill_value=0)

    # --- INJECT PAST CHAMPIONS POINTS ---
    for s_name, awards in PAST_CHAMPIONS.items():
        s_num = s_name.split(" ")[1]
        t_col = f"Bonus RP S{s_num}"
        for award_name, p_string in awards.items():
            if p_string:
                p_name = p_string.split(" (")[0]
                if p_name in stats.index:
                    stats.at[p_name, t_col] += 10

    # --- ALL-TIME ROUNDS ---
    total_rounds_count = df_rounds.groupby("player_name").size()
    stats["Total Rounds"] = stats["Total Rounds"].add(total_rounds_count, fill_value=0)

    # --- CURRENT SEASON ISOLATION FOR LEADERBOARD STATS ---
    df_current_season = df_rounds[df_rounds["season"] == current_season]
    
    rounds_count = df_current_season.groupby("player_name").size()
    stats["Rounds (S)"] = stats["Rounds (S)"].add(rounds_count, fill_value=0)

    std_current = df_current_season[df_current_season["match_type"] == "Standard"]
    
    if not std_current.empty:
        std_current_copy = std_current.copy()
        std_current_copy["norm_gross"] = std_current_copy.apply(lambda r: r["gross_score"] * 2 if str(r["holes_played"]) == "9" else r["gross_score"], axis=1)
        valid_gross = std_current_copy[std_current_copy["norm_gross"] > 0]
        consistency = valid_gross.groupby("player_name")["norm_gross"].std()
        stats["Gross Consistency"] = stats["Gross Consistency"].add(consistency, fill_value=0)

    if not std_current.empty:
        for mid, group in std_current.groupby("match_id"):
            max_s = group["stableford_score"].max()
            winners = group[group["stableford_score"] == max_s]["player_name"].unique()
            for w in winners:
                if w in stats.index: stats.at[w, "Daily Wins"] += 1
                
    alliance_current = df_current_season[df_current_season["match_type"] == "Alliance"]
    if not alliance_current.empty:
        winners = alliance_current[alliance_current["rp_earned"] > 0]["player_name"]
        for w in winners:
            if w in stats.index: stats.at[w, "Daily Wins"] += 1

    # --- SNIPER LOGIC (MONTHLY RESET + PAST PERMANENT POINTS) ---
    df_rounds["month_period"] = df_rounds["_date_obj"].dt.to_period("M")
    current_month_period = pd.Timestamp.now().to_period("M")
    
    gross_rnds = df_rounds[
        (df_rounds["holes_played"] == "18") &
        (df_rounds["match_type"].isin(["Standard", "Duel"])) &
        (df_rounds["gross_score"] > 0)
    ]
    
    sniper_history_text = ""
    
    if not gross_rnds.empty:
        monthly_bests = gross_rnds.groupby(["month_period"])["gross_score"].min()
        
        for period, min_score in monthly_bests.items():
            if period < current_month_period:
                winners = gross_rnds[(gross_rnds["month_period"] == period) & (gross_rnds["gross_score"] == min_score)]
                winner_names = winners["player_name"].unique().tolist()
                
                month_name = period.strftime("%b")
                sniper_history_text += f"**{month_name}:** {', '.join(winner_names)} ({int(min_score)})<br>"
                
                for p in winner_names:
                    if p in stats.index:
                        m_idx = period.month
                        if 1 <= m_idx <= 3: target = "Bonus RP S1"
                        elif 4 <= m_idx <= 6: target = "Bonus RP S2"
                        elif 7 <= m_idx <= 9: target = "Bonus RP S3"
                        else: target = "Bonus RP S4"
                        stats.at[p, target] += 5

        current_pool = gross_rnds[gross_rnds["month_period"] == current_month_period]
        if not current_pool.empty:
            best_curr = current_pool.groupby("player_name")["gross_score"].min()
            for p, score in best_curr.items():
                if p in stats.index:
                    stats.at[p, "Best Gross"] = score

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

# --- 2. LIVE TROPHY LOGIC (Current Season Only) ---
holder_rock, holder_sniper, holder_conq, holder_rocket = None, None, None, None

if "Season" in current_season:
    s_num = current_season.split(" ")[1]
    current_season_col = f"Bonus RP S{s_num}"
else: current_season_col = "Bonus RP S1" 

def resolve_tie(cand, metric, method="max"):
    if len(cand) == 1: return cand.index[0]
    if method == "min": 
        if metric == "Best Gross": cand = cand[cand[metric] > 0]
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
    q_rock = stats[(stats["Rounds (S)"] >= 3) & (stats["Gross Consistency"] > 0)]
    if not q_rock.empty:
        holder_rock = resolve_tie(q_rock, "Gross Consistency", method="min")
        award_bonus(holder_rock, 10)

    # --- DYNAMIC ROCKET CALCULATION ---
    # Get the baseline handicaps for the start of the current season
    season_start_hcps = get_start_handicaps_for_season(df_rounds, df_players, current_season)
    
    # Calculate reduction based on that dynamic start point
    stats["HCP Reduction"] = stats.apply(lambda row: season_start_hcps.get(row.name, df_players.loc[df_players["name"]==row.name, "start_handicap"].values[0]) - df_players.loc[df_players["name"]==row.name, "handicap"].values[0] if row.name in df_players["name"].values else 0, axis=1)
    
    q_rocket = stats[stats["Rounds (S)"] >= 3]
    if not q_rocket.empty:
        q_rocket = q_rocket[q_rocket["HCP Reduction"] > 0]
        if not q_rocket.empty:
            holder_rocket = resolve_tie(q_rocket, "HCP Reduction", method="max")
            award_bonus(holder_rocket, 10)

    q_sniper = stats[stats["Best Gross"] > 0]
    if not q_sniper.empty:
        holder_sniper = resolve_tie(q_sniper, "Best Gross", method="min")
        award_bonus(holder_sniper, 5) 

    q_conq = stats[stats["Rounds (S)"] >= 3]
    if not q_conq.empty:
        holder_conq = resolve_tie(q_conq, "Daily Wins", method="max")
        award_bonus(holder_conq, 10)

    stats["Total RP"] = (stats["Season 1"] + stats["Bonus RP S1"] + stats["Season 2"] + stats["Bonus RP S2"] + stats["Season 3"] + stats["Bonus RP S3"] + stats["Season 4"] + stats["Bonus RP S4"])
    
    for p, val in stats["Total RP"].items(): current_rp_map[p] = val
    stats = stats.sort_values("Total RP", ascending=False).reset_index()
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
    st.header(f"Live Standings ({current_season})")
    if stats.empty:
        st.info("👋 Welcome! No players found. Go to the 'Admin' tab to add players.")
    else:
        v = stats.copy()
        v["1v1 Record"] = v["1v1 Wins"].astype(int).astype(str) + "-" + v["1v1 Losses"].astype(int).astype(str)
        
        # Merge Rounds into a single string column: "Season / Total"
        v["Rounds (S / T)"] = v["Rounds (S)"].astype(int).astype(str) + " / " + v["Total Rounds"].astype(int).astype(str)
        
        v = v.rename(columns={"handicap": "Handicap", "Best Gross": "Best Round (Month)", "Gross Consistency": "Consistency (±)", "Daily Wins": "Wins (S)", "Season 1": "Season 1 RP", "Season 2": "Season 2 RP", "Season 3": "Season 3 RP", "Season 4": "Season 4 RP"})
        
        if "Season" in current_season:
            s_num = current_season.split(" ")[1]
            curr_part_col = f"Part RP S{s_num}"
        else: curr_part_col = "Part RP S1"
        v["Part. Cap (20)"] = v[curr_part_col].astype(int).astype(str) + "/20"

        # --- LEADERBOARD COLUMNS UPDATED ---
        cols_order = ["Player", "Total RP", "Handicap", "Wins (S)", "Best Round (Month)", "Consistency (±)", "Rounds (S / T)", "Part. Cap (20)", "1v1 Record", "2v2 Record", "Season 1 RP", "Bonus RP S1", "Season 2 RP", "Bonus RP S2", "Season 3 RP", "Bonus RP S3", "Season 4 RP", "Bonus RP S4"]
        final_cols = [c for c in cols_order if c in v.columns]
        v = v[final_cols]

        for col in v.columns:
            if col not in ["Player", "1v1 Record", "2v2 Record", "Part. Cap (20)", "Rounds (S / T)"]:
                v[col] = v[col].apply(fmt_num)

        def color_row(row):
            if row.name == 0: return ['background-color: #FFA500; color: black'] * len(row)
            if 1 <= row.name <= 3: return ['background-color: #FFFFE0; color: black'] * len(row)
            return [''] * len(row)

        st.dataframe(v.style.apply(color_row, axis=1), use_container_width=True, hide_index=True, column_config={"Player": st.column_config.TextColumn("Player", width="medium")})
        st.caption("🔶 **Orange:** Leader | 🟡 **Yellow:** Top 4 | 🏆 **Bonuses:** 🪨 Rock(+10) 🎯 Sniper(+5) 👑 Conqueror(+10) 🚀 Rocket(+10)")
        st.caption("*(S) Indicates stat resets every season.*")

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

        rv = get_val(holder_rock, "Gross Consistency")
        sv = get_val(holder_sniper, "Best Gross")
        cv = get_val(holder_conq, "Daily Wins")
        rkv = get_val(holder_rocket, "HCP Reduction")
        
        past_rocks = "<br>".join([f"<b>{s}</b>: {data['Rock']}" for s, data in PAST_CHAMPIONS.items() if data['Rock']])
        past_rockets = "<br>".join([f"<b>{s}</b>: {data['Rocket']}" for s, data in PAST_CHAMPIONS.items() if data['Rocket']])
        past_conqs = "<br>".join([f"<b>{s}</b>: {data['Conqueror']}" for s, data in PAST_CHAMPIONS.items() if data['Conqueror']])
        
        st.markdown("""<style>.trophy-card { background-color: #262730; padding: 20px; border-radius: 10px; border: 1px solid #4B4B4B; text-align: center; } .t-icon { font-size: 40px; } .t-head { font-size: 18px; font-weight: bold; color: #FFD700; margin-top: 5px; } .t-sub { font-size: 12px; color: #A0A0A0; margin-bottom: 10px; } .t-name { font-size: 20px; font-weight: bold; color: white; } .t-bonus { color: #00FF00; font-weight: bold; font-size: 14px; margin-top: 5px; } .t-hist { font-size: 13px; color: #aaa; margin-top: 15px; border-top: 1px solid #444; padding-top: 10px; text-align: left; line-height: 1.4; }</style>""", unsafe_allow_html=True)
        def card(c, i, t, d, w, b, r, hist=None, hist_title="Past Winners"): 
            h_html = f"<div class='t-hist'><b>📜 {hist_title}:</b><br>{hist}</div>" if hist else ""
            c.markdown(f"""<div class="trophy-card"><div class="t-icon">{i}</div><div class="t-head">{t}</div><div class="t-sub">{d}<br><i>{r}</i></div><div class="t-name">{w}</div><div class="t-bonus">{b}</div>{h_html}</div>""", unsafe_allow_html=True)

        c1, c2, c3, c4 = st.columns(4)
        
        sniper_hist_display = sniper_history_text.rstrip("  ")

        card(c1, "🪨", "The Rock", "Best Consistency", txt(holder_rock, rv, "± Dev"), "+10", "Min 3 Rounds", past_rocks, "Past Rocks")
        card(c2, "🚀", "The Rocket", "Biggest HCP Drop", txt(holder_rocket, rkv, "Drop"), "+10", "Min 3 Rounds", past_rockets, "Past Rockets")
        card(c3, "🎯", "The Sniper", "Best Gross (Current Month)", txt(holder_sniper, sv, "Strks"), "+5 (Live)", "Std or 1v1 (18H)", sniper_hist_display, "Past Snipers")
        card(c4, "👑", "The Conqueror", "Most Wins", txt(holder_conq, cv, "Wins"), "+10", "Min 3 Rounds", past_conqs, "Past Conquerors")

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
                        current_season_part_map = {}
                        if not stats.empty:
                            if "Season" in current_season:
                                s_num = current_season.split(" ")[1]
                                target_col = f"Part RP S{s_num}"
                            else: target_col = "Part RP S1"
                            for _, row in stats.iterrows(): current_season_part_map[row["player_name"]] = row.get(target_col, 0)

                        new_rows = []
                        for d in input_data:
                            curr_part = current_season_part_map.get(d['name'], 0)
                            rp, note, actual_part_earned = calculate_standard_rp(d['score'], hl, d['cl'], d['rw'], d['ho'], group_scores, d['name'], current_rp_map, curr_part)
                            curr_hcp = df_players.loc[df_players["name"] == d['name'], "handicap"].values[0]
                            new_hcp = calculate_new_handicap(curr_hcp, d['score'], hl)
                            df_players.loc[df_players["name"] == d['name'], "handicap"] = new_hcp
                            
                            date_str = dt.strftime("%Y-%m-%d")
                            
                            new_rows.append({"date": date_str, "course": crs, "player_name": d['name'], "holes_played": hl, "stableford_score": d['score'], "gross_score": d['gross'], "rp_earned": rp, "notes": note, "match_type": "Standard", "match_id": batch_id, "part_rp": actual_part_earned})
                        
                        combined_rounds = pd.concat([df_rounds, pd.DataFrame(new_rows)], ignore_index=True)
                        combined_rounds["date"] = combined_rounds["date"].astype(str)
                        if "_date_obj" in combined_rounds.columns: combined_rounds = combined_rounds.drop(columns=["_date_obj"])
                        if "display_date" in combined_rounds.columns: combined_rounds = combined_rounds.drop(columns=["display_date"])
                        
                        conn.update(worksheet="rounds", data=combined_rounds, spreadsheet=SPREADSHEET_NAME)
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
                        
                        date_str = dt.strftime("%Y-%m-%d")
                        
                        rows = [{"date":date_str, "course":crs, "player_name":win_p, "holes_played":hl, "gross_score":(g1 if win_p==p1 else g2), "rp_earned": steal, "notes":w_note, "match_type":"Duel", "match_id": batch_id, "part_rp": 0}, {"date":date_str, "course":crs, "player_name":lose_p, "holes_played":hl, "gross_score":(g2 if win_p==p1 else g1), "rp_earned": -steal, "notes":l_note, "match_type":"Duel", "match_id": batch_id, "part_rp": 0}]
                        
                        combined_rounds = pd.concat([df_rounds, pd.DataFrame(rows)], ignore_index=True)
                        combined_rounds["date"] = combined_rounds["date"].astype(str)
                        if "_date_obj" in combined_rounds.columns: combined_rounds = combined_rounds.drop(columns=["_date_obj"])
                        if "display_date" in combined_rounds.columns: combined_rounds = combined_rounds.drop(columns=["display_date"])
                        
                        conn.update(worksheet="rounds", data=combined_rounds, spreadsheet=SPREADSHEET_NAME)
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
                    
                    date_str = dt.strftime("%Y-%m-%d")
                    
                    for p in [w1, w2]: 
                        bonus = 5 if is_debut(p) else 0
                        note = f"Win ({wh}-{lh})"
                        if bonus: note += ", Duo Debut(+5)"
                        rows.append({"date":date_str, "course":crs, "player_name":p, "holes_played":"18", "rp_earned": 5+bonus, "notes":note, "match_type":"Alliance", "match_id": batch_id, "part_rp": 0})
                    for p in [l1, l2]:
                        bonus = 5 if is_debut(p) else 0
                        note = f"Loss ({wh}-{lh})"
                        if bonus: note += ", Duo Debut(+5)"
                        rows.append({"date":date_str, "course":crs, "player_name":p, "holes_played":"18", "rp_earned": -5+bonus, "notes":note, "match_type":"Alliance", "match_id": batch_id, "part_rp": 0})
                    
                    combined_rounds = pd.concat([df_rounds, pd.DataFrame(rows)], ignore_index=True)
                    combined_rounds["date"] = combined_rounds["date"].astype(str)
                    if "_date_obj" in combined_rounds.columns: combined_rounds = combined_rounds.drop(columns=["_date_obj"])
                    if "display_date" in combined_rounds.columns: combined_rounds = combined_rounds.drop(columns=["display_date"])
                    
                    conn.update(worksheet="rounds", data=combined_rounds, spreadsheet=SPREADSHEET_NAME)
                    st.cache_data.clear()
                    st.success("Alliance Saved!")
                    st.rerun()
    else:
        st.warning("Please add players in the Admin tab to start submitting scores.")

with tab_history:
    st.header("📜 League History")
    if not df_rounds.empty:
        df_show = df_rounds.copy()
        
        df_show = df_show.sort_values("_date_obj", ascending=False)
        modern = df_show[df_show["match_id"] != "legacy"]
        legacy = df_show[df_show["match_id"] == "legacy"]
        groups = []
        if not modern.empty:
            for m_id, g in modern.groupby("match_id"):
                first = g.iloc[0]
                groups.append({"key": m_id, "label": f"📅 {first['display_date']} | {first['course']} | {first['match_type']} ({len(g)} Players)", "data": g, "sort_val": first['_date_obj']})
        if not legacy.empty:
            for (d_str, crs, mtype), g in legacy.groupby(['display_date', 'course', 'match_type']):
                groups.append({"key": f"{d_str}_{crs}", "label": f"📅 {d_str} | {crs} | {mtype} (Legacy)", "data": g, "sort_val": g.iloc[0]['_date_obj']})
        groups.sort(key=lambda x: x['sort_val'], reverse=True)
        
        for grp in groups:
            with st.expander(grp["label"]):
                g = grp["data"]
                cols = ["player_name", "stableford_score", "gross_score", "rp_earned", "notes"]
                edited = st.data_editor(g[cols], key=f"e_{grp['key']}", use_container_width=True, num_rows="dynamic")
                col_s, col_d = st.columns([1, 4])
                if col_s.button("Save Changes", key=f"s_{grp['key']}"):
                    df_rounds = df_rounds.drop(g.index)
                    save_df = edited.copy()
                    t = g.iloc[0]
                    for c in ["date", "course", "match_type", "holes_played", "match_id", "part_rp"]: 
                        if c in t: save_df[c] = t[c]
                        else: save_df[c] = 0
                    
                    new_rounds_db = pd.concat([df_rounds, save_df], ignore_index=True)
                    new_rounds_db["date"] = new_rounds_db["date"].astype(str)
                    
                    if "_date_obj" in new_rounds_db.columns: new_rounds_db = new_rounds_db.drop(columns=["_date_obj"])
                    if "display_date" in new_rounds_db.columns: new_rounds_db = new_rounds_db.drop(columns=["display_date"])
                    
                    conn.update(worksheet="rounds", data=new_rounds_db, spreadsheet=SPREADSHEET_NAME)
                    recalc_players = recalculate_all_handicaps(new_rounds_db, df_players)
                    conn.update(worksheet="players", data=recalc_players, spreadsheet=SPREADSHEET_NAME)
                    st.cache_data.clear()
                    st.success("Updated!")
                    st.rerun()
                    
                if col_d.button("Delete Match", key=f"d_{grp['key']}"):
                    new_rounds_db = df_rounds.drop(g.index)
                    new_rounds_db["date"] = new_rounds_db["date"].astype(str)
                    if "_date_obj" in new_rounds_db.columns: new_rounds_db = new_rounds_db.drop(columns=["_date_obj"])
                    if "display_date" in new_rounds_db.columns: new_rounds_db = new_rounds_db.drop(columns=["display_date"])
                    
                    conn.update(worksheet="rounds", data=new_rounds_db, spreadsheet=SPREADSHEET_NAME)
                    recalc_players = recalculate_all_handicaps(new_rounds_db, df_players)
                    conn.update(worksheet="players", data=recalc_players, spreadsheet=SPREADSHEET_NAME)
                    st.cache_data.clear()
                    st.error("Deleted!")
                    st.rerun()

with tab_admin:
    st.header("⚙️ Admin")
    
    with st.expander("⚠️ Danger Zone (Reset)"):
        st.warning("Use this to wipe ALL rounds and reset handicaps.")
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

    with st.expander("🚀 Season Management (Manual Override)"):
        st.warning("Use this to manually lock current handicaps as the baseline for the new season.")
        confirm = st.text_input("Type 'NEW SEASON' to confirm:")
        if st.button("🚀 Lock Handicaps for New Season"):
            if confirm == "NEW SEASON":
                df_players["start_handicap"] = df_players["handicap"]
                conn.update(worksheet="players", data=df_players, spreadsheet=SPREADSHEET_NAME)
                st.cache_data.clear()
                st.success("Handicaps Locked!")
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
