import requests
import time
import json
import sqlite3
from datetime import datetime, timedelta
import random
import os
import threading
from config import Config

# Test environment variables immediately
print(f"🔑 Bot token available: {'Yes' if Config.TELEGRAM_BOT_TOKEN else 'No'}")
print(f"💬 Chat ID available: {'Yes' if Config.TELEGRAM_CHAT_ID else 'No'}")
if Config.DISCORD_WEBHOOK_URL:
    print(f"📢 Discord webhook available: Yes")
else:
    print(f"📢 Discord webhook available: No")

class FutGGAPIExtinctMonitor:
    def __init__(self, db_path="fut_extinct_cards.db"):
        # Validate configuration on startup
        Config.validate_config()
        
        # For cloud deployment, try to use a persistent path
        if os.getenv('RENDER_EXTERNAL_HOSTNAME'):
            db_path = "/opt/render/project/src/fut_extinct_cards.db"
            print(f"🌐 Running on Render, using database path: {db_path}")
        else:
            print(f"🏠 Running locally, using database path: {db_path}")
        
        self.db_path = db_path
        
        # Test database write permissions
        try:
            test_conn = sqlite3.connect(self.db_path)
            test_conn.execute("CREATE TABLE IF NOT EXISTS test_table (id INTEGER)")
            test_conn.execute("INSERT INTO test_table (id) VALUES (1)")
            test_conn.execute("DROP TABLE test_table")
            test_conn.commit()
            test_conn.close()
            print("✅ Database write test successful")
        except Exception as e:
            print(f"⚠️ Database write test failed: {e}")
            self.db_path = "/tmp/fut_extinct_cards.db"
            print(f"📄 Using fallback database path: {self.db_path}")
        
        self.session = requests.Session()
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        ]
        self.init_database()
        self.startup_sent = False
        
        # API Configuration
        self.api_base_url = "https://www.fut.gg/api/fut"
        self.platform_id = "26"  # FIFA 26 platform ID
        self.batch_size = 50     # Number of player IDs to check per API call
    
    def rotate_user_agent(self):
        """Rotate user agent"""
        self.session.headers.update({
            'User-Agent': random.choice(self.user_agents)
        })
    
    def init_database(self):
        """Initialize SQLite database for API-based monitoring"""
        print(f"🔧 Initializing database at: {self.db_path}")
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS players (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ea_id INTEGER UNIQUE NOT NULL,
                    slug TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    overall INTEGER,
                    position TEXT,
                    club_name TEXT,
                    nation_name TEXT,
                    league_name TEXT,
                    last_checked TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS extinct_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ea_id INTEGER,
                    alert_sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    resolved_at TIMESTAMP NULL,
                    FOREIGN KEY (ea_id) REFERENCES players (ea_id)
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS price_checks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ea_id INTEGER,
                    is_extinct BOOLEAN,
                    price INTEGER,
                    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (ea_id) REFERENCES players (ea_id)
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS startup_locks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    startup_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    instance_id TEXT UNIQUE
                )
            ''')
            
            conn.commit()
            
            cursor.execute('SELECT COUNT(*) FROM players')
            existing_players = cursor.fetchone()[0]
            print(f"📊 Database initialized! Existing players: {existing_players}")
            
            conn.close()
            print("✅ Database initialization successful!")
            
        except Exception as e:
            print(f"❌ Database initialization failed: {e}")
            raise

    def check_and_send_startup_notification(self):
        """Send startup notification only once per deployment"""
        if self.startup_sent:
            return
        
        import uuid
        instance_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{os.getpid()}_{uuid.uuid4().hex[:8]}"
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO startup_locks (instance_id, startup_time)
                VALUES (?, ?)
            ''', (instance_id, datetime.now()))
            
            conn.commit()
            
            print(f"✅ Startup lock acquired: {instance_id}")
            
            self.send_notification_to_all(
                f"🚀 FUT.GG API Extinct Monitor Started!\n"
                f"⚡ Using native FUT.GG APIs for instant detection\n"
                f"🔍 Monitoring all players via price-sorted API\n"
                f"⏰ Check interval: Every 2-5 minutes\n"
                f"🎯 Instance: {instance_id[:12]}",
                "🚀 API Monitor Started"
            )
            
            self.startup_sent = True
            print("✅ Startup notification sent")
            
        except sqlite3.IntegrityError:
            print(f"⚠️ Another instance already started")
            self.startup_sent = True
        except Exception as e:
            print(f"Error with startup notification: {e}")
            self.startup_sent = True
        finally:
            try:
                conn.close()
            except:
                pass
    
    def fetch_players_from_api(self, page=1, sort="current_price"):
        """
        Fetch players using FUT.GG API with proper browser headers
        """
        try:
            self.rotate_user_agent()
            
            # Add browser-like headers to avoid detection
            headers = {
                'Accept': 'application/json, text/plain, */*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Referer': 'https://www.fut.gg/players/',
                'Origin': 'https://www.fut.gg',
                'Sec-Fetch-Dest': 'empty',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'same-origin',
            }
            self.session.headers.update(headers)
            
            url = f"{self.api_base_url}/players/v2/{self.platform_id}/"
            params = {
                "sorts": sort,
                "page": page
            }
            
            print(f"🌐 Fetching API page {page}: {url}")
            response = self.session.get(url, params=params, timeout=30)
            
            if response.status_code == 403:
                print(f"🚫 BLOCKED: FUT.GG/Cloudflare is blocking requests (403)")
                return None  # Return None to indicate blocking
            elif response.status_code == 429:
                print(f"⏰ RATE LIMITED: Too many requests (429)")
                return None
            elif response.status_code != 200:
                print(f"❌ API request failed: {response.status_code}")
                return []
            
            data = response.json()
            players_data = data.get('data', [])
            
            print(f"✅ API page {page}: Retrieved {len(players_data)} players")
            
            return players_data
            
        except Exception as e:
            print(f"Error fetching players from API: {e}")
            return []
    
    def check_prices_batch(self, ea_ids):
        """
        Check prices for a batch of player EA IDs using the price API
        """
        try:
            if not ea_ids:
                return {}
            
            self.rotate_user_agent()
            
            url = f"{self.api_base_url}/player-prices/{self.platform_id}/"
            params = {
                "ids": ",".join(map(str, ea_ids))
            }
            
            response = self.session.get(url, params=params)
            
            if response.status_code != 200:
                print(f"❌ Price API request failed: {response.status_code}")
                return {}
            
            data = response.json()
            price_data = data.get('data', [])
            
            # Convert to dictionary for easy lookup
            price_dict = {}
            for item in price_data:
                ea_id = item.get('eaId')
                is_extinct = item.get('isExtinct', False)
                price = item.get('price')
                
                price_dict[ea_id] = {
                    'is_extinct': is_extinct,
                    'price': price
                }
            
            print(f"✅ Price check: {len(price_dict)} players processed")
            
            return price_dict
            
        except Exception as e:
            print(f"Error checking prices: {e}")
            return {}
    
    def save_players_to_db(self, players_data):
        """Save players from API to database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        saved_count = 0
        for player in players_data:
            try:
                ea_id = player.get('eaId')
                slug = player.get('slug')
                first_name = player.get('firstName', '')
                last_name = player.get('lastName', '')
                overall = player.get('overall', 0)
                position = player.get('position', '')
                
                club_name = ''
                if player.get('club'):
                    club_name = player['club'].get('name', '')
                
                nation_name = ''
                if player.get('nation'):
                    nation_name = player['nation'].get('name', '')
                
                league_name = ''
                if player.get('league'):
                    league_name = player['league'].get('name', '')
                
                cursor.execute('''
                    INSERT OR REPLACE INTO players 
                    (ea_id, slug, first_name, last_name, overall, position, club_name, nation_name, league_name, last_checked)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (ea_id, slug, first_name, last_name, overall, position, club_name, nation_name, league_name, datetime.now()))
                
                if cursor.rowcount > 0:
                    saved_count += 1
                    
            except Exception as e:
                print(f"Error saving player {player.get('eaId')}: {e}")
        
        conn.commit()
        conn.close()
        return saved_count
    
    def sync_players_database(self, max_pages=100):
        """
        Sync players database with FUT.GG API data
        """
        print(f"🚀 Starting API player sync (max {max_pages} pages)...")
        
        total_saved = 0
        page = 1
        
        while page <= max_pages:
            try:
                print(f"📄 Syncing page {page}...")
                
                players_data = self.fetch_players_from_api(page, sort="current_price")
                
                if not players_data:
                    print(f"⚠️ No players returned from page {page}, stopping sync")
                    break
                
                saved = self.save_players_to_db(players_data)
                total_saved += saved
                
                print(f"✅ Page {page}: Saved {saved} players (total: {total_saved})")
                
                # Short delay between pages
                time.sleep(random.uniform(1, 2))
                page += 1
                
            except Exception as e:
                print(f"❌ Error on page {page}: {e}")
                page += 1
                continue
        
        print(f"🎉 Player sync complete! Total players saved: {total_saved}")
        
        self.send_notification_to_all(
            f"📊 Player database sync complete!\n"
            f"📄 Pages processed: {page-1}\n"
            f"💾 Players in database: {total_saved:,}\n"
            f"🔍 Starting extinct monitoring...",
            "📊 Database Synced"
        )
        
    def scrape_extinct_zone_players(self):
        """
        Scrape players from the extinct zone (dynamically determined pages)
        """
        print("🚀 Starting extinct zone scraping...")
        
        # Find the current extinct boundary
        last_extinct_page, total_extinct_estimated = self.find_extinct_boundary()
        
        if last_extinct_page == 0:
            print("⚠️ No extinct players found in current market")
            return 0
        
        # Now scrape all pages in the extinct zone
        total_saved = 0
        extinct_zone_cards = []
        
        for page in range(1, last_extinct_page + 1):
            try:
                print(f"📄 Scraping extinct zone page {page}/{last_extinct_page}...")
                
                cards = self.scrape_fut_gg_players_sorted(page)
                if cards:
                    # Only save cards that appear extinct
                    extinct_cards = [card for card in cards if card.get('appears_extinct', False)]
                    saved = self.save_cards_to_db(extinct_cards)
                    total_saved += saved
                    extinct_zone_cards.extend(extinct_cards)
                    
                    print(f"✅ Page {page}: Found {len(cards)} cards, {len(extinct_cards)} extinct, saved {saved} new")
                else:
                    print(f"⚠️ Page {page}: No cards found")
                
                # Short delay between pages
                time.sleep(random.uniform(1, 2))
                
            except Exception as e:
                print(f"❌ Error on extinct zone page {page}: {e}")
                continue
        
        print(f"🎉 Extinct zone scraping complete!")
        print(f"📊 Total extinct zone cards in database: {total_saved}")
        
        # Send notification about extinct zone discovery
        self.send_notification_to_all(
            f"🔍 Extinct Zone Analysis Complete!\n"
            f"📊 Found {total_extinct_estimated} extinct players across {last_extinct_page} pages\n"
            f"💾 Saved {total_saved} new cards to monitor\n"
            f"🎯 Now focusing monitoring on extinct zone players",
            "🔍 Extinct Zone Mapped"
        )
        
    def scrape_fut_gg_players(self, page_num=1):
        """
        Scrape players from fut.gg players page (regular unsorted)
        """
        try:
            self.rotate_user_agent()
            
            url = f'https://www.fut.gg/players/?page={page_num}'
            print(f"🌐 Fetching: {url}")
            response = self.session.get(url)
            
            if response.status_code != 200:
                print(f"❌ Failed to get page {page_num}: {response.status_code}")
                return []
            
            soup = BeautifulSoup(response.content, 'html.parser')
            cards = []
            
            # Look for player cards
            player_links = soup.find_all('a', href=lambda x: x and '/players/' in str(x))
            
            print(f"🔗 Found {len(player_links)} player links")
            
            if len(player_links) == 0:
                print("⚠️ WARNING: No player links found - website structure may have changed")
                return []
            
            # Extract unique players
            unique_players = {}
            for link in player_links:
                href = link.get('href', '')
                if href not in unique_players:
                    card_data = self.extract_player_data_from_link(link, soup)
                    if card_data:
                        unique_players[href] = card_data
            
            cards = list(unique_players.values())
            
            print(f"✅ Page {page_num}: Extracted {len(cards)} unique cards")
            
            return cards
            
        except Exception as e:
            print(f"Error scraping page {page_num}: {e}")
            return []
    
    def get_extinct_zone_cards_to_monitor(self, limit=50):
        """Get cards from database that are likely in the extinct zone"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Prioritize recently added cards (likely from extinct zone)
        cursor.execute('''
            SELECT id, name, rating, position, club, nation, league, fut_gg_url, fut_gg_id
            FROM cards 
            ORDER BY created_at DESC, RANDOM()
            LIMIT ?
        ''', (limit,))
        
        cards = []
        for row in cursor.fetchall():
            cards.append({
                'id': row[0], 'name': row[1], 'rating': row[2], 'position': row[3],
                'club': row[4], 'nation': row[5], 'league': row[6], 
                'fut_gg_url': row[7], 'fut_gg_id': row[8]
            })
        
        conn.close()
        return cards
    
    def get_players_to_monitor(self, limit=200):
        """Get players from database for monitoring"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get players, prioritizing those not checked recently
        cursor.execute('''
            SELECT ea_id, first_name, last_name, overall, position, club_name, nation_name
            FROM players 
            ORDER BY last_checked ASC NULLS FIRST, RANDOM()
            LIMIT ?
        ''', (limit,))
        
        players = []
        for row in cursor.fetchall():
            players.append({
                'ea_id': row[0],
                'name': f"{row[1]} {row[2]}".strip(),
                'overall': row[3],
                'position': row[4],
                'club': row[5],
                'nation': row[6]
            })
        
        conn.close()
        return players
    
    def log_price_check(self, ea_id, is_extinct, price):
        """Log price check result to database"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO price_checks (ea_id, is_extinct, price)
                VALUES (?, ?, ?)
            ''', (ea_id, is_extinct, price))
            
            # Update last checked time
            cursor.execute('''
                UPDATE players SET last_checked = ? WHERE ea_id = ?
            ''', (datetime.now(), ea_id))
            
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Error logging price check: {e}")
    
    def send_telegram_notification(self, message):
        """Send notification to Telegram"""
        url = f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {
            'chat_id': Config.TELEGRAM_CHAT_ID,
            'text': message,
            'parse_mode': 'HTML'
        }
        
        try:
            response = requests.post(url, data=data)
            if response.status_code == 200:
                print("✅ Telegram notification sent")
            else:
                print(f"❌ Telegram error: {response.status_code}")
        except Exception as e:
            print(f"❌ Telegram error: {e}")
    
    def send_discord_extinct_notification(self, player_info):
        """Send simple Discord notification for extinct players"""
        if not Config.DISCORD_WEBHOOK_URL:
            return
        
        embed = {
            "title": f"EXTINCT: {player_info['name']}",
            "description": f"Rating {player_info['overall']} - No longer available on market",
            "color": 0xff0000,
            "timestamp": datetime.now().isoformat(),
            "fields": [
                {
                    "name": "Status",
                    "value": "EXTINCT",
                    "inline": True
                },
                {
                    "name": "Rating", 
                    "value": str(player_info['overall']),
                    "inline": True
                }
            ]
        }
        
        payload = {
            "embeds": [embed]
        }
        
        try:
            response = requests.post(Config.DISCORD_WEBHOOK_URL, json=payload)
            if response.status_code == 204:
                print("✅ Discord extinct alert sent")
            else:
                print(f"❌ Discord error: {response.status_code}")
        except Exception as e:
            print(f"❌ Discord error: {e}")
    
    def send_discord_notification(self, message, title="FUT.GG API Monitor"):
        """Send general Discord notification"""
        if not Config.DISCORD_WEBHOOK_URL:
            return
        
        embed = {
            "title": title,
            "description": message,
            "color": 0x0099ff,
            "timestamp": datetime.now().isoformat()
        }
        
        payload = {
            "embeds": [embed]
        }
        
        try:
            response = requests.post(Config.DISCORD_WEBHOOK_URL, json=payload)
            if response.status_code == 204:
                print("✅ Discord notification sent")
            else:
                print(f"❌ Discord error: {response.status_code}")
        except Exception as e:
            print(f"❌ Discord error: {e}")
    
    def send_notification_to_all(self, message, title="FUT.GG API Monitor"):
        """Send notification to both platforms"""
        self.send_telegram_notification(message)
        self.send_discord_notification(message, title)
    
    def send_extinct_alert(self, player_info):
        """Send extinct player alert"""
        # Check if we already sent an alert recently
        alert_saved = self.save_extinct_alert(player_info['ea_id'])
        if not alert_saved:
            return
        
        # Telegram message
        telegram_message = f"""
🔥 <b>EXTINCT PLAYER DETECTED!</b> 🔥

🃏 <b>{player_info['name']}</b>
⭐ Rating: {player_info['overall']}
🏆 Position: {player_info.get('position', 'Unknown')}
🏟️ Club: {player_info.get('club', 'Unknown')}
🌍 Nation: {player_info.get('nation', 'Unknown')}

💰 <b>Status: EXTINCT</b>
📈 This player is not available on the market!
⚡ Perfect time to list if you have this card!

⏰ {datetime.now().strftime('%H:%M:%S')}

💡 <b>Action:</b> If you own this card, consider listing it now for maximum profit!
        """
        
        self.send_telegram_notification(telegram_message.strip())
        self.send_discord_extinct_notification(player_info)
        
        print(f"🔥 EXTINCT ALERT: {player_info['name']} ({player_info['overall']}) - Market extinct!")
    
    def save_extinct_alert(self, ea_id):
        """Save extinct alert and prevent duplicates"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Check if we already sent an alert recently (6 hours)
        cooldown_time = datetime.now() - timedelta(hours=Config.ALERT_COOLDOWN_HOURS)
        cursor.execute('''
            SELECT COUNT(*) FROM extinct_alerts 
            WHERE ea_id = ? AND alert_sent_at > ? AND resolved_at IS NULL
        ''', (ea_id, cooldown_time))
        
        recent_alerts = cursor.fetchone()[0]
        
        if recent_alerts > 0:
            print(f"⚠️ Extinct alert already sent for player {ea_id} recently, skipping...")
            conn.close()
            return False
        
        # Save new alert
        cursor.execute('''
            INSERT INTO extinct_alerts (ea_id)
            VALUES (?)
        ''', (ea_id,))
        
        conn.commit()
        conn.close()
        return True
    
    def run_extinct_monitoring(self):
        """Main monitoring loop using API"""
        print("🤖 Starting API-based extinct player monitoring...")
        
        cycle_count = 0
        consecutive_failures = 0
        
        while True:
            try:
                # Get players to monitor
                players = self.get_players_to_monitor(self.batch_size * 4)
                
                if not players:
                    consecutive_failures += 1
                    
                    if consecutive_failures <= 3:
                        print(f"❌ No players in database! Running sync... (attempt {consecutive_failures}/3)")
                        synced = self.sync_players_database(20)
                        
                        if synced == 0:
                            print(f"🚫 Sync failed - API access blocked. Waiting 10 minutes before retry...")
                            time.sleep(600)  # Wait 10 minutes
                            continue
                        else:
                            consecutive_failures = 0  # Reset on successful sync
                            continue
                    else:
                        print(f"🛑 STOPPING: Unable to sync database after {consecutive_failures} attempts")
                        self.send_notification_to_all(
                            f"🛑 Monitor stopped!\n"
                            f"❌ Unable to access FUT.GG API after multiple attempts\n"
                            f"🚫 API appears to be blocked\n"
                            f"💡 Consider using a VPS with different IP address",
                            "🛑 Monitor Stopped"
                        )
                        break
                
                print(f"🔍 Monitoring {len(players)} players for extinct status...")
                
                extinct_found = 0
                api_blocked = False
                
                # Process players in batches
                for i in range(0, len(players), self.batch_size):
                    batch = players[i:i + self.batch_size]
                    ea_ids = [p['ea_id'] for p in batch]
                    
                    # Check prices for this batch
                    price_results = self.check_prices_batch(ea_ids)
                    
                    # If price check failed (blocked), break out of monitoring
                    if price_results is None:  # Blocked
                        api_blocked = True
                        break
                    
                    # Process results
                    for player in batch:
                        ea_id = player['ea_id']
                        price_info = price_results.get(ea_id, {})
                        
                        is_extinct = price_info.get('is_extinct', False)
                        price = price_info.get('price')
                        
                        # Log the check
                        self.log_price_check(ea_id, is_extinct, price)
                        
                        # Send alert if extinct
                        if is_extinct:
                            self.send_extinct_alert(player)
                            extinct_found += 1
                    
                    # Delay between batches
                    time.sleep(random.uniform(2, 5))
                
                if api_blocked:
                    print(f"🚫 Price API blocked during monitoring. Waiting 10 minutes...")
                    time.sleep(600)  # Wait 10 minutes
                    continue
                
                cycle_count += 1
                consecutive_failures = 0  # Reset on successful monitoring
                
                if extinct_found > 0:
                    self.send_notification_to_all(
                        f"🔍 API monitoring cycle #{cycle_count} complete!\n"
                        f"📊 Checked {len(players)} players via API\n"
                        f"🔥 Found {extinct_found} extinct players\n"
                        f"⏰ Next check in 5-10 minutes",
                        "🔍 Cycle Complete"
                    )
                else:
                    print(f"🔍 Cycle #{cycle_count} complete - no extinct players found")
                
                # Wait 5-10 minutes before next check
                wait_time = random.uniform(300, 600)
                print(f"💤 Cycle #{cycle_count} complete. Found {extinct_found} extinct players. Waiting {wait_time/60:.1f} minutes...")
                time.sleep(wait_time)
                
            except KeyboardInterrupt:
                print("🛑 Monitoring stopped!")
                break
            except Exception as e:
                print(f"Monitoring error: {e}")
                time.sleep(120)  # Wait 2 minutes on general error
    
    def run_complete_system(self):
        """Run the complete API-based extinct monitoring system"""
        print("🚀 Starting FUT.GG API-based Extinct Player Monitor!")
        
        # Send startup notification
        self.check_and_send_startup_notification()
        
        # Check current database state
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM players')
        player_count = cursor.fetchone()[0]
        conn.close()
        
        print(f"📊 Current players in database: {player_count}")
        
        if Config.SKIP_SCRAPING and player_count > 0:
            print("⚠️ SKIP_SCRAPING enabled - using existing database")
            self.send_notification_to_all(
                f"✅ Using existing database with {player_count:,} players\n"
                f"⚡ Starting API-based extinct monitoring!",
                "🔍 API Monitoring Started"
            )
        elif player_count < 1000:
            print("🔄 Syncing player database from FUT.GG API...")
            self.sync_players_database(50)
        else:
            print(f"✅ Found {player_count:,} players in database")
            self.send_notification_to_all(
                f"✅ Database ready with {player_count:,} players\n"
                f"⚡ Starting API-based extinct monitoring!",
                "🔍 API Monitoring Started"
            )
        
        # Start API-based extinct monitoring
        print("🔥 Starting API-based extinct monitoring...")
        self.run_extinct_monitoring()

# Entry point
if __name__ == "__main__":
    monitor = FutGGAPIExtinctMonitor()
    monitor.run_complete_system()