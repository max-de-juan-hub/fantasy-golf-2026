import streamlit as st
import pandas as pd
from datetime import date
import database as db
import logic
import uuid

# --- CONFIG ---
st.set_page_config(page_title="Fantasy Golf 2026", layout="wide", page_icon="🏆")
db.init_db()

# --- STYLING ---
st.markdown("""
    <style>
    .stApp {background-color: #0e1117;}
    h1, h2, h3 {font-family: 'Georgia', serif; color: #E5C100 !important;}
    div[data-testid="stMetricValue"] {color: #E5C100 !important;}
    
    .award-card {
        background-color: #1E1E1E;
        padding: 15px;
        border-radius: 10px;
        border: 1px solid #333;
        text-align: center;
        height: 280px;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
    }
    .award-icon {font-size: 40px; margin-bottom: 5px;}
    .award-title {color: #E5C100; font-weight: bold; font-size: 16px; text-transform: uppercase; height: 40px; display: flex; align-items: center; justify-content: center;}
    .award-holder {font-size: 18px; font-weight: bold; color: white;}
    .award-stat {font-size: 13px; color: #D4AF37; font-weight: bold;}
    .award-lore {font-size: 11px; color: #aaa; font-style: italic; border-top: 1px solid #444; padding-top: 8px; margin-top: auto;}
    </style>
    """, unsafe_allow_html=True)

st.title("🏆 Fantasy Golf 2026 Manager")

# --- DATA ---
df_players = db.get_leaderboard()
df_history = db.get_history()

# --- HELPERS ---
def fmt_num(val):
    """Format number to remove .0 if integer, else keep 1 decimal"""
    try:
        f_val = float(val)
        if f_val.is_integer():
            return int(f_val)
        return round(f_val, 1)
    except:
        return val

def get_record(player_name, match_type_str):
    if df_history.empty: return "0-0" if match_type_str == "Duel" else "0-0-0"
    p_rows = df_history[df_history["player_name"] == player_name]
    riv_rows = p_rows[p_rows["is_rivalry"] == 1]
    wins, losses, ties = 0, 0, 0
    for note in riv_rows["notes"]:
        if match_type_str in note:
            if "Win" in note: wins += 1
            elif "Loss" in note: losses += 1
            elif "Tie" in note: ties += 1
    if match_type_str == "Duel": return f"{wins}-{losses}"
    else: return f"{wins}-{losses}-{ties}"

def get_daily_wins(player_name):
    if df_history.empty: return 0
    wins = 0
    for note in df_history[df_history["player_name"] == player_name]["notes"]:
        if "Winner of Day" in note or "Duel Win" in note or "Alliance Win" in note: 
            wins += 1
    return wins

def calculate_awards_snapshot(rounds_df, players_df):
    holders = {}
    bonuses = {name: 0 for name in players_df["name"]}
    stats = {} 
    
    if rounds_df.empty: return holders, bonuses, stats

    # 1. Sniper (Low Gross)
    valid_gross = rounds_df[rounds_df["gross_score"] > 20]
    if not valid_gross.empty:
        min_score = valid_gross["gross_score"].min()
        candidates = valid_gross[valid_gross["gross_score"] == min_score]["player_name"].unique().tolist()
        winner, reason = logic.resolve_tie_via_head_to_head(candidates, rounds_df)
        
        holders["Sniper"] = winner
        stats["Sniper"] = int(min_score)
        if isinstance(winner, str): bonuses[winner] += 5
    
    # 2. Rock (Avg Stableford) - Min 5 rounds
    counts = rounds_df["player_name"].value_counts()
    elig = counts[counts >= 5].index.tolist()
    
    if elig:
        avgs = rounds_df[rounds_df["player_name"].isin(elig)].groupby("player_name")["stableford_score"].mean()
        if not avgs.empty:
            max_avg = avgs.max()
            candidates = avgs[avgs == max_avg].index.tolist()
            winner, reason = logic.resolve_tie_via_head_to_head(candidates, rounds_df)
            
            holders["Rock"] = winner
            stats["Rock"] = f"{max_avg:.2f}"
            if isinstance(winner, str): bonuses[winner] += 10
    else:
        holders["Rock"] = None

    # 3. Conqueror (Wins) - MIN 3 WINS
    wins_map = {}
    for index, row in rounds_df.iterrows():
        note = row["notes"]
        name = row["player_name"]
        if "Winner of Day" in note or "Duel Win" in note or "Alliance Win" in note:
            wins_map[name] = wins_map.get(name, 0) + 1
            
    # Filter for Min 3 Wins
    eligible_wins = {k:v for k,v in wins_map.items() if v >= 3}
    
    if eligible_wins:
        max_wins = max(eligible_wins.values())
        candidates = [p for p, w in eligible_wins.items() if w == max_wins]
        winner, reason = logic.resolve_tie_via_head_to_head(candidates, rounds_df)
        
        holders["Conqueror"] = winner
        stats["Conqueror"] = max_wins
        if isinstance(winner, str): bonuses[winner] += 10
    else:
        holders["Conqueror"] = None
        stats["Conqueror"] = "Min 3 Wins"
        
    return holders, bonuses, stats

