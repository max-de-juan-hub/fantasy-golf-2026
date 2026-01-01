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
        if "notes" not in rounds.columns: rounds["notes"] = ""
        
        rounds["holes_played"] = rounds["holes_played"].fillna("18").astype(str)
        rounds["gross_score"] = rounds["gross_score"].fillna(0).astype(int)
        rounds["stableford_score"] = rounds["stableford_score"].fillna(0).astype(int)
        rounds["rp_earned"] = rounds["rp_earned"].fillna(0).astype(int)
        rounds["date"] = pd.to_datetime(rounds["date"], errors='coerce')
        
        return players, rounds
    except Exception as e:
        # Fallback for empty/new sheet
        return pd.DataFrame(columns=["name", "handicap"]), pd.DataFrame(columns=["player_name", "rp_earned", "stableford_score", "gross_score", "date", "course", "match_type", "notes", "holes_played"])

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
    if pd.isnull(date_obj): return "Unknown"
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
for col in ["Tournament 1 Ranking Points", "Season 1", "Season 2", "Rounds", "Avg Score", "Best Gross", "1v1 Wins", "1v1 Losses", "Daily Wins"]:
    stats[col] = 0
stats["2v2 Record"] = "0-0-0" # Init as string

if not df_rounds.empty:
    # A. Ranking Points & Rounds
    for idx, row in df_rounds.iterrows():
        p = row["player_name"]
        rp = row["rp_earned"]
        if pd.notnull(row["date"]) and p in stats.index:
            season = get_season(row["date"])
            
            # Add Total & Season
            stats.at[p, "Tournament 1 Ranking Points"] += rp
            if season in stats.columns:
                stats.at[p, season] += rp
            
            # Count Rounds (Standard & Duels count as rounds)
            if row["match_type"] in ["Standard", "Duel"]:
                stats.at[p, "Rounds"] += 1

    # B. Avg Score (18H Standard Only)
    std_rounds = df_rounds[(df_rounds["holes_played"] == "18") & (df_rounds["match_type"] == "Standard")]
    if not std_rounds.empty:
        avg = std_rounds.groupby("player_name")["stableford_score"].mean()
        stats["Avg Score"] = stats["Avg Score"].add(avg, fill_value=0)
    
    # C. Best Gross (Standard OR Duel 18H)
    gross_valid = df_rounds[
        (df_rounds["gross_score"] > 0) & 
        (df_rounds["holes_played"] == "18") & 
        (df_rounds["match_type"].isin(["Standard", "Duel"]))
    ]
    if not gross_valid.empty:
        best = gross_valid.groupby("player_name")["gross_score"].min()
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
        a_ties = allies[allies["rp_earned"] == 0].groupby("player_name").size()
        a_loss = allies[allies["rp_earned"] < 0].groupby("player_name").size()
        
        for p in stats.index:
            w = int(a_wins.get(p, 0))
            t = int(a_ties.get(p, 0))
            l = int(a_loss.get(p, 0))
            stats.at[p, "2v2 Record"] = f"{w}-{t}-{l}"
            
    # F. Daily Wins (Standard + Duel Winners)
    # 1. Standard Rounds
    match_groups = std_rounds.groupby(["date", "course"])
    for _, group in match_groups:
        if not group.empty:
            max_s = group["stableford_score"].max()
            winners = group[group["stableford_score"] == max_s]["player_name"].unique()
            for w in winners:
                if w in stats.index:
                    stats.at[w, "Daily Wins"] += 1
    
    # 2. Duel Winners (RP > 0 implies win/upset in Duel logic)
    duel_winners = duels[duels["rp_earned"] > 0]["player_name"]
    for w in duel_winners:
        if w in stats.index:
             stats.at[w, "Daily Wins"] += 1

# --- 2. TROPHY LOGIC ---
holder_rock = None
holder_sniper = None
holder_conq = None

# A. Rock
qualified_rock = stats[stats["Rounds"] >= 5].sort_values("Avg Score", ascending=False)
if not qualified_rock.empty:
    holder_rock = qualified_rock.index[0]
    stats.at[holder_rock, "Tournament 1 Ranking Points"] += 10

