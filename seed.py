import requests, time, re
from app import app, db, Novel, Chapter

API = 'https://ar.wikisource.org/w/api.php'
HEADERS = {'User-Agent': 'KanawNovels/1.0 (educational)'}

# كل كتاب مع عدة أسماء صفحات محتملة
BOOKS = [
    {'title': 'كليلة ودمنة', 'author': 'ابن المقفع', 'pages': ['كليلة ودمنة'], 'category': 'أدب'},
    {'title': 'البخلاء', 'author': 'الجاحظ', 'pages': ['البخلاء'], 'category': 'أدب ساخر'},
    {'title': 'حي بن يقظان', 'author': 'ابن طفيل', 'pages': ['حي بن يقظان'], 'category': 'فلسفة'},
    {'title': 'طوق الحمامة', 'author': 'ابن حزم', 'pages': ['طوق الحمامة', 'رسالة طوق الحمامة'], 'category': 'أدب'},
    {'title': 'مقامات الحريري', 'author': 'القاسم الحريري', 'pages': ['مقامات الحريري', 'المقامات الحريرية'], 'category': 'أدب'},
    {'title': 'مقامات بديع الزمان', 'author': 'بديع الزمان الهمذاني', 'pages': ['مقامات بديع الزمان الهمذاني', 'المقامات'], 'category': 'أدب'},
    {'title': 'رسالة التوابع والزوابع', 'author': 'ابن شهيد', 'pages': ['رسالة التوابع والزوابع'], 'category': 'أدب'},
    {'title': 'ديوان المتنبي', 'author': 'أبو الطيب المتنبي', 'pages': ['ديوان المتنبي'], 'category': 'شعر'},
    {'title': 'رباعيات الخيام', 'author': 'عمر الخيام', 'pages': ['رباعيات الخيام'], 'category': 'شعر'},
    {'title': 'رسالة الغفران', 'author': 'أبو العلاء المعري', 'pages': ['رسالة الغفران'], 'category': 'فلسفة'},
    {'title': 'الأيام', 'author': 'طه حسين', 'pages': ['الأيام (طه حسين)', 'الأيام'], 'category': 'سيرة ذاتية'},
    {'title': 'ألف ليلة وليلة', 'author': 'مجهول', 'pages': ['ألف ليلة وليلة', 'حكايات ألف ليلة وليلة'], 'category': 'حكايات'},
    {'title': 'مقدمة ابن خلدون', 'author': 'ابن خلدون', 'pages': ['مقدمة ابن خلدون'], 'category': 'تاريخ'},
    {'title': 'نهج البلاغة', 'author': 'الشريف الرضي', 'pages': ['نهج البلاغة'], 'category': 'أدب'},
]


def api_get(params):
    for _ in range(3):
        try:
            r = requests.get(API, params=params, headers=HEADERS, timeout=30)
            return r.json()
        except Exception:
            time.sleep(2)
    return None


def fetch_page(name):
    data = api_get({
        'action': 'parse', 'page': name,
        'prop': 'wikitext', 'format': 'json',
        'formatversion': '2', 'redirects': '1'
    })
    if not data or 'error' in data:
        return None
    return data.get('parse', {}).get('wikitext', '')


def get_subpages(prefix, limit=30):
    data = api_get({
        'action': 'query', 'list': 'allpages',
        'apprefix': prefix + '/', 'aplimit': limit,
        'format': 'json', 'formatversion': '2'
    })
    if not data:
        return []
    return [p['title'] for p in data.get('query', {}).get('allpages', [])]


def clean_wikitext(text):
    if not text:
        return ''
    text = re.sub(r'\{\{[^{}]*\}\}', '', text)
    text = re.sub(r'\[\[(?:ملف|File|Image|تصنيف|Category):[^\]]*\]\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[\[[^\]|]+\|([^\]]+)\]\]', r'\1', text)
    text = re.sub(r'\[\[([^\]]+)\]\]', r'\1', text)
    text = re.sub(r'\[https?://[^\s\]]+\s*([^\]]*)\]', r'\1', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r"'{2,}", '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def split_chapters(text):
    parts = re.split(r'\n==+\s*([^=\n]+?)\s*==+\n', text)
    chs = []
    if len(parts) > 5:
        for i in range(1, len(parts), 2):
            if i + 1 >= len(parts):
                break
            title = parts[i].strip() or 'فصل'
            content = parts[i+1].strip()
            if len(content) > 500:
                chs.append((len(chs)+1, title[:200], content))
        if chs:
            return chs[:40]
    chunk = 15000
    for i, start in enumerate(range(0, len(text), chunk), 1):
        c = text[start:start+chunk].strip()
        if len(c) > 500:
            chs.append((i, 'الجزء %d' % i, c))
    return chs[:40]


def seed_one(book):
    if Novel.query.filter_by(title=book['title']).first():
        print('موجود مسبقاً')
        return False

    wikitext = None
    used_page = None
    for page in book['pages']:
        wikitext = fetch_page(page)
        if wikitext:
            used_page = page
            break

    if not wikitext:
        print('❌ الصفحة غير موجودة')
        return False

    text = clean_wikitext(wikitext)
    arabic = sum(1 for c in text[:3000] if '\u0600' <= c <= '\u06FF')

    # إذا كان النص قصيراً، نجرب الصفحات الفرعية (بوابات)
    if len(text) < 1500 or arabic < 100:
        print('محاولة الصفحات الفرعية...', end=' ')
        subpages = get_subpages(used_page)
        if subpages:
            parts = []
            for sp in subpages[:25]:
                sub = fetch_page(sp)
                if sub:
                    parts.append(clean_wikitext(sub))
                time.sleep(0.3)
            if parts:
                text = '\n\n'.join(parts)
                arabic = sum(1 for c in text[:3000] if '\u0600' <= c <= '\u06FF')

    if len(text) < 1000 or arabic < 50:
        print('❌ نص قصير (%d حرف)' % len(text))
        return False

    novel = Novel(
        title=book['title'],
        author=book['author'],
        description='%s — %s' % (book['category'], book['author']),
        category=book['category'],
        status='مكتملة',
        source='wikisource',
        source_id=used_page,
    )
    db.session.add(novel)
    db.session.commit()

    chapters = split_chapters(text)
    for num, title, content in chapters:
        db.session.add(Chapter(novel_id=novel.id, number=num, title=title, content=content))
    db.session.commit()

    print('✅ %d فصل' % len(chapters))
    return True


def seed():
    with app.app_context():
        db.create_all()
        added = 0
        for i, book in enumerate(BOOKS, 1):
            print('[%d/%d] %s... ' % (i, len(BOOKS), book['title']), end='')
            try:
                if seed_one(book):
                    added += 1
            except Exception as e:
                db.session.rollback()
                print('❌ %s' % str(e)[:60])
            time.sleep(0.5)
        print('\n🎉 أضيفت %d رواية جديدة' % added)
        print('📊 الإجمالي: %d' % Novel.query.count())


if __name__ == '__main__':
    seed()