import logging
import sqlite3
import json
from datetime import datetime
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import threading

# Настройки
TOKEN = "8580593984:AAGJClodpSPOFK7dQPSSWa_IuDwhtwr8llE"
ADMIN_CHAT_ID = 7973988177
COMMISSION = 0.1  # 10% комиссия

# Настройка Flask
app = Flask(__name__)
app.secret_key = 'your_secret_key_here'
app.config['SESSION_TYPE'] = 'filesystem'

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Таблица заданий
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            task_id INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_id INTEGER,
            description TEXT,
            task_text TEXT,
            reward REAL,
            status TEXT DEFAULT 'active',
            executor_id INTEGER,
            proof_text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (creator_id) REFERENCES users (user_id),
            FOREIGN KEY (executor_id) REFERENCES users (user_id)
        )
    ''')
    
    conn.commit()
    conn.close()

# Получение пользователя
def get_user(user_id):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

# Создание пользователя
def create_user(user_id, username):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)', (user_id, username))
    conn.commit()
    conn.close()

# Обновление баланса
def update_balance(user_id, amount):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
    conn.commit()
    conn.close()

# Создание задания
def create_task(creator_id, description, task_text, reward):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO tasks (creator_id, description, task_text, reward)
        VALUES (?, ?, ?, ?)
    ''', (creator_id, description, task_text, reward))
    task_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return task_id

# Получение активных заданий
def get_active_tasks():
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM tasks WHERE status = "active"')
    tasks = cursor.fetchall()
    conn.close()
    return tasks

# Получение задания по ID
def get_task(task_id):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM tasks WHERE task_id = ?', (task_id,))
    task = cursor.fetchone()
    conn.close()
    return task

# Получение заданий пользователя
def get_user_tasks(user_id):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM tasks WHERE creator_id = ? ORDER BY created_at DESC', (user_id,))
    tasks = cursor.fetchall()
    conn.close()
    return tasks

# Получение заданий исполнителя
def get_executor_tasks(user_id):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM tasks WHERE executor_id = ? ORDER BY created_at DESC', (user_id,))
    tasks = cursor.fetchall()
    conn.close()
    return tasks

# Обновление статуса задания
def update_task_status(task_id, status, executor_id=None, proof_text=None):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    if executor_id and proof_text:
        cursor.execute('''
            UPDATE tasks SET status = ?, executor_id = ?, proof_text = ?
            WHERE task_id = ?
        ''', (status, executor_id, proof_text, task_id))
    elif executor_id:
        cursor.execute('''
            UPDATE tasks SET status = ?, executor_id = ? WHERE task_id = ?
        ''', (status, executor_id, task_id))
    else:
        cursor.execute('UPDATE tasks SET status = ? WHERE task_id = ?', (status, task_id))
    conn.commit()
    conn.close()

# Получение всех пользователей
def get_all_users():
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM users')
    users = cursor.fetchall()
    conn.close()
    return [user[0] for user in users]

# Получение статистики
def get_stats():
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM tasks')
    total_tasks = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM tasks WHERE status = "active"')
    active_tasks = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM tasks WHERE status = "completed"')
    completed_tasks = cursor.fetchone()[0]
    
    cursor.execute('SELECT SUM(balance) FROM users')
    total_balance = cursor.fetchone()[0] or 0
    
    conn.close()
    
    return {
        'total_users': total_users,
        'total_tasks': total_tasks,
        'active_tasks': active_tasks,
        'completed_tasks': completed_tasks,
        'total_balance': total_balance
    }

