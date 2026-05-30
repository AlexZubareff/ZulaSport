#!/usr/bin/env python3
"""
Генератор страницы новостей.
"""

import os, sys, json
from datetime import datetime, timezone, timedelta

sys.path.insert(0, '/opt')
import site_common
from generate_site_legacy import fetch_news, escape

MOW = timedelta(hours=3)
UTC = timezone.utc


def generate_news(output_path='/var/www/sport/news.html'):
    now = datetime.now(UTC) + MOW
    now_str = now.strftime('%d.%m.%Y %H:%M')

    # Загружаем кеш контента
    try:
        from generate_site_legacy import _load_content_cache
        content_cache = _load_content_cache()
    except:
        content_cache = None

    news = fetch_news(content_cache)

    # Добавляем статью Zula Sport в начало
    try:
        import json as _json
        from datetime import datetime as _dt, timezone as _tz, timedelta as _td
        _MOW = _td(hours=3)
        _now = _dt.now(_tz.utc) + _MOW
        
        with open('/var/www/sport/docs/articles/premier-league.txt', 'r') as _f:
            _text = _f.read()
        
        _news_item = {
            'source': 'Zula Sport',
            'title': 'Итоги сезона. Англия',
            'time': f'{_now.strftime("%H:%M")} МСК',
            'desc': '«Арсенал» на троне: 22 года боли — и вот оно, золото. Канониры Артеты вернули титул.',
            'link': 'https://zulasport.ru/docs/articles/premier-league.html',
            'image': '/docs/articles/premier-league-card.png',
            'content_ru': _text,
            'content': '',
        'ts': _now.timestamp(),
        }
        news.insert(0, _news_item)
    except Exception as _e:
        print(f'  ⚠️ статья Zula: {_e}')


    # Сохраняем JSON для модалки
    news_json_path = '/var/www/sport/news_data.json'
    news_clean = []
    for n in news:
        news_clean.append({
            'title': n['title'],
            'desc': n['desc'],
            'desc_full': n.get('desc_full', ''),
            'link': n['link'],
            'source': n['source'],
            'image': n.get('image', ''),
            'time': n['time'],
            'ts': n['ts'],
            'content': n.get('content', ''),
            'content_ru': n.get('content_ru', ''),
        })
    try:
        with open(news_json_path, 'w', encoding='utf-8') as f:
            json.dump(news_clean, f, ensure_ascii=False)
    except Exception as e:
        print(f'⚠️ Не удалось сохранить news_data.json: {e}')

    news_json_escaped = json.dumps(news_clean, ensure_ascii=False)

    # HTML новостей (первые 15)
    news_html = ''
    for i, n in enumerate(news[:15]):
        img_src = n.get('image')
        news_html += f'''
        <div class="news-card" data-news-idx="{i}" onclick="openArticle({i})">
            <div class="news-row">'''
        if img_src:
            news_html += f'''
                <div class="news-img"><img src="{escape(img_src)}" alt="" loading="lazy" onerror="this.closest('.news-row').classList.add('no-img');this.remove()"></div>'''
        news_html += f'''
                <div class="news-body">
                    <div class="news-meta">
                        <span class="news-source">{escape(n['source'])}</span>
                        <span class="news-time">{escape(n['time'])}</span>
                    </div>
                    <div class="news-title">{escape(n['title'])}</div>
                    <div class="news-desc">{escape(n['desc'])}</div>
                </div>
            </div>
        </div>'''

    more_news_count = len(news) - 15
    if more_news_count > 0:
        news_html += f'''
        <div id="news-more-container"></div>
        <button id="news-more-btn" class="more-btn" onclick="loadMoreNews()">Показать ещё</button>'''

    # Собираем страницу
    html = site_common.page_header('Новости', 'news', now_str)
    html += f'''
    <div class="section-title">📰 Последние новости</div>
    {news_html}'''

    if more_news_count > 0:
        html += f'''
    <script>
    function loadMoreNews() {{
        var btn = document.getElementById('news-more-btn');
        var container = document.getElementById('news-more-container');
        var start = document.querySelectorAll('.news-card').length;
        var batch = ARTICLE_DATA.slice(start, start + 15);
        if (batch.length === 0) {{ btn.style.display = 'none'; return; }}
        for (var i = 0; i < batch.length; i++) {{
            var a = batch[i];
            var card = document.createElement('div');
            card.className = 'news-card';
            card.setAttribute('data-news-idx', start + i);
            card.onclick = function() {{ openArticle(parseInt(this.getAttribute('data-news-idx'))); }};
            var row = document.createElement('div');
            row.className = 'news-row';
            if (a.image) {{
                var imgDiv = document.createElement('div');
                imgDiv.className = 'news-img';
                imgDiv.innerHTML = '<img src="' + escapeHtml(a.image) + '" alt="" loading="lazy" onerror="this.closest(\'.news-row\').classList.add(\'no-img\');this.remove()">';
                row.appendChild(imgDiv);
            }}
            var body = document.createElement('div');
            body.className = 'news-body';
            body.innerHTML = '<div class="news-meta"><span class="news-source">' + escapeHtml(a.source) + '</span><span class="news-time">' + escapeHtml(a.time) + '</span></div><div class="news-title">' + escapeHtml(a.title) + '</div><div class="news-desc">' + escapeHtml(a.desc) + '</div>';
            row.appendChild(body);
            card.appendChild(row);
            container.appendChild(card);
        }}
        if (start + batch.length >= ARTICLE_DATA.length) btn.style.display = 'none';
    }}
    </script>'''

    html += site_common.page_footer()
    html = html.replace(
        'JS_PLACEHOLDER',
        site_common.page_script(news_json_escaped, '{}')
    )

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f'✅ Новости ({len(news)} шт): {output_path}')
    return len(news)


if __name__ == '__main__':
    generate_news()