# --- DATE LOGIC ---
today = date.today()
s1_end = date(2026, 3, 31)
season_1_over = today > s1_end

# --- AWARD CALCULATION ---
s1_bonus_points = {name: 0 for name in df_players["name"]}
s1_holders = {}
if season_1_over:
    s1_history = df_history[df_history["season"] == "Season 1"]
    s1_valid = s1_history[s1_history["gross_score"] > 20]
    s1_holders, s1_bonus_points, _ = calculate_awards_snapshot(s1_valid, df_players)

valid_stroke_play = df_history[df_history["gross_score"] > 20]
live_holders, live_bonus_points, live_stats = calculate_awards_snapshot(valid_stroke_play, df_players)

# Rocket Logic - MIN 3 ROUNDS
if not df_players.empty:
    # Filter only players with >= 3 rounds
    eligible_rocket = df_players[df_players["rounds_played"] >= 3].copy()
    
    if not eligible_rocket.empty:
        eligible_rocket["prog"] = eligible_rocket["starting_handicap"] - eligible_rocket["handicap"]
        max_prog = eligible_rocket["prog"].max()
        
        if max_prog > 0:
            candidates = eligible_rocket[eligible_rocket["prog"] == max_prog]["name"].tolist()
            winner, reason = logic.resolve_tie_via_head_to_head(candidates, df_history)
            
            live_holders["Rocket"] = winner
            live_stats["Rocket"] = f"-{max_prog:.1f}"
            if isinstance(winner, str): live_bonus_points[winner] += 10
        else:
            live_holders["Rocket"] = None
            live_stats["Rocket"] = "No Drop"
    else:
        live_holders["Rocket"] = None
        live_stats["Rocket"] = "Min 3 Rnds"

# --- TABS ---
tab1, tab2, tab3, tab4, tab5 = st.tabs(["📊 Standings", "📝 Submit", "🕰️ History", "🏆 Awards", "👥 Players"])

