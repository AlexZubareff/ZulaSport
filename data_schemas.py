#!/usr/bin/env python3
"""
Схемы для валидации JSON-файлов пайплайна Zula Sport.

Использование:
    from data_schemas import validate
    ok, errors = validate(data, 'predictions_data')
    if not ok:
        print('Ошибки:', errors)
"""


SCHEMAS = {
    'predictions_data': {
        'type': 'object',
        'required': ['predictions'],
        'properties': {
            'predictions': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'required': ['league', 'home', 'away', 'prediction'],
                    'properties': {
                        'league': {'type': 'string'},
                        'home': {'type': 'string'},
                        'away': {'type': 'string'},
                        'prediction': {'type': 'string'},
                        'verdict': {'type': 'string'},
                        'time': {'type': 'string'},
                        'game_id': {'type': ['integer', 'string']},
                        'status': {'type': 'string', 'enum': ['upcoming', 'finished', None]},
                        'odds': {'type': 'object'},
                        'totals': {'type': 'object'},
                        'glicko': {'type': ['object', 'null']},
                        'xgb_verdict': {'type': ['object', 'null']},
                        'generated_at': {'type': 'string'},
                    },
                },
            },
            'count': {'type': 'integer'},
            'generated_at': {'type': 'string'},
        },
    },
    'tv_channels_data': {
        'type': 'object',
        'required': ['matches_by_date'],
        'properties': {
            'matches_by_date': {
                'type': 'object',
                'pattern_properties': {
                    r'^\d{8}$': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'required': ['league', 'home', 'away'],
                            'properties': {
                                'league': {'type': 'string'},
                                'home': {'type': 'string'},
                                'away': {'type': 'string'},
                                'time': {'type': 'string'},
                                'game_id': {'type': ['integer', 'string']},
                                'sport': {'type': 'string'},
                            },
                        },
                    },
                },
            },
            'updated_at': {'type': 'string'},
        },
    },
    'live_scores': {
        'type': 'object',
        'required': ['matches'],
        'properties': {
            'matches': {
                'type': 'object',
                'pattern_properties': {
                    r'^.+\|\|.+\|\|.+$': {
                        'type': 'object',
                        'required': ['status'],
                        'properties': {
                            'status': {'type': 'string', 'enum': ['live', 'upcoming', 'finished']},
                            'score': {'type': ['string', 'null']},
                            'match_time': {'type': 'string'},
                            'sport': {'type': 'string'},
                        },
                    },
                },
            },
        },
    },
    'predictions_history': {
        'type': 'object',
        'required': ['predictions', 'summary'],
        'properties': {
            'predictions': {'type': 'array'},
            'summary': {
                'type': 'object',
                'required': ['total_predictions', 'finished', 'win', 'total'],
            },
            'last_updated': {'type': 'string'},
        },
    },
}


