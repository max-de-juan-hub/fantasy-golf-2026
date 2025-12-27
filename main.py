import streamlit as st
import pandas as pd
from datetime import date
import database as db
import logic
import uuid

# --- CONFIG ---
st.set_page_config(page_title="Fantasy Golf 2026", layout="wide", page_icon="🏆")

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

# --- DATA LOADING (GOOGLE SHEETS) ---
# We use try/except to prevent the app from crashing if the sheet is empty or connection fails
try:
    df_players = db.load_players()
    df_history = db.load_history()
    
    # CALCULATE SEASONS DYNAMICALLY
    # Since we don't save "Season 1" in the sheet, we calculate it from the date here
    if not df_history.empty:
        df_history["season"] = df_history["date"].apply(lambda x: logic.get_season(str(x)))
        # Ensure numbers are numbers (Google Sheets sometimes sends text)
        df_history["rp_earned"] = pd.to_numeric(df_history["rp_earned"], errors='coerce').fillna(0)
        df_history["gross_score"] = pd.to_numeric(df_history["gross_score"], errors='coerce').fillna(0)
        df_history["stableford_score"] = pd.to_numeric(df_history["stableford_score"], errors='coerce').fillna(0)
        
    # Ensure Player data is numeric
    if not df_players.empty:
        df_players["total_rp"] = pd.to_numeric(df_players["total_rp"], errors='coerce').fillna(0)
        df_players["handicap"] = pd.to_numeric(df_players["handicap"], errors='coerce').fillna(0)
        df_players["rounds_played"] = pd.to_numeric(df_players["rounds_played"], errors='coerce').fillna(0)

except Exception as e:
    st.error(f"Connection Error: {e}")
    df_players = pd.DataFrame()
    df_history = pd.DataFrame()

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
    # Check notes for match type
    # We look for "Duel" or "Alliance" in notes column
    relevant_rows = p_rows[p_rows["notes"].str.contains(match_type_str, na=False)]
    
    wins, losses, ties = 0, 0, 0
    for note in relevant_rows["notes"]:
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

valid_stroke_play = df_history[df_history["gross_score"] > 20] if not df_history.empty else pd.DataFrame()
live_holders, live_bonus_points, live_stats = calculate_awards_snapshot(valid_stroke_play, df_players)

# Rocket Logic - MIN 3 ROUNDS
if not df_players.empty:
    # We calculate progression based on current HCP vs Starting HCP
    # Note: For now, assuming starting handicap is not stored in Sheets, we skip or treat as 0 change
    # Or, we can look at the very first round in history for that player?
    # Simplified: We will disable Rocket for the first version to keep it simple, or default to None
    live_holders["Rocket"] = None
    live_stats["Rocket"] = "Coming Soon"

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
            if df_history.empty:
                s1_totals[name] = 0
                continue
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
            
            # Icons logic
            icons = ""
            for aw_key, icon in [("Sniper","🎯"), ("Rock","🪨"), ("Rocket","🚀"), ("Conqueror","⚔️")]:
                h = live_holders.get(aw_key)
                if isinstance(h, str) and h == name: icons += f" {icon}"
                elif isinstance(h, list) and name in h: icons += f" {icon}"
            
            if not df_history.empty:
                p_hist = df_history[df_history["player_name"] == name]
                s1_base = p_hist[p_hist["season"]=="Season 1"]["rp_earned"].sum()
                s2_base = p_hist[p_hist["season"]=="Season 2"]["rp_earned"].sum()
                lifetime_rp = p_hist["rp_earned"].sum()
            else:
                p_hist = pd.DataFrame()
                s1_base = 0
                s2_base = 0
                lifetime_rp = 0

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
            
            total_rp = lifetime_rp + s1_podium_map.get(name, 0)
            if season_1_over:
                total_rp += s1_bonus_points.get(name, 0) + live_bonus_points.get(name, 0)
            else:
                total_rp += live_bonus_points.get(name, 0)

            p_stats = p_hist[p_hist["gross_score"] > 20] if not p_hist.empty else pd.DataFrame()
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
    else:
        st.info("No players found. Add players in the 'Players' tab.")