# ==========================
# TAB 1: STANDINGS
# ==========================
with tab1:
    st.header("Live Standings")
    if not df_players.empty:
        s1_totals = {}
        for name in df_players["name"]:
            p_hist = df_history[df_history["player_name"] == name]
            base_s1 = p_hist[p_hist["season"]=="Season 1"]["rp_earned"].sum()
            bonus = s1_bonus_points.get(name, 0) if season_1_over else 0
            s1_totals[name] = base_s1 + bonus
        
        s1_ranked = sorted(s1_totals.items(), key=lambda x: x[1], reverse=True)
        s1_podium_map = {}
        if season_1_over:
            rewards = [15, 10, 7, 4, 2]
            for i, (p_name, score) in enumerate(s1_ranked[:5]):
                if score > 0: s1_podium_map[p_name] = rewards[i]

        display_data = []
        for idx, row in df_players.iterrows():
            name = row["name"]
            
            # Icons logic (Check if name is IN the holder list if it's a list)
            icons = ""
            for aw_key, icon in [("Sniper","🎯"), ("Rock","🪨"), ("Rocket","🚀"), ("Conqueror","⚔️")]:
                h = live_holders.get(aw_key)
                if isinstance(h, str) and h == name: icons += f" {icon}"
                elif isinstance(h, list) and name in h: icons += f" {icon}"
            
            p_hist = df_history[df_history["player_name"] == name]
            s1_base = p_hist[p_hist["season"]=="Season 1"]["rp_earned"].sum()
            s1_display_val = s1_base
            s1_decor = ""
            if season_1_over:
                s1_display_val += s1_bonus_points.get(name, 0)
                rank_idx = -1
                for i, (rn, rs) in enumerate(s1_ranked):
                    if rn == name: rank_idx = i; break
                if rank_idx == 0: s1_decor = " 🥇"
                elif rank_idx == 1: s1_decor = " 🥈"
                elif rank_idx == 2: s1_decor = " 🥉"
            
            s2_base = p_hist[p_hist["season"]=="Season 2"]["rp_earned"].sum()
            lifetime_rp = p_hist["rp_earned"].sum()
            total_rp = lifetime_rp + s1_podium_map.get(name, 0)
            if season_1_over:
                total_rp += s1_bonus_points.get(name, 0) + live_bonus_points.get(name, 0)
            else:
                total_rp += live_bonus_points.get(name, 0)

            p_stats = p_hist[p_hist["gross_score"] > 20]
            avg = p_stats["stableford_score"].mean() if not p_stats.empty else 0
            best = p_stats["gross_score"].min() if not p_stats.empty else 0
            
            display_data.append({
                "Player": f"{name}{icons}",
                "Tournament 1 RP": fmt_num(total_rp),
                "Season 1": f"{fmt_num(s1_display_val)}{s1_decor}", 
                "Season 2": fmt_num(s2_base),
                "Handicap": f"{row['handicap']:.1f}", 
                "Rounds Played": row["rounds_played"],
                "Best Round": int(best) if best > 0 else "-",
                "Avg Pts": f"{avg:.1f}",
                "1v1 Record": get_record(name, "Duel"),
                "2v2 Record": get_record(name, "Alliance"),
                "Daily Wins": get_daily_wins(name),
                "sort_val": total_rp 
            })
            
        df_disp = pd.DataFrame(display_data).sort_values("sort_val", ascending=False)
        df_disp = df_disp.drop(columns=["sort_val"])
        df_disp.insert(0, "Rank", range(1, len(df_disp) + 1))
        
        def highlight_rows(row):
            styles = [''] * len(row)
            if row["Rank"] == 1: styles = ['background-color: #D4AF37; color: black; font-weight: bold'] * len(row)
            elif row["Rank"] <= 4: styles = ['background-color: #F4E7BE; color: black'] * len(row)
            return styles

        st.dataframe(
            df_disp.style.apply(highlight_rows, axis=1),
            use_container_width=True,
            hide_index=True
        )
        st.caption("🔶 Gold: Leader | 🟡 Pale Yellow: Top 4 (King's Cup Qualifiers)")