def _validate_recursive(data, schema, errors, path=''):
    """Рекурсивная проверка data по схеме."""
    # Проверка типа
    expected_types = schema.get('type', [])
    if isinstance(expected_types, str):
        expected_types = [expected_types]

    # None/null — допустим только если в списке типов есть None
    if data is None:
        if None in expected_types or 'null' in expected_types:
            return
        errors.append(f'{path}: ожидается {expected_types}, получен None')
        return

    type_map = {
        'object': dict,
        'array': list,
        'string': str,
        'integer': int,
        'number': (int, float),
        'boolean': bool,
    }

    # Проверка, что тип данных соответствует схеме
    type_ok = False
    for et in expected_types:
        if et == 'null':
            continue  # уже проверили выше
        py_type = type_map.get(et)
        if py_type and isinstance(data, py_type):
            type_ok = True
            break
        elif et == 'integer' and isinstance(data, bool):
            continue  # bool is subclass of int, not wanted here

    if not type_ok and expected_types:
        err_type_names = [t for t in expected_types if t != 'null']
        if err_type_names:
            errors.append(f'{path}: ожидается тип {err_type_names}, получен {type(data).__name__}')
            return

    # Enum
    enum_vals = schema.get('enum')
    if enum_vals is not None:
        if data not in enum_vals:
            errors.append(f'{path}: значение {data!r} не из допустимых {enum_vals}')
            return

    # Object — проверка свойств
    if isinstance(data, dict):
        required = schema.get('required', [])
        for field in required:
            if field not in data:
                errors.append(f'{path}.{field}: обязательное поле отсутствует')

        properties = schema.get('properties', {})
        for key, value in data.items():
            if key in properties:
                _validate_recursive(value, properties[key], errors, f'{path}.{key}')
            else:
                # Паттерн-свойства
                pattern_properties = schema.get('pattern_properties', {})
                matched = False
                for pattern, subschema in pattern_properties.items():
                    import re
                    if re.match(pattern, str(key)):
                        _validate_recursive(value, subschema, errors, f'{path}."{key}"')
                        matched = True
                        break
                if not matched and not schema.get('additionalProperties', True):
                    errors.append(f'{path}: неожиданное поле {key!r}')

    # Array — проверка элементов
    elif isinstance(data, list):
        items_schema = schema.get('items', {})
        if items_schema:
            for i, item in enumerate(data):
                _validate_recursive(item, items_schema, errors, f'{path}[{i}]')

        # Проверка minItems / maxItems
        min_items = schema.get('minItems')
        if min_items is not None and len(data) < min_items:
            errors.append(f'{path}: минимум {min_items} элементов, получено {len(data)}')
        max_items = schema.get('maxItems')
        if max_items is not None and len(data) > max_items:
            errors.append(f'{path}: максимум {max_items} элементов, получено {len(data)}')


def validate(data, schema_name) -> tuple:
    """
    Проверяет data по схеме schema_name.
    Возвращает (ok: bool, errors: list[str]).
    """
    schema = SCHEMAS.get(schema_name)
    if not schema:
        return False, [f'Неизвестная схема: {schema_name}']

    errors = []
    _validate_recursive(data, schema, errors, '')
    return len(errors) == 0, errors


# ─── Тесты ──────────────────────────────────────────────────────────

if __name__ == '__main__':
    # Тест 1: корректные данные predictions_data
    ok, errors = validate({
        'predictions': [
            {
                'league': 'АПЛ',
                'home': 'Team A',
                'away': 'Team B',
                'prediction': 'Победа Team A',
                'generated_at': '2026-05-20T12:00:00',
            },
        ],
        'count': 1,
        'generated_at': '2026-05-20T12:00:00',
    }, 'predictions_data')
    assert ok, f'Ожидался ok, получено: {errors}'
    print('✅ predictions_data: корректные данные — OK')

    # Тест 2: отсутствует обязательное поле
    ok, errors = validate({
        'predictions': [{'league': 'АПЛ', 'home': 'Team A'}],
    }, 'predictions_data')
    assert not ok, 'Ожидалась ошибка'
    print(f'✅ predictions_data: отсутствует поле — OK ({errors[0]})')

    # Тест 3: пустой объект
    ok, errors = validate({'matches_by_date': {}}, 'tv_channels_data')
    assert ok, f'Ожидался ok, получено: {errors}'
    print('✅ tv_channels_data: пустой — OK')

    # Тест 4: live_scores с матчами
    ok, errors = validate({
        'matches': {
            'АПЛ||Team A||Team B': {
                'status': 'live',
                'score': '2:1',
                'match_time': '20:00',
                'sport': 'football',
            },
        },
    }, 'live_scores')
    assert ok, f'Ожидался ok, получено: {errors}'
    print('✅ live_scores: корректные данные — OK')

    # Тест 5: невалидный статус
    ok, errors = validate({
        'matches': {
            'АПЛ||A||B': {
                'status': 'invalid_status',
                'match_time': '',
                'sport': '',
            },
        },
    }, 'live_scores')
    assert not ok, 'Ожидалась ошибка'
    print(f'✅ live_scores: невалидный статус — OK ({errors[0]})')

    print('\n🎉 Все тесты data_schemas пройдены')
