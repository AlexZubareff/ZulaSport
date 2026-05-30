#!/usr/bin/env python3
"""
Единый модуль перевода названий на русский язык.
Объединяет: теннис, футбол, хоккей, баскетбол.

Использование:
    from name_ru import ru_name
    print(ru_name('Novak Djokovic'))  # → Новак Джокович
    print(ru_name('FC Barcelona'))    # → Барселона
"""

import re
import sys

sys.path.insert(0, '/opt')

# ─── Собираем словари из всех модулей ──────────────────────────────

_RU_NAMES = {}

# Теннис
try:
    from tennis_names import TENNIS_RU
    _RU_NAMES.update(TENNIS_RU)
except Exception:
    pass

# Футбол
try:
    from upcoming import TEAMS_RU as FOOTBALL_RU
    _RU_NAMES.update(FOOTBALL_RU)
    try:
        from upcoming import TEAMS_RU_EXTRA
        _RU_NAMES.update(TEAMS_RU_EXTRA)
    except Exception:
        pass
except Exception:
    pass

# Хоккей
try:
    from nhl_api import NHL_TEAMS_RU
    _RU_NAMES.update(NHL_TEAMS_RU)
except Exception:
    pass

# Баскетбол
try:
    from balldontlie_api import NBA_TEAMS_RU
    _RU_NAMES.update(NBA_TEAMS_RU)
except Exception:
    pass


# ─── Проверка кириллицы ────────────────────────────────────────────

def _has_cyrillic(s):
    """Проверить, содержит ли строка кириллические символы."""
    if not s:
        return False
    return bool(re.search(r'[а-яёА-ЯЁ]', s))


# ─── Обратный словарь (русское → английское) ────────────────────
_RU_TO_EN = {v: k for k, v in _RU_NAMES.items()}
# Также индексируем по фамилии (последнее слово)
_SURNAME_RU = {}  # английская фамилия → русская фамилия
for eng, rus in _RU_NAMES.items():
    eng_parts = eng.split()
    rus_parts = rus.split()
    if len(eng_parts) == len(rus_parts) and len(eng_parts) >= 2:
        eng_surname = eng_parts[-1].lower()
        rus_surname = rus_parts[-1]
        _SURNAME_RU[eng_surname] = rus_surname

# ─── Хвостовая транслитерация (окончания имён) ────────────────
_ENDPAT_RU = [
    # Английские мужские окончания
    ('son', 'сон'),  # Jackson → Джексон
    ('ton', 'тон'),  # Walton → Уолтон
    ('man', 'ман'),  # Coleman → Коулман
    ('ster', 'стер'),
    ('ard', 'ард'),
    ('ard', 'ард'),
    ('ley', 'ли'),
    # Русские фамилии в английской записи
    ('ov', 'ов'),
    ('ev', 'ев'),
    ('in', 'ин'),
    ('iy', 'ий'),
    ('sky', 'ский'),
    ('enko', 'енко'),
    # Французские
    ('ier', 'ье'),
    ('oux', 'у'),
    ('ais', 'э'),
    ('ois', 'уа'),
    ('eau', 'о'),
    ('and', 'ан'),
    ('ent', 'ан'),
    # Итальянские/испанские
    ('ini', 'ини'),
    ('ino', 'ино'),
    ('elli', 'елли'),
    ('ez', 'ес'),
]

# Таблица односимвольной транслитерации
_TRANS_SINGLE = {
    'a': 'а', 'b': 'б', 'c': 'к', 'd': 'д', 'e': 'е',
    'f': 'ф', 'g': 'г', 'h': 'х', 'i': 'и', 'j': 'ж',
    'k': 'к', 'l': 'л', 'm': 'м', 'n': 'н', 'o': 'о',
    'p': 'п', 'q': 'к', 'r': 'р', 's': 'с', 't': 'т',
    'u': 'у', 'v': 'в', 'w': 'у', 'x': 'кс', 'y': 'и', 'z': 'з',
}
_TRANS_CAPS = {k.upper(): v.upper() if len(v) == 1 else v[0].upper() + v[1:] for k, v in _TRANS_SINGLE.items()}
_TRANS_ALL = {**_TRANS_SINGLE, **_TRANS_CAPS}


