from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_session import Session
import random
from sqlalchemy import MetaData
from datetime import datetime
from flask_socketio import SocketIO
from waitress import serve
from flask import Flask, request

from dotenv import load_dotenv
import os
from redis import Redis

load_dotenv()

app = Flask(__name__)
app.jinja_env.auto_reload = True
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('SQLALCHEMY_DATABASE_URI')
app.config['SESSION_TYPE'] = os.getenv('SESSION_TYPE')
app.config['DEBUG'] = False
app.config['FLASK_ENV'] = os.getenv('FLASK_ENV')
app.config['SESSION_REDIS'] = Redis.from_url(os.getenv('REDIS_URL'))
app.config['SESSION_USE_SIGNER'] = True

db = SQLAlchemy(app)
Session(app)
socketio = SocketIO(app)

metadata = MetaData(schema='test_eaf')
class User(db.Model):
    __tablename__ = 'user_tbl'
    __table_args__ = {'schema': 'test_eaf'}
    id = db.Column(db.Integer, primary_key=True)
    userid = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    wishlist = db.Column(db.Text)
    address = db.Column(db.Text)

class Santa(db.Model):
    __tablename__ = 'santa_tbl'
    __table_args__ = {'schema': 'test_eaf'}
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    santa = db.Column(db.String(100), nullable=False)

class Message(db.Model):
    __tablename__ = 'message_tbl'
    __table_args__ = {'schema': 'test_eaf'}
    id = db.Column(db.Integer, primary_key=True)
    sender = db.Column(db.String(100), nullable=False)
    recipient = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

class Flag(db.Model):
    __tablename__ = 'flag_tbl'
    __table_args__ = {'schema': 'test_eaf'}
    id = db.Column(db.Integer, primary_key=True)
    assign_santa_run = db.Column(db.Boolean, default=False)


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/assign_santa')
def assign_santa():
    flag = Flag.query.first()
    if not flag.assign_santa_run:
        users = User.query.all()
        santa_list = [user.userid for user in users]
        random.shuffle(santa_list)

        for i, user in enumerate(users):
            santa = Santa(
                name=user.name,
                santa=santa_list[(i+1)%len(santa_list)],
            )
            db.session.add(santa)
            db.session.commit()
        session['santa_name'] = santa.santa
        flash('Secret Santa assignment completed!')
        flag.assign_santa_run = True
        db.session.commit()
    return redirect(url_for('index'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user_id = request.form['userid']
        session['userid'] = user_id
        user = User.query.filter_by(userid=user_id).first()
        session['user_name'] = user.name

        if user:
            santa = Santa.query.filter_by(name=user.name).first()
            if santa:
                santa_user = User.query.filter_by(userid=santa.santa).first()
                if santa_user:
                    session['santa_name'] = santa.santa
                    session['santa_wishlist'] = santa_user.wishlist
                    session['santa_address'] = santa_user.address
                    return redirect(url_for('scratch_card'))
                else:
                    print(f"No user found with userid: {santa.santa}")
            else:
                print("No Santa found for this user")
    return render_template('login.html')


@app.route('/scratch_card')
def scratch_card():
    santa_name = session.get('santa_name')
    santa_wishlist = session.get('santa_wishlist')
    santa_address = session.get('santa_address')
    print(f"Session data: {santa_name}, {santa_wishlist}, {santa_address}")

    if santa_name is None or santa_wishlist is None:
        flash('No Secret Santa information available.')
        return redirect(url_for('index'))
    
    # Fetch the chat history of the user
    sender = session.get('user_name')
    print("Print the sender in scratch_card route:", sender)
    messages_sent = Message.query.filter_by(sender=sender).all()
    messages_received = Message.query.filter_by(recipient=sender).all()

    # Make sure to anonymize sender/recipient names in the messages
    anonymized_sent_messages = [{'content': msg.content, 'timestamp': msg.timestamp} for msg in messages_sent]
    anonymized_received_messages = [{'content': msg.content, 'timestamp': msg.timestamp} for msg in messages_received]

    return render_template('scratch_card.html', 
                           santa_name=santa_name, 
                           santa_wishlist=santa_wishlist,
                           santa_address=santa_address, 
                           messages_sent=anonymized_sent_messages, 
                           messages_received=anonymized_received_messages)


@app.route('/send_message', methods=['POST'])
def send_message():
    if request.method == 'POST':
        sender = session.get('user_name')
        recipient = request.form['recipient']
        content = request.form['content']

        message = Message(sender=sender, recipient=recipient, content=content)
        db.session.add(message)
        db.session.commit()

        room = sender + recipient
        socketio.emit('message', {'sender': sender, 'message': content}, room=room)

        santa_room = recipient + sender
        socketio.emit('message', {'sender': sender, 'message': content}, room=santa_room)

    return redirect(url_for('scratch_card'))


@socketio.on('message')
def handle_message(data):
    sender = data['sender']
    recipient = data['recipient']
    content = data['message']

    message = Message(sender=sender, recipient=recipient, content=content)
    db.session.add(message)
    db.session.commit()

    room = sender + recipient
    socketio.emit('message', {'sender': sender, 'message': content}, room=room)

if __name__ == '__main__':
    app.run()
    with app.app_context():
        db.create_all()
    serve(app, host='0.0.0.0', port=5004, threads=1)

