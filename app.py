# app.py (Web interface + background worker for FUT.GG Extinct Monitor)
from flask import Flask, render_template, jsonify, send_file, request
import threading
import time
import os
import sys
from datetime import datetime
import sqlite3

app = Flask(__name__)

# Global monitor instance
monitor = None
monitor_thread = None
is_running = False

def run_complete_system(self):
    """Run the complete extinct monitoring system using dynamic extinct zone detection"""
    print("🚀 Starting FUT.GG Extinct Player Monitor with Dynamic Zone Detection!")
    print("🐛 DEBUG: run_complete_system called")
    sys.stdout.flush()
    
    # Test mode - just try a simple request to fut.gg
    if os.getenv('TEST_MODE') == 'true':
        print("🧪 TEST MODE: Testing basic fut.gg connectivity...")
        sys.stdout.flush()
        try:
            import requests
            print("🧪 TEST: Making request to fut.gg...")
            sys.stdout.flush()
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            }
            
            response = requests.get('https://www.fut.gg/players/?page=1', headers=headers, timeout=15)
            print(f"🧪 TEST: fut.gg responded with status {response.status_code}")
            print(f"🧪 TEST: Response length: {len(response.content)} bytes")
            sys.stdout.flush()
            
            # Test if we can find any player links
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.content, 'html.parser')
            player_links = soup.find_all('a', href=lambda x: x and '/players/' in str(x))
            print(f"🧪 TEST: Found {len(player_links)} player links")
            sys.stdout.flush()
            
            # Test price-sorted page
            print("🧪 TEST: Testing price-sorted page...")
            sys.stdout.flush()
            
            sorted_response = requests.get('https://www.fut.gg/players/?page=1&sorts=current_price', headers=headers, timeout=15)
            print(f"🧪 TEST: Price-sorted page status: {sorted_response.status_code}")
            sys.stdout.flush()
            
            if len(player_links) == 0:
                print("❌ TEST FAILED: No player links found - fut.gg may be blocking us or structure changed")
                print("🔄 FALLBACK: Switching to existing HTML scraping method")
                sys.stdout.flush()
                # Continue with fallback method
            else:
                print("✅ TEST PASSED: fut.gg is accessible and has player data")
                sys.stdout.flush()
                
        except Exception as e:
            print(f"❌ TEST FAILED: Cannot access fut.gg - {e}")
            print("🔄 FALLBACK: Switching to existing HTML scraping method")
            sys.stdout.flush()
            import traceback
            traceback.print_exc()
            sys.stdout.flush()
    
    # Send startup notification
    print("🐛 DEBUG: About to send startup notification")
    sys.stdout.flush()
    self.check_and_send_startup_notification()
    print("🐛 DEBUG: Startup notification sent")
    sys.stdout.flush()
    
    # Check current database state
    print("🐛 DEBUG: Checking database state")
    sys.stdout.flush()
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM cards')
    card_count = cursor.fetchone()[0]
    conn.close()
    
    print(f"📊 Current cards in database: {card_count}")
    sys.stdout.flush()
    
    # Check if we should skip scraping
    skip_scraping = os.getenv('SKIP_SCRAPING', 'false').lower() == 'true'
    
    if skip_scraping and card_count > 0:
        print("⚠️ SKIP_SCRAPING enabled - using existing database")
        sys.stdout.flush()
        self.send_notification_to_all(
            f"✅ Using existing database with {card_count:,} cards\n"
            f"🎯 Starting dynamic extinct zone monitoring!",
            "🎯 Zone Monitoring Started"
        )
    elif card_count < 100:
        print("📄 Database needs players - starting extinct zone scraping...")
        sys.stdout.flush()
        
        # Use try/except to handle missing methods gracefully
        try:
            print("🐛 DEBUG: Attempting extinct zone scraping...")
            sys.stdout.flush()
            scraped = self.scrape_extinct_zone_players()
            # Ensure scraped is a number
            scraped = scraped if scraped is not None else 0
            print(f"🐛 DEBUG: Extinct zone scraping returned: {scraped}")
            sys.stdout.flush()
        except AttributeError:
            print("⚠️ scrape_extinct_zone_players method not found, using fallback")
            sys.stdout.flush()
            scraped = self.scrape_all_players(int(os.getenv('MAX_PAGES_TO_SCRAPE', 10)))
            scraped = scraped if scraped is not None else 0
            print(f"🐛 DEBUG: Fallback scraping returned: {scraped}")
            sys.stdout.flush()
        except Exception as e:
            print(f"⚠️ Error during scraping: {e}")
            sys.stdout.flush()
            import traceback
            traceback.print_exc()
            sys.stdout.flush()
            print("🔄 Trying fallback HTML scraping...")
            sys.stdout.flush()
            try:
                scraped = self.scrape_all_players(5)  # Just scrape 5 pages as fallback
                scraped = scraped if scraped is not None else 0
                print(f"🐛 DEBUG: Emergency fallback returned: {scraped}")
                sys.stdout.flush()
            except Exception as e2:
                print(f"❌ Emergency fallback also failed: {e2}")
                sys.stdout.flush()
                scraped = 0
            
        if scraped > 0:
            print(f"✅ Scraped {scraped} players from extinct zone. Starting monitoring...")
            sys.stdout.flush()
        else:
            print("⚠️ No players scraped - will try monitoring anyway")
            sys.stdout.flush()
    else:
        print(f"✅ Found {card_count:,} cards in database")
        sys.stdout.flush()
        self.send_notification_to_all(
            f"✅ Database ready with {card_count:,} cards\n"
            f"🎯 Starting dynamic extinct zone monitoring!",
            "🎯 Zone Monitoring Started"
        )
    
    # Start the monitoring - use try/except for this too
    print("🔥 Starting dynamic extinct zone monitoring...")
    sys.stdout.flush()
    try:
        print("🐛 DEBUG: About to call monitor_extinct_zone()")
        sys.stdout.flush()
        self.monitor_extinct_zone()
        print("🐛 DEBUG: monitor_extinct_zone() returned")
        sys.stdout.flush()
    except AttributeError:
        print("⚠️ monitor_extinct_zone method not found, using fallback monitoring")
        sys.stdout.flush()
        self.run_extinct_monitoring()  # Use existing method as fallback
    except Exception as e:
        print(f"⚠️ Error in monitoring: {e}")
        sys.stdout.flush()
        import traceback
        traceback.print_exc()
        sys.stdout.flush()
        # Try fallback monitoring method
        print("🔄 Trying fallback monitoring...")
        sys.stdout.flush()
        try:
            self.run_extinct_monitoring()
        except Exception as e2:
            print(f"❌ Fallback monitoring also failed: {e2}")
            sys.stdout.flush()
            
