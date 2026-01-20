import telebot
import requests
import re
import time
import csv
import io
import hashlib

# --- НАЛАШТУВАННЯ ---
TOKEN = '6894138077:AAG88jDrUp0lJKfZSNJh8KSRzFbQrx3uLt0'
CHAT_ID = '-1002340507906'
MY_GROUP_ID = "272"  # Пиши сюди будь-яку групу: 101, 272, 370, П-226...

bot = telebot.TeleBot(TOKEN)
last_table_hash = ""

# Список слів, які бот НЕ МАЄ права видаляти (назви предметів)
SAFE_SUBJECT_WORDS = [
    "Фізичне", "виховання", "Всесвітня", "Громадянська", "Іноземна", "Українська",
    "Математика", "Інженерна", "Нарисна", "Захист", "Основи", "Програмування",
    "Технологічне", "Економіка", "Фізика", "Хімія", "Геометрія", "України",
    "мова", "мови", "культура", "література", "ТЗ", "ПС", "АПП", "Фізкультура"
]


def clean_subject_v21(text, group_id):
    """ Повна чистка: залишає тільки предмет. Фіксує баг з 'Фізичне' та викладачами. """
    # 1. Видаляємо тех. заголовок пари (1 пр., 2 пара, 1 - )
    text = re.sub(r'^\s*\d\s*(пр\.?|пара|[\-–—])\s*', '', text, flags=re.I)

    # 2. Видаляємо номер групи (П-226, 370). Префікс обмежений 4 буквами.
    # Це захищає довгі слова типу "Фізичне" від випадкового видалення.
    text = re.sub(r'\b[А-Яа-яіІєЄґҐ]{1,4}\s*-?\s*' + re.escape(group_id) + r'\b', '', text)
    text = re.sub(r'\b' + re.escape(group_id) + r'\b', '', text)

    # 3. Видаляємо викладачів (ініціали типу Шеремет С.Л. або С.Л. Шеремет)
    text = re.sub(r'[А-Я][а-яієґ]+\s+[А-Я]\s*\.\s*[А-Я]\s*\.', '', text)
    text = re.sub(r'[А-Я]\s*\.\s*[А-Я]\s*\.\s*[А-Я][а-яієґ]+', '', text)
    text = re.sub(r'[А-Я]\s*\.\s*[А-Я]\s*\.', '', text)

    # 4. Видаляємо викладачів (формати: Дорощук / Панарін або Шеремет ..)
    text = re.sub(r'\s+[А-Я][а-яієґ]+\s*/\s*[А-Я][а-яієґ]+', '', text)
    text = re.sub(r'\s+[А-Я][а-яієґ]+\s*\.\.', '', text)

    # 5. Видаляємо останнє слово, якщо це прізвище (з великої літери, не в білому списку)
    words = text.split()
    if len(words) > 1:
        last_word = re.sub(r'[^\wіІєЄґҐ]', '', words[-1])
        if last_word and last_word[0].isupper() and last_word not in SAFE_SUBJECT_WORDS:
            text = " ".join(words[:-1])

    # 6. Фінальна очистка зайвих знаків
    text = re.sub(r'^[^\wіІєЄґҐ]+', '', text)
    text = re.sub(r'[^\wіІєЄґҐ)]+$', '', text)

    return text.strip()


def get_full_schedule():
    global last_table_hash
    try:
        SITE_URL = 'https://www.bfcpep.org.ua/rozklad-zanyat/zamina-zanyat/'
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(SITE_URL, headers=headers, timeout=15)
        match = re.search(r'(https://docs\.google\.com/spreadsheets/d/e/[a-zA-Z0-9-_]+)/pubhtml', response.text)
        if not match: return None

        csv_url = f"{match.group(1)}/pub?output=csv"
        csv_data = requests.get(csv_url, timeout=15)
        csv_data.encoding = 'utf-8'

        current_hash = hashlib.md5(csv_data.text.encode('utf-8')).hexdigest()
        if current_hash == last_table_hash: return "NO_CHANGES"
        last_table_hash = current_hash

        f = io.StringIO(csv_data.text)
        reader = csv.reader(f)
        all_rows = list(reader)

        week_info, date_info = "", ""
        final_lines = []
        is_my_group = False
        lessons_found = 0

        # Парсимо загальну інформацію
        for row in all_rows[:35]:
            line = " ".join(row).lower()
            if "тиждень" in line and not week_info:
                week_info = "🔴 Червоний" if "червон" in line else "⚪️ Білий"
            d_match = re.search(r'(\d{1,2}\s+[а-яієґ]{3,})', line)
            if d_match and not date_info:
                date_info = f"📅 {d_match.group(1)}"

        for row in all_rows:
            clean_cells = [c.strip() for c in row if c.strip()]
            row_text = " ".join(clean_cells)
            if not row_text: continue

            # ПОШУК ГРУПИ
            if not is_my_group:
                if re.search(r'\b' + re.escape(MY_GROUP_ID) + r'\b', row_text):
                    is_my_group = True
                    final_lines.append(f"🎓 *ГРУПА {MY_GROUP_ID}*\n{week_info} тиждень | {date_info}\n⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯")
                # ВАЖЛИВО: видалено continue, щоб схопити пару з цього ж рядка!

            if is_my_group:
                # УМОВА ЗУПИНКИ (якщо почалася інша група)
                id_match = re.search(r'\b\d{2,4}\b', row_text)
                if id_match and MY_GROUP_ID not in row_text:
                    # Перевіряємо, що це не номер пари
                    if not re.search(r'^\s*\d\s*(пр\.?|пара|[\-–—])', row_text, re.I):
                        if lessons_found > 0: break

                        # ПОШУК ПАРИ (підтримує 1 пр., 1 пара, 1 - )
                p_match = re.search(r'(\d)\s*(пр\.?|пара|[\-–—])', row_text, re.I)
                if p_match:
                    num = p_match.group(1)
                    icon = {"1": "1️⃣", "2": "2️⃣", "3": "3️⃣", "4": "4️⃣"}.get(num, "🔹")
                    subject = clean_subject_v21(row_text, MY_GROUP_ID)

                    if subject:
                        # Перевірка на дублікати (якщо пара розбита на кілька рядків)
                        if not any(icon in line for line in final_lines):
                            final_lines.append(f"{icon} {subject}")
                            lessons_found += 1

                if lessons_found >= 4: break

        if len(final_lines) > 1:
            return "\n".join(final_lines) + f"\n\n🕒 _Оновлено: {time.strftime('%H:%M')}_"
        return None

    except Exception as e:
        print(f"Error: {e}");
        return None


if __name__ == '__main__':
    print(f"🚀 Бот V21.0 запущений для групи {MY_GROUP_ID}")
    while True:
        res = get_full_schedule()
        if res == "NO_CHANGES":
            print(f"💤 {time.strftime('%H:%M:%S')} - Змін немає.")
        elif res:
            bot.send_message(CHAT_ID, res, parse_mode="Markdown")
            print(f"✅ Розклад для {MY_GROUP_ID} відправлено!")
        time.sleep(600)