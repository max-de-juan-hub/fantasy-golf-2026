import sqlite3
import pandas as pd

DB_NAME = "league_data.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Create Tables
    c.execute('''CREATE TABLE IF NOT EXISTS players (
                    name TEXT PRIMARY KEY,
                    handicap REAL,
                    starting_handicap REAL,
                    total_rp REAL,
                    rounds_played INTEGER,
                    wins INTEGER DEFAULT 0
                )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS rounds (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    match_group_id TEXT, 
                    player_name TEXT,
                    date TEXT,
                    season TEXT,
                    course TEXT,
                    gross_score INTEGER,
                    stableford_score INTEGER,
                    rp_earned REAL,
                    new_handicap REAL,
                    notes TEXT,
                    clean_sheet INTEGER DEFAULT 0,
                    hole_in_one INTEGER DEFAULT 0,
                    is_rivalry INTEGER DEFAULT 0
                )''')
    
    # MIGRATION: Check if match_group_id exists (for existing DBs)
    c.execute("PRAGMA table_info(rounds)")
    columns = [info[1] for info in c.fetchall()]
    if "match_group_id" not in columns:
        print("Migrating DB: Adding match_group_id column...")
        c.execute("ALTER TABLE rounds ADD COLUMN match_group_id TEXT")
        
    conn.commit()
    conn.close()

def add_player(name, handicap):
    conn = sqlite3.connect(DB_NAME)
    try:
        conn.execute("INSERT INTO players VALUES (?, ?, ?, 0, 0, 0)", (name, handicap, handicap))
        conn.commit()
        return True
    except: return False
    finally: conn.close()

def delete_player(name):
    conn = sqlite3.connect(DB_NAME)
    conn.execute("DELETE FROM players WHERE name = ?", (name,))
    conn.execute("DELETE FROM rounds WHERE player_name = ?", (name,))
    conn.commit()
    conn.close()

def save_round(player, date, season, course, gross, stbl, rp, new_hcp, notes, clean=0, hio=0, rivalry=0, match_group_id=None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""INSERT INTO rounds 
                 (match_group_id, player_name, date, season, course, gross_score, stableford_score, rp_earned, new_handicap, notes, clean_sheet, hole_in_one, is_rivalry) 
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", 
              (match_group_id, player, date, season, course, gross, stbl, rp, new_hcp, notes, clean, hio, rivalry))
    
    c.execute("""UPDATE players 
                 SET handicap = ?, total_rp = total_rp + ?, rounds_played = rounds_played + 1 
                 WHERE name = ?""", (new_hcp, rp, player))
    conn.commit()
    conn.close()

def delete_round_group(match_group_id):
    """Deletes all rounds associated with a specific match submission."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # 1. Revert Player Stats
    c.execute("SELECT player_name, rp_earned FROM rounds WHERE match_group_id = ?", (match_group_id,))
    for p_name, rp in c.fetchall():
        c.execute("UPDATE players SET total_rp = total_rp - ?, rounds_played = rounds_played - 1 WHERE name = ?", (rp, p_name))
        
    # 2. Delete Rounds
    c.execute("DELETE FROM rounds WHERE match_group_id = ?", (match_group_id,))
    conn.commit()
    conn.close()

def get_leaderboard():
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM players ORDER BY total_rp DESC", conn)
    conn.close()
    return df

def get_history():
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM rounds ORDER BY date DESC, id DESC", conn)
    conn.close()
    return df

def has_played_2v2(player_name):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT count(*) FROM rounds WHERE player_name = ? AND is_rivalry = 1", (player_name,))
    count = c.fetchone()[0]
    conn.close()
    return count > 0

if __name__ == "__main__":
    init_db()