# B. Sniper (Current Month)
today = datetime.date.today()
month_rounds = df_rounds[
    (df_rounds["date"].dt.month == today.month) & 
    (df_rounds["date"].dt.year == today.year) &
    (df_rounds["gross_score"] > 0) &
    (df_rounds["holes_played"] == "18")
]
best_month_score = 0
if not month_rounds.empty:
    best_month_score = month_rounds["gross_score"].min()
    snipers = month_rounds[month_rounds["gross_score"] == best_month_score]["player_name"].unique()
    if len(snipers) > 0:
        holder_sniper = snipers[0]
        if holder_sniper in stats.index:
            stats.at[holder_sniper, "Tournament 1 Ranking Points"] += 5

# C. Conqueror
conq_sort = stats.sort_values(["Daily Wins", "Tournament 1 Ranking Points"], ascending=False)
if not conq_sort.empty and conq_sort.iloc[0]["Daily Wins"] > 0:
    holder_conq = conq_sort.index[0]
    stats.at[holder_conq, "Tournament 1 Ranking Points"] += 10

# Final Polish
stats["Avg Score"] = stats["Avg Score"].round(1)
stats = stats.sort_values("Tournament 1 Ranking Points", ascending=False).reset_index()

def decorate_name(row):
    name = row["player_name"]
    icons = ""
    if name == holder_rock: icons += " 🪨"
    if name == holder_sniper: icons += " 🎯"
    if name == holder_conq: icons += " 👑"
    return f"{name}{icons}"

stats["Player"] = stats.apply(decorate_name, axis=1)

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
    
    lb_data = stats.copy()
    lb_data["1v1 Record"] = lb_data["1v1 Wins"].astype(int).astype(str) + "-" + lb_data["1v1 Losses"].astype(int).astype(str)
    
    view = lb_data[[
        "Player", "Tournament 1 Ranking Points", "Season 1", "Season 2", "handicap", 
        "Best Gross", "Rounds", "Avg Score", "1v1 Record", "2v2 Record", "Daily Wins"
    ]]
    view = view.rename(columns={"handicap": "Handicap", "Best Gross": "Best Round Strokes"})

    def highlight_rows(row):
        if row.name == 0:
            return ['background-color: #FFA500; color: black'] * len(row) 
        elif 1 <= row.name <= 3:
            return ['background-color: #FFFFE0; color: black'] * len(row)
        return [''] * len(row)

    st.dataframe(
        view.style.apply(highlight_rows, axis=1).format({"Handicap": "{:.0f}"}), 
        use_container_width=True,
        hide_index=True
    )
    st.caption("🔶 **Orange:** League Leader | 🟡 **Yellow:** Top 4 (Qualify for King's Cup)")

