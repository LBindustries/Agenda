from flask import Flask, session, url_for, redirect, request, render_template, abort
from flask_sqlalchemy import SQLAlchemy
import bcrypt
from datetime import datetime, date, timedelta
import os
import requests
import telepot
from telepot.loop import MessageLoop
import threading

app = Flask(__name__)
app.secret_key = "nondovreiessereinchiaro"
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.sqlite'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
telegramkey = "METTILATUACHIAVE"  # Oh boy


class User(db.Model):
    __tablename__ = "user"
    username = db.Column(db.String, unique=True, nullable=False, primary_key=True)
    password = db.Column(db.LargeBinary, nullable=False)
    telegramUsername = db.Column(db.String, nullable=False, unique=True)
    chatId = db.Column(db.String, unique=True)
    task = db.relationship("Task", back_populates="user")

    def __init__(self, username, plain_password, telegramUsername):
        self.username = username
        self.password = bcrypt.hashpw(bytes(plain_password, encoding="utf-8"), bcrypt.gensalt())
        self.telegramUsername = telegramUsername

    def __repr__(self):
        return "User Record: {}".format(self.username)


class Task(db.Model):
    __tablename__ = "task"
    tid = db.Column(db.Integer, primary_key=True)
    impegno = db.Column(db.DateTime, nullable=False)
    desc = db.Column(db.String, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.username'))
    user = db.relationship("User", back_populates="task")

    def __init__(self, impegno, desc):
        self.impegno = impegno
        self.desc = desc

    def __repr__(self):
        return "Event Record: {}-{}".format(self.impegno, self.desc)


def login(username, password):
    user = User.query.filter_by(username=username).first()
    try:
        return bcrypt.checkpw(bytes(password, encoding="utf-8"), user.password)
    except AttributeError:
        # Se non esiste l'Utente
        return False


def find_user(username):
    return User.query.filter_by(username=username).first()


@app.route("/")
def page_home():
    if 'username' not in session:
        return redirect(url_for('page_login'))
    else:
        session.pop('username')
        return redirect(url_for('page_login'))


@app.route("/login", methods=['GET', 'POST'])
def page_login():
    if request.method == "GET":
        return render_template("login.htm")
    else:
        if login(request.form['username'], request.form['password']):
            session['username'] = request.form['username']
            return redirect(url_for('page_dashboard'))
        else:
            abort(403)


@app.route("/register", methods=['GET', 'POST'])
def page_register():
    if request.method == "GET":
        return render_template("user/register.htm")
    else:
        newuser = User(request.form['username'], request.form['password'], request.form['usernameTelegram'])
        db.session.add(newuser)
        db.session.commit()
        return redirect(url_for('page_login'))


@app.route("/dashboard")
def page_dashboard():
    if 'username' not in session or 'username' is None:
        return redirect(url_for('page_login'))
    else:
        utente = find_user(session['username'])
        return render_template("dashboard.htm", utente=utente)


@app.route("/api/newtask", methods=['POST'])
def api_newtask():
    if 'username' not in session or 'username' is None:
        abort(403)
    else:
        nonseparato = request.form['impegno']
        splittato = nonseparato.split(" ", 1)
        giorno, mese, anno = splittato[0].split("/", 3)
        ora, minuto = splittato[1].split(":", 1)
        data = datetime(int(anno), int(mese), int(giorno), int(ora), int(minuto))
        note = request.form['nota']
        utente = find_user(session['username'])
        nuovoimpegno = Task(data, note)
        nuovoimpegno.user_id = utente.username
        db.session.add(nuovoimpegno)
        db.session.commit()
        return "Success"


@app.route("/api/gatherer")
def api_gatherer():
    if 'username' not in session or 'username' is None:
        abort(403)
    else:
        utente = find_user(session['username'])
        tasks = Task.query.filter_by(user_id=utente.username).order_by(Task.impegno.asc()).all()
        message = ""
        for task in tasks:
            message += "<div class=\"alert alert-primary\" role=\"alert\">" \
                       "<div class=\"row\"><div class=\"col-md-8\">{}</div><div class=\"col-md-4\">" \
                       "{}-{}-{} {}:{}<br><a href=\"/api/delete/{}\">Elimina</a> <a href=\"/api/mod/{}\">Mod" \
                       "</a></div></div></div>".format(
                task.desc, task.impegno.year, task.impegno.month, task.impegno.day, task.impegno.hour,
                task.impegno.minute, task.tid, task.tid)

        return message


@app.route("/api/delete/<int:tid>")
def api_delete(tid):
    if 'username' not in session or 'username' is None:
        abort(403)
    else:
        task = Task.query.get_or_404(tid)
        utente = find_user(session['username'])
        if task.user_id == utente.username:
            db.session.delete(task)
            db.session.commit()
            return redirect(url_for('page_dashboard'))
        else:
            abort(403)


@app.route("/api/mod/<int:tid>", methods=["GET", "POST"])
def api_mod(tid):
    if 'username' not in session or 'username' is None:
        abort(403)
    else:
        task = Task.query.get_or_404(tid)
        utente = find_user(session['username'])
        if task.user_id == utente.username:
            if request.method == "GET":
                return render_template("mod.htm", utente=utente, task=task)
            else:
                nonseparato = request.form['impegno']
                splittato = nonseparato.split(" ", 1)
                giorno, mese, anno = splittato[0].split("/", 3)
                ora, minuto = splittato[1].split(":", 1)
                data = datetime(int(anno), int(mese), int(giorno), int(ora), int(minuto))
                note = request.form['note']
                task.impegno = data
                task.note = note
                db.session.commit()
                return redirect(url_for('page_dashboard'))
        else:
            abort(403)


def thread():
    global bot
    bot = telepot.Bot(telegramkey)
    bot.getMe()
    MessageLoop(bot, handle).run_as_thread()


# Bot


def handle(msg):
    with app.app_context():
        content_type, chat_type, chat_id = telepot.glance(msg)
        username = "@"
        username += msg['from']['username']
        if content_type == 'text':
            utenza = User.query.filter_by(chatId=chat_id).first()
            if not utenza:
                accedi(chat_id, username)
            else:
                testo = msg['text']
                if testo == "/aiuto":
                    bot.sendMessage(chat_id,
                                    "I comandi disponibili sono:\n/aiuto - Lista comandi\n/impegni - Lista degli impegni in agenda")
                if testo == "/impegni":
                    impegni = Task.query.filter_by(user_id=utenza.username).order_by(Task.impegno.asc()).all()
                    msg = ""
                    for task in impegni:
                        msg += "= {}-{}-{} {}:{} =\n{}\n\n".format(task.impegno.year, task.impegno.month,
                                                                   task.impegno.day, task.impegno.hour,
                                                                   task.impegno.minute, task.desc)
                    bot.sendMessage(chat_id, msg)


def accedi(chat_id, username):
    with app.app_context():
        utente = User.query.filter_by(telegramUsername=username).first()
        print(username)
        if not utente:
            bot.sendMessage(chat_id,
                            "Si è verificato un problema con l'autenticazione. Assicurati di aver impostato correttamete il tuo username su Agenda")
        else:
            bot.sendMessage(chat_id,
                            "Collegamento riuscito.\nPer visualizzare i comandi, digita /aiuto.")
            utente.chatId = chat_id
            db.session.commit()


def controllore():
    while True:
        oggi = datetime.now()
        oggetto = datetime(year=oggi.year, month=oggi.month, day=oggi.day, hour=oggi.hour, minute=oggi.minute)
        tasks = Task.query.filter_by(impegno=oggetto).all()
        for task in tasks:
            utente = User.query.get_or_404(task.user_id)
            if utente.chatId:
                testo = "Evento programmato: {}".format(task.desc)
                param = {"chat_id": utente.chatId, "text": testo}
                requests.get("https://api.telegram.org/bot" + telegramkey + "/sendMessage", params=param)
            db.session.delete(task)
            db.session.commit()


if __name__ == "__main__":
    # Se non esiste il database viene creato
    if not os.path.isfile("db.sqlite"):
        db.create_all()
    processo = threading.Thread(target=thread)
    processo.start()
    altroprocesso = threading.Thread(target=controllore)
    altroprocesso.start()
    print("Bot Telegram avviato. API in ascolto.")
    app.run(host="0.0.0.0", debug=False)
