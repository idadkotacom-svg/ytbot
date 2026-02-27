# Panduan Deployment di Render (menggunakan Docker)

Panduan ini berisi langkah-langkah untuk melakukan *deploy* (hosting) Telegram Bot YouTube Auto Uploader ke **Render.com** secara gratis. 
Kita akan menggunakan environment **Docker** agar pustaka pendukung seperti `ffmpeg` (dibutuhkan oleh fitur download yt-dlp) dapat terinstall dengan baik.

---

## 🚀 Langkah 1: Persiapan File Credentials (Wajib di Komputer Lokal Dulu)

Bot tidak bisa berjalan tanpa konfigurasi `.env` dan *file credentials* Google yang valid. Khusus untuk Render Docker, kita tidak bisa sekadar *drag-and-drop* file JSON. Kita harus mengubah file-file rahasia tersebut menjadi teks Base64 untuk dimasukkan ke sistem **Secret Files** milik Render.

1. **Pastikan Bot sudah pernah jalan sukses di komputermu.**
   Ini penting, karena kamu harus sudah melewati proses login browser Google Chrome agar file otorisasi `youtube_token_*.json` tercipta di dalam folder `credentials/`.

2. Buka terminal/command prompt di komputer kamu, jalankan perintah ini:
   ```bash
   python scripts/setup_credentials.py --encode
   ```
3. Script tersebut akan membaca semua file JSON di folder `credentials/` (seperti `service_account.json`, `client_secrets.json`, hingga semua `youtube_token_*.json`) lalu membuat file baru bernama **`render_env_vars.txt`** di folder utama kamu.
*(Perhatian: Jangan pernah meng-upload file ini ke GitHub karena berisi kunci rahasia)*

---

## ☁️ Langkah 2: Buat Web Service di Render
1. *Push* kode bot ini ke repository [GitHub](https://github.com/new). (Pastikan folder `credentials` dan file `render_env_vars.txt` **TIDAK** ikut ter-push).
2. Buka [Dashboard Render](https://dashboard.render.com).
3. Klik tombol **New** -> Pilih **Web Service**.
4. Hubungkan akun GitHub kamu dan pilih repository bot yang baru saja dibuat.
5. Isi konfigurasi dasar berikut:
   - **Name**: (Bebas, misal: `youtube-auto-bot`)
   - **Region**: (Pilih yang terdekat, misal: Singapore/Frankfurt)
   - **Branch**: `main`
   - **Environment**: Pilihlah **`Docker`** *(Sangat Penting! Jangan pilih Python 3)*.
   - **Instance Type**: `Free` (Gratis)

---

## 🔐 Langkah 3: Konfigurasi Environment Variables & Secrets di Render

### A. Environment Variables (Variabel Biasa)
Lihat di bagian **Environment Variables** lalu klik **Add Environment Variable**.

Masukkan variabel berikut sesuai isi `.env` lokal kamu:
| Key | Value |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Token bot dari BotFather |
| `TELEGRAM_CHAT_ID` | (Opsional) ID Telegram admin |
| `GROQ_API_KEY` | API Key dari Groq |
| `GOOGLE_SHEET_ID` | ID File Google Sheets kamu |
| `GOOGLE_DRIVE_FOLDER_ID` | ID Folder Google Drive |
| `YOUTUBE_CHANNELS` | Nama channel (misal: `default` atau `gaming, vlog`) |
| `RENDER` | `true` *(Penting!)* |

---

### B. Secret Files (File Kredensial Google Berbasis Base64)

Di sinilah file `render_env_vars.txt` yang kita buat di **Langkah 1** digunakan.

1. Scroll ke bawah ke bagian **Secret Files** dan klik **Add Secret File**.
2. **Filename**: ketik tepat `render_env_vars.txt`
3. **Contents**: Buka file `render_env_vars.txt` di komputermu, lalu *copy-paste* **seluruh isinya** ke dalam kotak ini.

> **💡 Mengapa pakai Secret Files begini?** Saat container Docker dijalankan di cloud Render nanti, file `Dockerfile` sudah mengatur sebuah script khusus untuk membaca file `render_env_vars.txt` ini dan me-restore kembali semua teks Base64 tersebut menjadi file-file JSON asli (seperti `youtube_token_xxx.json`, `client_secrets_xxx.json`) ke dalam folder `credentials/` di dalam server. 

---

## 🌐 Langkah 4: Trik Mencegah Render (Free Tier) Tidur / Sleep
Render tipe Free Web Service akan "tidur" (spin down) jika tidak menerima traffic web (HTTP) selama 15 menit. Karena bot ini berbasis Telegram Webhook Polling dan *scheduler*, ia perlu terus hidup.

Untuk mencegahnya tertidur:
1. Setelah Render selesai *deploy*, copy URL public aplikasi milikmu (contoh: `https://youtube-auto-bot.onrender.com`).
2. Gunakan layanan *ping* gratis (seperti [cron-job.org](https://cron-job.org) atau uptime robot).
3. Buat job di *cron-job.org* untuk mengunjungi URL Render milikmu setiap **14 menit**.
   *(Error 404/502 dari browser tidak masalah, karena trafficnya sudah cukup untuk membangunkan server).*

---

## ✅ Selesai!
Klik **Create Web Service** / **Save Changes** di Render. Sistem akan otomatis mem-build Docker image (menginstall `ffmpeg` dan `Python 3.13`) lalu menjalankan botmu. Kamu bisa memantau semuanya di tab **Logs** dashboard.