# =========================================================
# TAB 2: TROPHY ROOM
# =========================================================
with tab_trophy:
    st.header("🏆 The Hall of Fame")
    
    def get_text(holder, val, label): return f"{holder}\n\n*({val} {label})*" if holder else "Unclaimed"
    
    rock_val = stats[stats["player_name"] == holder_rock]["Avg Score"].values[0] if holder_rock else 0
    snip_val = best_month_score if holder_sniper else 0
    conq_val = stats[stats["player_name"] == holder_conq]["Daily Wins"].values[0] if holder_conq else 0

    st.markdown("""<style>.trophy-card { background-color: #262730; padding: 20px; border-radius: 10px; border: 1px solid #4B4B4B; text-align: center; } .t-icon { font-size: 40px; } .t-head { font-size: 18px; font-weight: bold; color: #FFD700; margin-top: 5px; } .t-sub { font-size: 12px; color: #A0A0A0; margin-bottom: 10px; } .t-name { font-size: 20px; font-weight: bold; color: white; } .t-bonus { color: #00FF00; font-weight: bold; font-size: 14px; margin-top: 5px; }</style>""", unsafe_allow_html=True)

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
                        "date": str(dt), "course": crs, "player_name": p, "holes_played": hl,
                        "stableford_score": sf, "gross_score": gr, "rp_earned": rp, "notes": ", ".join(n), "match_type": "Standard"
                    })
                
                if st.form_submit_button("Submit Scorecards"):
                    conn.update(worksheet="rounds", data=pd.concat([df_rounds, pd.DataFrame(new_rows)], ignore_index=True), spreadsheet=SPREADSHEET_NAME)
                    st.success("Saved!")
                    st.rerun()

    # --- DUEL (1v1) ---
    elif mode == "The Duel (1v1)":
        with st.form("duel_form"):
            st.warning("⚔️ **1v1 STAKES**")
            c1, c2 = st.columns(2)
            p1 = c1.selectbox("Player 1", player_list)
            p2 = c2.selectbox("Player 2", player_list, index=1)
            
            winner_name = st.radio("🏆 THE WINNER IS:", [p1, p2], horizontal=True)
            
            c3, c4, c5 = st.columns(3)
            dt = c3.date_input("Date")
            crs = c4.text_input("Course", "Chinderah")
            hl = c5.radio("Length", ["18", "9"], horizontal=True)
            
            st.divider()
            c6, c7 = st.columns(2)
            g1 = c6.number_input(f"{p1} Gross Score", 0)
            g2 = c7.number_input(f"{p2} Gross Score", 0)
            
            stake = st.radio("Stakes Rule:", ["Standard (Winner +5, Loser -5)", "Upset (Winner +10, Loser -10)"])
            
            if st.form_submit_button("Record Duel"):
                if p1 == p2:
                    st.error("Select different players.")
                else:
                    win_p = winner_name
                    lose_p = p2 if win_p == p1 else p1
                    part = 1 if hl == "9" else 2
                    steal = 10 if "Upset" in stake else 5
                    
                    # Scores
                    win_gross = g1 if win_p == p1 else g2
                    lose_gross = g2 if win_p == p1 else g1
                    
                    rows = [
                        {"date": str(dt), "course": crs, "player_name": win_p, "holes_played": hl, "gross_score": win_gross, "stableford_score": 0, "rp_earned": part + steal, "notes": f"Won Duel vs {lose_p}", "match_type": "Duel"},
                        {"date": str(dt), "course": crs, "player_name": lose_p, "holes_played": hl, "gross_score": lose_gross, "stableford_score": 0, "rp_earned": part - steal, "notes": f"Lost Duel vs {win_p}", "match_type": "Duel"}
                    ]
                    conn.update(worksheet="rounds", data=pd.concat([df_rounds, pd.DataFrame(rows)], ignore_index=True), spreadsheet=SPREADSHEET_NAME)
                    st.success("Duel Saved!")
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
                rows = []
                note = f"Result: {wh}-{lh}"
                for p in [w1, w2]: rows.append({"date":str(dt), "course":crs, "player_name":p, "holes_played":"18", "rp_earned": 7, "notes":f"Win ({note})", "match_type":"Alliance"})
                for p in [l1, l2]: rows.append({"date":str(dt), "course":crs, "player_name":p, "holes_played":"18", "rp_earned": -3, "notes":f"Loss ({note})", "match_type":"Alliance"})
                conn.update(worksheet="rounds", data=pd.concat([df_rounds, pd.DataFrame(rows)], ignore_index=True), spreadsheet=SPREADSHEET_NAME)
                st.success("Alliance Saved!")
                st.rerun()

