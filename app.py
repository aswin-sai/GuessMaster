# Requires psycopg v3: pip install psycopg[binary]
from flask import Flask, render_template, jsonify, request, session
from random import randint
import psycopg
import os


app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Needed for session


# Set your PostgreSQL connection string here
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "dbname=postgres user=postgres password=aswin host=localhost"
)

def get_db():
    return psycopg.connect(DATABASE_URL, autocommit=True)

def init_db():
    with get_db() as conn:
        with conn.cursor() as cur:
            # Only keep tables needed for single player
            cur.execute("DROP TABLE IF EXISTS game_state;")
            cur.execute("DROP TABLE IF EXISTS games;")
            cur.execute("DROP TABLE IF EXISTS users CASCADE;")
            cur.execute("DROP TABLE IF EXISTS admins CASCADE;")
            # Admins table
            cur.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                username TEXT PRIMARY KEY,
                password TEXT NOT NULL
            );
            """)
            # Users table
            cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS games (
                id SERIAL PRIMARY KEY,
                username TEXT REFERENCES users(username),
                number INTEGER NOT NULL,
                attempts_left INTEGER NOT NULL,
                result TEXT NOT NULL,
                played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS game_state (
                username TEXT PRIMARY KEY REFERENCES users(username),
                number INTEGER NOT NULL,
                chances INTEGER NOT NULL
            );
            """)

# Remove @app.before_serving and call init_db() directly at startup
init_db()

@app.route('/')
def index():
    return render_template('index.html', title="GuessMaster: The Ultimate Number Challenge")

@app.route('/start', methods=['POST'])
def start():
    data = request.get_json()
    username = data.get('username')
    if not username:
        return jsonify({"error": "Username required"}), 400
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO users (username) VALUES (%s) ON CONFLICT DO NOTHING;", (username,))
            cur.execute("SELECT number, chances FROM game_state WHERE username = %s;", (username,))
            row = cur.fetchone()
            if row and row[1] > 0:
                # Resume existing game
                number, chances = row
                return jsonify({"message": f"Welcome back {username}! You have {chances} chances left. Keep guessing your 2-digit number!"})
            else:
                # Start a new game
                number = randint(10, 99)
                chances = 5
                cur.execute("""
                    INSERT INTO game_state (username, number, chances)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (username) DO UPDATE SET number = EXCLUDED.number, chances = EXCLUDED.chances;
                """, (username, number, chances))
                return jsonify({"message": f"Game started for {username}! Guess a 2-digit number. You have 5 chances."})

@app.route('/guess', methods=['POST'])
def guess():
    username = request.args.get('username')
    if not username:
        return jsonify({"error": "Username required"}), 400
    data = request.get_json()
    guess = int(data.get('guess', 0))
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT number, chances FROM game_state WHERE username = %s;", (username,))
            row = cur.fetchone()
            if not row or row[1] == 0:
                return jsonify({"error": "Game not started or no chances left."}), 400
            number, chances = row
            if guess == number:
                cur.execute("""
                    INSERT INTO games (username, number, attempts_left, result)
                    VALUES (%s, %s, %s, %s);
                """, (username, number, chances, "win"))
                cur.execute("UPDATE game_state SET chances = 0 WHERE username = %s;", (username,))
                return jsonify({
                    "result": "correct",
                    "guess": guess,
                    "number": number,
                    "chances": 0,
                    "clue": "🎉 You nailed it! That's the magic number!"
                })
            chances -= 1
            # More interactive and catchy hints
            if guess < number:
                clue = [
                    "🔼 Go higher! The number is bigger.",
                    "📈 Aim up! Try a larger number.",
                    "🚀 Too low! Shoot for the stars.",
                    "⬆️ Not quite! Think bigger.",
                    "🧐 Hint: It's more than that!"
                ][chances % 5]
            else:
                clue = [
                    "🔽 Go lower! The number is smaller.",
                    "📉 Aim down! Try a smaller number.",
                    "🌙 Too high! Come back to earth.",
                    "⬇️ Not quite! Think smaller.",
                    "🤔 Hint: It's less than that!"
                ][chances % 5]
            if chances == 0:
                cur.execute("""
                    INSERT INTO games (username, number, attempts_left, result)
                    VALUES (%s, %s, %s, %s);
                """, (username, number, 0, "lose"))
                cur.execute("UPDATE game_state SET chances = 0 WHERE username = %s;", (username,))
                return jsonify({
                    "result": "failed",
                    "guess": guess,
                    "number": number,
                    "chances": 0,
                    "clue": f"💥 Game over! The number was {number}. Better luck next time!"
                })
            else:
                cur.execute("UPDATE game_state SET chances = %s WHERE username = %s;", (chances, username))
                return jsonify({
                    "result": "wrong",
                    "guess": guess,
                    "number": None,
                    "chances": chances,
                    "clue": f"{clue} ({chances} chances left)"
                })

