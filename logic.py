import math
import pandas as pd
from datetime import datetime

# --- SEASONS ---
def get_season(date_obj):
    if isinstance(date_obj, str):
        try:
            date_obj = datetime.strptime(date_obj, "%Y-%m-%d").date()
        except ValueError:
            # Handle different date formats if Google sends them weirdly
            date_obj = datetime.now().date()
            
    m = date_obj.month
    d = date_obj.day
    if 1 <= m <= 3: return "Season 1"
    elif 4 <= m <= 6 and d <= 20: return "Season 2"
    elif m == 6 and d > 20: return "Kings Cup"
    elif 7 <= m <= 9: return "Season 3"
    elif 10 <= m <= 12 and d <= 20: return "Season 4"
    else: return "Finals"

# --- RANKING POINTS (Standalone) ---
def calculate_rp(stableford_score, clean_sheet=False, hole_in_one=False, bonuses=0):
    """
    Calculates RP based on Stableford performance + Bonuses.
    """
    # SAFETY: Ensure inputs are numbers
    score = int(float(stableford_score))
    
    target = 36
    note_parts = []
    
    # 1. Base Score Logic
    if score >= target:
        # x2 Multiplier Rule
        diff = score - target
        base = diff * 2
        note_parts.append(f"Stbl Perf (+{base})")
    else:
        # Damage Control
        diff = score - target
        base = round(diff / 2) 
        note_parts.append(f"Stbl Perf ({base})")
        
    # 2. Add Bonuses
    total = base + float(bonuses)
    
    if clean_sheet:
        total += 2
        note_parts.append("Clean Sheet (+2)")
        
    if hole_in_one:
        total += 10
        note_parts.append("Hole-in-One (+10)")
        
    return total, ", ".join(note_parts)

# --- BONUS CALCULATOR (GROUP) ---
def calculate_group_bonuses(group_data, current_standings):
    results = {}
    
    # SAFETY: Ensure stableford scores are numbers for sorting
    for p in group_data:
        p['stbl'] = int(float(p['stbl']))
    
    # 1. Identify Winners and Pot Size
    sorted_players = sorted(group_data, key=lambda x: x['stbl'], reverse=True)
    highest_stbl = sorted_players[0]['stbl']
    winners = [p for p in sorted_players if p['stbl'] == highest_stbl]
    
    num_players = len(group_data)
    pot_size = 0
    if num_players == 2: pot_size = 2
    elif num_players == 3: pot_size = 4
    elif num_players >= 4: pot_size = 6
    
    # SPLIT LOGIC
    wod_share = 0
    is_tie = len(winners) > 1
    if num_players >= 2 and pot_size > 0:
        wod_share = pot_size / len(winners)

    for p in group_data:
        name = p['name']
        score = p['stbl']
        bonuses = 0
        notes = []
        
        # A. Participation
        bonuses += 2
        notes.append("Part (+2)")
        
        # B. Winner of the Day (Split Pot)
        if name in [w['name'] for w in winners] and num_players >= 2:
            bonuses += wod_share
            share_str = f"{wod_share:g}" # Removes trailing zeros
            tie_msg = " (Tie)" if is_tie else ""
            notes.append(f"Winner of Day{tie_msg} (+{share_str})")
            
        # C. Giant Slayer
        slayer_pts = 0
        my_rp = float(current_standings.get(name, {}).get('rp', 0))
        
        for opp in group_data:
            if opp['name'] == name: continue
            opp_rp = float(current_standings.get(opp['name'], {}).get('rp', 0))
            if score > opp['stbl'] and opp_rp > my_rp:
                slayer_pts += 1
        
        if slayer_pts > 0:
            bonuses += slayer_pts
            notes.append(f"Giant Slayer (+{slayer_pts})")
            
        # D. Road Warrior
        if p.get('road_warrior', False):
            bonuses += 2
            notes.append("Road Warrior (+2)")
        
        # Calculate Base RP
        base_rp, base_note = calculate_rp(score, p.get('clean', False), p.get('hio', False), bonuses)
        final_notes = f"{base_note}, {', '.join(notes)}"

        results[name] = {
            "total_rp": base_rp, 
            "notes": final_notes,
            "new_hcp": calculate_new_handicap(p['hcp'], score)
        }
        
    return results