def _transliterate_word(word):
    """Транслитерировать одно слово."""
    if not word or len(word) < 2:
        return word
    result = word
    # Многосимвольные правила
    for eng, rus in _MULTI_RULES:
        result = result.replace(eng, rus)
    # Односимвольные
    for eng, rus in _TRANS_ALL.items():
        result = result.replace(eng, rus)
    # Убираем тройные повторы
    result = re.sub(r'([а-яё])\1{2,}', r'\1\1', result)
    return result


def _transliterate(name):
    """EN→RU транслитерация имён, которых нет в словаре."""
    if not name or len(name) < 2:
        return name

    parts = name.split()
    translated_parts = []

    for word in parts:
        # Если слово уже на кириллице — оставляем
        if _has_cyrillic(word):
            translated_parts.append(word)
            continue

        result = word

        # 🔥 Специфичные правила для теннисных имён
        # Французский: ch → ш (Chardy → Шарди, Vacherot → Вашеро)
        result = re.sub(r'ch', 'ш', result, flags=re.I)
        # sch → ш для немецких (Schwartzman → Шварцман)
        result = re.sub(r'sch', 'ш', result, flags=re.I)
        # ph → ф
        result = re.sub(r'ph', 'ф', result, flags=re.I)
        # th → т 
        result = re.sub(r'th', 'т', result, flags=re.I)
        # sh → ш (уже могло быть через ch→ш, проверяем чётко s+h)
        result = re.sub(r'(?<!c)sh', 'ш', result, flags=re.I)
        # zh → ж
        result = re.sub(r'zh', 'ж', result, flags=re.I)
        # kh → х
        result = re.sub(r'kh', 'х', result, flags=re.I)
        # ts → ц
        result = re.sub(r'ts', 'ц', result, flags=re.I)
        # qu → к
        result = re.sub(r'qu', 'ку', result, flags=re.I)

        # Итальянский: c перед e/i → ч (Cilich → Чилич, Cinà → Чина)
        result = re.sub(r'c([ei])', r'ч\1', result, flags=re.I)
        # gn → нь
        result = re.sub(r'gn', 'нь', result, flags=re.I)
        # gli → льи
        result = re.sub(r'gli', 'льи', result, flags=re.I)

        # Французские носовые
        result = re.sub(r'ain\b', 'ен', result, flags=re.I)
        result = re.sub(r'ein\b', 'ен', result, flags=re.I)
        result = re.sub(r'oin\b', 'уан', result, flags=re.I)

        # ou → у
        result = re.sub(r'ou', 'у', result, flags=re.I)
        # oo → у
        result = re.sub(r'oo', 'у', result, flags=re.I)
        # oi → уа (французский)
        result = re.sub(r'oi', 'уа', result, flags=re.I)
        # au → ау
        result = re.sub(r'au', 'ау', result, flags=re.I)
        # ei → эй
        result = re.sub(r'ei', 'эй', result, flags=re.I)
        # eu → э
        result = re.sub(r'eu', 'э', result, flags=re.I)
        # ea → и
        result = re.sub(r'ea', 'иа', result, flags=re.I)

        # y в конце слова → й (после гласной) или ый (после согласной)
        if result.endswith('y'):
            if len(result) > 2 and result[-2].lower() in 'aeiou':
                result = result[:-1] + 'й'
            else:
                result = result[:-1] + 'и'
        # y в начале слова → й
        if result.startswith('Y') and len(result) > 1:
            result = 'Й' + result[1:]
        elif result.startswith('y') and len(result) > 1:
            result = 'й' + result[1:]

        # ck → к
        result = re.sub(r'ck', 'к', result, flags=re.I)

        # Односимвольная транслитерация (оставшиеся буквы)
        for eng, rus in {**_TRANS_SINGLE, **{k.upper(): v.upper() if len(v) == 1 else v[0].upper() + v[1:] for k, v in _TRANS_SINGLE.items()}}.items():
            result = result.replace(eng, rus)

        # Убираем тройные повторы
        result = re.sub(r'([а-яё])\1{2,}', r'\1\1', result)

        # Капитализация: первая буква заглавная
        if result:
            result = result[0].upper() + result[1:]

        translated_parts.append(result)

    return ' '.join(translated_parts)