@app.route('/')
def home():
    """Simple web interface to check status"""
    return '''
    <html>
    <head><title>FUT.GG Extinct Player Monitor</title></head>
    <body style="font-family: Arial; max-width: 800px; margin: 50px auto; padding: 20px;">
        <h1>🔥 FUT.GG Extinct Player Monitor</h1>
        <p>Your bot is monitoring fut.gg for extinct players!</p>
        
        <div style="background: #f5f5f5; padding: 20px; margin: 20px 0; border-radius: 8px;">
            <h3>📊 Status</h3>
            <p id="status">Loading...</p>
            <button onclick="checkStatus()" style="padding: 10px 20px; background: #007cba; color: white; border: none; border-radius: 4px; cursor: pointer;">
                Refresh Status
            </button>
        </div>
        
        <div style="background: #e8f4f8; padding: 20px; margin: 20px 0; border-radius: 8px;">
            <h3>⚙️ Configuration</h3>
            <p><strong>Target:</strong> Extinct players on FUT.GG</p>
            <p><strong>Check Interval:</strong> Every 5-10 minutes</p>
            <p><strong>Alert Cooldown:</strong> 6 hours per card</p>
            <p><strong>Monitoring:</strong> Dynamic extinct zone detection</p>
        </div>
        
        <div style="background: #f0f8e8; padding: 20px; margin: 20px 0; border-radius: 8px;">
            <h3>📱 Alerts</h3>
            <p>Extinct player notifications are sent to your Telegram and Discord!</p>
            <p>Recent alerts will appear in your configured channels.</p>
        </div>
        
        <div style="background: #e8f0ff; padding: 20px; margin: 20px 0; border-radius: 8px;">
            <h3>💾 Database Backup</h3>
            <p><strong>Cards in Database:</strong> <span id="card-count">Loading...</span></p>
            <div style="margin: 15px 0;">
                <a href="/download-db" style="padding: 10px 20px; background: #28a745; color: white; text-decoration: none; border-radius: 4px; margin-right: 10px;">
                    Download Database Backup
                </a>
                <a href="/upload-db" style="padding: 10px 20px; background: #007cba; color: white; text-decoration: none; border-radius: 4px;">
                    Upload Database
                </a>
            </div>
            <p style="font-size: 0.9em; color: #666;">
                Download your database before making changes to preserve player data.
            </p>
        </div>
        
        <div style="background: #fff3cd; padding: 20px; margin: 20px 0; border-radius: 8px; border: 1px solid #ffeaa7;">
            <h3>🔧 Debug Info</h3>
            <p><strong>Monitor Thread Running:</strong> <span id="thread-status">Unknown</span></p>
            <p><strong>Environment Check:</strong> <span id="env-status">Checking...</span></p>
            <p><strong>Debug Mode:</strong> Enhanced logging enabled</p>
        </div>
        
        <div style="background: #e3f2fd; padding: 20px; margin: 20px 0; border-radius: 8px;">
            <h3>🎯 Extinct Zone Detection</h3>
            <p>Using dynamic price-sorted monitoring to focus on pages where extinct players appear first.</p>
            <p><strong>Strategy:</strong> Monitor pages 1-40 of price-sorted list where extinct players concentrate</p>
        </div>
        
        <script>
            function checkStatus() {
                fetch('/status')
                    .then(response => response.json())
                    .then(data => {
                        document.getElementById('status').innerHTML = 
                            '<strong>Monitor Status:</strong> ' + (data.running ? '🟢 Running' : '🔴 Stopped') + '<br>' +
                            '<strong>Cards in Database:</strong> ' + data.card_count + '<br>' +
                            '<strong>Last Update:</strong> ' + data.last_update;
                        
                        document.getElementById('card-count').innerHTML = data.card_count.toLocaleString();
                        document.getElementById('thread-status').innerHTML = data.running ? '🟢 Yes' : '🔴 No';
                        document.getElementById('env-status').innerHTML = data.env_check;
                    });
            }
            
            // Auto-refresh every 30 seconds
            setInterval(checkStatus, 30000);
            checkStatus(); // Initial load
        </script>
    </body>
    </html>
    '''

