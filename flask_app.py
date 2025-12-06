from flask import Flask, render_template, request, jsonify
import mysql.connector # pip install mysql-connector-python
import random
import configparser
import sys
import time

app = Flask(__name__)
games = {}
config = None
prompts = []

# Időtúllépés másodpercben (ha ennyi ideig nem "pingel" az admin, töröljük a játékot)
TIMEOUT_SECONDS = 60

class Game:
    def __init__(self, prompt) -> None:
        self.prompt = prompt
        self.sentences = []
        self.is_final = False
        # Létrehozáskor beállítjuk az aktuális időt
        self.last_active = time.time()

def get_database_connection():
    global config
    if config is None:
        config = configparser.ConfigParser()
        config.read('config.ini')
    return mysql.connector.connect(
        host = config.get('Database', 'db_host'),
        user = config.get('Database', 'db_user'),
        password = config.get('Database', 'db_password'),
        database = config.get('Database', 'db_database')
    )

def initialize_prompts():
    global prompts
    try:
        database_connection = get_database_connection()
        cursor = database_connection.cursor()
        cursor.execute('SELECT prompt, gpt_answer FROM prompts WHERE is_custom=FALSE')
        prompts = cursor.fetchall()
        database_connection.close()
    except Exception as e:
        print(f"Hiba az adatbázis kapcsolódáskor: {e}", file=sys.stderr)
        # Fallback, ha nincs DB kapcsolat, hogy a kód ne szálljon el teszteléskor
        prompts = [("Teszt prompt (nincs DB)", "Teszt válasz")]

def insert_into_database(insert_command, values):
    try:
        database_connection = get_database_connection()
        cursor = database_connection.cursor()
        cursor.execute(insert_command, values)
        database_connection.commit()
        database_connection.close()
    except Exception as e:
        print(f"Adatbázis hiba: {e}", file=sys.stderr)

@app.route('/get_game_status', methods=['GET'])
def get_game_status():
    game_id = request.args.get('game')

    if game_id in games:
        current_game = games[game_id]

        # HEARTBEAT: Frissítjük az utolsó aktivitás idejét,
        # mert valaki (valószínűleg az admin JS-e) lekérdezte az állapotot.
        current_game.last_active = time.time()

        return jsonify({
            'exists': True,
            'sentence_count': len(current_game.sentences),
            'is_final': current_game.is_final
        })
    else:
        return jsonify({'exists': False})

@app.route('/', methods=['GET', 'POST'])
def home():
    global games

    message = None
    action = 'refresh'
    guessed = False

    is_admin = request.values.get('is_admin') == 'True'
    game = request.values.get('game')

    if request.method == 'POST':
        if 'action' in request.form:
            action = request.form['action']

        if action == 'generate':
            game = str(random.randint(1000, 9999))
            if 'is_custom_prompt' in request.form:
                games[game] = Game(request.form['custom_prompt'])
                games[game].sentences = [(request.form['custom_answer'], True)]
                insert_into_database('INSERT INTO prompts(prompt, gpt_answer, is_custom) VALUES (%s, %s, %s)', (request.form['custom_prompt'], request.form['custom_answer'], True))
            else:
                if prompts:
                    random_prompt = random.randint(0, len(prompts)-1)
                    games[game] = Game(prompts[random_prompt][0])
                    games[game].sentences = [(prompts[random_prompt][1], True)]
                else:
                    games[game] = Game("Hiba: Nincsenek promptok betöltve.")

            games[game].is_final = False

        elif action == 'setcode':
            if game not in games:
                message = "Hibás kód vagy a játék már törlődött."
                game = None

        elif action == 'submit':
            # Ellenőrizzük, létezik-e még a játék
            if game in games:
                # Aktivitás frissítése
                games[game].last_active = time.time()

                if games[game].is_final:
                    message = "A játék már le lett zárva!"
                else:
                    sentence = request.form['sentence']
                    if not 3 <= len(sentence.split()) <= 5:
                        message = "A válasz legalább 3, legfeljebb 5 szóból állhat!"
                    else:
                        if not is_admin:
                            insert_into_database('INSERT INTO submissions(prompt, answer) VALUES (%s, %s)', (games[game].prompt, sentence))
                        games[game].sentences.append([sentence, is_admin])
                        message = "Sikeresen beküldve!"
            else:
                message = "A játék munkamenete lejárt."
                game = None

        elif action == 'guess':
            if game in games:
                games[game].last_active = time.time()
                guess = request.form['guess']
                message = "Talált!" if guess == 'True' else 'Nem talált! Helyes válasz: ' + ', '.join([sentence[0] for sentence in games[game].sentences if sentence[1]])
                guessed = True
                insert_into_database('INSERT INTO guesses(prompt, is_correct) VALUES (%s, %s)', (games[game].prompt, guess == 'True'))
            else:
                message = "A játék már nem aktív."
                game = None

        elif action == 'finalize':
            if game in games:
                games[game].last_active = time.time()
                random.shuffle(games[game].sentences)
                games[game].is_final = True

        elif action == 'restart':
            # Ha az admin kilép, töröljük a játékot a memóriából
            if is_admin and game in games:
                del games[game]
            game = None # Nullázzuk a változót, hogy a kezdőképernyő jöjjön be

        elif action == 'refresh':
            pass

    return render_template(
        'index.html',
        is_admin = is_admin,
        game = game,
        message = message,
        prompt = games[game].prompt if game in games else None,
        sentences = games[game].sentences if game in games else [],
        is_final = games[game].is_final if game in games else False,
        guessed = guessed
    )

@app.route('/list_games')
def list_games():
    global games
    available_games = []
    current_time = time.time()

    # Fontos: list(games.keys()) másolatot használunk, mert iterálás közben törölhetünk
    for game_id in list(games.keys()):
        game_obj = games[game_id]

        # AUTOMATIKUS TÖRLÉS (HEARTBEAT ELLENŐRZÉS)
        # Ha a last_active óta eltelt idő több mint TIMEOUT_SECONDS, töröljük
        if current_time - game_obj.last_active > TIMEOUT_SECONDS:
            del games[game_id]
            continue # Ugrunk a következőre, ezt nem adjuk hozzá a listához

        if not game_obj.is_final:
            available_games.append({
                'id': game_id,
                'name': f"Játék #{game_id}"
            })

    return jsonify(available_games)


initialize_prompts()
if __name__ == '__main__':
    app.run()