# ==========================
# TAB 2: SUBMIT
# ==========================
with tab2:
    st.header("Submit Results")
    mode = st.radio("Mode", ["Standard Round", "⚔️ Rivalry Challenge"], horizontal=True)
    d_date = st.date_input("Date", date.today())
    d_course = st.text_input("Course", "Chinderah")
    d_season = logic.get_season(d_date)

    if mode == "Standard Round":
        selected = st.multiselect("Select Group", df_players["name"].tolist())
        with st.form("std_form", clear_on_submit=True):
            if selected:
                st.divider()
                group_inputs = []
                for p in selected:
                    st.markdown(f"**{p}**")
                    c1, c2, c3 = st.columns(3)
                    g = c1.number_input(f"Strokes", 50, 150, 80, key=f"g_{p}")
                    s = c2.number_input(f"Stableford", 0, 60, 30, key=f"s_{p}")
                    rw = c3.checkbox("New Course Played? (Road Warrior)", key=f"rw_{p}")
                    cl = c3.checkbox("Clean Sheet", key=f"cl_{p}")
                    hi = c3.checkbox("Hole in One", key=f"hi_{p}")
                    curr_p = df_players[df_players["name"]==p].iloc[0]
                    group_inputs.append({"name": p, "gross": g, "stbl": s, "hcp": curr_p["handicap"], "clean": cl, "hio": hi, "road_warrior": rw})
                    st.divider()
            
            if st.form_submit_button("🚀 Submit Group Round"):
                if not selected: st.error("Select players.")
                else:
                    batch_id = str(uuid.uuid4())
                    full_standings = {n: {'rp': r} for n, r in df_players.set_index("name")["total_rp"].to_dict().items()}
                    results = logic.calculate_group_bonuses(group_inputs, full_standings)
                    for p_data in group_inputs:
                        name = p_data['name']
                        res = results[name]
                        db.save_round(name, str(d_date), d_season, d_course, 
                                      p_data['gross'], p_data['stbl'], 
                                      res['total_rp'], res['new_hcp'], 
                                      res['notes'], p_data['clean'], p_data['hio'], rivalry=0, 
                                      match_group_id=batch_id)
                    st.success("Round Saved!")
                    st.rerun()

    else:
        riv_type = st.selectbox("Type", ["2v2 Alliance", "1v1 Duel"])
        with st.form("riv_form", clear_on_submit=True):
            if riv_type == "2v2 Alliance":
                c1, c2 = st.columns(2)
                team_a = c1.multiselect("Team A", df_players["name"].tolist())
                team_b = c2.multiselect("Team B", df_players["name"].tolist())
                st.write("Match Score (Holes Won)")
                c3, c4 = st.columns(2)
                ha = c3.number_input("Holes Won Team A", 0, 18, 0, key="ha_val")
                hb = c4.number_input("Holes Won Team B", 0, 18, 0, key="hb_val")
                
                submitted = st.form_submit_button("Submit 2v2 Result")
                if submitted:
                    if len(team_a)!=2 or len(team_b)!=2: st.error("2 players per team needed.")
                    else:
                        batch_id = str(uuid.uuid4())
                        res_code = "A" if ha > hb else "B" if hb > ha else "Tie"
                        win_rp, lose_rp = (5, -5) if res_code != "Tie" else (0, 0)
                        winners = team_a if res_code == "A" else team_b if res_code == "B" else team_a+team_b
                        losers = team_b if res_code == "A" else team_a if res_code == "B" else []
                        all_p = team_a+team_b
                        debut = {p: 5 if not db.has_played_2v2(p) else 0 for p in all_p}
                        for p in winners:
                            note = f"Alliance Win (+{win_rp})" if res_code != "Tie" else "Alliance Tie"
                            if debut[p]: note += ", Duo Debut (+5)"
                            h = df_players[df_players["name"]==p].iloc[0]["handicap"]
                            score = ha if p in team_a else hb
                            db.save_round(p, str(d_date), d_season, "2v2 Match", score, 0, win_rp+debut[p], h, note, rivalry=1, match_group_id=batch_id)
                        for p in losers:
                            note = f"Alliance Loss ({lose_rp})"
                            if debut[p]: note += ", Duo Debut (+5)"
                            h = df_players[df_players["name"]==p].iloc[0]["handicap"]
                            score = ha if p in team_a else hb
                            db.save_round(p, str(d_date), d_season, "2v2 Match", score, 0, lose_rp+debut[p], h, note, rivalry=1, match_group_id=batch_id)
                        st.success("2v2 Saved!")
                        st.rerun()

            elif riv_type == "1v1 Duel":
                c1, c2 = st.columns(2)
                p1 = c1.selectbox("Player 1", df_players["name"].tolist(), key="d_p1")
                p2 = c2.selectbox("Player 2", df_players["name"].tolist(), key="d_p2")
                st.write("Score Input (Total Strokes)")
                c3, c4 = st.columns(2)
                p1_str = c3.number_input(f"Player 1 Strokes", 50, 150, 80, key="p1_duel_str")
                p2_str = c4.number_input(f"Player 2 Strokes", 50, 150, 80, key="p2_duel_str")
                
                submitted = st.form_submit_button("Submit Duel Result")
                if submitted:
                    if p1==p2: st.error("Select different players.")
                    else:
                        batch_id = str(uuid.uuid4())
                        h1 = df_players[df_players["name"]==p1].iloc[0]["handicap"]
                        h2 = df_players[df_players["name"]==p2].iloc[0]["handicap"]
                        w_ref, stakes, reason = logic.calculate_rivalry_1v1(p1_str, p2_str, h1, h2)
                        rp1 = stakes if w_ref=="p1" else -stakes if w_ref=="p2" else 0
                        rp2 = stakes if w_ref=="p2" else -stakes if w_ref=="p1" else 0
                        n1 = f"Duel Win (+{rp1})" if rp1>0 else f"Duel Loss ({rp1})"
                        n2 = f"Duel Win (+{rp2})" if rp2>0 else f"Duel Loss ({rp2})"
                        if w_ref=="tie": n1, n2 = "Duel Tie", "Duel Tie"
                        course_name = f"{d_course} (Duel)"
                        db.save_round(p1, str(d_date), d_season, course_name, p1_str, 0, rp1, h1, n1, rivalry=1, match_group_id=batch_id)
                        db.save_round(p2, str(d_date), d_season, course_name, p2_str, 0, rp2, h2, n2, rivalry=1, match_group_id=batch_id)
                        st.success(f"Duel Saved! Winner: {w_ref} ({reason})")
                        st.rerun()

