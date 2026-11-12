# -*- coding: utf-8 -*-
"""同步豆瓣「书影音」五星记录到物语页。

用法：
    python scripts/fetch_douban_wuyu.py                 # 默认用户 bxycode000
    python scripts/fetch_douban_wuyu.py --user bxycode000 # 指定豆瓣用户

数据来源：豆瓣用户公开的「看过 / 读过 / 听过」收藏页。
只保留本人评分 5 星、且状态为「看过 / 读过 / 听过」的记录。

输出：
    data/wuyu.json                 —— 页面数据（书籍 / 电影 / 漫剧 / 音乐）
    static/wuyu/covers/*.webp      —— 本地封面（豆瓣图片有防盗链，必须本地化）

依赖：requests、lxml、Pillow（本机 Python 环境已具备）。
豆瓣对未登录访问有频率限制；脚本会缓存每一步，失败后重跑会从缓存继续。
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

UA_MOBILE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
UA_DESKTOP = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36'

GENRES = {
    '剧情', '喜剧', '爱情', '科幻', '动画', '悬疑', '惊悚', '恐怖', '纪录片', '短片',
    '情色', '音乐', '歌舞', '家庭', '儿童', '传记', '历史', '战争', '犯罪', '西部',
    '奇幻', '冒险', '灾难', '武侠', '古装', '运动', '黑色电影', '真人秀', '脱口秀',
    '舞台艺术', '同性', '戏曲', '动作', '鬼怪', '青春', '校园', '日常', '治愈', '热血',
    '流行', '摇滚', '民谣', '电子', '爵士', '古典', '嘻哈', '乡村', '金属', '朋克',
    '原声', '世界音乐', '轻音乐', '蓝调', '灵魂乐', '雷鬼', 'R&B', 'J-Pop', 'K-Pop',
}
COUNTRIES = {
    '中国', '中国大陆', '中国香港', '中国台湾', '美国', '英国', '日本', '韩国', '法国',
    '德国', '意大利', '西班牙', '印度', '泰国', '加拿大', '澳大利亚', '俄罗斯', '瑞典',
    '丹麦', '挪威', '芬兰', '荷兰', '比利时', '波兰', '捷克', '巴西', '墨西哥', '阿根廷',
    '新西兰', '爱尔兰', '奥地利', '瑞士', '土耳其', '伊朗', '以色列', '新加坡', '马来西亚',
    '越南', '菲律宾', '印度尼西亚',
}


def session() -> requests.Session:
    s = requests.Session()
    bid = ''.join(random.choices(string.ascii_letters + string.digits, k=11))
    s.cookies.set('bid', bid, domain='.douban.com')
    return s


def fetch(url: str, cache: Path, headers: dict, retries: int = 3) -> str:
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
            time.sleep(1.5)
        except Exception:
            time.sleep(1.5)
    return ''


def txt(el) -> str:
    return ' '.join(el.text_content().split()) if el is not None else ''


def get_id(url: str) -> str:
    m = re.search(r'/subject/(\d+)', url or '')
    return m.group(1) if m else ''


def year_of(s: str) -> str:
    m = re.search(r'(19|20)\d{2}', s or '')
    return m.group(0) if m else ''


def date_of(s: str) -> str:
    m = re.search(r'((?:19|20)\d{2}-\d{2}-\d{2})', s or '')
    return m.group(1) if m else ''


def hue_of(sid: str) -> int:
    return int(hashlib.md5(str(sid).encode()).hexdigest()[:6], 16) % 360


# ---------- 收藏页 ----------

def parse_collection_movie(src: dict):
    parts = [p.strip() for p in re.split(r'\s*/\s*', src.get('intro', '')) if p.strip()]
    genres = [p for p in parts if p in GENRES]
    countries = [p for p in parts if p in COUNTRIES]
    duration = next((p for p in parts if re.fullmatch(r'\d+\s*分钟', p)), '')
    director = ''
    try:
        idx = parts.index(duration)
        if idx > 0:
            director = parts[idx - 1]
    except ValueError:
        pass
    return genres, countries, duration, director, year_of(src.get('intro', ''))


def scrape_movies(user: str):
    rows, seen = [], set()
    for page in range(0, 101):
        start = page * 15
        url = (f'https://movie.douban.com/people/{user}/collect?start={start}'
               f'&sort=rating&rating=5&filter=all&mode=grid&tags_sort=count&type=all')
        html = fetch(url, CACHE_DIR / f'movie_list_{start}.html',
                     {'User-Agent': UA_DESKTOP, 'Referer': 'https://movie.douban.com/'})
        if not html:
            break
        doc = lxml.html.fromstring(html)
        items = doc.xpath('//div[contains(@class,"grid-view")]//div[contains(@class,"item")]')
        if not items:
            break
        ratings = [(x.xpath('.//span[contains(@class,"rating")]/@class') or [''])[0] for x in items]
        if all(r != 'rating5-t' for r in ratings):
            break
        for it, rating in zip(items, ratings):
            if rating != 'rating5-t':
                continue
            a = it.xpath('.//li[contains(@class,"title")]/a[1]')
            if not a:
                continue
            ta = a[0]
            href = ta.get('href')
            if href in seen:
                continue
            seen.add(href)
            img = it.xpath('.//div[contains(@class,"pic")]//img')
            rows.append({
                'href': href,
                'title': ' '.join(ta.text_content().split()),
                'intro': ' '.join((it.xpath('.//li[contains(@class,"intro")]')[0].text_content()
                                   if it.xpath('.//li[contains(@class,"intro")]') else '').split()),
                'date': it.xpath('string(.//span[contains(@class,"date")])').strip(),
                'cover': img[0].get('src') if img else '',
                'comment': ' '.join((it.xpath('.//div[contains(@class,"comment")]')[0].text_content()
                                     if it.xpath('.//div[contains(@class,"comment")]') else '').split()),
            })
    return rows


def scrape_subjects(user: str, kind: str):
    """kind: book / music，收藏页可直接用 rating=5 过滤。"""
    rows, seen = [], set()
    for page in range(0, 20):
        start = page * 15
        domain = 'book' if kind == 'book' else 'music'
        url = (f'https://{domain}.douban.com/people/{user}/collect?start={start}'
               f'&sort=rating&rating=5&filter=all&mode=grid&tags_sort=count')
        html = fetch(url, CACHE_DIR / f'{kind}_list_{start}.html',
                     {'User-Agent': UA_DESKTOP, 'Referer': f'https://{domain}.douban.com/'})
        if not html:
            break
        doc = lxml.html.fromstring(html)
        if kind == 'book':
            items = doc.xpath('//li[contains(@class,"subject-item")]')
        else:
            items = doc.xpath('//div[contains(@class,"grid-view")]//div[contains(@class,"item")]')
        if not items:
            break
        for it in items:
            if kind == 'book':
                a = it.xpath('.//div[contains(@class,"info")]//h2//a')
                if not a:
                    continue
                ta = a[0]
                href = ta.get('href')
                if href in seen:
                    continue
                seen.add(href)
                img = it.xpath('.//div[contains(@class,"pic")]//img')
                rows.append({
                    'href': href,
                    'title': ' '.join(ta.text_content().split()),
                    'pub': ' '.join((it.xpath('.//div[contains(@class,"pub")]')[0].text_content()
                                     if it.xpath('.//div[contains(@class,"pub")]') else '').split()),
                    'date': ' '.join((it.xpath('.//span[contains(@class,"date")]')[0].text_content()
                                      if it.xpath('.//span[contains(@class,"date")]') else '').split()),
                    'cover': img[0].get('src') if img else '',
                    'comment': ' '.join((it.xpath('.//p[contains(@class,"comment")]')[0].text_content()
                                         if it.xpath('.//p[contains(@class,"comment")]') else '').split()),
                })
            else:
                a = it.xpath('.//li[contains(@class,"title")]/a[1]')
                if not a:
                    continue
                ta = a[0]
                href = ta.get('href')
                if href in seen:
                    continue
                seen.add(href)
                img = it.xpath('.//div[contains(@class,"pic")]//img')
                rows.append({
                    'href': href,
                    'title': ' '.join(ta.text_content().split()),
                    'intro': ' '.join((it.xpath('.//li[contains(@class,"intro")]')[0].text_content()
                                       if it.xpath('.//li[contains(@class,"intro")]') else '').split()),
                    'date': it.xpath('string(.//span[contains(@class,"date")])').strip(),
                    'cover': img[0].get('src') if img else '',
                    'comment': ' '.join((it.xpath('.//div[contains(@class,"comment")]')[0].text_content()
                                         if it.xpath('.//div[contains(@class,"comment")]') else '').split()),
                })
        if len(items) < 15:
            break
    return rows


# ---------- 详情页 ----------

def parse_mobile(kind: str, sid: str):
    html = fetch(f'https://m.douban.com/{kind}/subject/{sid}/',
                 CACHE_DIR / 'mobile' / f'{kind}_{sid}.html',
                 {'User-Agent': UA_MOBILE, 'Referer': 'https://m.douban.com/'})
    if not html:
        return {}
    doc = lxml.html.fromstring(html)
    out = {
        'title': txt(doc.xpath('//div[contains(@class,"sub-title")]')[0]) if doc.xpath('//div[contains(@class,"sub-title")]') else '',
        'original': txt(doc.xpath('//div[contains(@class,"sub-original-title")]')[0]) if doc.xpath('//div[contains(@class,"sub-original-title")]') else '',
        'sub_info': [txt(x) for x in doc.xpath('//div[contains(@class,"sub-info")]')],
        'sub_meta': txt(doc.xpath('//div[contains(@class,"sub-meta")]')[0]) if doc.xpath('//div[contains(@class,"sub-meta")]') else '',
        'og_image': (doc.xpath('//meta[@property="og:image"]/@content') or [''])[0],
    }
    intro = ''
    for sel in ('//section[contains(@class,"subject-intro")]//p',
                '//section[contains(@class,"subject-section_intro")]//p',
                '//section[contains(@class,"subject-intro")]',
                '//section[contains(@class,"subject-section_intro")]'):
        els = doc.xpath(sel)
        if els and txt(els[0]):
            intro = txt(els[0])
            break
    if not intro:
        md = doc.xpath('//meta[@name="description"]/@content')
        if md:
            m = re.search(r'简介[：:]\s*(.*)$', md[0], re.S)
            if m:
                intro = m.group(1).strip()
    for prefix in ('剧集简介', '电影简介', '影片简介', '内容简介', '唱片简介', '简介'):
        if intro.startswith(prefix):
            intro = intro[len(prefix):].strip()
    out['intro'] = intro
    return out


def build_movie(src: dict) -> dict:
    sid = get_id(src['href'])
    mob = parse_mobile('movie', sid)
    genres, countries, duration, director, cb_year = parse_collection_movie(src)
    original = re.sub(r'[（(]\d{4}[）)]\s*$', '', mob.get('original', '')).strip()
    return {
        'id': sid, 'kind': 'movie',
        'title': mob.get('title') or (src.get('title') or '').split(' / ')[0].strip(),
        'original_title': original,
        'year': year_of(mob.get('original', '')) or cb_year,
        'cover': mob.get('og_image') or src.get('cover', ''),
        'douban_rating': None, 'douban_votes': None,
        'intro': mob.get('intro', ''),
        'genres': genres, 'url': src['href'], 'finished': src.get('date', ''),
        'my_comment': src.get('comment', ''),
        'directors': [director] if director else [], 'actors': [],
        'countries': countries, 'durations': [duration] if duration else [],
        'episodes': None, 'short_comment': '', 'short_comment_author': '',
        'hue': hue_of(sid),
    }


def build_book(src: dict) -> dict:
    sid = get_id(src['href'])
    mob = parse_mobile('book', sid)
    meta = mob.get('sub_meta') or src.get('pub', '')
    parts = [p.strip() for p in meta.split(' / ') if p.strip()]
    authors = [x.strip() for x in parts[0].split('/') if x.strip()] if parts else []
    publisher = parts[1] if len(parts) > 1 else ''
    pubdate = re.sub(r'出版$', '', parts[2]).strip() if len(parts) > 2 else ''
    return {
        'id': sid, 'kind': 'book',
        'title': mob.get('title') or (src.get('title') or '').split(' / ')[0].strip(),
        'original_title': mob.get('original', ''),
        'year': year_of(pubdate) or year_of(src.get('pub', '')),
        'cover': mob.get('og_image') or src.get('cover', ''),
        'douban_rating': None, 'douban_votes': None,
        'intro': mob.get('intro', ''), 'genres': [],
        'url': src['href'], 'finished': src.get('date', ''), 'my_comment': src.get('comment', ''),
        'authors': authors, 'publisher': publisher, 'pubdate': pubdate,
        'pages': None, 'translator': [], 'hue': hue_of(sid),
    }


def build_music(src: dict) -> dict:
    sid = get_id(src['href'])
    mob = parse_mobile('music', sid)
    parts = [p.strip() for p in src.get('intro', '').split(' / ') if p.strip()]
    singers = [parts[0]] if parts else []
    pubdate = parts[1] if len(parts) > 1 else ''
    media = parts[3] if len(parts) > 3 and parts[3] in ('CD', '黑胶', '数字', '磁带') else (parts[2] if len(parts) > 2 else '')
    genres = [parts[-1]] if parts and parts[-1] in GENRES else []
    return {
        'id': sid, 'kind': 'music',
        'title': mob.get('title') or (src.get('title') or '').split(' / ')[0].strip(),
        'original_title': mob.get('original', ''),
        'year': year_of(pubdate) or year_of(src.get('intro', '')),
        'cover': mob.get('og_image') or src.get('cover', ''),
        'douban_rating': None, 'douban_votes': None,
        'intro': mob.get('intro', ''), 'genres': genres,
        'url': src['href'], 'finished': src.get('date', ''), 'my_comment': src.get('comment', ''),
        'singers': singers, 'publisher': [], 'pubdate': pubdate, 'media': media,
        'hue': hue_of(sid),
    }


# ---------- 封面 ----------

def fetch_cover(kind: str, sid: str, url: str) -> str:
    fn = COVER_DIR / f'{kind}-{sid}.webp'
    if fn.exists() and fn.stat().st_size > 1000:
        return f'wuyu/covers/{kind}-{sid}.webp'
    if not url:
        return ''
    ref = {'book': 'https://book.douban.com/', 'music': 'https://music.douban.com/'}.get(kind, 'https://movie.douban.com/')
    headers = {'User-Agent': UA_DESKTOP, 'Referer': ref}
    candidates = [url]
    for host in ('img1', 'img2', 'img3', 'img9'):
        for old in ('img1', 'img2', 'img3', 'img9'):
            candidates.append(url.replace(f'//{old}.doubanio.com', f'//{host}.doubanio.com'))
    for candidate in candidates:
        try:
            r = requests.get(candidate, headers=headers, timeout=30)
            if r.status_code != 200 or len(r.content) < 2000:
                continue
            img = Image.open(io.BytesIO(r.content)).convert('RGB')
            w, h = img.size
            if w > 360:
                img = img.resize((360, int(h * 360 / w)), Image.LANCZOS)
            fn.parent.mkdir(parents=True, exist_ok=True)
            img.save(fn, 'WEBP', quality=84, method=6)
            return f'wuyu/covers/{kind}-{sid}.webp'
        except Exception:
            continue
    return ''


# ---------- 主流程 ----------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--user', default='bxycode000')
    args = parser.parse_args()

    print('抓取电影收藏 ...')
    movies = scrape_movies(args.user)
    print('抓取书籍收藏 ...')
    books = scrape_subjects(args.user, 'book')
    print('抓取音乐收藏 ...')
    music = scrape_subjects(args.user, 'music')
    print(f'收藏页：电影 {len(movies)} / 书籍 {len(books)} / 音乐 {len(music)}')

    movie_rows = [build_movie(x) for x in movies]
    book_rows = [build_book(x) for x in books]
    music_rows = [build_music(x) for x in music]

    anime_rows, film_rows = [], []
    for row in movie_rows:
        if '动画' in (row.get('genres') or []):
            row['kind'] = 'anime'
            anime_rows.append(row)
        else:
            film_rows.append(row)

    for rows in (film_rows, anime_rows, book_rows, music_rows):
        rows.sort(key=lambda r: date_of(r.get('finished', '')) or '0000-00-00', reverse=True)

    data = {
        'generatedAt': time.strftime('%Y-%m-%d'),
        'source': f'https://www.douban.com/people/{args.user}/',
        'books': book_rows,
        'movies': film_rows,
        'anime': anime_rows,
        'music': music_rows,
    }

    # 如果本轮详情页抓取失败，用上一次的富数据补齐，避免把已有简介/评分冲掉
    if DATA_FILE.exists():
        try:
            old = json.loads(DATA_FILE.read_text(encoding='utf-8'))
            old_map = {(it.get('kind'), it.get('id')): it
                       for key in ('books', 'movies', 'anime', 'music') for it in old.get(key, [])}
            fill_keys = ('intro', 'original_title', 'douban_rating', 'douban_votes', 'genres',
                         'directors', 'actors', 'countries', 'durations', 'episodes',
                         'short_comment', 'short_comment_author', 'authors', 'publisher',
                         'pubdate', 'pages', 'translator', 'singers', 'media')
            for group in ('books', 'movies', 'anime', 'music'):
                for row in data[group]:
                    prev = old_map.get((row.get('kind'), row.get('id')))
                    if not prev:
                        continue
                    for key in fill_keys:
                        if not row.get(key) and prev.get(key):
                            row[key] = prev[key]
        except Exception:
            pass

    # 下载封面；已存在的本地封面不重复下载
    for group in ('books', 'movies', 'anime', 'music'):
        for row in data[group]:
            path = fetch_cover(row['kind'], row['id'], row.get('cover', ''))
            if path:
                row['cover'] = path
            print('.', end='', flush=True)
    print()

    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'写入 {DATA_FILE}')
    print(f'书籍 {len(book_rows)} · 电影 {len(film_rows)} · 漫剧 {len(anime_rows)} · 音乐 {len(music_rows)}')


if __name__ == '__main__':
    main()
