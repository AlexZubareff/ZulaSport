#!/usr/bin/env python3
"""Мини API для дашборда - отдаёт статистику из БД в JSON."""
import json, sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone, timedelta

MOW = timedelta(hours=3)

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != '/api/stats.json':
            self.send_response(404)
            self.end_headers()
            return
        
        try:
            import db
            total = db.execute("SELECT COUNT(*) AS c FROM predictions")[0]['c']
            by_status = {r['status']: r['c'] for r in db.execute("SELECT status, COUNT(*) AS c FROM predictions GROUP BY status")}

            tennis = {
                'by_league': [dict(r) for r in db.execute("""
                    SELECT league, COUNT(*) AS total,
                        SUM(CASE WHEN result_win IS NOT NULL THEN 1 ELSE 0 END) AS evaluated,
                        SUM(CASE WHEN result_win = 'correct' THEN 1 ELSE 0 END) AS win_correct,
                        SUM(CASE WHEN result_total = 'correct' THEN 1 ELSE 0 END) AS total_correct
                    FROM predictions WHERE league IN ('ATP','WTA')
                    GROUP BY league ORDER BY league
                """)],
                'total': 0,
            }
            tennis['total'] = sum(r['total'] for r in tennis['by_league'])
            by_league = {r['league']: r['c'] for r in db.execute("SELECT league, COUNT(*) AS c FROM predictions GROUP BY league ORDER BY c DESC")}
            evaluated = db.execute("SELECT COUNT(*) AS c FROM predictions WHERE result_win IS NOT NULL")[0]['c']
            correct_win = db.execute("SELECT COUNT(*) AS c FROM predictions WHERE result_win = 'correct'")[0]['c']
            correct_total = db.execute("SELECT COUNT(*) AS c FROM predictions WHERE result_total = 'correct'")[0]['c']
            
            # Ежедневная статистика
            daily = db.execute("""
                SELECT match_date, COUNT(*) AS total,
                    SUM(CASE WHEN result_win = 'correct' OR result_total = 'correct' THEN 1 ELSE 0 END) AS correct
                FROM predictions GROUP BY match_date ORDER BY match_date
            """)
            
            correct_overall = db.execute("SELECT COUNT(*) AS c FROM predictions WHERE result_win = 'correct' OR result_total = 'correct'")[0]['c']
            total_evaluated = db.execute("SELECT COUNT(*) AS c FROM predictions WHERE result_win IS NOT NULL OR result_total IS NOT NULL")[0]['c']

            # a) Точность по лигам
            accuracy_by_league = db.execute("""
                SELECT league, 
                       COUNT(*) AS total,
                       SUM(CASE WHEN result_win IS NOT NULL THEN 1 ELSE 0 END) AS evaluated,
                       SUM(CASE WHEN result_win = 'correct' THEN 1 ELSE 0 END) AS win_correct,
                       SUM(CASE WHEN odds_over IS NOT NULL THEN 1 ELSE 0 END) AS with_totals,
                       SUM(CASE WHEN result_total = 'correct' THEN 1 ELSE 0 END) AS total_correct
                FROM predictions 
                WHERE result_win IS NOT NULL OR result_total IS NOT NULL
                GROUP BY league ORDER BY total DESC
            """)

            # b) Типы ставок П1/X/П2
            win_types = db.execute("""
                SELECT 
                    league,
                    CASE xgb_win_pred
                        WHEN 'home' THEN 'П1'
                        WHEN 'draw' THEN 'X'
                        WHEN 'away' THEN 'П2'
                    END AS bet_type,
                    COUNT(*) AS total,
                    SUM(CASE WHEN result_win = 'correct' THEN 1 ELSE 0 END) AS correct
                FROM predictions
                WHERE result_win IS NOT NULL AND xgb_win_pred IS NOT NULL
                GROUP BY league, bet_type
            """)

            # b) Типы ставок Over/Under
            total_types = db.execute("""
                SELECT league, 
                    CASE xgb_total_pred
                        WHEN 'over' THEN 'Over'
                        WHEN 'under' THEN 'Under'
                    END AS bet_type,
                    COUNT(*) AS total,
                    SUM(CASE WHEN result_total = 'correct' THEN 1 ELSE 0 END) AS correct
                FROM predictions
                WHERE result_total IS NOT NULL AND xgb_total_pred IS NOT NULL
                GROUP BY league, bet_type
            """)

            # c) Ежедневные данные для тренда (весь массив для расчёта МА на фронте)
            daily_accuracy = db.execute("""
                SELECT match_date,
                       COUNT(*) AS total,
                       SUM(CASE WHEN result_win = 'correct' OR result_total = 'correct' THEN 1 ELSE 0 END) AS correct
                FROM predictions 
                WHERE result_win IS NOT NULL OR result_total IS NOT NULL
                GROUP BY match_date ORDER BY match_date
            """)

            # d) Последние 10 оценённых прогнозов
            recent_evaluated = db.execute("""
                SELECT league, home, away, match_date, 
                       result_win, result_total,
                       prediction_text, score
                FROM predictions 
                WHERE result_win IS NOT NULL OR result_total IS NOT NULL
                ORDER BY match_date DESC NULLS LAST, id DESC
                LIMIT 10
            """)

            # e) Точность по лигам с процентами (уже accuracy_by_league выше - дополним процентами на фронте)

            # Сводка: всего, оценено (исходы/тоталы), % правильных
            win_pct = round(correct_win / evaluated * 100, 1) if evaluated > 0 else 0
            total_pct = round(correct_total / evaluated * 100, 1) if evaluated > 0 else 0
            overall_pct = round(correct_overall / total_evaluated * 100, 1) if total_evaluated > 0 else 0

            data = {
                'total': total,
                'by_status': by_status,
                'by_league': by_league,
                'tennis': tennis,
                'evaluated': evaluated,
                'correct_win': correct_win,
                'correct_total': correct_total,
                'total_evaluated': total_evaluated,
                'correct_overall': correct_overall,
                'win_pct': win_pct,
                'total_pct': total_pct,
                'overall_pct': overall_pct,
                'daily': [{'date': str(r['match_date']), 'total': r['total'], 'correct': r['correct']} for r in daily],
                'accuracy_by_league': [
                    {
                        'league': r['league'],
                        'total': r['total'],
                        'evaluated': r['evaluated'],
                        'win_correct': r['win_correct'],
                        'with_totals': r['with_totals'],
                        'total_correct': r['total_correct'],
                        'win_pct': round(r['win_correct'] / r['evaluated'] * 100, 1) if r['evaluated'] > 0 else 0,
                        'total_pct': round(r['total_correct'] / r['with_totals'] * 100, 1) if r['with_totals'] > 0 else None
                    }
                    for r in accuracy_by_league
                ],
                'win_types': [{'league': r['league'], 'bet_type': r['bet_type'], 'total': r['total'], 'correct': r['correct']} for r in win_types],
                'total_types': [{'league': r['league'], 'bet_type': r['bet_type'], 'total': r['total'], 'correct': r['correct']} for r in total_types],
                'daily_accuracy': [
                    {
                        'date': str(r['match_date']),
                        'total': r['total'],
                        'correct': r['correct']
                    }
                    for r in daily_accuracy
                ],
                'recent_evaluated': [
                    {
                        'league': r['league'],
                        'home': r['home'],
                        'away': r['away'],
                        'date': str(r['match_date']),
                        'result_win': r['result_win'],
                        'result_total': r['result_total'],
                        'text': r['prediction_text'][:120] + '...' if r['prediction_text'] and len(r['prediction_text']) > 120 else r['prediction_text'],
                        'score': r['score']
                    }
                    for r in recent_evaluated
                ],
                'updated_at': (datetime.now(timezone.utc) + MOW).strftime('%d.%m.%Y %H:%M'),
            }
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
        except Exception as e:
            import traceback
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'error': str(e), 'traceback': traceback.format_exc()}).encode())
    
    def log_message(self, *a):
        pass

port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
HTTPServer(('127.0.0.1', port), Handler).serve_forever()
