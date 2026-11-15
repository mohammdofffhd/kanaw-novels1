from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os, ssl

app = Flask(__name__)
app.config['SECRET_KEY'] = 'kanaw-novels-2026-secret'

# ==========================================
# إعداد قاعدة البيانات (Neon + pg8000)
# ==========================================
db_url = os.environ.get('DATABASE_URL', 'sqlite:///kanaw.db')
if db_url.startswith('postgres://'):
    db_url = db_url.replace('postgres://', 'postgresql://', 1)

if db_url.startswith('postgresql://'):
    db_url = db_url.split('?')[0]
    db_url = db_url.replace('postgresql://', 'postgresql+psycopg2://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'connect_args': {'sslmode': 'require'}
    }
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'يجب تسجيل الدخول أولاً'
login_manager.login_message_category = 'warning'

# ==========================================
# نظام الرتب والمستويات (60 مستوى)
# ==========================================
MAX_LEVEL = 60
XP_PER_CHAPTER = 7

def xp_needed(level):
    return 300 + (level - 1) * 200

LEVEL_THRESHOLDS = [0]
for _i in range(1, MAX_LEVEL + 1):
    LEVEL_THRESHOLDS.append(LEVEL_THRESHOLDS[-1] + xp_needed(_i))

def get_rank(level):
    if level <= 10: return ("مبتدئ", "🌱")
    if level <= 20: return ("عادي", "📗")
    if level <= 30: return ("متمرس", "📘")
    if level <= 40: return ("خبير", "📙")
    if level <= 50: return ("أسطوري", "🔥")
    return ("سلف القراء", "👑")

# ==========================================
# الموديلات
# ==========================================
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    xp = db.Column(db.Integer, default=0)
    level = db.Column(db.Integer, default=1)
    last_checkin = db.Column(db.DateTime)
    checkin_streak = db.Column(db.Integer, default=0)
    chapters_read = db.Column(db.Integer, default=0)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def xp_progress(self):
        if self.level >= MAX_LEVEL: return 100
        cur = LEVEL_THRESHOLDS[self.level - 1]
        nxt = LEVEL_THRESHOLDS[self.level]
        span = nxt - cur
        if span <= 0: return 0
        return max(0, min(100, int(((self.xp - cur) / span) * 100)))

    @property
    def xp_remaining(self):
        if self.level >= MAX_LEVEL: return 0
        return max(0, LEVEL_THRESHOLDS[self.level] - self.xp)

    @property
    def rank_name(self): return get_rank(self.level)[0]
    @property
    def rank_icon(self): return get_rank(self.level)[1]

    @property
    def can_checkin(self):
        if not self.last_checkin: return True
        return self.last_checkin.date() < datetime.utcnow().date()

class Novel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300), nullable=False)
    author = db.Column(db.String(200), default='غير معروف')
    description = db.Column(db.Text, default='')
    cover_url = db.Column(db.String(500), default='')
    category = db.Column(db.String(100), default='عام')
    status = db.Column(db.String(50), default='مكتملة')
    source = db.Column(db.String(50), default='manual')
    source_id = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    views = db.Column(db.Integer, default=0)
    chapters = db.relationship('Chapter', backref='novel', lazy=True, cascade='all, delete-orphan', order_by='Chapter.number')

class Chapter(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    novel_id = db.Column(db.Integer, db.ForeignKey('novel.id'), nullable=False)
    number = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(300))
    content = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Favorite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    novel_id = db.Column(db.Integer, db.ForeignKey('novel.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    novel = db.relationship('Novel', backref='favorited_by')
    __table_args__ = (db.UniqueConstraint('user_id', 'novel_id', name='unique_fav'),)

class ReadingHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    chapter_id = db.Column(db.Integer, db.ForeignKey('chapter.id'), nullable=False)
    novel_id = db.Column(db.Integer, db.ForeignKey('novel.id'), nullable=False)
    read_at = db.Column(db.DateTime, default=datetime.utcnow)
    chapter = db.relationship('Chapter')
    novel = db.relationship('Novel')


class PublisherRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    pen_name = db.Column(db.String(100), nullable=False)
    bio = db.Column(db.Text, default='')
    social_link = db.Column(db.String(300), default='')
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User')

class SiteSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text, default='')

class NovelSuggestion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(300), nullable=False)
    reason = db.Column(db.Text, default='')
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User')