@app.route('/download-db')
def download_db():
    """Download the current database file"""
    try:
        # Check if database exists and has data
        if not os.path.exists('fut_extinct_cards.db'):
            return "No database file found", 404
        
        # Check if database has cards
        conn = sqlite3.connect('fut_extinct_cards.db')
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM cards')
        card_count = cursor.fetchone()[0]
        conn.close()
        
        if card_count == 0:
            return "Database is empty - no cards to download", 400
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'fut_extinct_cards_backup_{timestamp}.db'
        
        return send_file('fut_extinct_cards.db', 
                        as_attachment=True, 
                        download_name=filename,
                        mimetype='application/octet-stream')
    
    except Exception as e:
        return f"Error downloading database: {str(e)}", 500

@app.route('/upload-db', methods=['GET', 'POST'])
def upload_db():
    """Upload a database file to restore data"""    
    if request.method == 'GET':
        return '''
        <html>
        <head><title>Upload Database</title></head>
        <body style="font-family: Arial; max-width: 600px; margin: 50px auto; padding: 20px;">
            <h1>Upload Database Backup</h1>
            <p>Upload a previously downloaded database file to restore your player data.</p>
            
            <form method="POST" enctype="multipart/form-data">
                <div style="margin: 20px 0;">
                    <label for="database">Select Database File (.db):</label><br>
                    <input type="file" name="database" accept=".db" required style="margin: 10px 0;">
                </div>
                <div style="margin: 20px 0;">
                    <input type="submit" value="Upload Database" 
                           style="padding: 10px 20px; background: #28a745; color: white; border: none; border-radius: 4px; cursor: pointer;">
                </div>
            </form>
            
            <div style="background: #fff3cd; padding: 15px; margin: 20px 0; border-radius: 5px;">
                <strong>Warning:</strong> This will replace your current database. Make sure to download a backup first if needed.
            </div>
            
            <a href="/">← Back to Dashboard</a>
        </body>
        </html>
        '''
    
    try:
        if 'database' not in request.files:
            return "No file uploaded", 400
        
        file = request.files['database']
        if file.filename == '':
            return "No file selected", 400
        
        if file and file.filename.endswith('.db'):
            # Save uploaded file as the main database
            file.save('fut_extinct_cards.db')
            
            # Verify the uploaded database
            conn = sqlite3.connect('fut_extinct_cards.db')
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM cards')
            card_count = cursor.fetchone()[0]
            conn.close()
            
            return f'''
            <html>
            <head><title>Upload Success</title></head>
            <body style="font-family: Arial; max-width: 600px; margin: 50px auto; padding: 20px;">
                <h1>✅ Database Uploaded Successfully!</h1>
                <p>Restored database with <strong>{card_count:,}</strong> cards.</p>
                <p>The bot will now use this data for extinct monitoring.</p>
                <a href="/">← Back to Dashboard</a>
            </body>
            </html>
            '''
        else:
            return "Invalid file type. Please upload a .db file.", 400
            
    except Exception as e:
        return f"Error uploading database: {str(e)}", 500