# ==========================
# TAB 3: HISTORY
# ==========================
with tab3:
    st.header("Match History")
    if not df_history.empty:
        if 'match_group_id' in df_history.columns:
             df_history["display_group"] = df_history["match_group_id"].fillna(df_history["date"] + df_history["course"])
        else:
             df_history["display_group"] = df_history["date"] + " | " + df_history["course"]

        unique_groups = df_history["display_group"].unique()[::-1]
        
        for group_id in unique_groups:
            data = df_history[df_history["display_group"] == group_id]
            first_row = data.iloc[0]
            label = f"{first_row['date']} | {first_row['course']}"
            
            with st.expander(label):
                is_2v2 = "2v2" in str(first_row["course"]) or "Alliance" in str(first_row["notes"])
                
                if is_2v2:
                    disp = data[["player_name", "gross_score", "rp_earned", "notes"]].copy()
                    disp["rp_earned"] = disp["rp_earned"].apply(fmt_num)
                    disp.columns = ["Player", "Holes Won", "RP", "Notes"]
                    st.table(disp)
                else:
                    disp = data[["player_name", "gross_score", "stableford_score", "rp_earned", "notes"]].copy()
                    disp["rp_earned"] = disp["rp_earned"].apply(fmt_num)
                    disp.columns = ["Player", "Strokes", "Stbl", "RP", "Notes"]
                    st.table(disp)
                
                del_key = str(group_id)
                if st.button("🗑️ Delete Round", key=del_key): 
                    if 'match_group_id' in data.columns and pd.notna(first_row['match_group_id']):
                        db.delete_round_group(first_row['match_group_id'])
                    else:
                        st.error("Cannot delete legacy rounds without Group ID.")
                    st.rerun()

# ==========================
# TAB 4: AWARDS
# ==========================
with tab4:
    st.header("🏆 Hall of Fame")
    c1, c2, c3, c4 = st.columns(4)
    def render_award(col, title, icon, holder, stat, lore):
        
        # Display Logic
        if isinstance(holder, list):
            # TIE
            display_holder = f"<span style='color: #ff4b4b'>TIE: {', '.join(holder)}</span>"
        elif holder:
            # WINNER
            display_holder = holder
        else:
            # VACANT
            display_holder = "VACANT"
            
        col.markdown(f"""
        <div class="award-card">
            <div>
                <div class="award-icon">{icon}</div>
                <div class="award-title">{title}</div>
                <div class="award-holder">{display_holder}</div>
                <div class="award-stat">{stat}</div>
            </div>
            <div class="award-lore">{lore}</div>
        </div>
        """, unsafe_allow_html=True)
    
    s_val = f"{live_stats.get('Sniper', '-')} Strokes" if live_holders.get("Sniper") else str(live_stats.get('Sniper', '-'))
    render_award(c1, "THE SNIPER", "🎯", live_holders.get("Sniper"), s_val, "Lowest single round strokes. (+5 RP)")
    
    if live_holders.get("Rock"): r_val = f"{live_stats.get('Rock', '-')} Avg"
    else: r_val = str(live_stats.get('Rock', "Min 5 Rnds"))
    render_award(c2, "THE ROCK", "🪨", live_holders.get("Rock"), r_val, "Highest average Stableford points. (+10 RP)")
    
    roc_val = f"{live_stats.get('Rocket', '-')}"
    render_award(c3, "THE ROCKET", "🚀", live_holders.get("Rocket"), roc_val, "Best handicap progression (Min 3 Rnds). (+10 RP)")
    
    cq_val = f"{live_stats.get('Conqueror', '-')} Wins"
    render_award(c4, "THE CONQUEROR", "⚔️", live_holders.get("Conqueror"), cq_val, "Most 'Winner of the Day' titles (Min 3 Wins). (+10 RP)")

# ==========================
# TAB 5: PLAYERS
# ==========================
with tab5:
    st.header("Player Management")
    st.dataframe(df_players, use_container_width=True)
    st.divider()
    with st.expander("Actions"):
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Add")
            n = st.text_input("Name")
            h = st.number_input("HCP", 0.0, 54.0)
            if st.button("Add Player"): 
                db.add_player(n, h); st.success("Added"); st.rerun()
        with c2:
            st.subheader("Delete")
            d = st.selectbox("Select Player", df_players["name"].tolist())
            if st.button("Delete") and d:
                db.delete_player(d); st.warning("Deleted"); st.rerun()
