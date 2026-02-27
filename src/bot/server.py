import os
import time
import requests
import json
from threading import Thread
from flask import Flask, request, jsonify, render_template, redirect, url_for, session, send_from_directory

app = Flask(__name__)
# Try to get a persistent secret key for sessions, fallback to random if not available
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "bocils-admin-dashboard-secret-1234")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "rahasia123")

# We will import these lazy-loaded so it doesn't break initialization
def get_sheets():
    from src.main import get_sheets as gs
    return gs()

def get_drive():
    from src.main import get_drive as gd
    return gd()


def require_auth(f):
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    # Give the wrapper the generic name of the original function so Flask route binding works
    decorated.__name__ = f.__name__
    return decorated


@app.route('/')
def home():
    return "Bot is alive and web server is running!"

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if request.form['password'] == ADMIN_PASSWORD:
            session['logged_in'] = True
            next_url = request.args.get('next')
            return redirect(next_url or url_for('admin_dashboard'))
        else:
            error = 'Password salah.'
    
    return f"""
    <html>
    <head><title>Login Admin</title><meta name="viewport" content="width=device-width, initial-scale=1"></head>
    <body style="font-family: Arial, sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; background: #f0f2f5;">
        <div style="background: white; padding: 2rem; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); width: 100%; max-width: 400px;">
            <h2 style="text-align: center; color: #1a73e8; margin-bottom: 1.5rem;">YT Bot Admin</h2>
            {f'<p style="color: red; text-align: center;">{error}</p>' if error else ''}
            <form method="post" style="display: flex; flex-direction: column; gap: 1rem;">
                <input type="password" name="password" placeholder="Masukkan Password Admin..." required style="padding: 0.8rem; border: 1px solid #ddd; border-radius: 4px; font-size: 1rem;">
                <button type="submit" style="background: #1a73e8; color: white; border: none; padding: 0.8rem; border-radius: 4px; font-size: 1rem; cursor: pointer; font-weight: bold;">Login Masuk</button>
            </form>
        </div>
    </body>
    </html>
    """

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('home'))

@app.route('/admin')
@require_auth
def admin_dashboard():
    # Will look for templates/admin.html
    # We will pass all videos from google sheets
    try:
        from src.core import config
        sheets = get_sheets()
        videos = sheets.get_all_videos()
        return render_template('admin.html', videos=videos, channels=config.YOUTUBE_CHANNELS)
    except Exception as e:
        return f"Gagal mengambil antrean video: {e}", 500

@app.route('/api/action', methods=['POST'])
@require_auth
def admin_action():
    try:
        data = request.json
        action = data.get('action') # approve, reject, edit
        row = data.get('row')
        
        if not action or not row:
            return jsonify({'success': False, 'message': 'Missing data'}), 400
            
        sheets = get_sheets()
        
        # Action: Approve
        if action == 'approve':
            sheets.update_status(row, 'pending') # Re-confirm it as pending to be picked up by scheduler
            return jsonify({'success': True, 'message': 'Video disetujui untuk di-upload.'})
            
        # Action: Reject
        elif action == 'reject':
            # Needs file_id to delete from drive
            file_link = data.get('drive_link')
            
            # Step 1: Delete from drive if link exists
            if file_link and "id=" in file_link:
                try:
                    file_id = file_link.split("id=")[1]
                    drive = get_drive()
                    drive.delete(file_id)
                except Exception as de:
                    print(f"Failed to delete from drive: {de}")
                    
            # Step 2: Delete row from sheets
            sheets.delete_row(row)
            return jsonify({'success': True, 'message': 'Video ditolak dan dihapus dari Drive & Sheet.'})
            
        # Action: Edit
        elif action == 'edit':
            title = data.get('title', '')
            desc = data.get('description', '')
            tags = data.get('tags', '')
            channel = data.get('channel')
            sheets.update_metadata(row, title, desc, tags, channel=channel)
            return jsonify({'success': True, 'message': 'Metadata video berhasil diperbarui.'})
            
        else:
            return jsonify({'success': False, 'message': 'Aksi tidak valid.'}), 400
            
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

def run():
    port = int(os.environ.get("PORT", 8080))
    # Render requires binding to 0.0.0.0
    app.run(host='0.0.0.0', port=port)

def ping_self():
    """Pings the web service periodically to keep Render from sleeping."""
    # Look for the URL Render gives us, or default to localhost if testing
    url = os.environ.get("RENDER_EXTERNAL_URL")
    if not url:
        print("No RENDER_EXTERNAL_URL found, self-ping requires external URL or just skipping if local.")
        return
        
    print(f"Starting self-ping loop targeting {url} every 14 minutes...")
    while True:
        try:
            # 14 minutes = 840 seconds
            time.sleep(840)
            
            # Send a simple GET request to wake the server up
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                print(f"[Keep-Alive] Pinged {url} successfully.")
            else:
                print(f"[Keep-Alive] Ping {url} returned status {response.status_code}.")
        except Exception as e:
            print(f"[Keep-Alive] Error pinging {url}: {e}")

def keep_alive():
    """Starts a simple web server and an internal ping background thread to keep Render active."""
    # 1. Start Web Server
    t = Thread(target=run)
    t.daemon = True
    t.start()
    
    # 2. Start Self-Ping
    p = Thread(target=ping_self)
    p.daemon = True
    p.start()