# ==========================
# TAB 2: SUBMIT
# ==========================
with tab2:
    st.header("Submit Results")
    mode = st.radio("Mode", ["Standard Round", "⚔️ Rivalry Challenge"], horizontal=True)
    d_date = st.date_input("Date", date.today())
    d_course = st.text_input("Course", "Chinderah")
    d_season = logic.get_season(str(d_date))

    if mode == "Standard Round":
        if not df_players.empty:
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
                        
                        # Get current handicap from dataframe
                        curr_hcp = df_players[df_players["name"]==p].iloc[0]["handicap"]
                        group_inputs.append({"name": p, "gross": g, "stbl": s, "hcp": curr_hcp, "clean": cl, "hio": hi, "road_warrior": rw})
                        st.divider()
                
                if st.form_submit_button("🚀 Submit Group Round"):
                    if not selected: st.error("Select players.")
                    else:
                        batch_id = str(uuid.uuid4())
                        # Create a quick dict of standings for logic
                        full_standings = {n: {'rp': r} for n, r in zip(df_players["name"], df_players["total_rp"])}
                        
                        results = logic.calculate_group_bonuses(group_inputs, full_standings)
                        
                        for p_data in group_inputs:
                            name = p_data['name']
                            res = results[name]
                            
                            # Check if they won (if "Winner of Day" is in notes)
                            is_win = "Winner of Day" in res['notes']
                            
                            # 1. Update Player Stats (Handicap, RP, etc.)
                            db.update_player_stats(name, res['new_hcp'], res['total_rp'], is_win=is_win)
                            
                            # 2. Log the Round
                            db.log_round(str(d_date), d_course, name, 
                                         p_data['stbl'], res['total_rp'], res['notes'], 
                                         batch_id) # Note: Gross score is not saved in this sheet schema to save cols, can add if needed
                            
                        st.success("Round Saved to Google Sheets!")
                        st.rerun()
        else:
            st.warning("Please add players first.")

    else:
        # RIVALRY MODE
        if not df_players.empty:
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
                            
                            # Note: Debut logic requires checking history, skipping for simplicity in V1 of Sheets
                            
                            for p in winners:
                                note = f"Alliance Win (+{win_rp})" if res_code != "Tie" else "Alliance Tie"
                                h = df_players[df_players["name"]==p].iloc[0]["handicap"]
                                db.update_player_stats(p, h, win_rp, is_win=True)
                                db.log_round(str(d_date), "2v2 Match", p, 0, win_rp, note, batch_id)

                            for p in losers:
                                note = f"Alliance Loss ({lose_rp})"
                                h = df_players[df_players["name"]==p].iloc[0]["handicap"]
                                db.update_player_stats(p, h, lose_rp, is_win=False)
                                db.log_round(str(d_date), "2v2 Match", p, 0, lose_rp, note, batch_id)
                                
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
                            
                            # Save P1
                            db.update_player_stats(p1, h1, rp1, is_win=(w_ref=="p1"))
                            db.log_round(str(d_date), f"{d_course} (Duel)", p1, 0, rp1, n1, batch_id)
                            
                            # Save P2
                            db.update_player_stats(p2, h2, rp2, is_win=(w_ref=="p2"))
                            db.log_round(str(d_date), f"{d_course} (Duel)", p2, 0, rp2, n2, batch_id)

                            st.success(f"Duel Saved! Winner: {w_ref} ({reason})")
                            st.rerun()
        else:
            st.warning("Add players first.")

# ==========================
# TAB 3: HISTORY
# ==========================
with tab3:
    st.header("Match History")
    if not df_history.empty:
        # Use match_group_id to group display
        if 'match_group_id' in df_history.columns:
             df_history["display_group"] = df_history["match_group_id"].fillna(df_history["date"] + df_history["course"])
        else:
             df_history["display_group"] = df_history["date"] + " | " + df_history["course"]

        unique_groups = df_history["display_group"].unique()[::-1] # Show newest first
        
        for group_id in unique_groups:
            data = df_history[df_history["display_group"] == group_id]
            first_row = data.iloc[0]
            label = f"{first_row['date']} | {first_row['course']}"
            
            with st.expander(label):
                # Check match type based on notes/course
                is_2v2 = "2v2" in str(first_row["course"]) or "Alliance" in str(first_row["notes"])
                
                if is_2v2:
                    disp = data[["player_name", "rp_earned", "notes"]].copy()
                    disp.columns = ["Player", "RP", "Notes"]
                    st.table(disp)
                else:
                    disp = data[["player_name", "stableford_score", "rp_earned", "notes"]].copy()
                    disp.columns = ["Player", "Stbl", "RP", "Notes"]
                    st.table(disp)
                
                st.caption("To edit or delete this round, please edit the Google Sheet 'rounds' tab directly.")
    else:
        st.info("No history found. Submit a round!")

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
    if not df_players.empty:
        st.dataframe(df_players, use_container_width=True)
    
    st.divider()
    with st.expander("Add New Player"):
        n = st.text_input("Name")
        h = st.number_input("HCP", 0.0, 54.0)
        if st.button("Add Player"): 
            if n:
                # We use update_player_stats with 0 RP to create the row
                db.update_player_stats(n, h, 0, is_win=False)
                st.success(f"Added {n}")
                st.rerun()
            else:
                st.error("Enter a name.")
                
    st.info("To DELETE a player, delete their row in the Google Sheet 'players' tab.")