"""Bounded, per-screen presentation preferences; never a data-access policy."""
import json

CARDS = ('calendar', 'finance', 'tasks', 'shopping', 'trips')
THEMES = ('forest', 'light', 'ocean')
DENSITIES = ('comfortable', 'compact')


def default_layout():
    return {'order': list(CARDS), 'hidden': [], 'theme': 'forest', 'density': 'comfortable'}


def validate_layout(value, Problem):
    if not isinstance(value, dict) or set(value) != {'order', 'hidden', 'theme', 'density'}:
        raise Problem('请提供完整的电视卡片顺序、显示选择、主题和密度')
    order, hidden = value['order'], value['hidden']
    if (not isinstance(order, list) or len(order) != len(CARDS)
            or any(not isinstance(key, str) or key not in CARDS for key in order)
            or len(set(order)) != len(CARDS)):
        raise Problem('电视卡片顺序须包含每张支持的卡片，且不能重复')
    if (not isinstance(hidden, list) or len(hidden) >= len(CARDS)
            or any(not isinstance(key, str) or key not in CARDS for key in hidden)
            or len(set(hidden)) != len(hidden)):
        raise Problem('请选择有效的隐藏卡片，并至少保留一张可见卡片')
    if not isinstance(value['theme'], str) or value['theme'] not in THEMES:
        raise Problem('请选择支持的电视主题')
    if not isinstance(value['density'], str) or value['density'] not in DENSITIES:
        raise Problem('请选择支持的电视显示密度')
    return {'order': list(order), 'hidden': [key for key in order if key in hidden],
            'theme': value['theme'], 'density': value['density']}


def stored_layout(raw):
    """Legacy/invalid stored presentation falls back without changing the row."""
    try:
        value = json.loads(raw)
        return validate_layout(value, ValueError)
    except (ValueError, TypeError):
        return default_layout()