@app.route('/user_result', methods=['GET'])
def user_result():
    username = request.args.get('username')
    if not username:
        return jsonify({"error": "Username required"}), 400
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT result, number, attempts_left FROM games
                WHERE username = %s
                ORDER BY played_at DESC, id DESC LIMIT 1;
            """, (username,))
            row = cur.fetchone()
            if not row:
                return jsonify({"message": "No result found for this user."})
            return jsonify({"result": row[0], "number": row[1], "attempts_left": row[2]})

@app.route('/all_results', methods=['GET'])
def all_results():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT username, result, number, attempts_left, played_at FROM games
                ORDER BY played_at DESC, id DESC;
            """)
            results = cur.fetchall()
            data = {}
            for username, result, number, attempts_left, played_at in results:
                if username not in data:
                    data[username] = []
                data[username].append({
                    "result": result,
                    "number": number,
                    "attempts_left": attempts_left,
                    "played_at": str(played_at)
                })
            return jsonify(data)

@app.route('/scoreboard', methods=['GET'])
def scoreboard():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT username, result, number, attempts_left, played_at
                FROM games
                ORDER BY played_at DESC, id DESC;
            """)
            results = cur.fetchall()
            scoreboard = []
            user_game_count = {}
            for username, result, number, attempts_left, played_at in results:
                user_game_count[username] = user_game_count.get(username, 0) + 1
                scoreboard.append({
                    "username": username,
                    "game": user_game_count[username],
                    "result": result,
                    "number": number,
                    "attempts_left": attempts_left,
                    "played_at": str(played_at)
                })
            return jsonify(scoreboard)

@app.route('/admin_login', methods=['POST'])
def admin_login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM admins WHERE username=%s AND password=%s", (username, password))
            if cur.fetchone():
                session["is_admin"] = True
                return jsonify({"success": True})
            else:
                return jsonify({"success": False, "error": "Invalid admin credentials"}), 403

@app.route('/admin_logout', methods=['POST'])
def admin_logout():
    session.pop("is_admin", None)
    return jsonify({"success": True})

def is_admin():
    return session.get("is_admin", False)

@app.route('/delete_user', methods=['POST'])
def delete_user():
    if not is_admin():
        return jsonify({"error": "Admin privileges required"}), 403
    data = request.get_json()
    username = data.get('username')
    if not username:
        return jsonify({"error": "Username required"}), 400
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM games WHERE username=%s", (username,))
            cur.execute("DELETE FROM game_state WHERE username=%s", (username,))
            cur.execute("DELETE FROM users WHERE username=%s", (username,))
    return jsonify({"success": True})

@app.route('/reset_scoreboard', methods=['POST'])
def reset_scoreboard():
    if not is_admin():
        return jsonify({"error": "Admin privileges required"}), 403
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM games;")
            cur.execute("DELETE FROM game_state;")
            cur.execute("DELETE FROM users;")
    return jsonify({"message": "Scoreboard reset."})

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0')