def get_setting(key, default=''):
    s = SiteSettings.query.filter_by(key=key).first()
    return s.value if s else default

@app.context_processor
def inject_site_settings():
    return {
        'site_name': get_setting('site_name', 'Kanaw'),
        'site_logo': get_setting('site_logo', ''),
    }

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def add_xp(user, amount):
    user.xp = (user.xp or 0) + amount
    new_level = 1
    for i, threshold in enumerate(LEVEL_THRESHOLDS):
        if user.xp >= threshold: new_level = i + 1
        else: break
    user.level = min(new_level, MAX_LEVEL)
    db.session.add(user)

@app.context_processor
def inject_globals():
    return {'now': datetime.utcnow(), 'max_level': MAX_LEVEL}

# ==========================================
# المسارات (Routes)
# ==========================================
@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated: return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if len(username) < 4:
            flash('اسم المستخدم يجب أن يكون 4 أحرف على الأقل', 'danger')
        elif len(password) < 9:
            flash('كلمة المرور يجب أن تكون 9 أحرف على الأقل', 'danger')
        elif User.query.filter_by(username=username).first():
            flash('اسم المستخدم محجوز', 'danger')
        else:
            user = User(username=username)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash(f'مرحباً {username}! ابدأ رحلتك كمبتدئ 🌱', 'success')
            return redirect(url_for('index'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated: return redirect(url_for('index'))
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username', '').strip()).first()
        if user and user.check_password(request.form.get('password', '')):
            login_user(user)
            flash(f'مرحباً بعودتك {user.username}!', 'success')
            return redirect(request.args.get('next') or url_for('index'))
        flash('اسم المستخدم أو كلمة المرور خاطئة', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/api/checkin', methods=['POST'])
@login_required
def api_checkin():
    if not current_user.can_checkin:
        return jsonify({'success': False, 'message': 'سجلت حضورك اليوم بالفعل'})
    if current_user.last_checkin and current_user.last_checkin.date() == (datetime.utcnow().date() - timedelta(days=1)):
        current_user.checkin_streak += 1
    else:
        current_user.checkin_streak = 1
    xp_reward = 15 + (current_user.checkin_streak - 1) * 5
    current_user.last_checkin = datetime.utcnow()
    add_xp(current_user, xp_reward)
    db.session.commit()
    return jsonify({'success': True, 'xp': xp_reward, 'streak': current_user.checkin_streak, 'message': f'حصلت على {xp_reward} XP!'})

@app.route('/')
def index():
    page = request.args.get('page', 1, type=int)
    q = request.args.get('q', '').strip()
    query = Novel.query
    if q:
        query = query.filter(Novel.title.contains(q) | Novel.author.contains(q))
    # عرض 20 رواية في كل صفحة
    novels = query.order_by(Novel.id.desc()).paginate(page=page, per_page=20, error_out=False)
    return render_template('index.html', novels=novels, q=q)

@app.route('/novel/<int:novel_id>')
def novel_page(novel_id):
    novel = Novel.query.get_or_404(novel_id)
    is_fav = False
    if current_user.is_authenticated:
        is_fav = bool(Favorite.query.filter_by(user_id=current_user.id, novel_id=novel_id).first())
    
    # زيادة المشاهدات (بس مرة واحدة لكل مستخدم)
    viewed_novels = session.get('viewed_novels', [])
    if novel_id not in viewed_novels:
        novel.views = (novel.views or 0) + 1
        db.session.commit()
        viewed_novels.append(novel_id)
        session['viewed_novels'] = viewed_novels
    
    return render_template('novel.html', novel=novel, is_favorite=is_fav)

@app.route('/read/<int:chapter_id>')
def read_chapter(chapter_id):
    ch = Chapter.query.get_or_404(chapter_id)
    if current_user.is_authenticated:
        existing = ReadingHistory.query.filter_by(user_id=current_user.id, chapter_id=ch.id).first()
        if existing:
            existing.read_at = datetime.utcnow()
        else:
            db.session.add(ReadingHistory(user_id=current_user.id, chapter_id=ch.id, novel_id=ch.novel_id))
            add_xp(current_user, XP_PER_CHAPTER)
            current_user.chapters_read = (current_user.chapters_read or 0) + 1
        db.session.commit()
    all_chapters = ch.novel.chapters
    idx = next((i for i, c in enumerate(all_chapters) if c.id == ch.id), -1)
    prev_ch = all_chapters[idx - 1] if idx > 0 else None
    next_ch = all_chapters[idx + 1] if idx < len(all_chapters) - 1 else None
    return render_template('chapter.html', chapter=ch, novel=ch.novel, prev_ch=prev_ch, next_ch=next_ch, all_chapters=all_chapters)

@app.route('/api/favorite/<int:novel_id>', methods=['POST'])
@login_required
def toggle_favorite(novel_id):
    Novel.query.get_or_404(novel_id)
    fav = Favorite.query.filter_by(user_id=current_user.id, novel_id=novel_id).first()
    if fav:
        db.session.delete(fav)
        db.session.commit()
        return jsonify({'success': True, 'favorited': False})
    db.session.add(Favorite(user_id=current_user.id, novel_id=novel_id))
    db.session.commit()
    return jsonify({'success': True, 'favorited': True})

@app.route('/favorites')
@login_required
def favorites():
    favs = Favorite.query.filter_by(user_id=current_user.id).order_by(Favorite.created_at.desc()).all()
    return render_template('favorites.html', favorites=favs)

@app.route('/history')
@login_required
def history():
    items = ReadingHistory.query.filter_by(user_id=current_user.id).order_by(ReadingHistory.read_at.desc()).all()
    novels_dict = {}
    for h in items:
        if h.novel_id not in novels_dict:
            novels_dict[h.novel_id] = {
                'novel': h.novel,
                'chapters': [],
                'last_read': h.read_at
            }
        novels_dict[h.novel_id]['chapters'].append(h)
        if h.read_at > novels_dict[h.novel_id]['last_read']:
            novels_dict[h.novel_id]['last_read'] = h.read_at
            
    novels_list = list(novels_dict.values())
    novels_list.sort(key=lambda x: x['last_read'], reverse=True)
    
    total_novels = len(novels_list)
    total_chapters = len(items)
    
    return render_template('history.html', novels_list=novels_list, total_novels=total_novels, total_chapters=total_chapters)

@app.route('/clear-history', methods=['POST'])
@login_required
def clear_history():
    ReadingHistory.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()
    flash('تم مسح سجل القراءة بالكامل', 'success')
    return redirect(url_for('history'))

@app.route('/clear-history/novel/<int:novel_id>', methods=['POST'])
@login_required
def clear_history_novel(novel_id):
    ReadingHistory.query.filter_by(user_id=current_user.id, novel_id=novel_id).delete()
    db.session.commit()
    flash('تم مسح سجل هذه الرواية', 'success')
    return redirect(url_for('history'))

@app.route('/clear-history/chapter/<int:history_id>', methods=['POST'])
@login_required
def clear_history_chapter(history_id):
    h = ReadingHistory.query.get_or_404(history_id)
    if h.user_id == current_user.id:
        db.session.delete(h)
        db.session.commit()
        flash('تم مسح الفصل من السجل', 'success')
    return redirect(url_for('history'))


@app.route('/profile')
@login_required
def profile():
    favs = Favorite.query.filter_by(user_id=current_user.id).order_by(Favorite.created_at.desc()).all()
    history = ReadingHistory.query.filter_by(user_id=current_user.id).order_by(ReadingHistory.read_at.desc()).limit(30).all()
    return render_template('profile.html', favorites=favs, history=history)

# ==========================================
# لوحة التحكم
# ==========================================
@app.route('/admin')
@login_required
def admin():
    if not current_user.is_admin:
        flash('هذه الصفحة للمشرف فقط', 'danger')
        return redirect(url_for('index'))
    try:
        from sqlalchemy import func
        page = request.args.get('page', 1, type=int)
        stats = dict(
            novels=Novel.query.count(),
            users=User.query.count(),
            chapters=db.session.query(func.count(Chapter.id)).scalar() or 0,
        )
        novels = Novel.query.order_by(Novel.id.desc()).paginate(page=page, per_page=30, error_out=False)
        return render_template('admin.html', novels=novels, stats=stats)
    except Exception as e:
        flash('خطأ: ' + str(e)[:200], 'danger')
        return redirect(url_for('index'))

@app.route('/admin/novel/new', methods=['POST'])
@login_required
def admin_new_novel():
    if not current_user.is_admin: return redirect(url_for('index'))
    title = request.form.get('title', '').strip()
    if title:
        novel = Novel(title=title, author=request.form.get('author', '').strip() or 'غير معروف', description=request.form.get('description', '').strip(), cover_url=request.form.get('cover_url', '').strip(), category=request.form.get('category', 'عام').strip() or 'عام', status=request.form.get('status', 'مكتملة'))
        db.session.add(novel)
        db.session.commit()
    return redirect('/admin')

@app.route('/admin/novel/<int:novel_id>')
@login_required
def admin_edit_novel(novel_id):
    if not current_user.is_admin: return redirect(url_for('index'))
    novel = Novel.query.get_or_404(novel_id)
    return render_template('admin.html', novels=Novel.query.order_by(Novel.id.desc()).all(), edit_novel=novel)

@app.route('/admin/novel/<int:novel_id>/chapter/new', methods=['POST'])
@login_required
def admin_new_chapter(novel_id):
    if not current_user.is_admin: return redirect(url_for('index'))
    novel = Novel.query.get_or_404(novel_id)
    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()
    if title and content:
        num = (db.session.query(db.func.max(Chapter.number)).filter_by(novel_id=novel.id).scalar() or 0) + 1
        db.session.add(Chapter(novel_id=novel.id, number=num, title=title, content=content))
        db.session.commit()
    return redirect(f'/admin/novel/{novel.id}')

@app.route('/admin/novel/<int:novel_id>/delete', methods=['POST'])
@login_required
def admin_delete_novel(novel_id):
    if not current_user.is_admin: return redirect(url_for('index'))
    novel = Novel.query.get_or_404(novel_id)
    db.session.delete(novel)
    db.session.commit()
    return redirect('/admin')

@app.route('/admin/chapter/<int:chapter_id>/delete', methods=['POST'])
@login_required
def admin_delete_chapter(chapter_id):
    if not current_user.is_admin: return redirect(url_for('index'))
    ch = Chapter.query.get_or_404(chapter_id)
    novel_id = ch.novel_id
    db.session.delete(ch)
    db.session.commit()
    return redirect(f'/admin/novel/{novel_id}')

# ==========================================
# إنشاء الجداول والأدمن الافتراضي
# ==========================================

# ============ صفحات المستخدم الجديدة ============
@app.route('/suggest', methods=['GET', 'POST'])
@login_required
def suggest_novel():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        reason = request.form.get('reason', '').strip()
        if title:
            db.session.add(NovelSuggestion(user_id=current_user.id, title=title, reason=reason))
            db.session.commit()
            flash('✅ تم إرسال اقتراحك! شكراً لك', 'success')
            return redirect(url_for('suggest_novel'))
    return render_template('suggest.html')

@app.route('/join-publisher', methods=['GET', 'POST'])
@login_required
def join_publisher():
    existing = PublisherRequest.query.filter_by(user_id=current_user.id, status='approved').first()
    pending = PublisherRequest.query.filter_by(user_id=current_user.id, status='pending').first()
    if request.method == 'POST' and not existing and not pending:
        pen_name = request.form.get('pen_name', '').strip()
        bio = request.form.get('bio', '').strip()
        social = request.form.get('social_link', '').strip()
        if pen_name:
            db.session.add(PublisherRequest(user_id=current_user.id, pen_name=pen_name, bio=bio, social_link=social))
            db.session.commit()
            flash('✅ تم إرسال طلبك! سيتم مراجعته قريباً', 'success')
            return redirect(url_for('join_publisher'))
    return render_template('join_publisher.html', existing=existing, pending=pending)

@app.route('/dmca')
def dmca_page():
    return render_template('dmca.html')

@app.route('/admin/publishers')
@login_required
def admin_publishers():
    if not current_user.is_admin: return redirect(url_for('index'))
    try:
        pending = PublisherRequest.query.filter_by(status='pending').order_by(PublisherRequest.created_at.desc()).limit(50).all()
        approved = PublisherRequest.query.filter_by(status='approved').limit(50).all()
        return render_template('admin_publishers.html', pending=pending, approved=approved)
    except Exception as e:
        flash('خطأ في الناشرين: ' + str(e)[:200], 'danger')
        return redirect(url_for('index'))

@app.route('/admin/publishers/<int:req_id>/approve', methods=['POST'])
@login_required
def admin_approve_publisher(req_id):
    if not current_user.is_admin: return redirect(url_for('index'))
    req = PublisherRequest.query.get_or_404(req_id)
    req.status = 'approved'
    db.session.commit()
    flash(f'✅ تم قبول الناشر {req.pen_name}', 'success')
    return redirect(url_for('admin_publishers'))

@app.route('/admin/publishers/<int:req_id>/reject', methods=['POST'])
@login_required
def admin_reject_publisher(req_id):
    if not current_user.is_admin: return redirect(url_for('index'))
    req = PublisherRequest.query.get_or_404(req_id)
    req.status = 'rejected'
    db.session.commit()
    flash('❌ تم رفض الطلب', 'info')
    return redirect(url_for('admin_publishers'))

# ============ إعدادات الموقع (للأدمن فقط) ============
@app.route('/admin/settings', methods=['GET', 'POST'])
@login_required
def admin_settings():
    if not current_user.is_admin: return redirect(url_for('index'))
    if request.method == 'POST':
        for key in ['site_name', 'site_logo', 'site_description']:
            val = request.form.get(key, '').strip()
            s = SiteSettings.query.filter_by(key=key).first()
            if s:
                s.value = val
            else:
                db.session.add(SiteSettings(key=key, value=val))
        db.session.commit()
        flash('✅ تم حفظ الإعدادات', 'success')
        return redirect(url_for('admin_settings'))
    settings = {s.key: s.value for s in SiteSettings.query.all()}
    return render_template('admin_settings.html', settings=settings)

# ============ إدارة الاقتراحات (للأدمن) ============
@app.route('/admin/suggestions')
@login_required
def admin_suggestions():
    if not current_user.is_admin: return redirect(url_for('index'))
    try:
        suggestions = NovelSuggestion.query.order_by(NovelSuggestion.created_at.desc()).limit(50).all()
        return render_template('admin_suggestions.html', suggestions=suggestions)
    except Exception as e:
        flash('خطأ في الاقتراحات: ' + str(e)[:200], 'danger')
        return redirect(url_for('index'))

@app.route('/library')
def library():
    page = request.args.get('page', 1, type=int)
    q = request.args.get('q', '').strip()
    cat = request.args.get('cat', '').strip()
    status = request.args.get('status', '').strip()
    sort_by = request.args.get('sort', 'newest')

    query = Novel.query
    if q: query = query.filter(Novel.title.contains(q) | Novel.author.contains(q))
    if cat: query = query.filter(Novel.category == cat)
    if status: query = query.filter(Novel.status == status)

    if sort_by == 'newest': query = query.order_by(Novel.id.desc())
    elif sort_by == 'oldest': query = query.order_by(Novel.id.asc())

    novels = query.paginate(page=page, per_page=10, error_out=False)
    categories = [c[0] for c in db.session.query(Novel.category).distinct().all() if c[0]]
    statuses = ['مكتملة', 'مستمرة']

    return render_template('library.html', novels=novels, q=q, current_cat=cat, current_status=status, current_sort=sort_by, categories=categories, statuses=statuses)

with app.app_context():
    db.create_all()
    print('=' * 60, flush=True)
    print(f'🔍 DB URL: {app.config.get("SQLALCHEMY_DATABASE_URI", "N/A")[:70]}', flush=True)
    try:
        print(f'📊 Novels in DB: {Novel.query.count()}', flush=True)
    except Exception as e:
        print(f'❌ Novel count error: {e}', flush=True)
    print('=' * 60, flush=True)
    if not User.query.filter_by(username='kanaw').first():
        admin = User(username='kanaw', is_admin=True)
        admin.set_password('0594683283')
        db.session.add(admin)
        db.session.commit()
        print('✅ تم إنشاء حساب المشرف: kanaw')


@app.route('/debug-db')
def debug_db():
    try:
        count = Novel.query.count()
        db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', 'غير موجود')
        if '@' in db_uri:
            db_uri = 'postgresql://***@' + db_uri.split('@')[-1]
        return f"""
        <div dir='rtl' style='font-family:sans-serif;padding:20px;line-height:2;'>
            <h2>🔍 حالة قاعدة البيانات</h2>
            <p><strong>الرابط:</strong> {db_uri}</p>
            <p><strong>عدد الروايات:</strong> <span style='color:red;font-size:24px;'>{count}</span></p>
            <a href='/'>→ الرئيسية</a>
        </div>
        """
    except Exception as e:
        return f"<h2>❌ خطأ:</h2><pre>{e}</pre>"


@app.route('/debug-list')
def debug_list():
    try:
        novels = Novel.query.limit(10).all()
        html = "<div dir='rtl' style='padding:20px;font-family:sans-serif;'>"
        html += f"<h2>أول 10 روايات (إجمالي: {Novel.query.count()})</h2><ul>"
        for n in novels:
            html += f"<li>ID {n.id}: {n.title}</li>"
        html += "</ul><a href='/'>→ الرئيسية</a></div>"
        return html
    except Exception as e:
        return f"<h2>خطأ: {e}</h2>"


@app.route('/debug-home')
def debug_home():
    try:
        novels = Novel.query.paginate(page=1, per_page=24, error_out=False)
        html = "<div dir='rtl' style='padding:20px;font-family:sans-serif;'>"
        html += f"<h2>Debug Home</h2>"
        html += f"<p><b>Total novels:</b> {novels.total}</p>"
        html += f"<p><b>Pages:</b> {novels.pages}</p>"
        html += f"<p><b>Items on page 1:</b> {len(novels.items)}</p>"
        if novels.items:
            html += "<h3>First 5:</h3><ul>"
            for n in novels.items[:5]:
                html += f"<li>{n.title} (id={n.id})</li>"
            html += "</ul>"
        html += "<hr><a href='/'>→ الرئيسية</a></div>"
        return html
    except Exception as e:
        return f"<h2>❌ خطأ:</h2><pre>{e}</pre>"

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)