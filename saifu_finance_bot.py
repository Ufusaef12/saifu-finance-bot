"""
SaifuFinanceBot - Telegram bot (Python)

Fitur:
- /start, /help
- /catat -> format terstruktur (jumlah, jenis, kategori, deskripsi)
- Menyimpan ke Google Sheets: Spreadsheet "SaifuFinance Data", sheet "Transaksi"
- /laporan mingguan dan /laporan bulanan (ringkasan teks & CSV attachment)
- /tips mengirimkan tips keuangan acak

Catatan setup:
1) Letakkan file credential Google Cloud (service account) dengan nama:
   saifu-finance-bot-credential.json
   di folder yang sama dengan script ini (atau atur path di variabel CREDENTIALS_FILE).
2) Export token bot di environment variable: BOT_TOKEN
   Contoh (Linux): export BOT_TOKEN="123:ABC..."
3) Install dependencies:
   pip install python-telegram-bot==13.15 gspread oauth2client pandas

Deploy: script ini dapat dijalankan di hosting seperti Render/Railway/VPS.
Pastikan environment variable BOT_TOKEN dan file credential tersedia di container.

"""

import os
import logging
from datetime import datetime, timedelta
import csv
import io
import random

import gspread
from oauth2client.service_account import ServiceAccountCredentials

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, Bot
from telegram.ext import (Updater, CommandHandler, MessageHandler, Filters,
                          ConversationHandler, CallbackContext)

# ---------- Konfigurasi ----------
SPREADSHEET_NAME = "SaifuFinance Data"
SHEET_NAME = "Transaksi"
CREDENTIALS_FILE = "saifu-finance-bot-credential.json"  # sesuai permintaan kamu
BOT_TOKEN_ENV = "BOT_TOKEN"

# Conversation states
JUMLAH, JENIS, KATEGORI, DESKRIPSI, KONFIRM = range(5)

# Setup logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Tips keuangan sederhana
TIPS = [
    "Buat anggaran mingguan dan patuhi batasnya.",
    "Sisihkan minimal 10% pemasukan setiap bulan untuk tabungan darurat.",
    "Catat pengeluaran harian — kebiasaan kecil tampak besar di akhir bulan.",
    "Bandingkan harga sebelum membeli barang bernilai besar.",
    "Bayar tagihan tepat waktu untuk menghindari denda.",
]

# ---------- Google Sheets helper ----------

def init_gspread():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)
    sheet = client.open(SPREADSHEET_NAME).worksheet(SHEET_NAME)
    return sheet


def append_transaction(sheet, row):
    """Row is a list matching columns: tanggal, jenis, jumlah, kategori, deskripsi, user_id"""
    try:
        sheet.append_row(row)
        return True
    except Exception as e:
        logger.exception("Gagal menulis ke Google Sheets: %s", e)
        return False


def read_all_transactions(sheet):
    try:
        records = sheet.get_all_records()
        return records
    except Exception as e:
        logger.exception("Gagal membaca sheet: %s", e)
        return []

# ---------- Bot command handlers ----------

def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "Halo! Aku SaifuFinanceBot. Kita bisa catat pemasukan & pengeluaranmu.\n"
        "Ketik /catat untuk mulai masukkan transaksi, atau /help untuk daftar perintah.")


def help_cmd(update: Update, context: CallbackContext):
    update.message.reply_text(
        "/catat - Catat transaksi (format terstruktur)\n"
        "/laporan minggu - Ringkasan mingguan\n"
        "/laporan bulan - Ringkasan bulanan\n"
        "/tips - Dapat tips keuangan acak\n"
        "/sheet - Dapatkan link ke Google Sheet-mu (harus tersedia share)")

# ----- Conversation for /catat -----

def catat_start(update: Update, context: CallbackContext):
    update.message.reply_text("Masukin jumlah (tanpa tanda, contoh: 20000):", reply_markup=ReplyKeyboardRemove())
    return JUMLAH


def catat_jumlah(update: Update, context: CallbackContext):
    text = update.message.text.strip().replace(',', '')
    if not text.replace('.', '').isdigit():
        update.message.reply_text("Jumlah tidak valid. Masukin angka saja, contoh: 20000")
        return JUMLAH
    context.user_data['jumlah'] = float(text)
    reply_keyboard = [['pemasukan', 'pengeluaran']]
    update.message.reply_text("Jenis transaksi? (pemasukan / pengeluaran)", reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True))
    return JENIS