# --- HANDICAP ---
def calculate_new_handicap(current_hcp, stableford_score, is_away_game=False, par_70_plus=False):
    # SAFETY CASTS
    current_hcp = float(current_hcp)
    stableford_score = int(float(stableford_score))

    playing_hcp = current_hcp
    if is_away_game and par_70_plus:
        if current_hcp <= 10: playing_hcp += 3
        elif current_hcp <= 20: playing_hcp += 5
        else: playing_hcp += 7
    
    new_hcp = current_hcp
    if current_hcp > 36 and stableford_score > 36:
        cut = stableford_score - 36
        new_hcp = current_hcp - cut
    elif stableford_score >= 40: new_hcp -= 2.0
    elif 37 <= stableford_score <= 39: new_hcp -= 1.0
    elif 27 <= stableford_score <= 36: pass
    else: new_hcp += 1.0

    return round(new_hcp, 1)

# --- RIVALRY 1v1 LOGIC ---
def calculate_rivalry_1v1(p1_strokes, p2_strokes, p1_hcp, p2_hcp):
    # SAFETY CASTS
    p1_strokes = int(float(p1_strokes))
    p2_strokes = int(float(p2_strokes))
    p1_hcp = float(p1_hcp)
    p2_hcp = float(p2_hcp)

    winner = None
    reason = ""
    
    if p1_strokes < p2_strokes:
        winner = "p1"
        reason = "Lower Strokes"
    elif p2_strokes < p1_strokes:
        winner = "p2"
        reason = "Lower Strokes"
    else:
        # TIE ON STROKES - Check Handicap
        if p1_hcp > p2_hcp:
            winner = "p1"
            reason = "Tie-Breaker (Underdog)"
        elif p2_hcp > p1_hcp:
            winner = "p2"
            reason = "Tie-Breaker (Underdog)"
        else:
            winner = "tie"
            reason = "Absolute Tie"
            
    # Stakes
    if winner == "p1":
        is_upset = p1_hcp > p2_hcp
        stakes = 10 if is_upset else 5
        return "p1", stakes, reason
    elif winner == "p2":
        is_upset = p2_hcp > p1_hcp
        stakes = 10 if is_upset else 5
        return "p2", stakes, reason
    else:
        return "tie", 0, reason

# --- TIE BREAKER / HALL OF FAME LOGIC ---
def resolve_tie_via_head_to_head(tied_players_list, history_df):
    if len(tied_players_list) == 1:
        return tied_players_list[0], "Clear Winner"
    
    if len(tied_players_list) < 1:
        return None, "No Candidates"
    
    h2h_wins = {name: 0 for name in tied_players_list}
    matches_found = False
    
    if history_df.empty: return tied_players_list, "No History"

    if 'match_group_id' in history_df.columns:
        history_df['group_key'] = history_df['match_group_id'].fillna(history_df['date'].astype(str) + history_df['course'])
        grouped = history_df.groupby('group_key')
    else:
        grouped = history_df.groupby(['date', 'course'])
    
    for _, group in grouped:
        players_in_round = group['player_name'].tolist()
        candidates_present = [p for p in tied_players_list if p in players_in_round]
        
        if len(candidates_present) >= 2:
            matches_found = True
            round_scores = group[group['player_name'].isin(candidates_present)][['player_name', 'stableford_score']]
            max_score_in_round = round_scores['stableford_score'].max()
            round_winners = round_scores[round_scores['stableford_score'] == max_score_in_round]['player_name'].tolist()
            
            for w in round_winners:
                h2h_wins[w] += 1

    if not matches_found:
        return tied_players_list, "Tie Unresolved (Never played together)"
    
    max_wins = max(h2h_wins.values())
    best_h2h_players = [p for p, wins in h2h_wins.items() if wins == max_wins]
    
    if len(best_h2h_players) == 1:
        return best_h2h_players[0], f"Won H2H ({max_wins} wins)"
    else:
        return best_h2h_players, "Tie Unresolved (Equal H2H record)"