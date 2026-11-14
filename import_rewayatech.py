import os
import random
from app import app, db, Novel, Chapter

TEXT_DIR = os.path.join('Rewayatech-Saudi-Stories', 'TextFiles')
CATEGORIES = ['فانتازيا', 'أكشن', 'خيال علمي', 'رومانسية', 'غموض']

def split_text(text, chunk_size=15000):
    chapters = []
    for i, start in enumerate(range(0, len(text), chunk_size), 1):
        chunk = text[start:start + chunk_size].strip()
        if len(chunk) > 500:
            chapters.append((i, f'الجزء {i}', chunk))
    return chapters

def import_rewayatech():
    with app.app_context():
        db.create_all()
        
        if not os.path.exists(TEXT_DIR):
            print(f'❌ المجلد غير موجود: {TEXT_DIR}')
            return
        
        files = [f for f in os.listdir(TEXT_DIR) if f.endswith('.txt')]
        print(f'📚 تم العثور على {len(files)} رواية\n')
        
        added = 0
        for idx, filename in enumerate(files, 1):
            title = filename.replace('.txt', '').strip()
            
            if Novel.query.filter_by(title=title).first():
                continue
            
            filepath = os.path.join(TEXT_DIR, filename)
            try:
                # فتح الملف مع تخطي أي أحرف مشفرة خاطئة
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                if len(content) < 1000:
                    continue
                
                # اختيار تصنيف عشوائي لتنويع المكتبة
                category = random.choice(CATEGORIES)
                
                novel = Novel(
                    title=title,
                    author='مؤلف مجهول', 
                    category=category,
                    status='مكتملة',
                    source='rewayatech',
                    description=f'رواية ويب من أرشيف Rewayatech - تصنيف {category}'
                )
                db.session.add(novel)
                db.session.commit()
                
                chapters = split_text(content)
                for num, ch_title, ch_content in chapters:
                    db.session.add(Chapter(
                        novel_id=novel.id,
                        number=num,
                        title=ch_title,
                        content=ch_content
                    ))
                db.session.commit()
                
                added += 1
                if added % 10 == 0:
                    print(f'✅ تم استيراد {added} رواية...')
                
            except Exception as e:
                db.session.rollback()
                print(f'❌ {title}: {str(e)[:50]}')
        
        print(f'\n🎉 انتهى الاستيراد! تمت إضافة {added} رواية جديدة.')
        print(f'📊 إجمالي الروايات في الموقع: {Novel.query.count()}')

if __name__ == '__main__':
    import_rewayatech()