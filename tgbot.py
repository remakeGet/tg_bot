import random
import psycopg2
from typing import List, Dict, Tuple, Optional

from telebot import types, TeleBot, custom_filters
from telebot.storage import StateMemoryStorage
from telebot.handler_backends import State, StatesGroup


# Конфигурация PostgreSQL
POSTGRES_CONFIG = {
    'host': 'localhost',
    'database': 'postgres',
    'user': '',
    'password': '', 
    'port': '5432'
}


class Database:
    def __init__(self):
        self.conn = None
        self.connect()

    def connect(self):
        """Устанавливаем соединение с PostgreSQL"""
        try:
            self.conn = psycopg2.connect(**POSTGRES_CONFIG)
            self.conn.autocommit = True
            self.init_db()
        except Exception as e:
            print(f"Ошибка подключения к PostgreSQL: {e}")
            raise

    def init_db(self):
        """Инициализация таблиц в PostgreSQL"""
        with self.conn.cursor() as cursor:
            # Таблица пользователей
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                user_id BIGINT UNIQUE NOT NULL,
                username TEXT
            )
            ''')

            # Таблица общих слов
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS common_words (
                id SERIAL PRIMARY KEY,
                word TEXT NOT NULL,
                translation TEXT NOT NULL
            )
            ''')

            # Таблица пользовательских слов
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_words (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                word TEXT NOT NULL,
                translation TEXT NOT NULL
            )
            ''')

            # Проверяем, есть ли общие слова
            cursor.execute('SELECT COUNT(*) FROM common_words')
            if cursor.fetchone()[0] == 0:
                initial_words = [
                    ('red', 'красный'),
                    ('blue', 'синий'),
                    ('green', 'зеленый'),
                    ('yellow', 'желтый'),
                    ('black', 'черный'),
                    ('white', 'белый'),
                    ('I', 'я'),
                    ('you', 'ты'),
                    ('he', 'он'),
                    ('she', 'она')
                ]
                cursor.executemany(
                    'INSERT INTO common_words (word, translation) VALUES (%s, %s)',
                    initial_words
                )

    def execute(self, query: str, params: tuple = None, fetch: bool = False):
        """Универсальный метод для выполнения запросов"""
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(query, params or ())
                if fetch:
                    return cursor.fetchall()
                return None
        except psycopg2.InterfaceError:
            self.connect()  # Переподключаемся при разрыве соединения
            return self.execute(query, params, fetch)

    def close(self):
        """Закрываем соединение"""
        if self.conn:
            self.conn.close()


# Инициализируем базу данных
db = Database()

print('Start telegram bot...')

state_storage = StateMemoryStorage()
token_bot = 'YOUR_BOT_TOKEN'  # Замените на ваш токен
bot = TeleBot(token_bot, state_storage=state_storage)




known_users = []
userStep = {}
buttons = []


class Command:
    ADD_WORD = 'Добавить слово ➕'
    DELETE_WORD = 'Удалить слово🔙'
    NEXT = 'Дальше ⏭'
    CANCEL = 'Отмена'


class MyStates(StatesGroup):
    target_word = State()
    translate_word = State()
    another_words = State()
    add_word = State()
    add_translation = State()
    delete_word = State()


def get_user_step(uid):
    if uid in userStep:
        return userStep[uid]
    else:
        known_users.append(uid)
        userStep[uid] = 0
        print("New user detected, who hasn't used \"/start\" yet")
        return 0


def get_words_from_db(user_id: int) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
    """Получаем слова из БД: общие и пользовательские"""
    # Получаем общие слова
    common_words = db.execute(
        'SELECT word, translation FROM common_words',
        fetch=True
    )

    # Получаем пользовательские слова
    user_words = db.execute(
        '''
        SELECT word, translation FROM user_words 
        WHERE user_id = (SELECT id FROM users WHERE user_id = %s)
        ''',
        (user_id,),
        fetch=True
    )

    return common_words, user_words


def add_user_to_db(user_id: int, username: str = None):
    """Добавляем пользователя в БД, если его там нет"""
    db.execute(
        'INSERT INTO users (user_id, username) VALUES (%s, %s) ON CONFLICT (user_id) DO NOTHING',
        (user_id, username)
    )


def add_word_to_db(user_id: int, word: str, translation: str, is_common: bool = False):
    """Добавляем слово в БД"""
    if is_common:
        db.execute(
            'INSERT INTO common_words (word, translation) VALUES (%s, %s)',
            (word, translation)
        )
    else:
        db.execute(
            '''
            INSERT INTO user_words (user_id, word, translation) 
            VALUES ((SELECT id FROM users WHERE user_id = %s), %s, %s)
            ''',
            (user_id, word, translation)
        )


def delete_word_from_db(user_id: int, word: str):
    """Удаляем слово из пользовательского словаря"""
    db.execute(
        '''
        DELETE FROM user_words 
        WHERE user_id = (SELECT id FROM users WHERE user_id = %s) AND word = %s
        ''',
        (user_id, word)
    )


def get_random_word(user_id: int) -> Optional[Dict[str, str]]:
    """Получаем случайное слово и варианты ответов"""
    common_words, user_words = get_words_from_db(user_id)
    all_words = common_words + user_words
    
    if not all_words:
        return None
    
    target_word, translation = random.choice(all_words)
    
    # Собираем другие варианты ответов
    other_words = [w[0] for w in all_words if w[0] != target_word]
    other_words = random.sample(other_words, min(3, len(other_words)))  # Берем 3 случайных слова
    
    return {
        'target_word': target_word,
        'translate_word': translation,
        'other_words': other_words
    }


@bot.message_handler(commands=['cards', 'start'])
def create_cards(message):
    cid = message.chat.id
    user_id = message.from_user.id
    username = message.from_user.username
    
    # Добавляем пользователя в БД
    add_user_to_db(user_id, username)
    
    if cid not in known_users:
        known_users.append(cid)
        userStep[cid] = 0
        bot.send_message(cid, "Привет! Давай учить английские слова!")
    
    word_data = get_random_word(user_id)
    
    if not word_data:
        bot.send_message(cid, "У вас пока нет слов для изучения. Добавьте слова с помощью команды /add_word")
        return
    
    markup = types.ReplyKeyboardMarkup(row_width=2)

    global buttons
    buttons = []
    
    target_word = word_data['target_word']
    translate = word_data['translate_word']
    others = word_data['other_words']
    
    target_word_btn = types.KeyboardButton(target_word)
    buttons.append(target_word_btn)
    other_words_btns = [types.KeyboardButton(word) for word in others]
    buttons.extend(other_words_btns)
    random.shuffle(buttons)
    
    next_btn = types.KeyboardButton(Command.NEXT)
    add_word_btn = types.KeyboardButton(Command.ADD_WORD)
    delete_word_btn = types.KeyboardButton(Command.DELETE_WORD)
    buttons.extend([next_btn, add_word_btn, delete_word_btn])

    markup.add(*buttons)

    greeting = f"Выбери перевод слова:\n🇷🇺 {translate}"
    bot.send_message(message.chat.id, greeting, reply_markup=markup)
    bot.set_state(message.from_user.id, MyStates.target_word, message.chat.id)
    
    with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        data['target_word'] = target_word
        data['translate_word'] = translate
        data['other_words'] = others


@bot.message_handler(func=lambda message: message.text == Command.NEXT)
def next_cards(message):
    create_cards(message)


@bot.message_handler(func=lambda message: message.text == Command.DELETE_WORD)
def delete_word(message):
    cid = message.chat.id
    user_id = message.from_user.id
    
    # Получаем список пользовательских слов
    user_words = db.execute(
        '''
        SELECT word FROM user_words 
        WHERE user_id = (SELECT id FROM users WHERE user_id = %s)
        ''',
        (user_id,),
        fetch=True
    )
    
    if not user_words:
        bot.send_message(cid, "У вас нет своих слов для удаления.")
        return
    
    markup = types.ReplyKeyboardMarkup(row_width=1)
    for word in user_words:
        markup.add(types.KeyboardButton(word[0]))
    markup.add(types.KeyboardButton(Command.CANCEL))
    
    bot.send_message(cid, "Выберите слово для удаления:", reply_markup=markup)
    bot.set_state(message.from_user.id, MyStates.delete_word, message.chat.id)


@bot.message_handler(state=MyStates.delete_word)
def process_delete_word(message):
    cid = message.chat.id
    user_id = message.from_user.id
    
    if message.text == Command.CANCEL:
        bot.delete_state(message.from_user.id, message.chat.id)
        create_cards(message)
        return
    
    delete_word_from_db(user_id, message.text)
    bot.send_message(cid, f"Слово '{message.text}' удалено из вашего словаря.")
    bot.delete_state(message.from_user.id, message.chat.id)
    create_cards(message)


@bot.message_handler(func=lambda message: message.text == Command.ADD_WORD)
def add_word(message):
    cid = message.chat.id
    msg = bot.send_message(cid, "Введите слово на английском:", reply_markup=types.ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, process_add_word_step)
    bot.set_state(message.from_user.id, MyStates.add_word, message.chat.id)


def process_add_word_step(message):
    cid = message.chat.id
    user_id = message.from_user.id
    
    with bot.retrieve_data(user_id, cid) as data:
        data['new_word'] = message.text.lower()
    
    msg = bot.send_message(cid, "Теперь введите перевод:")
    bot.register_next_step_handler(msg, process_add_translation_step)


def process_add_translation_step(message):
    cid = message.chat.id
    user_id = message.from_user.id
    
    with bot.retrieve_data(user_id, cid) as data:
        new_word = data['new_word']
        translation = message.text.lower()
    
    add_word_to_db(user_id, new_word, translation)
    bot.send_message(cid, f"Слово '{new_word}' с переводом '{translation}' добавлено в ваш словарь.")
    bot.delete_state(user_id, cid)
    create_cards(message)


@bot.message_handler(func=lambda message: True, content_types=['text'])
def message_reply(message):
    text = message.text
    markup = types.ReplyKeyboardMarkup(row_width=2)
    cid = message.chat.id
    
    with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        if 'target_word' not in data:  # Если состояние не инициализировано
            create_cards(message)
            return
            
        target_word = data['target_word']
        if text == target_word:
            hint = f"Отлично! ❤\n{target_word} -> {data['translate_word']}"
            next_btn = types.KeyboardButton(Command.NEXT)
            add_word_btn = types.KeyboardButton(Command.ADD_WORD)
            delete_word_btn = types.KeyboardButton(Command.DELETE_WORD)
            buttons = [next_btn, add_word_btn, delete_word_btn]
            random.shuffle(buttons)
        else:
            hint = f"Допущена ошибка!\nПопробуй ещё раз вспомнить слово 🇷🇺{data['translate_word']}"
            buttons = []
            for word in data['other_words'] + [target_word]:
                if word == text:
                    buttons.append(types.KeyboardButton(word + '❌'))
                else:
                    buttons.append(types.KeyboardButton(word))
            
            next_btn = types.KeyboardButton(Command.NEXT)
            add_word_btn = types.KeyboardButton(Command.ADD_WORD)
            delete_word_btn = types.KeyboardButton(Command.DELETE_WORD)
            buttons.extend([next_btn, add_word_btn, delete_word_btn])
    
    markup.add(*buttons)
    bot.send_message(cid, hint, reply_markup=markup)


bot.add_custom_filter(custom_filters.StateFilter(bot))
bot.infinity_polling(skip_pending=True)
