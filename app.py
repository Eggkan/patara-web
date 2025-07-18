import os
import sqlite3
import json
import logging
import secrets
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, g
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import pandas as pd

# ------------------------------------------------------------------------------
# 1. GLOBAL AYARLAR VE YARDIMCI FONKSİYONLAR
# ------------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "caretta_web.db")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ------------------------------------------------------------------------------
# 2. UYGULAMA VE VERİTABANI KURULUMU
# ------------------------------------------------------------------------------
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(16))


def get_db_connection():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_connection(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS kullanicilar (
            id INTEGER PRIMARY KEY,
            kullanici_adi TEXT UNIQUE NOT NULL,
            sifre_hash TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS yuvalar (
            id INTEGER NOT NULL, yil INTEGER NOT NULL, kumsal TEXT, bolge TEXT,
            yuva_tarihi TEXT NOT NULL, notlar TEXT, lat REAL NOT NULL, lon REAL NOT NULL,
            sicaklik_aleti TEXT, ilk_yavru_cikis_tarihi TEXT, kulucka_suresi INTEGER,
            kuru_kum_uzaklik REAL, yari_islak_kum_uzaklik REAL, islak_kum_uzaklik REAL,
            toplam_denize_uzaklik REAL, tasinma_durumu TEXT, predasyon_durumu TEXT, marka TEXT,
            predasyon_tarihi_1 TEXT, predatorler_1 TEXT, predasyon_yumurta_sayisi_1 INTEGER,
            predasyon_tarihi_2 TEXT, predatorler_2 TEXT, predasyon_yumurta_sayisi_2 INTEGER,
            predasyon_tarihi_3 TEXT, predatorler_3 TEXT, predasyon_yumurta_sayisi_3 INTEGER,
            yuva_derinligi_cm REAL, yuva_capi_cm REAL, yuva_ici_canli_yavru INTEGER,
            yuva_ici_olu_yavru INTEGER, erken_donem_embriyo INTEGER, orta_donem_embriyo INTEGER,
            gec_donem_embriyo INTEGER, toplam_olu_embriyo INTEGER, bos_kabuk_sayisi INTEGER,
            predasyonlu_yumurta_sayisi INTEGER, dollenmemis_yumurta_sayisi INTEGER,
            toplam_yumurta_sayisi INTEGER, yuva_basarisi_yuzde REAL,
            PRIMARY KEY (id, yil)
        )
    """)
    default_password = '12345'
    hashed_pass = generate_password_hash(default_password, method='pbkdf2:sha256')
    for i in range(1, 11):
        username = f"admin{i}"
        cursor.execute("SELECT 1 FROM kullanicilar WHERE kullanici_adi = ?", (username,))
        if cursor.fetchone() is None:
            cursor.execute("INSERT INTO kullanicilar (kullanici_adi, sifre_hash) VALUES (?, ?)",
                           (username, hashed_pass))
            logging.info(f"Varsayılan kullanıcı '{username}' (şifre: {default_password}) oluşturuldu.")
    conn.commit()
    conn.close()


# ------------------------------------------------------------------------------
# 3. FLASK-LOGIN KURULUMU
# ------------------------------------------------------------------------------
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = "Lütfen devam etmek için giriş yapın."
login_manager.login_message_category = "info"


class Kullanici(UserMixin):
    def __init__(self, user_id, kullanici_adi):
        self.id = user_id
        self.kullanici_adi = kullanici_adi


@login_manager.user_loader
def load_user(user_id):
    user_data = get_db_connection().execute("SELECT * FROM kullanicilar WHERE id = ?", (user_id,)).fetchone()
    return Kullanici(user_id=user_data['id'], kullanici_adi=user_data['kullanici_adi']) if user_data else None


# ------------------------------------------------------------------------------
# 4. VERİ FONKSİYONLARI
# ------------------------------------------------------------------------------
def yuva_var_mi(id, yil):
    result = get_db_connection().execute("SELECT 1 FROM yuvalar WHERE id = ? AND yil = ?", (id, yil)).fetchone()
    return result is not None


def tum_yuvalari_getir():
    return [dict(row) for row in
            get_db_connection().execute("SELECT * FROM yuvalar ORDER BY yil DESC, id DESC").fetchall()]


# ------------------------------------------------------------------------------
# 5. ROUTE'LAR VE API ENDPOINT'LERİ
# ------------------------------------------------------------------------------
@app.route('/')
@login_required
def anasayfa():
    return render_template('index.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated: return redirect(url_for('anasayfa'))
    if request.method == 'POST':
        k_adi = request.form.get('kullanici_adi')
        sifre = request.form.get('sifre')
        user_data = get_db_connection().execute("SELECT * FROM kullanicilar WHERE kullanici_adi = ?",
                                                (k_adi,)).fetchone()
        if user_data and check_password_hash(user_data['sifre_hash'], sifre):
            login_user(Kullanici(user_id=user_data['id'], kullanici_adi=user_data['kullanici_adi']))
            return redirect(request.args.get('next') or url_for('anasayfa'))
        else:
            flash('Kullanıcı adı veya şifre yanlış.', 'danger')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Başarıyla çıkış yaptınız.', 'success')
    return redirect(url_for('login'))


@app.route('/api/yuvalar')
@login_required
def api_tum_yuvalari_getir():
    try:
        return jsonify({'success': True, 'yuvalar': tum_yuvalari_getir()})
    except Exception as e:
        logging.error(f"Hata - /api/yuvalar: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'Sunucu tarafında bir hata oluştu.'})


@app.route('/api/yuva_ekle', methods=['POST'])
@login_required
def api_yuva_ekle():
    try:
        data = request.form
        yuva_id = int(data.get('id'));
        yuva_tarihi = data.get('yuva_tarihi')
        lat = float(data.get('lat'));
        lon = float(data.get('lon'))
        if not all([yuva_id, yuva_tarihi, lat, lon]):
            return jsonify({'success': False, 'message': 'Lütfen tüm zorunlu alanları (*) doldurun.'})
        yuva_yil = int(yuva_tarihi.split('-')[0])
        if yuva_var_mi(yuva_id, yuva_yil):
            return jsonify({'success': False, 'message': f'{yuva_yil} yılı için {yuva_id} ID\'li yuva zaten mevcut.'})

        get_int = lambda key: int(v) if (v := data.get(key)) else None
        get_float = lambda key: float(v) if (v := data.get(key)) else None
        get_str = lambda key: v if (v := data.get(key)) else None

        canli_yavru = get_int('yuva_ici_canli_yavru')
        toplam_yumurta = get_int('toplam_yumurta_sayisi')
        yuva_basarisi = round((canli_yavru / toplam_yumurta * 100),
                              2) if canli_yavru and toplam_yumurta and toplam_yumurta > 0 else None

        yuva_data = {"id": yuva_id, "yil": yuva_yil, "yuva_tarihi": yuva_tarihi, "lat": lat, "lon": lon,
                     "kumsal": get_str('kumsal'), "bolge": get_str('bolge'), "notlar": get_str('notlar'),
                     "sicaklik_aleti": get_str('sicaklik_aleti'),
                     "ilk_yavru_cikis_tarihi": get_str('ilk_yavru_cikis_tarihi'),
                     "kulucka_suresi": get_int('kulucka_suresi'), "kuru_kum_uzaklik": get_float('kuru_kum_uzaklik'),
                     "yari_islak_kum_uzaklik": get_float('yari_islak_kum_uzaklik'),
                     "islak_kum_uzaklik": get_float('islak_kum_uzaklik'),
                     "toplam_denize_uzaklik": get_float('toplam_denize_uzaklik'),
                     "tasinma_durumu": get_str('tasinma_durumu'), "predasyon_durumu": get_str('predasyon_durumu'),
                     "marka": get_str('marka'), "predasyon_tarihi_1": get_str('predasyon_tarihi_1'),
                     "predatorler_1": get_str('predatorler_1'),
                     "predasyon_yumurta_sayisi_1": get_int('predasyon_yumurta_sayisi_1'),
                     "predasyon_tarihi_2": get_str('predasyon_tarihi_2'), "predatorler_2": get_str('predatorler_2'),
                     "predasyon_yumurta_sayisi_2": get_int('predasyon_yumurta_sayisi_2'),
                     "predasyon_tarihi_3": get_str('predasyon_tarihi_3'), "predatorler_3": get_str('predatorler_3'),
                     "predasyon_yumurta_sayisi_3": get_int('predasyon_yumurta_sayisi_3'),
                     "yuva_derinligi_cm": get_float('yuva_derinligi_cm'), "yuva_capi_cm": get_float('yuva_capi_cm'),
                     "yuva_ici_canli_yavru": canli_yavru, "yuva_ici_olu_yavru": get_int('yuva_ici_olu_yavru'),
                     "erken_donem_embriyo": get_int('erken_donem_embriyo'),
                     "orta_donem_embriyo": get_int('orta_donem_embriyo'),
                     "gec_donem_embriyo": get_int('gec_donem_embriyo'),
                     "toplam_olu_embriyo": get_int('toplam_olu_embriyo'),
                     "bos_kabuk_sayisi": get_int('bos_kabuk_sayisi'),
                     "predasyonlu_yumurta_sayisi": get_int('predasyonlu_yumurta_sayisi'),
                     "dollenmemis_yumurta_sayisi": get_int('dollenmemis_yumurta_sayisi'),
                     "toplam_yumurta_sayisi": toplam_yumurta, "yuva_basarisi_yuzde": yuva_basarisi}

        sutunlar = ', '.join(yuva_data.keys());
        isaretler = ', '.join(['?' for _ in yuva_data])
        conn = get_db_connection()
        conn.execute(f"INSERT INTO yuvalar ({sutunlar}) VALUES ({isaretler})", list(yuva_data.values()))
        conn.commit()
        return jsonify({'success': True, 'message': 'Yuva başarıyla eklendi!', 'yuvalar': tum_yuvalari_getir()})
    except (ValueError, TypeError) as e:
        return jsonify({'success': False, 'message': 'Lütfen sayısal alanlara doğru formatta veri girin.'})
    except Exception as e:
        logging.error(f"Hata - /api/yuva_ekle: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'Sunucu tarafında bir hata oluştu.'})


@app.route('/api/yuva_sil', methods=['POST'])
@login_required
def api_yuva_sil():
    try:
        data = request.get_json()
        conn = get_db_connection()
        conn.execute('DELETE FROM yuvalar WHERE id = ? AND yil = ?', (int(data['id']), int(data['yil'])))
        conn.commit()
        return jsonify({'success': True, 'message': 'Yuva başarıyla silindi!', 'yuvalar': tum_yuvalari_getir()})
    except Exception as e:
        logging.error(f"Hata - /api/yuva_sil: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'Sunucu tarafında bir hata oluştu.'})


@app.route('/api/durum_guncelle', methods=['POST'])
@login_required
def api_durum_guncelle():
    try:
        conn = get_db_connection()
        conn.execute('UPDATE yuvalar SET predasyon_durumu = ? WHERE id = ? AND yil = ?',
                     (request.form.get('durum'), int(request.form.get('id')), int(request.form.get('yil'))))
        conn.commit()
        return jsonify({'success': True, 'message': 'Durum başarıyla güncellendi!', 'yuvalar': tum_yuvalari_getir()})
    except Exception as e:
        logging.error(f"Hata - /api/durum_guncelle: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'Sunucu tarafında bir güncelleme hatası oluştu.'})


@app.route('/api/ozet_rapor')
@login_required
def api_ozet_rapor():
    try:
        df = pd.read_sql_query("SELECT * FROM yuvalar", get_db_connection())
        if df.empty:
            return jsonify({'success': True,
                            'html': '<div class="alert alert-warning text-center">Analiz edilecek veri bulunamadı.</div>'})
        toplam_yuva = len(df)
        basari_degerleri = pd.to_numeric(df.get('yuva_basarisi_yuzde'), errors='coerce').dropna()
        ortalama_basari = basari_degerleri.mean() if not basari_degerleri.empty else 0
        predasyonlu_sayisi = len(df[df['predasyon_durumu'].isin(['tam', 'yari'])])
        predasyon_orani = (predasyonlu_sayisi / toplam_yuva) * 100 if toplam_yuva > 0 else 0
        html_rapor = f"""<h4>Genel Veri Özeti</h4><table class="table table-bordered table-striped"><tbody>
                    <tr><td>Toplam Kayıtlı Yuva Sayısı</td><td><b>{toplam_yuva}</b></td></tr>
                    <tr><td>Ortalama Yuva Başarısı</td><td><b>% {ortalama_basari:.2f}</b></td></tr>
                    <tr><td>Predasyonlu Yuva Sayısı</td><td><b>{predasyonlu_sayisi}</b></td></tr>
                    <tr><td>Predasyon Oranı</td><td><b>% {predasyon_orani:.2f}</b></td></tr></tbody></table>
                    <p class="text-muted small mt-2">Not: Ortalama yuva başarısı, 'Yuva Başarısı (%)' değeri girilmiş yuvalar üzerinden hesaplanmıştır.</p>"""
        return jsonify({'success': True, 'html': html_rapor})
    except Exception as e:
        logging.error(f"Hata - /api/ozet_rapor: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'Rapor oluşturulurken bir sunucu hatası oluştu.'})


@app.route('/api/yillari_getir')
@login_required
def api_yillari_getir():
    try:
        yillar_data = get_db_connection().execute("SELECT DISTINCT yil FROM yuvalar ORDER BY yil DESC").fetchall()
        return jsonify({'success': True, 'yillar': [row['yil'] for row in yillar_data]})
    except Exception as e:
        logging.error(f"Hata - /api/yillari_getir: {e}", exc_info=True)
        return jsonify({'success': False, 'yillar': []})


@app.route('/api/karsilastir')
@login_required
def api_karsilastir():
    try:
        yil1, yil2 = int(request.args.get('yil1')), int(request.args.get('yil2'))
        df = pd.read_sql_query("SELECT * FROM yuvalar", get_db_connection())

        def hesapla(df_grup):
            if df_grup.empty: return {"Toplam Yuva": "0", "Ortalama Başarı": "N/A", "Predasyon Oranı": "N/A"}
            stats = {"Toplam Yuva": str(len(df_grup))}
            basari_degerleri = pd.to_numeric(df_grup.get('yuva_basarisi_yuzde'), errors='coerce').dropna()
            basari = basari_degerleri.mean() if not basari_degerleri.empty else 'N/A'
            stats["Ortalama Başarı"] = f"% {basari:.2f}" if isinstance(basari, (int, float)) else "N/A"
            pred_sayi = len(df_grup[df_grup['predasyon_durumu'].isin(['tam', 'yari'])])
            stats["Predasyon Oranı"] = f"% {(pred_sayi / len(df_grup)) * 100:.2f}" if len(df_grup) > 0 else "N/A"
            return stats

        stats1, stats2 = hesapla(df[df['yil'] == yil1]), hesapla(df[df['yil'] == yil2])
        html = f"""<table class="table table-bordered text-center table-hover"><thead class="table-light">
                    <tr><th>Ölçüm</th><th>{yil1} Yılı</th><th>{yil2} Yılı</th></tr></thead><tbody>
                    <tr><td>Toplam Yuva</td><td>{stats1['Toplam Yuva']}</td><td>{stats2['Toplam Yuva']}</td></tr>
                    <tr><td>Ortalama Başarı</td><td>{stats1['Ortalama Başarı']}</td><td>{stats2['Ortalama Başarı']}</td></tr>
                    <tr><td>Predasyon Oranı</td><td>{stats1['Predasyon Oranı']}</td><td>{stats2['Predasyon Oranı']}</td></tr>
                    </tbody></table>"""
        return jsonify({'success': True, 'html': html})
    except Exception as e:
        logging.error(f"Karşılaştırma hatası: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'Karşılaştırma sırasında bir hata oluştu.'})


# ------------------------------------------------------------------------------
# 6. UYGULAMAYI BAŞLATMA
# ------------------------------------------------------------------------------
if __name__ == '__main__':
    with app.app_context():
        init_db()
    app.run(debug=True, port=5001)