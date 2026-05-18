"""
Тест целостности сгенерированного index.html.

Проверяет структуру страницы, наличие всех разделов,
корректность дат и работоспособность JS-данных.
"""

import os, sys, json, pytest, re

sys.path.insert(0, '/opt')


SITE_PATH = '/var/www/sport/index.html'
NEWS_JSON_PATH = '/var/www/sport/news_data.json'


class TestSiteIntegrity:
    """Проверка index.html."""

    def _read_site(self):
        if not os.path.exists(SITE_PATH):
            pytest.skip(f"{SITE_PATH} не найден — тест пропущен")
        with open(SITE_PATH, encoding='utf-8') as f:
            return f.read()

    def test_site_exists(self):
        """Страница существует и не пуста."""
        assert os.path.exists(SITE_PATH), f"{SITE_PATH} не существует"
        size = os.path.getsize(SITE_PATH)
        assert size > 100_000, f"Страница слишком мала: {size} байт"

    def test_section_titles_present(self):
        """Все основные разделы присутствуют на странице."""
        html = self._read_site()

        sections = [
            'Последние новости',
            'Результаты',
            'Завтра',
        ]
        for s in sections:
            assert s in html, f"Раздел '{s}' не найден на странице"

    def test_tomorrow_date_in_header(self):
        """Заголовок 'События завтра' содержит дату."""
        html = self._read_site()
        match = re.search(r'Завтра — (\d{2}\.\d{2}\.\d{4})', html)
        assert match, "Не найден заголовок 'Завтра' с датой"

        from datetime import datetime, timedelta, timezone
        msk = timezone(timedelta(hours=3))
        date_str = match.group(1)
        parsed = datetime.strptime(date_str, '%d.%m.%Y')
        parsed_msk = parsed.replace(tzinfo=msk)
        now_msk = datetime.now(msk).replace(hour=0, minute=0, second=0, microsecond=0)

        diff = (parsed_msk - now_msk).days
        assert 0 <= diff <= 1, (
            f"Дата матчей '{date_str}' не сегодня/завтра "
            f"(разница {diff} дней)"
        )

    def test_news_data_json_exists(self):
        """news_data.json существует и содержит новости."""
        assert os.path.exists(NEWS_JSON_PATH), (
            f"{NEWS_JSON_PATH} не найден"
        )
        with open(NEWS_JSON_PATH, encoding='utf-8') as f:
            data = json.load(f)
        assert isinstance(data, list), "news_data.json должен быть списком"
        assert len(data) > 0, "news_data.json пуст"

        # Проверяем структуру новости
        news = data[0]
        for field in ('title', 'desc', 'link', 'source', 'time', 'ts'):
            assert field in news, f"Новость не содержит поле '{field}'"

    def test_predict_buttons_present(self):
        """На странице есть кнопки 'Прогноз' (активные или неактивные)."""
        html = self._read_site()
        predict_count = html.count('up-v1-predict-btn')
        assert predict_count > 0, "Нет кнопок 'Прогноз' на странице"

    def test_live_badge_or_no_predict(self):
        """На странице есть live-бейджи или неактивные кнопки прогнозов."""
        html = self._read_site()
        # Сегодняшние матчи показывают live/score или disabled predict
        has_live_badge = html.count('up-v1-live-badge') > 0
        has_disabled_predict = html.count('up-v1-predict-off') > 0
        has_score = html.count('up-v1-score') > 0
        assert has_live_badge or has_disabled_predict or has_score, \
            "На странице нет live-статусов или заблокированных кнопок прогнозов"

    def test_team_logos_loaded(self):
        """Логотипы команд загружаются (файлы в static/logos/)."""
        logo_dir = '/var/www/sport/static/logos'
        assert os.path.isdir(logo_dir), f"{logo_dir} не существует"
        logos = [f for f in os.listdir(logo_dir) if f.endswith('.png')]
        assert len(logos) > 50, (
            f"Мало логотипов: {len(logos)} (ожидается >50)"
        )

    def test_html_no_broken_images(self):
        """Нет битых ссылок на логотипы (проверка путей)."""
        html = self._read_site()
        # Все src="/static/... должны вести на существующие файлы
        img_srcs = re.findall(r'src="(/static/[^"]+)"', html)
        for src in img_srcs:
            full_path = f'/var/www/sport{src}'
            assert os.path.exists(full_path), (
                f"Изображение не найдено: {full_path}"
            )

    # ─── Stats Modal ───────────────────────────────────────────────────

    def test_stats_modal_exists(self):
        """Модалка статистики присутствует в HTML."""
        html = self._read_site()
        assert 'id="stats-modal"' in html, 'stats-modal не найден'
        assert 'id="stats-body"' in html, 'stats-body (таблица) не найден'
        assert 'id="stats-home-team"' in html, 'stats-home-team не найден'
        assert 'id="stats-away-team"' in html, 'stats-away-team не найден'
        assert 'id="stats-score"' in html, 'stats-score не найден'

    def test_stats_modal_js_functions(self):
        """JS-функции для статистики присутствуют."""
        html = self._read_site()
        assert 'function openStats(matchKey)' in html, 'openStats не найдена'
        assert 'function closeStats()' in html, 'closeStats не найдена'
        assert 'function percentRow(homeVal' in html, 'percentRow не найдена'
        assert 'STAT_NAMES' in html, 'STAT_NAMES не найден'
        assert 'PCT_STATS' in html, 'PCT_STATS не найден'

    def test_live_cards_have_click_handler(self):
        """Live-карточки (если есть) имеют data-match-key и onclick."""
        html = self._read_site()
        match_keys = re.findall(r'data-match-key="([^"]+)"', html)
        if not match_keys:
            pytest.skip('Нет live-матчей в данный момент — тест пропущен')

        onclick_count = html.count(
            'onclick="openStats(this.dataset.matchKey)"'
        )
        assert onclick_count > 0, 'Нет onclick="openStats..." на карточках'
        assert onclick_count == len(match_keys), (
            'Не совпадает число data-match-key ({}) и onclick ({})'.format(
                len(match_keys), onclick_count
            )
        )

    def test_live_scores_json_served(self):
        """live_scores.json доступен из web-root."""
        path = '/var/www/sport/live_scores.json'
        assert os.path.exists(path), '{} не найден'.format(path)
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        assert 'matches' in data, 'live_scores.json не содержит matches'
        assert 'updated_at' in data, 'live_scores.json не содержит updated_at'
        assert len(data['matches']) > 0, 'live_scores.json пуст'

    def test_stats_modal_overlay_close(self):
        """Overlay модалки статистики закрывается по клику."""
        html = self._read_site()
        assert "getElementById('stats-modal')" in html, (
            'Нет addEventListener на stats-modal'
        )