# ═══════════════════ Единая функция перевода ═══════════════════════

def ru_name(name):
    """
    Основная функция: переводит английское название на русский.
    
    Порядок:
    1. Если имя уже на кириллице — возвращаем как есть
    2. Точное совпадение в словаре
    3. Частичное совпадение (fuzzy) — для команд
    4. Транслитерация — для теннисистов и неизвестных имён
    """
    if not name:
        return name

    stripped = name.strip()
    if not stripped:
        return name

    # 1. Уже кириллица
    if _has_cyrillic(stripped):
        return stripped

    # 2. Точное совпадение
    if stripped in _RU_NAMES:
        return _RU_NAMES[stripped]

    # 3. Частичное совпадение (fuzzy) как в командах
    #    Ищем: полное совпадение по фамилии (последнему слову)
    name_lower = stripped.lower()
    name_parts = stripped.split()
    name_last = name_lower.split()[-1] if name_parts else ''
    
    # Сначала точное совпадение по фамилии
    if len(name_parts) >= 2 and len(name_last) >= 4:
        for eng, rus in _RU_NAMES.items():
            eng_parts = eng.split()
            eng_last = eng_parts[-1].lower() if eng_parts else ''
            if eng_last == name_last:
                rus_parts = rus.split()
                if len(rus_parts) == len(name_parts):
                    return rus
                if len(rus_parts) > 1:
                    translated = ' '.join(name_parts[:-1]) + ' ' + rus_parts[-1]
                    return translated
                return rus_parts[-1]
    
    # Затем вхождение фамилии в ключ или ключа в фамилию (мин 5 символов)
    if len(name_last) >= 5:
        for eng, rus in _RU_NAMES.items():
            eng_parts = eng.split()
            eng_last = eng_parts[-1].lower() if eng_parts else ''
            if len(eng_last) >= 5:
                if eng_last in name_last or name_last in eng_last:
                    rus_parts = rus.split()
                    return rus_parts[-1] if rus_parts else rus

    # 4. Транслитерация
    return _transliterate(stripped)


if __name__ == '__main__':
    # Тесты
    tests = [
        ('Novak Djokovic', 'Новак Джокович'),
        ('Carlos Alcaraz', 'Карлос Алькарас'),
        ('Federico Cinà', 'Федерико Чина'),
        ('Jesper De Jong', 'Йеспер Де Йонг'),
        ('Arthur Rinderknech', 'Артур Риндеркнеш'),
        ('Valentin Vacherot', 'Валентин Вашеро'),
        ('FC Barcelona', 'Барселона'),
        ('Manchester United', 'Манчестер Юнайтед'),
        ('Anaheim Ducks', 'Анахайм Дакс'),
        ('Boston Celtics', 'Бостон Селтикс'),
        ('Новак Джокович', 'Новак Джокович'),  # уже русское
        ('Karen Khachanov', 'Карен Хачанов'),
        ('Andrey Rublev', 'Андрей Рублёв'),
        ('Adam Walton', 'Адам Уолтон'),
        ('Quentin Halys', 'Квентин Алис'),
        ('Thanasi Kokkinakis', 'Танаси Кокинакис'),
        ('Moise Kouame', 'Моиз Куаме'),
    ]
    for name, expected in tests:
        result = ru_name(name)
        status = '✅' if result == expected else '⚠️'
        print(f'{status} {name:35s} → {result:25s} (expected: {expected})')