@app.route('/status')
def status():
    """API endpoint to check bot status"""
    try:
        # Check database
        try:
            conn = sqlite3.connect('fut_extinct_cards.db')
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM cards')
            card_count = cursor.fetchone()[0]
            conn.close()
        except:
            card_count = 0
        
        # Check environment variables
        telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
        telegram_chat = os.getenv('TELEGRAM_CHAT_ID')
        
        env_check = "✅ OK" if telegram_token and telegram_chat else "❌ Missing tokens"
        
        return jsonify({
            'running': is_running,
            'card_count': card_count,
            'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC'),
            'env_check': env_check,
            'has_token': bool(telegram_token),
            'has_chat_id': bool(telegram_chat),
            'debug_mode': True
        })
    except Exception as e:
        return jsonify({
            'running': False,
            'card_count': 0,
            'last_update': 'Error: ' + str(e),
            'env_check': '❌ Error',
            'has_token': False,
            'has_chat_id': False,
            'debug_mode': True
        })

@app.route('/health')
def health():
    """Health check for uptime monitoring"""
    return "OK", 200

@app.route('/logs')  
def logs():
    """Simple logs viewer"""
    return f"""
    <h1>Recent Activity</h1>
    <p>Monitor Running: {'🟢 Yes' if is_running else '🔴 No'}</p>
    <p>Debug Mode: Enabled with enhanced logging</p>
    <p>Check the Render logs for detailed information including extinct zone detection progress.</p>
    <a href="/">← Back to Dashboard</a>
    """

def keep_alive():
    """Ping self to prevent Render from sleeping"""
    while True:
        try:
            import requests
            hostname = os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'localhost')
            if hostname != 'localhost':
                requests.get(f"https://{hostname}/health", timeout=10)
                print("📍 Keep-alive ping sent")
                sys.stdout.flush()
        except Exception as e:
            print(f"Keep-alive error: {e}")
            sys.stdout.flush()
        time.sleep(600)  # Ping every 10 minutes

if __name__ == '__main__':
    print("🚀 Starting Flask app with extinct monitor...")
    sys.stdout.flush()
    
    # Start monitor in background thread
    print("📄 Starting monitor thread...")
    sys.stdout.flush()
    monitor_thread = threading.Thread(target=start_monitor, daemon=True)
    monitor_thread.start()
    
    # Start keep-alive thread
    print("📄 Starting keep-alive thread...")
    sys.stdout.flush()
    keepalive_thread = threading.Thread(target=keep_alive, daemon=True)
    keepalive_thread.start()
    
    # Start Flask web interface
    port = int(os.environ.get('PORT', 5000))
    print(f"🌐 Starting web server on port {port}...")
    sys.stdout.flush()
    app.run(host='0.0.0.0', port=port, debug=False)
