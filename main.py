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

    # STRICT DATE PARSING
    # We force errors='coerce' to handle bad data, but dayfirst=True is key for international formats
    rounds["date_parsed"] = pd.to_datetime(rounds["date"], dayfirst=True, errors='coerce')
    rounds["date"] = rounds["date_parsed"].fillna(pd.Timestamp.now())
    rounds = rounds.drop(columns=["date_parsed"])
    
    return players, rounds

def get_season(date_obj):
    if pd.isnull(date_obj): return "Unknown"
    y, d = date_obj.year, date_obj.date()
    
    # SEASON 1: Jan 1 - Mar 31
    if datetime.date(y, 1, 1) <= d <= datetime.date(y, 3, 31): return "Season 1"
    # SEASON 2: Apr 1 - Jun 30
    if datetime.date(y, 4, 1) <= d <= datetime.date(y, 6, 30): return "Season 2"
    # SEASON 3: Jul 1 - Sep 30
    if datetime.date(y, 7, 1) <= d <= datetime.date(y, 9, 30): return "Season 3"
    # SEASON 4: Oct 1 - Dec 31
    if datetime.date(y, 10, 1) <= d <= datetime.date(y, 12, 31): return "Season 4"
    
    return "Off-Season"

def calculate_new_handicap(current_hcp, score, holes="18"):
    is_9 = (str(holes) == "9")
    eff_score = score * 2 if is_9 else score
    current_hcp = float(current_hcp)
    
    # --- SANDBAGGER PROTOCOL (> 36.0) ---
    if current_hcp > 36.0:
        if eff_score > 36:
            drop = float(eff_score - 36)
            actual_drop = min(drop, 10.0)
            return max(0.0, current_hcp - actual_drop)
        else:
            if eff_score <= 33: return current_hcp + 1.0 
            return current_hcp 

    # --- STANDARD ADJUSTMENTS (<= 36.0) ---
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
    cols = [
        "Total RP", "Season 1", "Season 2", "Season 3", "Season 4",
        "Bonus RP S1", "Bonus RP S2", "Bonus RP S3", "Bonus RP S4",
        "Rounds", "Avg Score", "Best Gross", "1v1 Wins", "1v1 Losses", 
        "Daily Wins", "Part RP S1", "Part RP S2", "Part RP S3", "Part RP S4"
    ]
    for c in cols: stats[c] = 0
    stats["2v2 Record"] = "0-0-0"

current_rp_map = {}

if not df_rounds.empty and not stats.empty:
    df_rounds["season"] = df_rounds["date"].apply(get_season)
    
    # 1. Base RP & Participation
    season_rp = df_rounds.groupby(["player_name", "season"])["rp_earned"].sum().unstack(fill_value=0)
    part_rp_sum = df_rounds.groupby(["player_name", "season"])["part_rp"].sum().unstack(fill_value=0)
    
    for s in ["Season 1", "Season 2", "Season 3", "Season 4"]:
        if s in season_rp.columns: 
            stats[s] = stats[s].add(season_rp[s], fill_value=0)
        if s in part_rp_sum.columns:
            # Map "Season X" to "Part RP SX"
            s_num = s.split(" ")[1]
            target_col = f"Part RP S{s_num}"
            stats[target_col] = stats[target_col].add(part_rp_sum[s], fill_value=0)

    # 2. Rounds
    rounds_count = df_rounds.groupby("player_name").size()
    stats["Rounds"] = stats["Rounds"].add(rounds_count, fill_value=0)

    # 3. Avg Score
    std_matches = df_rounds[df_rounds["match_type"] == "Standard"]
    if not std_matches.empty:
        std_matches["norm_score"] = std_matches.apply(
            lambda r: r["stableford_score"] * 2 if r["holes_played"] == "9" else r["stableford_score"], axis=1
        )
        avg = std_matches.groupby("player_name")["norm_score"].mean()
        stats["Avg Score"] = stats["Avg Score"].add(avg, fill_value=0)

    # 4. Best Gross (Month)
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

    # 5. Daily Wins
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

    # 6. Records
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
# Dynamically pick bonus column
if "Season" in current_season:
    s_num = current_season.split(" ")[1]
    current_season_col = f"Bonus RP S{s_num}"