def catat_jenis(update: Update, context: CallbackContext):
    jenis = update.message.text.strip().lower()
    if jenis not in ('pemasukan', 'pengeluaran'):
        update.message.reply_text("Pilih 'pemasukan' atau 'pengeluaran'.")
        return JENIS
    context.user_data['jenis'] = jenis
    update.message.reply_text("Kategori (contoh: makan, transport, gaji, jualan):")
    return KATEGORI


def catat_kategori(update: Update, context: CallbackContext):
    kategori = update.message.text.strip()
    context.user_data['kategori'] = kategori
    update.message.reply_text("Deskripsi singkat (opsional):")
    return DESKRIPSI


def catat_deskripsi(update: Update, context: CallbackContext):
    deskripsi = update.message.text.strip()
    context.user_data['deskripsi'] = deskripsi

    jumlah = context.user_data.get('jumlah')
    jenis = context.user_data.get('jenis')
    kategori = context.user_data.get('kategori')

    summary = f"Konfirmasi: {jenis} Rp{int(jumlah)} - {kategori} - {deskripsi if deskripsi else '-'}\n\nKetik 'ya' untuk konfirmasi atau 'batal' untuk batalkan."
    update.message.reply_text(summary)
    return KONFIRM


def catat_konfirm(update: Update, context: CallbackContext):
    text = update.message.text.strip().lower()
    if text not in ('ya', 'y', 'yes'):
        update.message.reply_text('Transaksi dibatalkan.')
        return ConversationHandler.END

    sheet = init_gspread()
    now = datetime.utcnow().isoformat()`
    # Google Sheets columns: Tanggal, Jenis, Jumlah, Kategori, Deskripsi, User
    row = [datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'), context.user_data['jenis'], int(context.user_data['jumlah']), context.user_data['kategori'], context.user_data['deskripsi'], update.message.from_user.id]
    ok = append_transaction(sheet, row)
    if ok:
        update.message.reply_text('Sukses! Transaksi tersimpan ke Google Sheets.')
    else:
        update.message.reply_text('Gagal menyimpan transaksi. Coba lagi nanti.')
    return ConversationHandler.END


def cancel(update: Update, context: CallbackContext):
    update.message.reply_text('Oke, dibatalkan.', reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# ----- Laporan -----

def generate_summary(records, since_date):
    total_pemasukan = 0
    total_pengeluaran = 0
    by_category = {}

    for r in records:
        try:
            t = r.get('Tanggal') or r.get('tanggal') or r.get('Timestamp')
            if not t:
                continue
            dt = datetime.strptime(t, '%Y-%m-%d %H:%M:%S') if ' ' in t else datetime.strptime(t, '%Y-%m-%d')
            if dt < since_date:
                continue
            jenis = r.get('Jenis') or r.get('jenis') or r.get('Jenis (Pemasukan/Pengeluaran)')
            jumlah = float(r.get('Jumlah') or r.get('jumlah') or 0)
            kategori = r.get('Kategori') or r.get('kategori') or 'Lain-lain'
            if jenis and jenis.lower().startswith('pemasukan'):
                total_pemasukan += jumlah
            else:
                total_pengeluaran += jumlah
                by_category[kategori] = by_category.get(kategori, 0) + jumlah
        except Exception:
            continue

    return total_pemasukan, total_pengeluaran, by_category


def laporan_minggu(update: Update, context: CallbackContext):
    sheet = init_gspread()
    records = read_all_transactions(sheet)
    since = datetime.utcnow() - timedelta(days=7)
    pemasukan, pengeluaran, by_cat = generate_summary(records, since)
    text = f"Ringkasan 7 hari terakhir:\nPemasukan: Rp{int(pemasukan)}\nPengeluaran: Rp{int(pengeluaran)}\nSaldo bersih: Rp{int(pemasukan-pengeluaran)}\n\nTop kategori pengeluaran:\n"
    items = sorted(by_cat.items(), key=lambda x: x[1], reverse=True)[:5]
    if items:
        for k, v in items:
            text += f"- {k}: Rp{int(v)}\n"
    else:
        text += "Tidak ada pengeluaran tercatat.\n"

    # kirim ringkasan
    update.message.reply_text(text)

    # kirim CSV sebagai lampiran
    csvbuf = io.StringIO()
    writer = csv.writer(csvbuf)
    writer.writerow(['Tanggal', 'Jenis', 'Jumlah', 'Kategori', 'Deskripsi', 'User'])
    for r in records:
        t = r.get('Tanggal') or r.get('tanggal') or ''
        writer.writerow([t, r.get('Jenis') or r.get('jenis') or '', r.get('Jumlah') or r.get('jumlah') or '', r.get('Kategori') or r.get('kategori') or '', r.get('Deskripsi') or r.get('deskripsi') or '', r.get('User') or r.get('user') or ''])
    csvbuf.seek(0)
    update.message.reply_document(document=io.BytesIO(csvbuf.getvalue().encode('utf-8')), filename='laporan_mingguan.csv')


def laporan_bulan(update: Update, context: CallbackContext):
    sheet = init_gspread()
    records = read_all_transactions(sheet)
    since = datetime.utcnow() - timedelta(days=30)
    pemasukan, pengeluaran, by_cat = generate_summary(records, since)
    text = f"Ringkasan 30 hari terakhir:\nPemasukan: Rp{int(pemasukan)}\nPengeluaran: Rp{int(pengeluaran)}\nSaldo bersih: Rp{int(pemasukan-pengeluaran)}\n\nTop kategori pengeluaran:\n"
    items = sorted(by_cat.items(), key=lambda x: x[1], reverse=True)[:10]
    if items:
        for k, v in items:
            text += f"- {k}: Rp{int(v)}\n"
    else:
        text += "Tidak ada pengeluaran tercatat.\n"

    update.message.reply_text(text)

    # kirim CSV
    csvbuf = io.StringIO()
    writer = csv.writer(csvbuf)
    writer.writerow(['Tanggal', 'Jenis', 'Jumlah', 'Kategori', 'Deskripsi', 'User'])
    for r in records:
        t = r.get('Tanggal') or r.get('tanggal') or ''
        writer.writerow([t, r.get('Jenis') or r.get('jenis') or '', r.get('Jumlah') or r.get('jumlah') or '', r.get('Kategori') or r.get('kategori') or '', r.get('Deskripsi') or r.get('deskripsi') or '', r.get('User') or r.get('user') or ''])
    csvbuf.seek(0)
    update.message.reply_document(document=io.BytesIO(csvbuf.getvalue().encode('utf-8')), filename='laporan_bulanan.csv')

# ----- Tips -----

def tips_cmd(update: Update, context: CallbackContext):
    tip = random.choice(TIPS)
    update.message.reply_text(f"Tip keuangan: {tip}")

# ----- Link sheet -----

def sheet_link(update: Update, context: CallbackContext):
    try:
        client = gspread.authorize(ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']))
        ss = client.open(SPREADSHEET_NAME)
        url = ss.url
        update.message.reply_text(f"Link Google Sheet: {url}\nPastikan sheet sudah di-share ke service account (kamu sudah lakukan sebelumnya).")
    except Exception as e:
        logger.exception("Gagal dapatkan link: %s", e)
        update.message.reply_text("Gagal mendapatkan link spreadsheet. Cek credential dan nama spreadsheet.")

# ----- main -----

def main():
    token = os.environ.get(BOT_TOKEN_ENV)
    if not token:
        logger.error('BOT_TOKEN environment variable belum diset. Keluar.')
        return

    updater = Updater(token, use_context=True)
    dp = updater.dispatcher

    # Conversation handler untuk /catat
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('catat', catat_start)],
        states={
            JUMLAH: [MessageHandler(Filters.text & ~Filters.command, catat_jumlah)],
            JENIS: [MessageHandler(Filters.text & ~Filters.command, catat_jenis)],
            KATEGORI: [MessageHandler(Filters.text & ~Filters.command, catat_kategori)],
            DESKRIPSI: [MessageHandler(Filters.text & ~Filters.command, catat_deskripsi)],
            KONFIRM: [MessageHandler(Filters.text & ~Filters.command, catat_konfirm)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    dp.add_handler(CommandHandler('start', start))
    dp.add_handler(CommandHandler('help', help_cmd))
    dp.add_handler(conv_handler)
    dp.add_handler(CommandHandler('laporan_minggu', laporan_minggu))
    dp.add_handler(CommandHandler('laporan_bulan', laporan_bulan))
    dp.add_handler(CommandHandler('tips', tips_cmd))
    dp.add_handler(CommandHandler('sheet', sheet_link))

    updater.start_polling()
    logger.info('Bot berjalan...')
    updater.idle()


if __name__ == '__main__':
    main()
