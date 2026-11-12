# -*- coding: utf-8 -*-
"""同步豆瓣「书影音游」四星 / 五星记录到物语页。

用法：
    python scripts/fetch_douban_wuyu.py                 # 默认 UID 263906375
    python scripts/fetch_douban_wuyu.py --uid 263906375

数据来源：豆瓣用户公开的「书影音游」收藏（interests API）。
只保留状态为「看过 / 读过 / 听过 / 玩过」且本人评分 4 星或 5 星的记录。

分类规则（按优先级）：
    - 标题或简介出现 OVA / OAD → 漫剧（即使简介同时有「电影」「剧场版」也归漫剧）
    - 标题或简介出现「剧场版 / 电影 / 短片」→ 电影
    - subtype = movie 且无以上关键词 → 电影（电影大类优先，含动画电影）
    - subtype = tv，或集数 > 1 → 漫剧（动画剧集 + 真人剧集）
    - 书籍排除网文（辰东等网文作者、常见网文标题）
    - 音乐仍只收 5 星（与上一版保持一致）
    - 游戏单独成类

输出：
    data/wuyu.json
    static/wuyu/covers/*.webp

依赖：requests、lxml、Pillow。豆瓣有访问频率限制；脚本会缓存每一步，
失败后重跑会从 .cache/douban-wuyu/ 继续。
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import random
import re
import string
import time
from pathlib import Path

import lxml.html
import requests
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / 'data' / 'wuyu.json'
COVER_DIR = ROOT / 'static' / 'wuyu' / 'covers'
CACHE_DIR = ROOT / '.cache' / 'douban-wuyu'
UID = '263906375'

UA_MOBILE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
UA_DESKTOP = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36'

WEB_NOVEL_AUTHORS = {
    '辰东', '唐家三少', '天蚕土豆', '我吃西红柿', '爱潜水的乌贼', '耳根', '忘语', '猫腻',
    '烽火戏诸侯', '蝴蝶蓝', '萧鼎', '南派三叔', '天下霸唱', '梦入神机', '血红', '骷髅精灵',
    '跳舞', '月关', '烟雨江南', '愤怒的香蕉', '会说话的肘子', '卖报小郎君', '宅猪',
    '净无痕', '逆苍天', '善良的蜜蜂', '乱世狂刀', '鱼人二代', '打眼', '何常在', '骁骑校',
    '孑与2', '七月新番', '榴弹怕水', '老鹰吃小鸡', '言归正传', '错哪儿了', '黑山老鬼',
    '狐尾的笔', '风凌天下', '傲无常', '赤虎', '高楼大厦', '缘分0',
}
WEB_NOVEL_TITLES = (
    '完美世界', '遮天', '神墓', '斗破苍穹', '斗罗大陆', '凡人修仙传', '仙逆', '牧神记',
    '诡秘之主', '庆余年', '大奉打更人', '轮回乐园', '赤心巡天', '宿命之环', '道诡异仙',
    '剑来', '雪中悍刀行', '赘婿', '武动乾坤', '大主宰', '元尊', '圣墟', '深空彼岸',
    '夜无疆', '万相之王', '一世之尊', '灭运图录', '奥术神座', '长夜余火',
)

# 豆瓣有些动画电影 / OVA 的 genres 里没有「动画」，用片名与已知条目补充
MANUAL_ANIME_IDS = {
    '1307031', '27080656', '11639334', '26605865', '1764366', '26946612', '4826778',
    '1860453', '2085498', '20378834', '3217118', '1763899', '1763916', '3044673',
    '3263410', '1295064', '11026735', '3017508', '1937946',
}
ANIME_TITLE_HINTS = (
    '星际牛仔', '普罗米亚', '僵尸吗', '伪恋', '我的女神', '狐妖小红娘', '未来日记',
    '海贼王', '散华礼弥', '天元突破', '蜡笔小新', '城市猎人', '超能陆战队', '穿越时空的少女',
    '浪客剑心',
)
ANIME_TITLE_RE = re.compile(r'(OAD|OVA|剧场版|劇場版|第\d+[话話]|总集篇|特别篇|TV版|动画|动漫)', re.I)


def is_anime(title, intro, genres, subtype, sid, episodes=None):
    """OVA/OAD 优先归漫剧；剧场版/电影/短片归电影；其余按 subtype/集数。"""
    text = (title or '') + '\n' + (intro or '')
    upper = text.upper()
    if 'OVA' in upper or 'OAD' in upper:
        return True
    if any(k in text for k in ('剧场版', '劇場版', '电影', '短片')):
        return False
    if episodes not in (None, '', 0, '0'):
        try:
            return int(episodes) > 1
        except (TypeError, ValueError):
            pass
    return subtype == 'tv'


def session() -> requests.Session:
    s = requests.Session()
    s.cookies.set('bid', ''.join(random.choices(string.ascii_letters + string.digits, k=11)), domain='.douban.com')
    return s


def fetch_json(url: str, cache: Path, headers: dict, retries: int = 5):
    cache.parent.mkdir(parents=True, exist_ok=True)
    if cache.exists():
        try:
            return json.loads(cache.read_text(encoding='utf-8'))
        except Exception:
            pass
    for attempt in range(retries):
        try:
            r = session().get(url, headers=headers, timeout=30)
            if r.status_code == 200:
                d = r.json()
                cache.write_text(json.dumps(d, ensure_ascii=False), encoding='utf-8')
                time.sleep(0.3)
                return d
            time.sleep(1.5 + attempt)
        except Exception:
            time.sleep(1.5 + attempt)
    return None


def fetch_text(url: str, cache: Path, headers: dict, retries: int = 4) -> str:
    cache.parent.mkdir(parents=True, exist_ok=True)
    if cache.exists() and cache.stat().st_size > 5000:
        return cache.read_text(encoding='utf-8', errors='ignore')
    for attempt in range(retries):
        try:
            r = session().get(url, headers=headers, timeout=30)
            if r.status_code == 200 and len(r.content) > 5000:
                cache.write_bytes(r.content)
                time.sleep(0.5)
                return r.content.decode('utf-8', 'ignore')
            time.sleep(1.5 + attempt)
        except Exception:
            time.sleep(1.5 + attempt)
    return ''


def names(lst):
    out = []
    for x in lst or []:
        if isinstance(x, dict):
            n = x.get('name') or x.get('cn_name') or ''
            if n:
                out.append(n)
        elif isinstance(x, str) and x:
            out.append(x)
    return out


def year_of(s):
    m = re.search(r'(19|20)\d{2}', s or '')
    return m.group(0) if m else ''


def date_of(s):
    m = re.search(r'((?:19|20)\d{2}-\d{2}-\d{2})', s or '')
    return m.group(1) if m else ''


def hue_of(sid):
    return int(hashlib.md5(str(sid).encode()).hexdigest()[:6], 16) % 360


def fetch_interests(uid: str, kind: str):
    cache = CACHE_DIR / 'interests'
    first = fetch_json(
        f'https://m.douban.com/rexxar/api/v2/user/{uid}/interests?type={kind}&start=0&count=50',
        cache / f'{kind}_0.json',
        {'User-Agent': UA_MOBILE, 'Referer': 'https://m.douban.com/'},
    )
    if not first:
        return []
    total = first.get('total', 0)
    items = list(first.get('interests', []))
    seen = {x['subject']['id'] for x in items}
    start = len(items)
    while start < total:
        d = fetch_json(
            f'https://m.douban.com/rexxar/api/v2/user/{uid}/interests?type={kind}&start={start}&count=50',
            cache / f'{kind}_{start}.json',
            {'User-Agent': UA_MOBILE, 'Referer': 'https://m.douban.com/'},
        )
        if not d:
            break
        batch = d.get('interests', [])
        if not batch:
            break
        for x in batch:
            sid = x['subject']['id']
            if sid not in seen:
                seen.add(sid)
                items.append(x)
        start += len(batch)
    return items


def fetch_detail(kind: str, sid: str, allow_api: bool = True):
    cache = CACHE_DIR / 'details' / f'{kind}_{sid}.json'
    if cache.exists():
        try:
            return json.loads(cache.read_text(encoding='utf-8'))
        except Exception:
            pass
    if not allow_api:
        return {}
    d = fetch_json(
        f'https://m.douban.com/rexxar/api/v2/{kind}/{sid}',
        cache,
        {'User-Agent': UA_MOBILE, 'Referer': 'https://m.douban.com/'},
    )
    return d or {}


def build_rows(uid: str):
    rows = {'books': [], 'movies': [], 'anime': [], 'music': [], 'games': []}

    for it in fetch_interests(uid, 'movie'):
        if it.get('status') != 'done':
            continue
        rating = (it.get('rating') or {}).get('value')
        if rating not in (4, 5):
            continue
        s = it['subject']
        sid = str(s.get('id'))
        subtype = s.get('subtype') or ''
        genres = [x for x in (s.get('genres') or []) if isinstance(x, str)]
        kind = 'anime' if is_anime(s.get('title') or '', s.get('intro') or '', genres, subtype, sid, s.get('episodes_count')) else 'movie'
        row = {
            'id': sid, 'kind': kind, 'title': s.get('title') or '',
            'original_title': '', 'year': str(s.get('year') or year_of(s.get('card_subtitle'))),
            'cover': s.get('cover_url') or '',
            'douban_rating': (s.get('rating') or {}).get('value'),
            'douban_votes': (s.get('rating') or {}).get('count'),
            'my_rating': rating, 'intro': '', 'genres': genres,
            'url': s.get('url') or f'https://movie.douban.com/subject/{sid}/',
            'finished': date_of(it.get('create_time')), 'my_comment': it.get('comment') or '',
            'directors': names(s.get('directors')), 'actors': names(s.get('actors')),
            'countries': [], 'durations': [], 'episodes': None, 'subtype': subtype,
            'hue': hue_of(sid),
        }
        rows['anime' if kind == 'anime' else 'movies'].append(row)

    for it in fetch_interests(uid, 'book'):
        if it.get('status') != 'done':
            continue
        rating = (it.get('rating') or {}).get('value')
        if rating not in (4, 5):
            continue
        s = it['subject']
        authors = s.get('author') or []
        title = s.get('title') or ''
        if any(a in WEB_NOVEL_AUTHORS for a in authors):
            continue
        if any(title.startswith(t) for t in WEB_NOVEL_TITLES):
            continue
        sid = str(s.get('id'))
        rows['books'].append({
            'id': sid, 'kind': 'book', 'title': title,
            'original_title': s.get('book_subtitle') or '',
            'year': year_of((s.get('pubdate') or [''])[0]), 'cover': s.get('cover_url') or '',
            'douban_rating': (s.get('rating') or {}).get('value'),
            'douban_votes': (s.get('rating') or {}).get('count'),
            'my_rating': rating, 'intro': s.get('intro') or '', 'genres': [],
            'url': s.get('url') or f'https://book.douban.com/subject/{sid}/',
            'finished': date_of(it.get('create_time')), 'my_comment': it.get('comment') or '',
            'authors': authors, 'publisher': (s.get('press') or [''])[0],
            'pubdate': (s.get('pubdate') or [''])[0], 'pages': s.get('pages'),
            'translator': [], 'hue': hue_of(sid),
        })

    for it in fetch_interests(uid, 'music'):
        if it.get('status') != 'done':
            continue
        rating = (it.get('rating') or {}).get('value')
        if rating != 5:
            continue
        s = it['subject']
        sid = str(s.get('id'))
        rows['music'].append({
            'id': sid, 'kind': 'music', 'title': s.get('title') or '',
            'original_title': '', 'year': year_of((s.get('pubdate') or [''])[0]),
            'cover': s.get('cover_url') or '',
            'douban_rating': (s.get('rating') or {}).get('value'),
            'douban_votes': (s.get('rating') or {}).get('count'),
            'my_rating': rating, 'intro': '',
            'genres': [x for x in (s.get('genres') or []) if isinstance(x, str)],
            'url': s.get('url') or f'https://music.douban.com/subject/{sid}/',
            'finished': date_of(it.get('create_time')), 'my_comment': it.get('comment') or '',
            'singers': names(s.get('singer')), 'publisher': [],
            'pubdate': (s.get('pubdate') or [''])[0], 'media': '', 'hue': hue_of(sid),
        })

    for it in fetch_interests(uid, 'game'):
        if it.get('status') != 'done':
            continue
        rating = (it.get('rating') or {}).get('value')
        if rating not in (4, 5):
            continue
        s = it['subject']
        sid = str(s.get('id'))
        rows['games'].append({
            'id': sid, 'kind': 'game', 'title': s.get('title') or '',
            'original_title': '', 'year': year_of(s.get('release_date')),
            'cover': s.get('cover_url') or '',
            'douban_rating': (s.get('rating') or {}).get('value'),
            'douban_votes': (s.get('rating') or {}).get('count'),
            'my_rating': rating, 'intro': '',
            'genres': [x for x in (s.get('genres') or []) if isinstance(x, str)],
            'url': s.get('url') or f'https://www.douban.com/game/{sid}/',
            'finished': date_of(it.get('create_time')), 'my_comment': it.get('comment') or '',
            'platforms': names(s.get('platforms')), 'developers': [], 'publishers': [],
            'release_date': s.get('release_date') or '', 'hue': hue_of(sid),
        })
    return rows


def enrich(rows):
    """详情只取书籍 / 音乐 / 游戏；电影详情接口限流严重，用条目自带元数据。"""
    jobs = [row for group in rows.values() for row in group if row['kind'] in ('book', 'music', 'game')]
    print('details to fetch', len(jobs), flush=True)
    for i, row in enumerate(jobs, 1):
        d = fetch_detail(row['kind'], row['id'])
        if d:
            row['cover'] = d.get('cover_url') or row['cover']
            row['intro'] = (d.get('intro') or row['intro'] or '').strip()
            if d.get('rating'):
                row['douban_rating'] = d['rating'].get('value', row['douban_rating'])
                row['douban_votes'] = d['rating'].get('count', row['douban_votes'])
            if row['kind'] == 'book':
                row['authors'] = d.get('author') or row['authors']
                row['publisher'] = (d.get('press') or [row['publisher']])[0]
                row['pubdate'] = (d.get('pubdate') or [row['pubdate']])[0]
                row['pages'] = d.get('pages') or row['pages']
                row['translator'] = d.get('translator') or row['translator']
            elif row['kind'] == 'music':
                row['singers'] = names(d.get('singer')) or row['singers']
                row['publisher'] = d.get('publisher') or row['publisher']
                row['pubdate'] = (d.get('pubdate') or [row['pubdate']])[0]
                row['media'] = d.get('media') or row['media']
                row['genres'] = d.get('genres') or row['genres']
            elif row['kind'] == 'game':
                row['platforms'] = names(d.get('platforms')) or row['platforms']
                row['developers'] = names(d.get('developers')) or row['developers']
                row['publishers'] = names(d.get('publishers')) or row['publishers']
                row['release_date'] = d.get('release_date') or row['release_date']
                row['genres'] = d.get('genres') or row['genres']
        if i % 25 == 0:
            print('detail', i, flush=True)
    return rows


def fallback_intro(row):
    if row.get('intro'):
        return row['intro']
    kind = row.get('kind')
    bits = []
    if kind in ('movie', 'anime'):
        label = '动画剧集' if row.get('subtype') == 'tv' else ('动画电影' if kind == 'anime' else '电影')
        bits.append(f"{row.get('year') or '未知年份'} 年{label}")
        if row.get('countries'):
            bits.append(' / '.join(row['countries']))
        if row.get('directors'):
            bits.append('导演：' + ' / '.join(row['directors']))
        if row.get('episodes'):
            bits.append(f"{row['episodes']} 集")
        elif row.get('durations'):
            bits.append(' / '.join(row['durations']))
        if row.get('genres'):
            bits.append('类型：' + ' / '.join(row['genres']))
    elif kind == 'music':
        bits.append(' / '.join(row.get('singers') or []) or '音乐')
        if row.get('pubdate'):
            bits.append(row['pubdate'])
        if row.get('genres'):
            bits.append(' / '.join(row['genres']))
    elif kind == 'game':
        bits.append(f"{row.get('year') or '未知年份'} 年游戏")
        if row.get('platforms'):
            bits.append('平台：' + ' / '.join(row['platforms']))
        if row.get('genres'):
            bits.append('类型：' + ' / '.join(row['genres']))
    return '，'.join([b for b in bits if b]) + '。' if bits else ''


def fetch_cover(row):
    fn = COVER_DIR / f"{row['kind']}-{row['id']}.webp"
    if fn.exists() and fn.stat().st_size > 1000:
        row['cover'] = f"wuyu/covers/{row['kind']}-{row['id']}.webp"
        return True
    url = row.get('cover') or ''
    if not url:
        return False
    ref = {'book': 'https://book.douban.com/', 'music': 'https://music.douban.com/'}.get(row['kind'], 'https://movie.douban.com/')
    headers = {'User-Agent': UA_DESKTOP, 'Referer': ref}
    candidates = [url]
    for host in ('img1', 'img2', 'img3', 'img9'):
        for old in ('img1', 'img2', 'img3', 'img9'):
            candidates.append(url.replace(f'//{old}.doubanio.com', f'//{host}.doubanio.com'))
    for cand in candidates:
        try:
            r = requests.get(cand, headers=headers, timeout=30)
            if r.status_code == 200 and len(r.content) > 2000:
                img = Image.open(io.BytesIO(r.content)).convert('RGB')
                w, h = img.size
                if w > 360:
                    img = img.resize((360, int(h * 360 / w)), Image.LANCZOS)
                fn.parent.mkdir(parents=True, exist_ok=True)
                img.save(fn, 'WEBP', quality=84, method=6)
                row['cover'] = f"wuyu/covers/{row['kind']}-{row['id']}.webp"
                return True
        except Exception:
            continue
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--uid', default=UID)
    args = parser.parse_args()

    rows = build_rows(args.uid)
    print({k: len(v) for k, v in rows.items()}, flush=True)
    rows = enrich(rows)
    for group in rows:
        for row in rows[group]:
            row['intro'] = fallback_intro(row)
        # 先按本人评分（5 星在前），再按豆瓣评分从高到低；缺豆瓣评分的排后面
        rows[group].sort(key=lambda r: (
            -(r.get('my_rating') or 0),
            -(float(r.get('douban_rating') or 0)),
            -(r.get('douban_votes') or 0),
            r.get('title') or '',
        ))

    jobs = [row for group in rows.values() for row in group]
    print('covers', len(jobs), flush=True)
    ok = 0
    for i, row in enumerate(jobs, 1):
        if fetch_cover(row):
            ok += 1
        if i % 100 == 0:
            print('cover', i, 'ok', ok, flush=True)

    data = {
        'generatedAt': time.strftime('%Y-%m-%d'),
        'source': 'https://www.douban.com/people/bxycode000/',
        'books': rows['books'],
        'movies': rows['movies'],
        'anime': rows['anime'],
        'music': rows['music'],
        'games': rows['games'],
    }
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    print('wrote', DATA_FILE)
    print({k: len(v) for k, v in rows.items()})


if __name__ == '__main__':
    main()