# =========================================================
# TAB 4: HISTORY (GROUPED & EDITABLE)
# =========================================================
with tab_history:
    st.header("📜 Round History")
    st.info("Edit scores directly in the table, then click 'Save Changes'.")
    
    if not df_rounds.empty:
        # Group by match instance
        # We assume a 'match' is defined by Date + Course + Type
        # To handle multiple matches same day/course, we really need IDs, but for now we group.
        
        # 1. Create unique keys
        df_display = df_rounds.copy()
        if pd.notnull(df_display['date']).any():
            df_display['date_str'] = df_display['date'].dt.strftime('%Y-%m-%d')
        else:
            df_display['date_str'] = "No Date"
            
        groups = df_display.groupby(['date_str', 'course', 'match_type'])
        
        # Sort groups by date descending
        sorted_groups = sorted(groups, key=lambda x: x[0][0], reverse=True)
        
        for (d_str, crs, m_type), group_df in sorted_groups:
            # Expander Label
            label = f"📅 {d_str} | ⛳ {crs} | 🏷️ {m_type} ({len(group_df)} Players)"
            
            with st.expander(label):
                # We need to edit the ORIGINAL df, so we need the indices
                # Streamlit data editor returns the edited dataframe
                
                # Prepare editor view
                edit_cols = ['player_name', 'stableford_score', 'gross_score', 'rp_earned', 'notes']
                
                edited_group = st.data_editor(
                    group_df[edit_cols],
                    key=f"editor_{d_str}_{crs}_{m_type}",
                    column_config={
                        "player_name": "Player",
                        "stableford_score": st.column_config.NumberColumn("Stableford", min_value=0, max_value=60),
                        "gross_score": st.column_config.NumberColumn("Gross", min_value=0, max_value=150),
                        "rp_earned": st.column_config.NumberColumn("RP", min_value=-50, max_value=50),
                        "notes": "Notes"
                    },
                    use_container_width=True,
                    num_rows="dynamic"
                )
                
                col_save, col_del = st.columns([1, 4])
                
                if col_save.button("💾 Save Changes", key=f"save_{d_str}_{crs}_{m_type}"):
                    # Logic: Drop old rows, add new rows
                    # 1. Get indices of original group
                    original_indices = group_df.index
                    
                    # 2. Update the main df at these indices
                    # We iterate through the edited dataframe and update the main df by index
                    # Note: This assumes user didn't ADD/REMOVE rows in editor, just edited values.
                    # If they added rows, indices won't match. 
                    # Safer: Delete old indices, append new rows.
                    
                    # A. Delete old
                    df_rounds = df_rounds.drop(original_indices)
                    
                    # B. Prepare new rows (restore hidden cols like date/course)
                    save_df = edited_group.copy()
                    save_df['date'] = pd.to_datetime(d_str)
                    save_df['course'] = crs
                    save_df['match_type'] = m_type
                    # Restore holes_played from first row of original group (assuming same)
                    h_played = group_df.iloc[0]['holes_played']
                    save_df['holes_played'] = h_played
                    
                    # C. Append
                    df_rounds = pd.concat([df_rounds, save_df], ignore_index=True)
                    
                    # D. Write
                    conn.update(worksheet="rounds", data=df_rounds, spreadsheet=SPREADSHEET_NAME)
                    st.success("Match updated!")
                    st.rerun()

                if col_del.button("🗑️ Delete Match Record", key=f"del_{d_str}_{crs}_{m_type}"):
                    # Delete all rows in this group
                    df_rounds = df_rounds.drop(group_df.index)
                    conn.update(worksheet="rounds", data=df_rounds, spreadsheet=SPREADSHEET_NAME)
                    st.error("Match deleted!")
                    st.rerun()
    else:
        st.info("No matches recorded yet.")

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
    st.header("📘 Official Rulebook")
    with st.expander("1. SCORING", expanded=True):
        st.markdown("**Stableford:** Play against Personal Par (Net Par). Albatross(5), Eagle(4), Birdie(3), Par(2), Bogey(1).")
    with st.expander("2. RANKING POINTS (RP)"):
        st.markdown("**Target 36:** (Score-36)*2 = Gain. (Score-36)/2 = Loss.")
    with st.expander("3. BONUSES"):
        st.markdown("Participation(+2), Clean Sheet(+2), Road Warrior(+2), HIO(+10).")
    with st.expander("4. RIVALRY"):
        st.markdown("**1v1:** Winner +5/+10, Loser -5/-10.\n**2v2:** Winners +5, Losers -5.")
