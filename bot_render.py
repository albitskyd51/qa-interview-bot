import logging
import os
import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import random
from keep_alive import keep_alive
from contextlib import contextmanager

# Запускаем keep-alive сервер для Render
keep_alive()

# Настройка расширенного логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ==================== DATABASE ====================

DB_NAME = 'qa_bot.db'

@contextmanager
def get_db():
    """Context manager для работы с БД"""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    except Exception as e:
        conn.rollback()
        logger.error(f"Database error: {e}")
        raise
    else:
        conn.commit()
    finally:
        conn.close()

def init_database():
    """Инициализация базы данных"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()

            # Таблица пользователей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Таблица результатов тестов
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS test_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    level TEXT,
                    mode TEXT,
                    correct_answers INTEGER,
                    total_questions INTEGER,
                    percentage REAL,
                    completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')

            # Таблица текущих сессий
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    user_id INTEGER PRIMARY KEY,
                    level TEXT,
                    mode TEXT,
                    questions_json TEXT,
                    current_question INTEGER,
                    correct_answers INTEGER,
                    total_questions INTEGER,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

        logger.info("✅ Database initialized successfully")
    except Exception as e:
        logger.error(f"❌ Failed to initialize database: {e}")
        raise

def save_user(user_id: int, username: str, first_name: str):
    """Сохранение пользователя"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO users (user_id, username, first_name)
                VALUES (?, ?, ?)
            ''', (user_id, username, first_name))
    except Exception as e:
        logger.error(f"Error saving user {user_id}: {e}")

def save_test_result(user_id: int, level: str, mode: str, correct: int, total: int):
    """Сохранение результата теста"""
    try:
        percentage = (correct / total) * 100 if total > 0 else 0
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO test_results (user_id, level, mode, correct_answers, total_questions, percentage)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, level, mode, correct, total, percentage))
        logger.info(f"Saved test result for user {user_id}: {correct}/{total} ({percentage:.1f}%)")
    except Exception as e:
        logger.error(f"Error saving test result for user {user_id}: {e}")

def get_user_stats(user_id: int):
    """Получение статистики пользователя"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()

            # Общая статистика
            cursor.execute('''
                SELECT
                    COUNT(*) as total_tests,
                    AVG(percentage) as avg_percentage,
                    MAX(percentage) as best_percentage,
                    SUM(correct_answers) as total_correct,
                    SUM(total_questions) as total_questions
                FROM test_results
                WHERE user_id = ?
            ''', (user_id,))
            overall = cursor.fetchone()

            # Статистика по уровням
            cursor.execute('''
                SELECT
                    level,
                    COUNT(*) as attempts,
                    AVG(percentage) as avg_percentage,
                    MAX(percentage) as best_percentage
                FROM test_results
                WHERE user_id = ?
                GROUP BY level
            ''', (user_id,))
            by_level = cursor.fetchall()

            # Последние 5 тестов
            cursor.execute('''
                SELECT level, mode, percentage, completed_at
                FROM test_results
                WHERE user_id = ?
                ORDER BY completed_at DESC
                LIMIT 5
            ''', (user_id,))
            recent = cursor.fetchall()

            return {
                'overall': dict(overall) if overall else None,
                'by_level': [dict(row) for row in by_level],
                'recent': [dict(row) for row in recent]
            }
    except Exception as e:
        logger.error(f"Error getting stats for user {user_id}: {e}")
        return None

def save_session(user_id: int, data: dict):
    """Сохранение текущей сессии"""
    try:
        import json
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO sessions
                (user_id, level, mode, questions_json, current_question, correct_answers, total_questions)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_id,
                data['level'],
                data.get('mode', 'full'),
                json.dumps(data['questions']),
                data['current_question'],
                data['correct_answers'],
                data['total_questions']
            ))
    except Exception as e:
        logger.error(f"Error saving session for user {user_id}: {e}")

def load_session(user_id: int):
    """Загрузка сессии"""
    try:
        import json
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM sessions WHERE user_id = ?', (user_id,))
            row = cursor.fetchone()
            if row:
                return {
                    'level': row['level'],
                    'mode': row['mode'],
                    'questions': json.loads(row['questions_json']),
                    'current_question': row['current_question'],
                    'correct_answers': row['correct_answers'],
                    'total_questions': row['total_questions']
                }
    except Exception as e:
        logger.error(f"Error loading session for user {user_id}: {e}")
    return None

def delete_session(user_id: int):
    """Удаление сессии"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM sessions WHERE user_id = ?', (user_id,))
    except Exception as e:
        logger.error(f"Error deleting session for user {user_id}: {e}")

# ==================== HELPER FUNCTIONS ====================

def get_progress_bar(current: int, total: int, length: int = 10) -> str:
    """Создание прогресс-бара"""
    filled = int(length * current / total)
    bar = '█' * filled + '░' * (length - filled)
    return f"[{bar}] {current}/{total}"

def format_test_mode(mode: str) -> str:
    """Форматирование названия режима"""
    modes = {
        'full': 'Полный тест (20 вопросов)',
        'quick': 'Быстрый тест (10 вопросов)'
    }
    return modes.get(mode, mode)

def split_long_text(text, max_length=35):
    """Разбивает текст на строки указанной максимальной длины"""
    words = text.split()
    lines = []
    current_line = []
    current_length = 0

    for word in words:
        if current_length + len(word) + 1 <= max_length:
            current_line.append(word)
            current_length += len(word) + 1
        else:
            if current_line:
                lines.append(' '.join(current_line))
            current_line = [word]
            current_length = len(word)

    if current_line:
        lines.append(' '.join(current_line))

    return '\n'.join(lines)

# ==================== QUESTIONS ====================

# Расширенная база вопросов (50 вопросов на уровень)
# Все тексты уже отформатированы для корректного отображения

QUESTIONS = {
    'junior': [
        {
            'question': 'Что такое тестирование ПО?',
            'options': [
                'Выявление дефектов в ПО',
                'Написание кода',
                'Установка программ',
                'Удаление багов'
            ],
            'correct': 0,
            'explanation': 'Тестирование ПО - это процесс проверки соответствия между реальным и ожидаемым поведением программы.'
        },
        {
            'question': 'Что такое баг (дефект)?',
            'options': [
                'Отклонение результата от ожидаемого',
                'Новая функция',
                'Документация',
                'Тестовый сценарий'
            ],
            'correct': 0,
            'explanation': 'Баг - это ошибка в программе, вызывающая неправильное или неожиданное поведение.'
        },
        {
            'question': 'Виды тестирования по знанию системы?',
            'options': [
                'Черный, белый, серый ящик',
                'Быстрое и медленное',
                'Простое и сложное',
                'Ручное и автоматическое'
            ],
            'correct': 0,
            'explanation': 'Черный ящик (без знания кода), белый ящик (с доступом к коду), серый ящик (частичное знание).'
        },
        {
            'question': 'Что такое регрессионное тестирование?',
            'options': [
                'Проверка старого функционала после изменений',
                'Тестирование новых функций',
                'Тестирование производительности',
                'Тестирование безопасности'
            ],
            'correct': 0,
            'explanation': 'Регрессия проверяет, что новые изменения не сломали существующую функциональность.'
        },
        {
            'question': 'Что такое тест-кейс?',
            'options': [
                'Документ с шагами и ожидаемыми результатами',
                'Список найденных багов',
                'План тестирования',
                'Отчет о тестировании'
            ],
            'correct': 0,
            'explanation': 'Тест-кейс описывает, как именно протестировать конкретную функцию или сценарий.'
        },
        {
            'question': 'Что проверяется при функциональном тестировании?',
            'options': [
                'Соответствие функций требованиям',
                'Скорость работы',
                'Безопасность системы',
                'Дизайн интерфейса'
            ],
            'correct': 0,
            'explanation': 'Функциональное тестирование проверяет, что система делает то, что должна делать.'
        },
        {
            'question': 'Что такое smoke testing?',
            'options': [
                'Быстрая проверка основного функционала',
                'Тестирование в дыму',
                'Тестирование производительности',
                'Финальное тестирование'
            ],
            'correct': 0,
            'explanation': 'Smoke testing - беглая проверка критического функционала для решения о начале полного тестирования.'
        },
        {
            'question': 'Приоритет критического бага?',
            'options': [
                'Highest/Critical - требует срочного исправления',
                'Low - можно потом',
                'Medium - в следующем релизе',
                'Trivial - не требуется'
            ],
            'correct': 0,
            'explanation': 'Критические баги блокируют работу системы и требуют срочного исправления.'
        },
        {
            'question': 'Что такое верификация (verification)?',
            'options': [
                'Проверка соответствия продукта спецификации',
                'Проверка ожиданий пользователей',
                'Исправление багов',
                'Написание тестов'
            ],
            'correct': 0,
            'explanation': 'Верификация отвечает на вопрос: "Правильно ли мы создаем продукт?"'
        },
        {
            'question': 'Что такое валидация (validation)?',
            'options': [
                'Проверка соответствия ожиданиям пользователей',
                'Проверка соответствия спецификации',
                'Установка программы',
                'Удаление программы'
            ],
            'correct': 0,
            'explanation': 'Валидация отвечает на вопрос: "Создаем ли мы правильный продукт?"'
        },
        {
            'question': 'Что такое санитарное тестирование?',
            'options': [
                'Проверка основных функций после исправления',
                'Полное тестирование',
                'Тестирование новых функций',
                'Тестирование интерфейса'
            ],
            'correct': 0,
            'explanation': 'Sanity testing - быстрая проверка что исправления работают и не сломали основной функционал.'
        },
        {
            'question': 'Что такое acceptance testing?',
            'options': [
                'Приемочное тестирование со стороны заказчика',
                'Тестирование программистом',
                'Автоматическое тестирование',
                'Тестирование производительности'
            ],
            'correct': 0,
            'explanation': 'Acceptance testing определяет, готов ли продукт к релизу и соответствует ли ожиданиям заказчика.'
        },
        {
            'question': 'Жизненный цикл дефекта: правильный порядок?',
            'options': [
                'New → Assigned → Fixed → Verified → Closed',
                'Open → Close',
                'Found → Deleted',
                'Bug → No Bug'
            ],
            'correct': 0,
            'explanation': 'Типичный life cycle бага: создание, назначение, исправление, проверка, закрытие.'
        },
        {
            'question': 'Что такое test plan?',
            'options': [
                'Документ с описанием стратегии тестирования',
                'Список тест-кейсов',
                'Список багов',
                'Расписание тестов'
            ],
            'correct': 0,
            'explanation': 'Test plan описывает что, как, когда и кто будет тестировать в проекте.'
        },
        {
            'question': 'Что такое exploratory testing?',
            'options': [
                'Исследовательское тестирование без сценариев',
                'Автоматизированное тестирование',
                'Тестирование по документации',
                'Повторное тестирование'
            ],
            'correct': 0,
            'explanation': 'Exploratory testing - свободное исследование приложения для поиска неочевидных багов.'
        },
        {
            'question': 'Что такое positive testing?',
            'options': [
                'Проверка с корректными входными данными',
                'Проверка с некорректными данными',
                'Позитивное отношение к багам',
                'Быстрое тестирование'
            ],
            'correct': 0,
            'explanation': 'Positive testing проверяет что система работает правильно при валидных данных.'
        },
        {
            'question': 'Что такое negative testing?',
            'options': [
                'Проверка с некорректными входными данными',
                'Проверка с корректными данными',
                'Негативное отношение к системе',
                'Медленное тестирование'
            ],
            'correct': 0,
            'explanation': 'Negative testing проверяет обработку ошибок и поведение при невалидных данных.'
        },
        {
            'question': 'Что такое boundary testing?',
            'options': [
                'Тестирование граничных значений',
                'Тестирование границ экрана',
                'Тестирование рамок',
                'Тестирование лимитов времени'
            ],
            'correct': 0,
            'explanation': 'Boundary testing проверяет поведение на минимальных, максимальных и граничных значениях.'
        },
        {
            'question': 'Severity vs Priority - в чем разница?',
            'options': [
                'Severity - влияние, Priority - срочность',
                'Это синонимы',
                'Severity для багов, Priority для фич',
                'Нет разницы'
            ],
            'correct': 0,
            'explanation': 'Severity - насколько критичен баг технически, Priority - насколько срочно нужно исправить.'
        },
        {
            'question': 'Что такое use case?',
            'options': [
                'Описание взаимодействия пользователя с системой',
                'Список тест-кейсов',
                'Описание бага',
                'Документация кода'
            ],
            'correct': 0,
            'explanation': 'Use case описывает сценарий использования системы реальным пользователем для достижения цели.'
        },
        {
            'question': 'Что такое SDLC?',
            'options': [
                'Software Development Life Cycle',
                'System Data Life Code',
                'Standard Development Link',
                'Secure Data Life Cycle'
            ],
            'correct': 0,
            'explanation': 'SDLC - жизненный цикл разработки ПО, включающий все этапы от идеи до выпуска.'
        },
        {
            'question': 'Что такое STLC?',
            'options': [
                'Software Testing Life Cycle',
                'System Testing Link Code',
                'Standard Test Life Check',
                'Secure Testing Life Cycle'
            ],
            'correct': 0,
            'explanation': 'STLC - жизненный цикл тестирования, охватывающий все активности тестирования.'
        },
        {
            'question': 'Что такое Ad-hoc тестирование?',
            'options': [
                'Неформальное тестирование без подготовки',
                'Тестирование рекламы',
                'Автоматическое тестирование',
                'Регрессионное тестирование'
            ],
            'correct': 0,
            'explanation': 'Ad-hoc testing - неструктурированное тестирование для быстрого поиска очевидных дефектов.'
        },
        {
            'question': 'Что такое test suite?',
            'options': [
                'Набор тест-кейсов для конкретной цели',
                'Один тест-кейс',
                'Отчет о тестировании',
                'Инструмент тестирования'
            ],
            'correct': 0,
            'explanation': 'Test suite - коллекция тест-кейсов, объединенных общей целью или функциональностью.'
        },
        {
            'question': 'Что такое test data?',
            'options': [
                'Данные используемые во время тестирования',
                'Результаты тестов',
                'Отчеты о багах',
                'Документация'
            ],
            'correct': 0,
            'explanation': 'Test data - входные данные и условия окружения для выполнения тестов.'
        },
        {
            'question': 'Что такое baseline в тестировании?',
            'options': [
                'Утвержденная версия артефакта проекта',
                'Линия на графике',
                'Начало проекта',
                'Конец тестирования'
            ],
            'correct': 0,
            'explanation': 'Baseline - зафиксированная версия документа/кода, используемая как точка отсчета.'
        },
        {
            'question': 'Что такое traceability matrix?',
            'options': [
                'Связь требований с тест-кейсами',
                'График багов',
                'Матрица приоритетов',
                'Таблица результатов'
            ],
            'correct': 0,
            'explanation': 'Traceability matrix показывает покрытие требований тест-кейсами.'
        },
        {
            'question': 'Что такое entry criteria?',
            'options': [
                'Условия для начала тестирования',
                'Вход в систему',
                'Первый тест',
                'Регистрация пользователя'
            ],
            'correct': 0,
            'explanation': 'Entry criteria - условия которые должны быть выполнены для старта тестирования.'
        },
        {
            'question': 'Что такое exit criteria?',
            'options': [
                'Условия для завершения тестирования',
                'Выход из системы',
                'Последний тест',
                'Удаление аккаунта'
            ],
            'correct': 0,
            'explanation': 'Exit criteria - условия определяющие когда тестирование можно считать завершенным.'
        },
        {
            'question': 'Что такое defect density?',
            'options': [
                'Количество дефектов на единицу кода',
                'Размер бага',
                'Скорость исправления',
                'Приоритет дефекта'
            ],
            'correct': 0,
            'explanation': 'Defect density - метрика показывающая концентрацию дефектов в коде.'
        },
        {
            'question': 'Что такое re-testing?',
            'options': [
                'Повторное тестирование исправленного бага',
                'Регрессионное тестирование',
                'Первое тестирование',
                'Автоматическое тестирование'
            ],
            'correct': 0,
            'explanation': 'Re-testing - проверка что конкретный баг действительно исправлен.'
        },
        {
            'question': 'Что такое build?',
            'options': [
                'Скомпилированная версия приложения',
                'Инструмент разработки',
                'Тестовый сервер',
                'База данных'
            ],
            'correct': 0,
            'explanation': 'Build - готовая к тестированию версия приложения определенного момента времени.'
        },
        {
            'question': 'Что такое release?',
            'options': [
                'Версия ПО переданная пользователям',
                'Удаление приложения',
                'Тестовая версия',
                'Исходный код'
            ],
            'correct': 0,
            'explanation': 'Release - официальная версия продукта, выпущенная для использования.'
        },
        {
            'question': 'Что такое hotfix?',
            'options': [
                'Срочное исправление критического бага',
                'Плановое обновление',
                'Новая функция',
                'Улучшение производительности'
            ],
            'correct': 0,
            'explanation': 'Hotfix - быстрый патч для исправления критической проблемы в production.'
        },
        {
            'question': 'Что такое environment?',
            'options': [
                'Окружение для запуска приложения',
                'Природная среда',
                'Офис разработчиков',
                'Язык программирования'
            ],
            'correct': 0,
            'explanation': 'Environment - настроенная среда (сервер, БД, конфиги) для тестирования или работы.'
        },
        {
            'question': 'Что такое staging environment?',
            'options': [
                'Предпродакшн окружение для финального теста',
                'Разработческое окружение',
                'Тестовый сервер',
                'Локальная машина'
            ],
            'correct': 0,
            'explanation': 'Staging - окружение максимально приближенное к production для финальной проверки.'
        },
        {
            'question': 'Что такое production environment?',
            'options': [
                'Боевое окружение с реальными пользователями',
                'Тестовый сервер',
                'Локальная машина',
                'Резервная копия'
            ],
            'correct': 0,
            'explanation': 'Production - реальное окружение где работают конечные пользователи.'
        },
        {
            'question': 'Что такое UAT?',
            'options': [
                'User Acceptance Testing',
                'Automated Testing',
                'Unit Testing',
                'Universal Testing'
            ],
            'correct': 0,
            'explanation': 'UAT - финальное тестирование реальными пользователями перед релизом.'
        },
        {
            'question': 'Smoke test vs Sanity test - разница?',
            'options': [
                'Smoke - базовая проверка, Sanity - исправления',
                'Это одно и то же',
                'Smoke для багов, Sanity для фич',
                'Нет разницы'
            ],
            'correct': 0,
            'explanation': 'Smoke проверяет можно ли начать тестирование, Sanity - что исправления работают.'
        },
        {
            'question': 'Что такое alpha testing?',
            'options': [
                'Внутреннее тестирование командой разработки',
                'Тестирование пользователями',
                'Автоматическое тестирование',
                'Финальное тестирование'
            ],
            'correct': 0,
            'explanation': 'Alpha testing - раннее тестирование внутри компании до выпуска пользователям.'
        },
        {
            'question': 'Что такое beta testing?',
            'options': [
                'Тестирование ограниченной группой пользователей',
                'Внутреннее тестирование',
                'Автоматическое тестирование',
                'Тестирование багов'
            ],
            'correct': 0,
            'explanation': 'Beta testing - тестирование реальными пользователями в реальных условиях.'
        },
        {
            'question': 'Что такое GUI testing?',
            'options': [
                'Тестирование графического интерфейса',
                'Тестирование API',
                'Тестирование БД',
                'Тестирование кода'
            ],
            'correct': 0,
            'explanation': 'GUI testing проверяет элементы интерфейса: кнопки, поля, меню и их взаимодействие.'
        },
        {
            'question': 'Что такое usability testing?',
            'options': [
                'Проверка удобства использования',
                'Проверка функциональности',
                'Проверка производительности',
                'Проверка безопасности'
            ],
            'correct': 0,
            'explanation': 'Usability testing оценивает насколько продукт удобен и понятен пользователям.'
        },
        {
            'question': 'Что такое compatibility testing?',
            'options': [
                'Проверка работы на разных платформах',
                'Проверка функций',
                'Проверка скорости',
                'Проверка багов'
            ],
            'correct': 0,
            'explanation': 'Compatibility testing проверяет работу на разных ОС, браузерах, устройствах.'
        },
        {
            'question': 'Что такое installation testing?',
            'options': [
                'Проверка процесса установки/удаления',
                'Проверка интерфейса',
                'Проверка функций',
                'Проверка данных'
            ],
            'correct': 0,
            'explanation': 'Installation testing проверяет корректность установки, обновления и удаления приложения.'
        },
        {
            'question': 'Что такое monkey testing?',
            'options': [
                'Случайное тестирование без системного подхода',
                'Тестирование обезьян',
                'Автоматическое тестирование',
                'Стресс1тестирование'
            ],
            'correct': 0,
            'explanation': 'Monkey testing - хаотичное нажатие кнопок для поиска крашей и неожиданного поведения.'
        },
        {
            'question': 'Что такое локализация (L10n)?',
            'options': [
                'Адаптация продукта для конкретного региона',
                'Поиск багов',
                'Установка приложения',
                'Тестирование скорости'
            ],
            'correct': 0,
            'explanation': 'Локализация - перевод и адаптация интерфейса, формата дат, валют для региона.'
        },
        {
            'question': 'Что такое интернационализация (i18n)?',
            'options': [
                'Подготовка продукта для разных языков',
                'Интернет-тестирование',
                'Международная доставка',
                'Тестирование связи'
            ],
            'correct': 0,
            'explanation': 'Интернационализация - проектирование продукта для легкой адаптации под разные языки.'
        },
        {
            'question': 'Что такое test report?',
            'options': [
                'Документ с результатами тестирования',
                'План тестирования',
                'Список багов',
                'Тест-кейс'
            ],
            'correct': 0,
            'explanation': 'Test report - отчет содержащий результаты, метрики и выводы по итогам тестирования.'
        },
        {
            'question': 'Что такое root cause?',
            'options': [
                'Первопричина появления дефекта',
                'Корень дерева',
                'Главный тестировщик',
                'Первый баг'
            ],
            'correct': 0,
            'explanation': 'Root cause - базовая причина почему возник дефект, а не просто симптом.'
        }
    ],
    'middle': [
        {
            'question': 'Что такое API тестирование?',
            'options': [
                'Тестирование программных интерфейсов',
                'Тестирование UI',
                'Тестирование БД',
                'Тестирование сети'
            ],
            'correct': 0,
            'explanation': 'API тестирование проверяет взаимодействие между различными компонентами системы.'
        },
        {
            'question': 'Основные HTTP методы?',
            'options': [
                'GET, POST, PUT, DELETE, PATCH',
                'SEND, RECEIVE, UPDATE',
                'READ, WRITE, EXECUTE',
                'OPEN, CLOSE, SAVE'
            ],
            'correct': 0,
            'explanation': 'GET (получить), POST (создать), PUT (обновить), DELETE (удалить), PATCH (частично обновить).'
        },
        {
            'question': 'Что такое SQL injection?',
            'options': [
                'Внедрение вредоносного SQL кода в запрос',
                'Оптимизация БД',
                'Резервное копирование',
                'Тип индекса в БД'
            ],
            'correct': 0,
            'explanation': 'SQL injection - критическая уязвимость, позволяющая выполнить произвольные SQL команды.'
        },
        {
            'question': 'Что проверяется при load testing?',
            'options': [
                'Поведение системы под нагрузкой',
                'Функциональность',
                'Безопасность',
                'Удобство интерфейса'
            ],
            'correct': 0,
            'explanation': 'Load testing показывает, как система работает при большом количестве пользователей.'
        },
        {
            'question': 'Что такое CI/CD?',
            'options': [
                'Continuous Integration/Continuous Delivery',
                'Code Integration',
                'Computer Integration',
                'Critical Integration'
            ],
            'correct': 0,
            'explanation': 'CI/CD - практика автоматической сборки, тестирования и развертывания кода.'
        },
        {
            'question': 'HTTP код успешного запроса?',
            'options': [
                '200 OK',
                '404 Not Found',
                '500 Internal Server Error',
                '403 Forbidden'
            ],
            'correct': 0,
            'explanation': 'Код 200 означает успех. 2xx - успех, 4xx - ошибка клиента, 5xx - ошибка сервера.'
        },
        {
            'question': 'Что такое mock объект?',
            'options': [
                'Имитация реального объекта для тестов',
                'Реальный объект БД',
                'Файл конфигурации',
                'Тип переменной'
            ],
            'correct': 0,
            'explanation': 'Mock объекты имитируют поведение реальных объектов для изоляции тестируемого кода.'
        },
        {
            'question': 'Принцип DRY в тестировании?',
            'options': [
                "Don't Repeat Yourself - не повторяйся",
                'Do Repeat Yourself',
                'Delete Repeated Years',
                'Debug Ready Yearly'
            ],
            'correct': 0,
            'explanation': 'DRY - принцип избегания дублирования кода через переиспользуемые функции.'
        },
        {
            'question': 'Что такое Page Object Model?',
            'options': [
                'Паттерн где каждая страница - класс',
                'Модель БД',
                'Тип документации',
                'Метод ручного тестирования'
            ],
            'correct': 0,
            'explanation': 'POM помогает создать поддерживаемые автотесты через инкапсуляцию элементов страницы.'
        },
        {
            'question': 'Что проверяет security testing?',
            'options': [
                'Защищенность от несанкционированного доступа',
                'Скорость работы',
                'Функциональность',
                'Внешний вид'
            ],
            'correct': 0,
            'explanation': 'Security testing проверяет уязвимости: SQL injection, XSS, CSRF и другие атаки.'
        },
        {
            'question': 'Что такое REST API?',
            'options': [
                'Архитектурный стиль для сетевых приложений',
                'База данных',
                'Язык программирования',
                'Протокол шифрования'
            ],
            'correct': 0,
            'explanation': 'REST - архитектурный стиль использующий HTTP методы для работы с ресурсами.'
        },
        {
            'question': 'Что такое JSON?',
            'options': [
                'Формат обмена данными',
                'Язык программирования',
                'База данных',
                'Веб-сервер'
            ],
            'correct': 0,
            'explanation': 'JSON - легковесный текстовый формат для передачи структурированных данных.'
        },
        {
            'question': 'Что такое XPath?',
            'options': [
                'Язык запросов для навигации по XML/HTML',
                'Протокол передачи данных',
                'База данных',
                'Язык программирования'
            ],
            'correct': 0,
            'explanation': 'XPath используется для поиска элементов в XML/HTML документах в автоматизации.'
        },
        {
            'question': 'Что такое CSS selector?',
            'options': [
                'Паттерн для выбора элементов на странице',
                'Язык стилей',
                'База данных',
                'Протокол'
            ],
            'correct': 0,
            'explanation': 'CSS селекторы используются для нахождения элементов в DOM при автоматизации.'
        },
        {
            'question': 'Что такое stub?',
            'options': [
                'Заглушка с предопределенными ответами',
                'Реальный сервис',
                'Тип базы данных',
                'Протокол'
            ],
            'correct': 0,
            'explanation': 'Stub - упрощенная реализация компонента с заранее заданными ответами для тестов.'
        },
        {
            'question': 'Разница между mock и stub?',
            'options': [
                'Mock проверяет вызовы, stub просто отвечает',
                'Нет разницы',
                'Mock для unit, stub для API',
                'Stub быстрее'
            ],
            'correct': 0,
            'explanation': 'Mock проверяет как вызывался, stub просто возвращает предопределенные данные.'
        },
        {
            'question': 'Что такое API rate limiting?',
            'options': [
                'Ограничение запросов в единицу времени',
                'Скорость ответа API',
                'Размер ответа',
                'Время жизни токена'
            ],
            'correct': 0,
            'explanation': 'Rate limiting защищает API от перегрузки, ограничивая число запросов от клиента.'
        },
        {
            'question': 'Что такое idempotency в API?',
            'options': [
                'Повторный запрос дает тот же результат',
                'Быстрый ответ',
                'Безопасный запрос',
                'Кэшируемый запрос'
            ],
            'correct': 0,
            'explanation': 'Идемпотентность - свойство когда многократное выполнение дает тот же результат что и однократное.'
        },
        {
            'question': 'Что такое smoke test suite?',
            'options': [
                'Набор критических автотестов для проверки',
                'Все автотесты',
                'Ручные тесты',
                'Нагрузочные тесты'
            ],
            'correct': 0,
            'explanation': 'Smoke test suite - минимальный набор автотестов проверяющий основной функционал.'
        },
        {
            'question': 'Что такое flaky test?',
            'options': [
                'Тест который нестабильно падает/проходит',
                'Медленный тест',
                'Пропущенный тест',
                'Неправильный тест'
            ],
            'correct': 0,
            'explanation': 'Flaky test - нестабильный тест, который может упасть без изменений в коде.'
        },
        {
            'question': 'Что такое Selenium?',
            'options': [
                'Фреймворк для автоматизации веб-приложений',
                'Язык программирования',
                'База данных',
                'Операционная система'
            ],
            'correct': 0,
            'explanation': 'Selenium - популярный инструмент для автоматизации тестирования веб-приложений.'
        },
        {
            'question': 'Что такое WebDriver?',
            'options': [
                'API для управления браузером',
                'Драйвер принтера',
                'База данных',
                'Сетевой протокол'
            ],
            'correct': 0,
            'explanation': 'WebDriver - интерфейс для программного управления браузером в автотестах.'
        },
        {
            'question': 'Что такое Postman?',
            'options': [
                'Инструмент для тестирования API',
                'Почтовый клиент',
                'База данных',
                'Веб-сервер'
            ],
            'correct': 0,
            'explanation': 'Postman - популярная платформа для разработки и тестирования API.'
        },
        {
            'question': 'Что такое assertion в тестах?',
            'options': [
                'Проверка ожидаемого результата',
                'Создание данных',
                'Удаление данных',
                'Логирование'
            ],
            'correct': 0,
            'explanation': 'Assertion - утверждение проверяющее что результат соответствует ожиданиям.'
        },
        {
            'question': 'Что такое test fixture?',
            'options': [
                'Подготовка окружения перед тестами',
                'Сломанный тест',
                'Баг в коде',
                'Отчет о тестах'
            ],
            'correct': 0,
            'explanation': 'Fixture - настройка начального состояния (данные, конфиги) перед выполнением тестов.'
        },
        {
            'question': 'Что такое setUp и tearDown?',
            'options': [
                'Методы подготовки и очистки в тестах',
                'Команды БД',
                'HTTP методы',
                'Типы багов'
            ],
            'correct': 0,
            'explanation': 'setUp готовит окружение перед тестом, tearDown очищает после выполнения.'
        },
        {
            'question': 'Что такое test coverage?',
            'options': [
                'Процент кода покрытого тестами',
                'Количество тестов',
                'Скорость тестирования',
                'Количество багов'
            ],
            'correct': 0,
            'explanation': 'Test coverage - метрика показывающая какая часть кода выполняется тестами.'
        },
        {
            'question': 'Что такое unit test?',
            'options': [
                'Тест отдельной функции/метода',
                'Тест всей системы',
                'Тест интерфейса',
                'Тест производительности'
            ],
            'correct': 0,
            'explanation': 'Unit test - тест минимальной единицы кода (функции, метода) в изоляции.'
        },
        {
            'question': 'Что такое integration test?',
            'options': [
                'Тест взаимодействия между компонентами',
                'Тест одной функции',
                'Тест интерфейса',
                'Тест безопасности'
            ],
            'correct': 0,
            'explanation': 'Integration test проверяет корректность взаимодействия между модулями системы.'
        },
        {
            'question': 'Что такое E2E testing?',
            'options': [
                'End-to-End тестирование всего пути',
                'Тест одной функции',
                'Тест API',
                'Тест БД'
            ],
            'correct': 0,
            'explanation': 'E2E testing проверяет весь флоу от начала до конца с точки зрения пользователя.'
        },
        {
            'question': 'Что такое Docker в тестировании?',
            'options': [
                'Контейнеризация окружения для тестов',
                'База данных',
                'Язык программирования',
                'Фреймворк тестирования'
            ],
            'correct': 0,
            'explanation': 'Docker позволяет упаковать приложение и окружение в контейнер для консистентных тестов.'
        },
        {
            'question': 'Что такое Jenkins?',
            'options': [
                'Инструмент для CI/CD автоматизации',
                'Язык программирования',
                'База данных',
                'Браузер'
            ],
            'correct': 0,
            'explanation': 'Jenkins - сервер автоматизации для непрерывной интеграции и доставки.'
        },
        {
            'question': 'Что такое Git в контексте тестирования?',
            'options': [
                'Система контроля версий для кода и тестов',
                'Инструмент тестирования',
                'База данных',
                'Сервер приложений'
            ],
            'correct': 0,
            'explanation': 'Git используется для версионирования тест-кода и совместной работы команды.'
        },
        {
            'question': 'Что такое regression suite?',
            'options': [
                'Набор тестов для проверки старого функционала',
                'Новые тесты',
                'Ручные тесты',
                'Тесты производительности'
            ],
            'correct': 0,
            'explanation': 'Regression suite - коллекция автотестов запускаемых после изменений в коде.'
        },
        {
            'question': 'Что такое data-driven testing?',
            'options': [
                'Тесты с разными наборами данных',
                'Тестирование БД',
                'Ручное тестирование',
                'Визуальное тестирование'
            ],
            'correct': 0,
            'explanation': 'Data-driven testing - подход где один тест выполняется с множеством наборов данных.'
        },
        {
            'question': 'Что такое keyword-driven testing?',
            'options': [
                'Тесты на основе ключевых слов-действий',
                'Поиск по ключевым словам',
                'Тестирование текста',
                'SEO тестирование'
            ],
            'correct': 0,
            'explanation': 'Keyword-driven - подход где тесты описываются через набор ключевых слов (Login, Click).'
        },
        {
            'question': 'Что такое BDD фреймворк Cucumber?',
            'options': [
                'Инструмент для тестов на языке Gherkin',
                'База данных',
                'Язык программирования',
                'Веб-сервер'
            ],
            'correct': 0,
            'explanation': 'Cucumber позволяет писать тесты на естественном языке (Given-When-Then).'
        },
        {
            'question': 'Что такое Gherkin?',
            'options': [
                'Язык для описания поведения (Given-When-Then)',
                'Язык программирования',
                'База данных',
                'Протокол'
            ],
            'correct': 0,
            'explanation': 'Gherkin - язык для написания BDD сценариев понятным бизнесу способом.'
        },
        {
            'question': 'Что такое headless browser?',
            'options': [
                'Браузер без графического интерфейса',
                'Старый браузер',
                'Мобильный браузер',
                'Защищенный браузер'
            ],
            'correct': 0,
            'explanation': 'Headless browser работает без GUI, быстрее для автотестов в CI/CD.'
        },
        {
            'question': 'Что такое explicit wait?',
            'options': [
                'Ожидание конкретного условия',
                'Фиксированная задержка',
                'Ожидание без условий',
                'Пропуск ожидания'
            ],
            'correct': 0,
            'explanation': 'Explicit wait ждет выполнения определенного условия (элемент кликабелен) до таймаута.'
        },
        {
            'question': 'Что такое implicit wait?',
            'options': [
                'Глобальное ожидание поиска элементов',
                'Условное ожидание',
                'Ожидание без задержки',
                'Ожидание клика'
            ],
            'correct': 0,
            'explanation': 'Implicit wait устанавливает таймаут для всех операций поиска элементов.'
        },
        {
            'question': 'Что такое OAuth в тестировании?',
            'options': [
                'Протокол авторизации через сторонние сервисы',
                'База данных',
                'Фреймворк тестирования',
                'Язык запросов'
            ],
            'correct': 0,
            'explanation': 'OAuth - стандарт авторизации (вход через Google/Facebook), требует специального тестирования.'
        },
        {
            'question': 'Что такое JWT?',
            'options': [
                'JSON Web Token для аутентификации',
                'Язык программирования',
                'База данных',
                'Протокол передачи'
            ],
            'correct': 0,
            'explanation': 'JWT - компактный токен для передачи информации между клиентом и сервером.'
        },
        {
            'question': 'Что такое CORS?',
            'options': [
                'Cross-Origin Resource Sharing для безопасности',
                'Тип базы данных',
                'Язык программирования',
                'Фреймворк'
            ],
            'correct': 0,
            'explanation': 'CORS - механизм безопасности браузера для кросс-доменных запросов.'
        },
        {
            'question': 'Что такое XSS атака?',
            'options': [
                'Cross-Site Scripting - внедрение скриптов',
                'Тип базы данных',
                'Метод оптимизации',
                'Протокол шифрования'
            ],
            'correct': 0,
            'explanation': 'XSS - уязвимость позволяющая внедрить вредоносный JS код на страницу.'
        },
        {
            'question': 'Что такое CSRF атака?',
            'options': [
                'Cross-Site Request Forgery - подделка запросов',
                'Тип шифрования',
                'Метод кэширования',
                'Протокол передачи'
            ],
            'correct': 0,
            'explanation': 'CSRF - атака заставляющая пользователя выполнить нежелательное действие.'
        },
        {
            'question': 'Что такое TestNG?',
            'options': [
                'Фреймворк тестирования для Java',
                'База данных',
                'Язык программирования',
                'Веб-сервер'
            ],
            'correct': 0,
            'explanation': 'TestNG - мощный фреймворк для написания и организации тестов на Java.'
        },
        {
            'question': 'Что такое JUnit?',
            'options': [
                'Unit testing фреймворк для Java',
                'База данных',
                'IDE',
                'Язык программирования'
            ],
            'correct': 0,
            'explanation': 'JUnit - популярный фреймворк для написания unit тестов на Java.'
        },
        {
            'question': 'Что такое pytest?',
            'options': [
                'Testing фреймворк для Python',
                'База данных',
                'Веб-фреймворк',
                'Язык программирования'
            ],
            'correct': 0,
            'explanation': 'pytest - мощный и гибкий фреймворк для написания тестов на Python.'
        },
        {
            'question': 'Что такое Allure Report?',
            'options': [
                'Инструмент для красивых отчетов тестирования',
                'База данных',
                'Фреймворк тестирования',
                'Язык программирования'
            ],
            'correct': 0,
            'explanation': 'Allure - фреймворк для генерации подробных и наглядных отчетов о тестировании.'
        }
    ],
    'senior': [
        {
            'question': 'Что такое TDD?',
            'options': [
                'Методология где тесты пишутся до кода',
                'Тесты после кода',
                'Инструмент тестирования',
                'Язык программирования'
            ],
            'correct': 0,
            'explanation': 'TDD: Red (пишем тест) → Green (пишем код) → Refactor (улучшаем код).'
        },
        {
            'question': 'Что такое BDD?',
            'options': [
                'Методология на основе описания поведения',
                'Тип БД',
                'Инструмент автоматизации',
                'Протокол передачи данных'
            ],
            'correct': 0,
            'explanation': 'BDD использует естественный язык (Given-When-Then) для описания поведения.'
        },
        {
            'question': 'Основные метрики качества кода?',
            'options': [
                'Code Coverage, Cyclomatic Complexity, Tech Debt',
                'Только строки кода',
                'Только функции',
                'Только классы'
            ],
            'correct': 0,
            'explanation': 'Метрики помогают объективно оценить качество кода и покрытие тестами.'
        },
        {
            'question': 'Что такое Contract Testing?',
            'options': [
                'Тестирование контрактов между микросервисами',
                'Тестирование юр. документов',
                'Тестирование UI',
                'Тестирование БД'
            ],
            'correct': 0,
            'explanation': 'Contract testing проверяет соблюдение договоренностей между сервисами (Pact).'
        },
        {
            'question': 'Что такое Fuzz Testing?',
            'options': [
                'Поиск уязвимостей через случайные данные',
                'Unit Testing',
                'Integration Testing',
                'Smoke Testing'
            ],
            'correct': 0,
            'explanation': 'Fuzzing отправляет случайные/некорректные данные для выявления неожиданного поведения.'
        },
        {
            'question': 'Что такое Chaos Engineering?',
            'options': [
                'Внедрение отказов для проверки отказоустойчивости',
                'Беспорядочное тестирование',
                'Тестирование без плана',
                'Тестирование хаотичного кода'
            ],
            'correct': 0,
            'explanation': 'Chaos Engineering (Netflix Chaos Monkey) - преднамеренное создание сбоев в production.'
        },
        {
            'question': 'Что проверяет stress testing?',
            'options': [
                'Поведение за пределами нормальной нагрузки',
                'Функциональность',
                'Удобство интерфейса',
                'Цвета дизайна'
            ],
            'correct': 0,
            'explanation': 'Stress testing проверяет точку отказа и поведение при критических нагрузках.'
        },
        {
            'question': 'Что такое Shift-Left Testing?',
            'options': [
                'Тестирование на ранних этапах разработки',
                'Тестирование левой части UI',
                'Тестирование левой кнопки',
                'Перенос тестов влево'
            ],
            'correct': 0,
            'explanation': 'Shift-Left - раннее вовлечение QA для снижения стоимости багов.'
        },
        {
            'question': 'Паттерны для тестовых данных?',
            'options': [
                'Test Data Builder, Object Mother, Fixture',
                'Только Singleton',
                'Только Factory',
                'Только Observer'
            ],
            'correct': 0,
            'explanation': 'Эти паттерны помогают управлять тестовыми данными более эффективно.'
        },
        {
            'question': 'Что такое A/B тестирование?',
            'options': [
                'Сравнение двух версий для определения лучшей',
                'Тестирование букв',
                'Тестирование первых функций',
                'Альтернатива unit-тестам'
            ],
            'correct': 0,
            'explanation': 'A/B тестирование показывает разные версии для определения более эффективной.'
        },
        {
            'question': 'Что такое mutation testing?',
            'options': [
                'Проверка качества тестов через мутации в коде',
                'Тестирование изменений',
                'Генетические алгоритмы',
                'Тестирование БД'
            ],
            'correct': 0,
            'explanation': 'Mutation testing вносит баги в код и проверяет находят ли их тесты.'
        },
        {
            'question': 'Что такое property-based testing?',
            'options': [
                'Тестирование свойств с автогенерацией данных',
                'Тестирование объектов',
                'Тестирование переменных',
                'Юнит-тестирование'
            ],
            'correct': 0,
            'explanation': 'Property-based testing генерирует множество тестовых данных для проверки свойств.'
        },
        {
            'question': 'Test Pyramid - правильная структура?',
            'options': [
                'Много unit → средне integration → мало E2E',
                'Много E2E → мало unit',
                'Все типы поровну',
                'Только unit тесты'
            ],
            'correct': 0,
            'explanation': 'Test Pyramid: много быстрых unit тестов в основании, мало медленных E2E на вершине.'
        },
        {
            'question': 'Что такое Test Double?',
            'options': [
                'Общий термин для mock, stub, fake, spy, dummy',
                'Двойное тестирование',
                'Дублирование тестов',
                'Два тестовых окружения'
            ],
            'correct': 0,
            'explanation': 'Test Double - общее название для всех видов тестовых замен реальных объектов.'
        },
        {
            'question': 'Что такое canary deployment?',
            'options': [
                'Постепенный выкат новой версии на часть юзеров',
                'Тестирование птиц',
                'Желтое окружение',
                'Быстрый деплой'
            ],
            'correct': 0,
            'explanation': 'Canary deployment снижает риск выкатывая изменения сначала небольшой группе.'
        },
        {
            'question': 'Что такое blue-green deployment?',
            'options': [
                'Два идентичных окружения для безопасного переключения',
                'Цветовое кодирование',
                'Два разных продукта',
                'Стадии разработки'
            ],
            'correct': 0,
            'explanation': 'Blue-green позволяет мгновенно откатиться переключившись обратно на старое окружение.'
        },
        {
            'question': 'Что такое feature toggle?',
            'options': [
                'Механизм включения/выключения функций без деплоя',
                'Переключатель в UI',
                'Настройка БД',
                'Конфигурация сервера'
            ],
            'correct': 0,
            'explanation': 'Feature toggle позволяет управлять доступностью функций через конфигурацию.'
        },
        {
            'question': 'Что такое observability?',
            'options': [
                'Способность понять состояние системы по выходным данным',
                'Видимость кода',
                'Мониторинг серверов',
                'Логирование'
            ],
            'correct': 0,
            'explanation': 'Observability включает метрики, логи и трейсы для понимания поведения системы.'
        },
        {
            'question': 'В чем разница monitoring vs observability?',
            'options': [
                'Monitoring - известные проблемы, observability - нет',
                'Нет разницы',
                'Monitoring быстрее',
                'Observability дешевле'
            ],
            'correct': 0,
            'explanation': 'Monitoring отслеживает известные метрики, observability помогает исследовать неизвестные проблемы.'
        },
        {
            'question': 'Что такое synthetic monitoring?',
            'options': [
                'Симуляция действий пользователей для проверки',
                'Искусственный интеллект',
                'Синтетические данные',
                'Виртуальные машины'
            ],
            'correct': 0,
            'explanation': 'Synthetic monitoring использует скрипты для постоянной проверки доступности и производительности.'
        },
        {
            'question': 'Что такое Microservices Testing Strategy?',
            'options': [
                'Тестирование сервисов независимо и их интеграций',
                'Тестирование маленьких файлов',
                'Юнит-тестирование',
                'Тестирование UI'
            ],
            'correct': 0,
            'explanation': 'Включает contract testing, service virtualization, consumer-driven contracts.'
        },
        {
            'question': 'Что такое Service Virtualization?',
            'options': [
                'Симуляция недоступных сервисов для тестов',
                'Виртуальные машины',
                'Облачные сервисы',
                'Контейнеризация'
            ],
            'correct': 0,
            'explanation': 'Service virtualization имитирует поведение зависимых систем при их недоступности.'
        },
        {
            'question': 'Что такое Consumer-Driven Contracts?',
            'options': [
                'Контракты определяемые потребителями API',
                'Юридические договоры',
                'Пользовательские соглашения',
                'Конфигурация БД'
            ],
            'correct': 0,
            'explanation': 'CDC позволяет потребителям API определять ожидания от провайдера (Pact).'
        },
        {
            'question': 'Что такое Performance Testing Strategy?',
            'options': [
                'Load, Stress, Spike, Endurance, Scalability тесты',
                'Только Load тесты',
                'Только Unit тесты',
                'Только UI тесты'
            ],
            'correct': 0,
            'explanation': 'Комплексная стратегия производительности включает различные типы нагрузочных тестов.'
        },
        {
            'question': 'Что такое JMeter?',
            'options': [
                'Инструмент для нагрузочного тестирования',
                'Единица измерения',
                'База данных',
                'Язык программирования'
            ],
            'correct': 0,
            'explanation': 'Apache JMeter - популярный инструмент для performance и load тестирования.'
        },
        {
            'question': 'Что такое Gatling?',
            'options': [
                'Инструмент нагрузочного тестирования на Scala',
                'Пулемет',
                'База данных',
                'Веб-сервер'
            ],
            'correct': 0,
            'explanation': 'Gatling - высокопроизводительный инструмент для load testing с красивыми отчетами.'
        },
        {
            'question': 'Что такое k6?',
            'options': [
                'Современный инструмент load testing',
                'Версия Kubernetes',
                'База данных',
                'Протокол'
            ],
            'correct': 0,
            'explanation': 'k6 - developer-friendly инструмент для performance testing с поддержкой JS.'
        },
        {
            'question': 'Что такое APM (Application Performance Monitoring)?',
            'options': [
                'Мониторинг производительности приложения в реальном времени',
                'Автоматическое тестирование',
                'Управление проектами',
                'Анализ багов'
            ],
            'correct': 0,
            'explanation': 'APM инструменты (New Relic, Dynatrace) отслеживают производительность в production.'
        },
        {
            'question': 'Что такое Distributed Tracing?',
            'options': [
                'Отслеживание запросов через микросервисы',
                'Географическое тестирование',
                'Тестирование кластеров',
                'Балансировка нагрузки'
            ],
            'correct': 0,
            'explanation': 'Distributed tracing (Jaeger, Zipkin) помогает отследить путь запроса через систему.'
        },
        {
            'question': 'Что такое SLI, SLO, SLA?',
            'options': [
                'Indicators, Objectives, Agreements для качества',
                'Типы тестов',
                'Языки программирования',
                'Протоколы связи'
            ],
            'correct': 0,
            'explanation': 'SLI - метрики, SLO - цели, SLA - соглашения об уровне сервиса.'
        },
        {
            'question': 'Что такое Error Budget?',
            'options': [
                'Допустимое количество ошибок для инноваций',
                'Бюджет на исправление багов',
                'Список ошибок',
                'Стоимость тестирования'
            ],
            'correct': 0,
            'explanation': 'Error budget (Google SRE) - баланс между надежностью и скоростью разработки.'
        },
        {
            'question': 'Что такое Site Reliability Engineering (SRE)?',
            'options': [
                'Практики обеспечения надежности систем',
                'Тестирование сайтов',
                'Разработка фронтенда',
                'Администрирование БД'
            ],
            'correct': 0,
            'explanation': 'SRE (Google) - подход применяющий инженерные принципы к операционным задачам.'
        },
        {
            'question': 'Что такое Infrastructure as Code (IaC)?',
            'options': [
                'Управление инфраструктурой через код',
                'Код приложения',
                'Тестовый код',
                'Документация'
            ],
            'correct': 0,
            'explanation': 'IaC (Terraform, Ansible) позволяет версионировать и тестировать инфраструктуру.'
        },
        {
            'question': 'Что такое GitOps?',
            'options': [
                'Git как источник истины для деплоя',
                'Операции с Git',
                'Тестирование Git',
                'Работа с репозиториями'
            ],
            'correct': 0,
            'explanation': 'GitOps - практика где Git репозиторий определяет желаемое состояние системы.'
        },
        {
            'question': 'Что такое Kubernetes в контексте тестирования?',
            'options': [
                'Оркестрация контейнеров для тестовых окружений',
                'База данных',
                'Язык программирования',
                'Фреймворк тестирования'
            ],
            'correct': 0,
            'explanation': 'Kubernetes управляет контейнерами, позволяя создавать изолированные тестовые окружения.'
        },
        {
            'question': 'Что такое Test Containerization?',
            'options': [
                'Запуск тестов в изолированных контейнерах',
                'Упаковка тестов',
                'Сжатие тестов',
                'Шифрование тестов'
            ],
            'correct': 0,
            'explanation': 'Контейнеризация тестов обеспечивает консистентность окружения и параллельность.'
        },
        {
            'question': 'Что такое Visual Regression Testing?',
            'options': [
                'Автоматическое сравнение скриншотов UI',
                'Ручное тестирование дизайна',
                'Тестирование цветов',
                'Проверка шрифтов'
            ],
            'correct': 0,
            'explanation': 'Visual regression (Percy, Applitools) автоматически находит визуальные изменения.'
        },
        {
            'question': 'Что такое Accessibility Testing (a11y)?',
            'options': [
                'Тестирование доступности для людей с ограничениями',
                'Тестирование доступа',
                'Тестирование прав',
                'Тестирование входа'
            ],
            'correct': 0,
            'explanation': 'A11y testing проверяет доступность для людей с особенностями (WCAG стандарты).'
        },
        {
            'question': 'Что такое WCAG?',
            'options': [
                'Web Content Accessibility Guidelines',
                'Язык программирования',
                'Протокол',
                'База данных'
            ],
            'correct': 0,
            'explanation': 'WCAG - международные стандарты доступности веб-контента (уровни A, AA, AAA).'
        },
        {
            'question': 'Что такое Security Testing Automation?',
            'options': [
                'Автоматизация SAST, DAST, SCA для безопасности',
                'Ручное тестирование безопасности',
                'Шифрование данных',
                'Управление паролями'
            ],
            'correct': 0,
            'explanation': 'Автоматизация сканирования уязвимостей (OWASP ZAP, Burp Suite, Snyk).'
        },
        {
            'question': 'Что такое SAST?',
            'options': [
                'Static Application Security Testing - анализ кода',
                'Динамическое тестирование',
                'Ручное тестирование',
                'Нагрузочное тестирование'
            ],
            'correct': 0,
            'explanation': 'SAST анализирует исходный код на уязвимости без запуска приложения.'
        },
        {
            'question': 'Что такое DAST?',
            'options': [
                'Dynamic App Security Testing - тест запущенного app',
                'Статический анализ',
                'Ручное тестирование',
                'Юнит-тестирование'
            ],
            'correct': 0,
            'explanation': 'DAST тестирует работающее приложение имитируя атаки (black-box подход).'
        },
        {
            'question': 'Что такое SCA (Software Composition Analysis)?',
            'options': [
                'Анализ уязвимостей в сторонних библиотеках',
                'Анализ производительности',
                'Анализ покрытия',
                'Анализ архитектуры'
            ],
            'correct': 0,
            'explanation': 'SCA выявляет известные уязвимости в зависимостях проекта.'
        },
        {
            'question': 'Что такое Penetration Testing?',
            'options': [
                'Симуляция реальных атак на систему',
                'Нагрузочное тестирование',
                'Функциональное тестирование',
                'Регрессионное тестирование'
            ],
            'correct': 0,
            'explanation': 'Pen testing - этичный взлом для выявления уязвимостей до реальных атак.'
        },
        {
            'question': 'Что такое Bug Bounty Program?',
            'options': [
                'Программа вознаграждения за найденные уязвимости',
                'Список багов',
                'Инструмент тестирования',
                'Конкурс тестировщиков'
            ],
            'correct': 0,
            'explanation': 'Bug bounty привлекает внешних исследователей для поиска уязвимостей за деньги.'
        },
        {
            'question': 'Что такое Test Impact Analysis?',
            'options': [
                'Определение каких тестов запускать при изменениях',
                'Анализ результатов',
                'Оценка покрытия',
                'Метрики производительности'
            ],
            'correct': 0,
            'explanation': 'TIA оптимизирует CI запуская только тесты затронутые изменениями кода.'
        },
        {
            'question': 'Что такое Parallel Test Execution?',
            'options': [
                'Одновременный запуск тестов для скорости',
                'Последовательное тестирование',
                'Тестирование на двух машинах',
                'Дублирование тестов'
            ],
            'correct': 0,
            'explanation': 'Параллелизация сокращает время выполнения test suite в разы.'
        },
        {
            'question': 'Что такое Test Sharding?',
            'options': [
                'Разделение тестов на группы для параллельности',
                'Удаление тестов',
                'Объединение тестов',
                'Шифрование тестов'
            ],
            'correct': 0,
            'explanation': 'Sharding распределяет тесты между несколькими машинами для быстрого выполнения.'
        },
        {
            'question': 'Что такое Flaky Test Detection?',
            'options': [
                'Автоматическое выявление нестабильных тестов',
                'Поиск багов',
                'Анализ покрытия',
                'Метрики производительности'
            ],
            'correct': 0,
            'explanation': 'Инструменты (BuildPulse, TestRail) выявляют тесты с нестабильными результатами.'
        },
        {
            'question': 'Что такое Test Quarantine?',
            'options': [
                'Изоляция flaky тестов от основного suite',
                'Удаление тестов',
                'Блокировка CI',
                'Пропуск тестов'
            ],
            'correct': 0,
            'explanation': 'Quarantine временно исключает нестабильные тесты не блокируя основной pipeline.'
        }
    ]
}

# Хранилище данных пользователей в памяти (для быстрого доступа)
user_data = {}

# ==================== COMMAND HANDLERS ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Расширенное стартовое сообщение с выбором режима и уровня"""
    try:
        user_id = update.message.from_user.id
        username = update.message.from_user.username or ""
        first_name = update.message.from_user.first_name or "друг"

        # Сохраняем пользователя
        save_user(user_id, username, first_name)

        # Удаляем старую сессию если есть
        delete_session(user_id)
        if user_id in user_data:
            del user_data[user_id]

        keyboard = [
            [InlineKeyboardButton("Junior QA 🌱", callback_data='select_junior')],
            [InlineKeyboardButton("Middle QA 🚀", callback_data='select_middle')],
            [InlineKeyboardButton("Senior QA 👑", callback_data='select_senior')],
            [InlineKeyboardButton("📊 Моя статистика", callback_data='show_stats')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        welcome_text = (
            f'👋 Привет, {first_name}!\n\n'
            f'Я — твой персональный помощник для подготовки к собеседованию на позицию QA Engineer.\n\n'
            f'🎯 <b>Что я умею:</b>\n'
            f'✅ Проверяю знания по 3 уровням сложности\n'
            f'✅ Два режима тестирования (полный и быстрый)\n'
            f'✅ Даю подробные объяснения к каждому ответу\n'
            f'✅ Сохраняю статистику и показываю прогресс\n'
            f'✅ Показываю прогресс-бар во время теста\n\n'
            f'📚 <b>Уровни тестирования:</b>\n'
            f'🌱 <b>Junior</b> — основы тестирования, базовая терминология (50 вопросов)\n'
            f'🚀 <b>Middle</b> — API, автоматизация, CI/CD, безопасность (50 вопросов)\n'
            f'👑 <b>Senior</b> — TDD/BDD, метрики, архитектурные подходы (50 вопросов)\n\n'
            f'🎮 <b>Режимы тестирования:</b>\n'
            f'• Полный тест — 20 случайных вопросов\n'
            f'• Быстрый тест — 10 случайных вопросов\n\n'
            f'💡 <b>Полезные команды:</b>\n'
            f'/start — Начать заново\n'
            f'/stats — Посмотреть статистику\n'
            f'/reset — Сбросить текущий тест\n\n'
            f'⚡️ <b>Выбери свой уровень и начинай!</b>'
        )

        await update.message.reply_text(
            welcome_text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )

        logger.info(f"User {user_id} ({first_name}) started the bot")

    except Exception as e:
        logger.error(f"Error in start command: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Произошла ошибка при запуске. Попробуйте еще раз: /start"
        )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда для показа статистики"""
    try:
        user_id = update.message.from_user.id
        await show_user_stats(update.message, user_id)
        logger.info(f"User {user_id} requested stats")
    except Exception as e:
        logger.error(f"Error in stats command: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Не удалось загрузить статистику. Попробуйте позже."
        )

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда для сброса текущего теста"""
    try:
        user_id = update.message.from_user.id

        # Удаляем сессию
        delete_session(user_id)
        if user_id in user_data:
            del user_data[user_id]

        keyboard = [
            [InlineKeyboardButton("Junior QA 🌱", callback_data='select_junior')],
            [InlineKeyboardButton("Middle QA 🚀", callback_data='select_middle')],
            [InlineKeyboardButton("Senior QA 👑", callback_data='select_senior')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            '🔄 Текущий тест сброшен!\n\nВыбери уровень для нового теста:',
            reply_markup=reply_markup
        )

        logger.info(f"User {user_id} reset their test")

    except Exception as e:
        logger.error(f"Error in reset command: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Не удалось сбросить тест. Попробуйте /start"
        )

# ==================== CALLBACK HANDLERS ====================

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка нажатий на кнопки"""
    query = update.callback_query

    try:
        await query.answer()
        user_id = query.from_user.id

        # Выбор уровня
        if query.data.startswith('select_'):
            level = query.data.replace('select_', '')
            await select_mode(query, user_id, level)

        # Выбор режима
        elif query.data.startswith('mode_'):
            parts = query.data.split('_')
            level = parts[1]
            mode = parts[2]
            await start_test(query, user_id, level, mode)

        # Ответ на вопрос
        elif query.data.startswith('answer_'):
            answer_idx = int(query.data.replace('answer_', ''))
            await check_answer(query, user_id, answer_idx)

        # Следующий вопрос
        elif query.data == 'next_question':
            await send_question(query, user_id)

        # Показать статистику
        elif query.data == 'show_stats':
            await show_user_stats(query.message, user_id, edit=True, query=query)

        # Вернуться к выбору уровня
        elif query.data == 'choose_level':
            await choose_level(query)

        # Повторить тест
        elif query.data.startswith('retry_'):
            parts = query.data.split('_')
            level = parts[1]
            mode = parts[2]
            await start_test(query, user_id, level, mode)

    except Exception as e:
        logger.error(f"Error in button callback: {e}", exc_info=True)
        try:
            await query.edit_message_text(
                "❌ Произошла ошибка. Используйте /reset чтобы начать заново."
            )
        except:
            pass

async def select_mode(query, user_id: int, level: str) -> None:
    """Выбор режима тестирования"""
    try:
        keyboard = [
            [InlineKeyboardButton("📝 Полный тест (20 вопросов)", callback_data=f'mode_{level}_full')],
            [InlineKeyboardButton("⚡️ Быстрый тест (10 вопросов)", callback_data=f'mode_{level}_quick')],
            [InlineKeyboardButton("◀️ Назад", callback_data='choose_level')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        level_emoji = {'junior': '🌱', 'middle': '🚀', 'senior': '👑'}
        level_names = {'junior': 'Junior QA', 'middle': 'Middle QA', 'senior': 'Senior QA'}

        text = (
            f"{level_emoji[level]} <b>{level_names[level]}</b>\n\n"
            f"Выбери режим тестирования:\n\n"
            f"📝 <b>Полный тест</b> — 20 случайных вопросов\n"
            f"⚡️ <b>Быстрый тест</b> — 10 случайных вопросов для быстрой проверки"
        )

        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error in select_mode: {e}", exc_info=True)
        raise

async def start_test(query, user_id: int, level: str, mode: str) -> None:
    """Начало тестирования с исправленным перемешиванием ответов"""
    try:
        # Удаляем старую сессию
        delete_session(user_id)

        # Определяем количество вопросов
        question_count = 10 if mode == 'quick' else 20

        # Выбираем случайные вопросы
        all_questions = QUESTIONS[level]
        selected_questions = random.sample(all_questions, min(question_count, len(all_questions)))

        # ИСПРАВЛЕНИЕ: Перемешиваем варианты ответов для каждого вопроса
        shuffled_questions = []
        for q in selected_questions:
            # Создаем список пар (вариант, это_правильный_ответ)
            options_with_flags = [(opt, i == q['correct']) for i, opt in enumerate(q['options'])]
            # Перемешиваем этот список
            random.shuffle(options_with_flags)
            # Находим новый индекс правильного ответа
            new_correct = next(i for i, (opt, is_correct) in enumerate(options_with_flags) if is_correct)
            # Создаем новый вопрос с перемешанными вариантами
            shuffled_q = {
                'question': split_long_text(q['question']),  # Форматируем вопрос
                'options': [split_long_text(opt) for opt, _ in options_with_flags],  # Форматируем все варианты
                'correct': new_correct,
                'explanation': split_long_text(q['explanation'])  # Форматируем объяснение
            }
            shuffled_questions.append(shuffled_q)

        # Создаем новую сессию
        user_data[user_id] = {
            'level': level,
            'mode': mode,
            'questions': shuffled_questions,
            'current_question': 0,
            'correct_answers': 0,
            'total_questions': len(shuffled_questions)
        }

        # Сохраняем в БД
        save_session(user_id, user_data[user_id])

        await send_question(query, user_id)

        logger.info(f"User {user_id} started {mode} test on {level} level")

    except Exception as e:
        logger.error(f"Error in start_test: {e}", exc_info=True)
        raise

async def send_question(query, user_id: int) -> None:
    """Отправка вопроса пользователю с форматированными вариантами ответов"""
    try:
        # Загружаем данные из памяти или БД
        if user_id not in user_data:
            session = load_session(user_id)
            if not session:
                await query.edit_message_text(
                    "❌ Сессия истекла. Начните заново: /start"
                )
                return
            user_data[user_id] = session

        data = user_data[user_id]

        # Проверяем завершение теста
        if data['current_question'] >= data['total_questions']:
            await show_results(query, user_id)
            return

        question_data = data['questions'][data['current_question']]
        question_num = data['current_question'] + 1

        # Создаем кнопки с вариантами ответов (уже отформатированными)
        keyboard = []
        for idx, option in enumerate(question_data['options']):
            keyboard.append([InlineKeyboardButton(option, callback_data=f'answer_{idx}')])

        reply_markup = InlineKeyboardMarkup(keyboard)

        level_emoji = {'junior': '🌱', 'middle': '🚀', 'senior': '👑'}
        mode_emoji = {'full': '📝', 'quick': '⚡️'}

        # Прогресс-бар
        progress = get_progress_bar(question_num - 1, data['total_questions'])

        question_text = (
            f"{level_emoji[data['level']]} {mode_emoji[data.get('mode', 'full')]} "
            f"Вопрос {question_num}/{data['total_questions']}\n\n"
            f"{progress}\n\n"
            f"❓ <b>{question_data['question']}</b>"
        )

        await query.edit_message_text(
            question_text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )

    except Exception as e:
        logger.error(f"Error in send_question: {e}", exc_info=True)
        await query.edit_message_text(
            "❌ Ошибка загрузки вопроса. Используйте /reset"
        )

async def check_answer(query, user_id: int, answer_idx: int) -> None:
    """Проверка ответа пользователя с форматированными текстами"""
    try:
        if user_id not in user_data:
            session = load_session(user_id)
            if not session:
                await query.edit_message_text(
                    "❌ Сессия истекла. Начните заново: /start"
                )
                return
            user_data[user_id] = session

        data = user_data[user_id]
        question_data = data['questions'][data['current_question']]

        is_correct = answer_idx == question_data['correct']

        if is_correct:
            data['correct_answers'] += 1
            message = (
                "✅ <b>Правильно!</b>\n\n"
                f"💡 {question_data.get('explanation', '')}"
            )
        else:
            correct_answer = question_data['options'][question_data['correct']]
            message = (
                f"❌ <b>Неправильно!</b>\n\n"
                f"<b>Правильный ответ:</b>\n{correct_answer}\n\n"
                f"💡 {question_data.get('explanation', '')}"
            )

        data['current_question'] += 1

        # Сохраняем прогресс
        save_session(user_id, data)

        # Кнопка для следующего вопроса
        keyboard = [[InlineKeyboardButton("Следующий вопрос ➡️", callback_data='next_question')]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )

    except Exception as e:
        logger.error(f"Error in check_answer: {e}", exc_info=True)
        await query.edit_message_text(
            "❌ Ошибка проверки ответа. Используйте /reset"
        )

async def show_results(query, user_id: int) -> None:
    """Показ результатов тестирования"""
    try:
        data = user_data[user_id]
        correct = data['correct_answers']
        total = data['total_questions']
        percentage = (correct / total) * 100 if total > 0 else 0

        # Сохраняем результат в БД
        save_test_result(user_id, data['level'], data.get('mode', 'full'), correct, total)

        # Удаляем сессию
        delete_session(user_id)
        if user_id in user_data:
            del user_data[user_id]

        # Определяем оценку
        if percentage >= 90:
            grade = "Отлично! 🌟"
            comment = "Ты отлично подготовлен к собеседованию!"
        elif percentage >= 70:
            grade = "Хорошо! 👍"
            comment = "Неплохой результат, но есть куда расти."
        elif percentage >= 50:
            grade = "Удовлетворительно 📚"
            comment = "Стоит подтянуть знания по некоторым темам."
        else:
            grade = "Нужно больше практики 💪"
            comment = "Рекомендую повторить материал и попробовать еще раз."

        level_names = {
            'junior': 'Junior QA Engineer 🌱',
            'middle': 'Middle QA Engineer 🚀',
            'senior': 'Senior QA Engineer 👑'
        }

        keyboard = [
            [InlineKeyboardButton("Пройти тест заново 🔄", callback_data=f"retry_{data['level']}_{data.get('mode', 'full')}")],
            [InlineKeyboardButton("Выбрать другой уровень 🎯", callback_data='choose_level')],
            [InlineKeyboardButton("Моя статистика 📊", callback_data='show_stats')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        mode_text = format_test_mode(data.get('mode', 'full'))

        results_text = (
            f"🎓 <b>Результаты теста</b>\n"
            f"{'='*30}\n\n"
            f"Уровень: {level_names[data['level']]}\n"
            f"Режим: {mode_text}\n"
            f"Правильных ответов: {correct}/{total}\n"
            f"Процент: {percentage:.1f}%\n\n"
            f"<b>{grade}</b>\n"
            f"{comment}"
        )

        await query.edit_message_text(
            results_text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )

        logger.info(f"User {user_id} completed test: {correct}/{total} ({percentage:.1f}%)")

    except Exception as e:
        logger.error(f"Error in show_results: {e}", exc_info=True)
        await query.edit_message_text(
            "❌ Ошибка показа результатов. Используйте /start"
        )

async def show_user_stats(message, user_id: int, edit: bool = False, query=None) -> None:
    """Показ статистики пользователя"""
    try:
        stats = get_user_stats(user_id)

        if not stats or not stats['overall'] or stats['overall']['total_tests'] == 0:
            text = (
                "📊 <b>Статистика</b>\n\n"
                "У вас пока нет завершенных тестов.\n"
                "Пройдите первый тест чтобы увидеть статистику!"
            )
            keyboard = [[InlineKeyboardButton("Начать тест 🚀", callback_data='choose_level')]]
        else:
            overall = stats['overall']

            text = (
                f"📊 <b>Ваша статистика</b>\n"
                f"{'='*30}\n\n"
                f"<b>Общая статистика:</b>\n"
                f"Пройдено тестов: {overall['total_tests']}\n"
                f"Средний результат: {overall['avg_percentage']:.1f}%\n"
                f"Лучший результат: {overall['best_percentage']:.1f}%\n"
                f"Правильных ответов: {overall['total_correct']}/{overall['total_questions']}\n\n"
            )

            if stats['by_level']:
                text += "<b>По уровням:</b>\n"
                level_names = {'junior': 'Junior 🌱', 'middle': 'Middle 🚀', 'senior': 'Senior 👑'}
                for level_stat in stats['by_level']:
                    level = level_stat['level']
                    text += (
                        f"\n{level_names.get(level, level)}:\n"
                        f"  • Попыток: {level_stat['attempts']}\n"
                        f"  • Средний: {level_stat['avg_percentage']:.1f}%\n"
                        f"  • Лучший: {level_stat['best_percentage']:.1f}%\n"
                    )

            if stats['recent']:
                text += f"\n\n<b>Последние тесты:</b>\n"
                for i, test in enumerate(stats['recent'][:3], 1):
                    mode_icon = '📝' if test.get('mode') == 'full' else '⚡️'
                    text += f"{i}. {mode_icon} {test['level']} - {test['percentage']:.0f}%\n"

            keyboard = [[InlineKeyboardButton("Пройти новый тест 🚀", callback_data='choose_level')]]

        reply_markup = InlineKeyboardMarkup(keyboard)

        if edit and query:
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
        else:
            await message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error in show_user_stats: {e}", exc_info=True)
        error_text = "❌ Не удалось загрузить статистику."
        if edit and query:
            await query.edit_message_text(error_text)
        else:
            await message.reply_text(error_text)

async def choose_level(query) -> None:
    """Возврат к выбору уровня"""
    try:
        keyboard = [
            [InlineKeyboardButton("Junior QA 🌱", callback_data='select_junior')],
            [InlineKeyboardButton("Middle QA 🚀", callback_data='select_middle')],
            [InlineKeyboardButton("Senior QA 👑", callback_data='select_senior')],
            [InlineKeyboardButton("📊 Моя статистика", callback_data='show_stats')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            '🎯 Выбери уровень для прохождения теста:',
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Error in choose_level: {e}", exc_info=True)
        raise


# ==================== MAIN ====================

def main() -> None:
    """Запуск бота"""
    try:
        # Инициализируем БД
        init_database()

        # Получаем токен из переменной окружения
        token = os.getenv('BOT_TOKEN')

        if not token:
            logger.error("❌ Ошибка: Не указан токен бота!")
            logger.error("Укажите переменную окружения BOT_TOKEN")
            return

        logger.info("🚀 Инициализация бота...")
        application = Application.builder().token(token).build()

        # Регистрация обработчиков
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("stats", stats))
        application.add_handler(CommandHandler("reset", reset))
        application.add_handler(CallbackQueryHandler(button_callback))

        # Запуск бота
        logger.info("🤖 Бот запущен и готов к работе!")
        application.run_polling(allowed_updates=Update.ALL_TYPES)

    except Exception as e:
        logger.error(f"❌ Critical error in main: {e}", exc_info=True)
        raise

if __name__ == '__main__':
    main()