# ========== TELEGRAM BOT FUNCTIONS ==========

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username
    create_user(user_id, username)
    
    keyboard = [
        [InlineKeyboardButton("👤 Профиль", callback_data="profile")],
        [InlineKeyboardButton("📋 Создать задание", callback_data="create_task")],
        [InlineKeyboardButton("🎯 Активные задания", callback_data="active_tasks")],
        [InlineKeyboardButton("📊 Мои задания", callback_data="my_tasks")],
        [InlineKeyboardButton("🌐 OPEN Web Version", url="http://localhost:5000")]
    ]
    
    if user_id == ADMIN_CHAT_ID:
        keyboard.append([InlineKeyboardButton("⚙️ Админ панель", callback_data="admin_panel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "👋 Добро пожаловать в бот для выполнения заданий!\n\n"
        "🌐 *Доступна Web-версия* - нажмите кнопку OPEN для удобной работы в браузере!\n\n"
        "Выберите действие:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    if data == "profile":
        await show_profile(query, context)
    elif data == "create_task":
        await create_task_start(query, context)
    elif data == "active_tasks":
        await show_active_tasks(query, context)
    elif data == "my_tasks":
        await show_my_tasks(query, context)
    elif data == "deposit":
        await deposit(query, context)
    elif data == "withdraw":
        await withdraw(query, context)
    elif data == "admin_panel":
        await admin_panel(query, context)
    elif data == "main_menu":
        await show_main_menu(query, context)
    elif data.startswith("task_"):
        task_id = int(data.split("_")[1])
        await take_task(query, context, task_id)
    elif data.startswith("approve_"):
        task_id = int(data.split("_")[1])
        await approve_task(query, context, task_id)
    elif data.startswith("reject_"):
        task_id = int(data.split("_")[1])
        await reject_task(query, context, task_id)

async def show_profile(query, context):
    user = get_user(query.from_user.id)
    balance = user[2] if user else 0
    
    keyboard = [
        [InlineKeyboardButton("💳 Пополнить баланс", callback_data="deposit")],
        [InlineKeyboardButton("💰 Вывести средства", callback_data="withdraw")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"👤 Ваш профиль\n\n"
        f"🆔 ID: {query.from_user.id}\n"
        f"👤 Имя: @{query.from_user.username or 'Не указано'}\n"
        f"💰 Баланс: {balance:.2f}₽\n\n"
        f"Пополнение от 10₽, вывод от 50₽",
        reply_markup=reply_markup
    )

async def deposit(query, context):
    await query.edit_message_text(
        "💳 По поводу пополнения/вывода, напишите сюда: @nezeexsupp, сразу укажите сумму!\n\n"
        "Минимальное пополнение: 10₽\n"
        "Минимальный вывод: 50₽"
    )

async def withdraw(query, context):
    await query.edit_message_text(
        "💰 По поводу пополнения/вывода, напишите сюда: @nezeexsupp, сразу укажите сумму!\n\n"
        "Минимальное пополнение: 10₽\n"
        "Минимальный вывод: 50₽"
    )

async def show_main_menu(query, context):
    user_id = query.from_user.id
    
    keyboard = [
        [InlineKeyboardButton("👤 Профиль", callback_data="profile")],
        [InlineKeyboardButton("📋 Создать задание", callback_data="create_task")],
        [InlineKeyboardButton("🎯 Активные задания", callback_data="active_tasks")],
        [InlineKeyboardButton("📊 Мои задания", callback_data="my_tasks")],
        [InlineKeyboardButton("🌐 OPEN Web Version", url="http://localhost:5000")]
    ]
    
    if user_id == ADMIN_CHAT_ID:
        keyboard.append([InlineKeyboardButton("⚙️ Админ панель", callback_data="admin_panel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "👋 Добро пожаловать в бот для выполнения заданий!\n\n"
        "🌐 *Доступна Web-версия* - нажмите кнопку OPEN для удобной работы в браузере!\n\n"
        "Выберите действие:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

# Остальные функции бота остаются такими же как в предыдущем коде...
# Для краткости я опущу их, но в реальном коде они должны быть

# ========== FLASK WEB VERSION ==========

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    user_id = data.get('user_id')
    
    user = get_user(user_id)
    if user:
        session['user_id'] = user_id
        session['username'] = user[1]
        session['balance'] = user[2]
        return jsonify({'success': True, 'user': {
            'user_id': user[0],
            'username': user[1],
            'balance': user[2]
        }})
    else:
        return jsonify({'success': False, 'error': 'User not found'})

@app.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    
    user_id = session['user_id']
    user = get_user(user_id)
    
    return jsonify({
        'user_id': user[0],
        'username': user[1],
        'balance': user[2]
    })

@app.route('/tasks/active')
def active_tasks():
    tasks = get_active_tasks()
    task_list = []
    
    for task in tasks:
        creator = get_user(task[1])
        task_list.append({
            'task_id': task[0],
            'creator_id': task[1],
            'creator_username': creator[1] if creator else 'Unknown',
            'description': task[2],
            'task_text': task[3],
            'reward': task[4],
            'status': task[5],
            'created_at': task[8]
        })
    
    return jsonify({'tasks': task_list})

@app.route('/tasks/my')
def my_tasks():
    if 'user_id' not in session:
        return jsonify({'error': 'Not authorized'})
    
    user_id = session['user_id']
    tasks = get_user_tasks(user_id)
    task_list = []
    
    for task in tasks:
        task_list.append({
            'task_id': task[0],
            'description': task[2],
            'task_text': task[3],
            'reward': task[4],
            'status': task[5],
            'executor_id': task[6],
            'created_at': task[8]
        })
    
    return jsonify({'tasks': task_list})

@app.route('/tasks/executing')
def executing_tasks():
    if 'user_id' not in session:
        return jsonify({'error': 'Not authorized'})
    
    user_id = session['user_id']
    tasks = get_executor_tasks(user_id)
    task_list = []
    
    for task in tasks:
        creator = get_user(task[1])
        task_list.append({
            'task_id': task[0],
            'creator_username': creator[1] if creator else 'Unknown',
            'description': task[2],
            'task_text': task[3],
            'reward': task[4],
            'status': task[5],
            'proof_text': task[7],
            'created_at': task[8]
        })
    
    return jsonify({'tasks': task_list})

@app.route('/tasks/create', methods=['POST'])
def create_task_web():
    if 'user_id' not in session:
        return jsonify({'error': 'Not authorized'})
    
    data = request.json
    user_id = session['user_id']
    description = data.get('description')
    task_text = data.get('task_text')
    reward = float(data.get('reward'))
    
    user = get_user(user_id)
    if user[2] < reward:
        return jsonify({'error': 'Insufficient balance'})
    
    if reward < 0.1:
        return jsonify({'error': 'Minimum reward is 0.1₽'})
    
    task_id = create_task(user_id, description, task_text, reward)
    update_balance(user_id, -reward)
    
    return jsonify({'success': True, 'task_id': task_id})

@app.route('/tasks/take', methods=['POST'])
def take_task_web():
    if 'user_id' not in session:
        return jsonify({'error': 'Not authorized'})
    
    data = request.json
    task_id = data.get('task_id')
    user_id = session['user_id']
    
    task = get_task(task_id)
    if not task or task[5] != 'active':
        return jsonify({'error': 'Task not available'})
    
    update_task_status(task_id, 'pending', user_id)
    
    return jsonify({'success': True})

@app.route('/tasks/complete', methods=['POST'])
def complete_task_web():
    if 'user_id' not in session:
        return jsonify({'error': 'Not authorized'})
    
    data = request.json
    task_id = data.get('task_id')
    proof_text = data.get('proof_text')
    user_id = session['user_id']
    
    task = get_task(task_id)
    if not task or task[6] != user_id:
        return jsonify({'error': 'Task not found or not assigned to you'})
    
    update_task_status(task_id, 'pending', user_id, proof_text)
    
    return jsonify({'success': True})

@app.route('/tasks/approve', methods=['POST'])
def approve_task_web():
    if 'user_id' not in session:
        return jsonify({'error': 'Not authorized'})
    
    data = request.json
    task_id = data.get('task_id')
    user_id = session['user_id']
    
    task = get_task(task_id)
    if not task or task[1] != user_id:
        return jsonify({'error': 'Task not found or not your task'})
    
    reward = task[4] * (1 - COMMISSION)
    update_balance(task[6], reward)
    update_task_status(task_id, 'completed')
    
    return jsonify({'success': True})

@app.route('/tasks/reject', methods=['POST'])
def reject_task_web():
    if 'user_id' not in session:
        return jsonify({'error': 'Not authorized'})
    
    data = request.json
    task_id = data.get('task_id')
    user_id = session['user_id']
    
    task = get_task(task_id)
    if not task or task[1] != user_id:
        return jsonify({'error': 'Task not found or not your task'})
    
    update_balance(task[1], task[4])
    update_task_status(task_id, 'rejected')
    
    return jsonify({'success': True})

# ========== MAIN ==========

def run_bot():
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    application.run_polling()

def run_web():
    app.run(host='0.0.0.0', port=5000, debug=False)

if __name__ == '__main__':
    init_db()
    
    # Запуск бота в отдельном потоке
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    
    # Запуск веб-сервера
    run_web()
