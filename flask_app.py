from flask import Flask, render_template, request
import mysql.connector # pip install mysql-connector-python
import random
import configparser
import sys

app = Flask(__name__)
games = {}
config = None
prompts = []

class Game:
    def __init__(self, prompt) -> None:
        self.prompt = prompt
        self.sentences = []
        self.is_final = False

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
    database_connection = get_database_connection()
    cursor = database_connection.cursor()
    cursor.execute('SELECT prompt, gpt_answer FROM prompts WHERE is_custom=FALSE')
    prompts = cursor.fetchall()
    database_connection.close()

def insert_into_database(insert_command, values):
    database_connection = get_database_connection()
    try:
        cursor = database_connection.cursor()
        cursor.execute(insert_command, values)
    except Exception as e:
        print(e, file=sys.stderr)
        database_connection.rollback()
    else:
        database_connection.commit()
    database_connection.close()

@app.route('/', methods=['GET', 'POST'])
def home():
    global games

    message = None
    is_admin = False
    action = 'refresh'
    game = None
    guessed = False
    if request.method == 'POST':
        if 'is_admin' in request.form:
            is_admin = request.form['is_admin'] == 'True'
        if 'action' in request.form:
            action = request.form['action']
        if 'game' in request.form:
            game = request.form['game']

        if action == 'generate':
            game = str(random.randint(100, 1000))
            if 'is_custom_prompt' in request.form:
                games[game] = Game(request.form['custom_prompt'])
                games[game].sentences = [(request.form['custom_answer'], True)]
                insert_into_database('INSERT INTO prompts(prompt, gpt_answer, is_custom) VALUES (%s, %s, %s)', (request.form['custom_prompt'], request.form['custom_answer'], True))
            else:
                random_prompt = random.randint(0, len(prompts)-1)
                games[game] = Game(prompts[random_prompt][0])
                games[game].sentences = [(prompts[random_prompt][1], True)]
            games[game].is_final = False
        elif action == 'setcode':
            if game not in games:
                message = "Hibás kód: " + str(game)
                game = None
        elif action == 'submit':
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
        elif action == 'guess':
            guess = request.form['guess']
            message = "Talált!" if guess == 'True' else 'Nem talált! Helyes válasz: ' + ', '.join([sentence[0] for sentence in games[game].sentences if sentence[1]])
            guessed = True
            insert_into_database('INSERT INTO guesses(prompt, is_correct) VALUES (%s, %s)', (games[game].prompt, guess == 'True'))
        elif action == 'finalize':
            random.shuffle(games[game].sentences)
            games[game].is_final = True
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

initialize_prompts() # in PythonAnywhere this does not work if moved into name main check, and could no figure out why
if __name__ == '__main__':
    app.run()
