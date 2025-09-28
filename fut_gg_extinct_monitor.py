import requests
import time
import json
import sys
import sqlite3
from datetime import datetime, timedelta
import random
from bs4 import BeautifulSoup
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

class FutGGExtinctMonitor:
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
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
        ]
        self.init_database()
        self.startup_sent = False
    
    def rotate_user_agent(self):
        """Rotate user agent to avoid detection"""
        self.session.headers.update({
            'User-Agent': random.choice(self.user_agents)
        })
    
    def init_database(self):
        """Initialize SQLite database for tracking extinct players"""
        print(f"🔧 Initializing database at: {self.db_path}")
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS extinct_players (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    rating INTEGER,
                    fut_gg_url TEXT UNIQUE NOT NULL,
                    status TEXT DEFAULT 'extinct',
                    first_detected TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_checked TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status_changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    alert_sent BOOLEAN DEFAULT 0
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS startup_locks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    startup_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    instance_id TEXT UNIQUE
                )
            ''')
            
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_url ON extinct_players(fut_gg_url)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_status ON extinct_players(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_last_checked ON extinct_players(last_checked)')
            
            conn.commit()
            
            cursor.execute('SELECT COUNT(*) FROM extinct_players')
            existing_players = cursor.fetchone()[0]
            print(f"📊 Database initialized! Existing tracked players: {existing_players}")
            
            conn.close()
            print("✅ Database initialization successful!")
            
        except Exception as e:
            print(f"❌ Database initialization failed: {e}")
            import traceback
            traceback.print_exc()
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
                f"🤖 FUT.GG Extinct Monitor Started!\n"
                f"🎯 Using smart prioritization & market analysis\n"
                f"⚡ Running on cloud infrastructure\n"
                f"⏰ Check interval: 3 minutes\n"
                f"🔒 Instance: {instance_id[:12]}",
                "🚀 Extinct Monitor Started"
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

    def discover_extinct_players(self, max_pages=None):
        """Discover extinct players and store them in database"""
        print("🔍 Discovering extinct players...")
        discovered_count = 0
        page = 1
        consecutive_no_new_players = 0
        
        while True:
            if max_pages and page > max_pages:
                print(f"Reached maximum page limit ({max_pages}), stopping discovery")
                break
            if page > 200:
                print("Reached safety limit of 200 pages, stopping discovery")
                break
                
            url = f"https://www.fut.gg/players/?page={page}&price__lte=0"
            
            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                }
                
                response = requests.get(url, headers=headers, timeout=30)
                response.raise_for_status()
                
                soup = BeautifulSoup(response.content, 'html.parser')
                player_links = soup.find_all('a', href=lambda x: x and '/players/' in str(x))
                
                if not player_links:
                    consecutive_no_new_players += 1
                    print(f"Page {page}: No player links found (empty page)")
                    
                    if consecutive_no_new_players >= 3:
                        print(f"Found 3 consecutive empty pages, stopping discovery at page {page}")
                        break
                    
                    page += 1
                    time.sleep(random.uniform(1, 2))
                    continue
                
                page_discovered = 0
                
                for link in player_links:
                    try:
                        href = link.get('href', '')
                        if not href or '/players/' not in href:
                            continue
                        
                        if href.startswith('/'):
                            fut_gg_url = f"https://www.fut.gg{href}"
                        else:
                            fut_gg_url = href
                        
                        img = link.find('img', alt=lambda x: x and ' - ' in str(x))
                        if not img:
                            container = link.find_parent(['div', 'article', 'section'])
                            if container:
                                img = container.find('img', alt=lambda x: x and ' - ' in str(x))
                        
                        if img:
                            alt_text = img.get('alt', '')
                            parts = alt_text.split(' - ')
                            
                            if len(parts) >= 2:
                                player_name = parts[0].strip()
                                try:
                                    rating = int(parts[1].strip())
                                except ValueError:
                                    continue
                                
                                if self.store_extinct_player(player_name, rating, fut_gg_url):
                                    discovered_count += 1
                                    page_discovered += 1
                    
                    except Exception as e:
                        continue
                
                print(f"Page {page}: Discovered {page_discovered} new extinct players")
                
                if page_discovered == 0:
                    consecutive_no_new_players += 1
                    if consecutive_no_new_players >= 10:
                        print(f"Found 10 consecutive pages with no new players, stopping discovery")
                        break
                else:
                    consecutive_no_new_players = 0
                
                page += 1
                time.sleep(random.uniform(1, 2))
                
            except Exception as e:
                print(f"Error discovering extinct players on page {page}: {e}")
                consecutive_no_new_players += 1
                page += 1
                time.sleep(random.uniform(2, 4))
                continue
        
        print(f"🎯 Discovery complete! Found {discovered_count} new extinct players across {page-1} pages")
        return discovered_count

    def get_additional_player_info(self, fut_gg_url):
        """Get additional player info by parsing the player page HTML"""
        try:
            headers = {
                'User-Agent': random.choice(self.user_agents),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
            }
            
            response = requests.get(fut_gg_url, headers=headers, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            info = {}
            
            paper_div = soup.find('div', class_='paper !bg-darker-gray mb-4 !p-4 hidden md:block')
            
            if paper_div:
                flex_containers = paper_div.find_all('div', class_='flex justify-between')
                flex_containers.extend(paper_div.find_all('div', class_='flex justify-between flex-row mt-2'))
                
                for container in flex_containers:
                    label_div = container.find('div', class_='text-lighter-gray')
                    if label_div:
                        label_text = label_div.get_text(strip=True)
                        
                        if label_text == 'Club':
                            club_container = label_div.find_next_sibling('div')
                            if club_container:
                                club_link = club_container.find('a')
                                if club_link:
                                    club_name = club_link.get_text(strip=True)
                                    if club_name:
                                        info['club'] = club_name
                                else:
                                    club_text = club_container.get_text(strip=True)
                                    if club_text:
                                        info['club'] = club_text
                        
                        elif label_text == 'Nation':
                            nation_container = label_div.find_next_sibling('div')
                            if nation_container:
                                nation_link = nation_container.find('a')
                                if nation_link:
                                    nation_name = nation_link.get_text(strip=True)
                                    if nation_name:
                                        info['nation'] = nation_name
            
            page_text = soup.get_text()
            positions = ['GK', 'ST', 'CF', 'LW', 'RW', 'CAM', 'CM', 'CDM', 'LB', 'RB', 'CB', 'LWB', 'RWB', 'RM', 'LM']
            for pos in positions:
                if f' {pos} ' in f' {page_text} ' or f'\n{pos}\n' in page_text:
                    info['position'] = pos
                    break
            
            return info
            
        except Exception as e:
            print(f"Error getting additional player info: {e}")
            return {}

    def store_extinct_player(self, name, rating, fut_gg_url):
        """Store extinct player in database and get additional info, return True if new"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                conn = sqlite3.connect(self.db_path, timeout=30.0)
                cursor = conn.cursor()
                
                cursor.execute('SELECT id FROM extinct_players WHERE fut_gg_url = ?', (fut_gg_url,))
                if cursor.fetchone():
                    conn.close()
                    return False
                
                additional_info = {}
                try:
                    print(f"📄 Getting player details for {name}...")
                    additional_info = self.get_additional_player_info(fut_gg_url)
                except Exception as e:
                    print(f"⚠️ Could not get additional info for {name}: {e}")
                    pass
                
                club_name = additional_info.get('club', 'Unknown')
                position = additional_info.get('position', 'Unknown')
                
                print(f"✅ Trusting filtered URL: {name} is extinct")
                
                cursor.execute('''
                    INSERT OR IGNORE INTO extinct_players (name, rating, fut_gg_url, status, alert_sent)
                    VALUES (?, ?, ?, 'extinct', 1)
                ''', (name, rating, fut_gg_url))
                
                if cursor.rowcount > 0:
                    conn.commit()
                    conn.close()
                    
                    print(f"🔥 NEW EXTINCTION: {name} ({rating}) - {club_name}")
                    
                    self.send_extinction_alert({
                        'name': name,
                        'rating': rating,
                        'fut_gg_url': fut_gg_url,
                        'club': club_name,
                        'position': position
                    })
                    
                    return True
                else:
                    conn.close()
                    return False
                
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    print(f"Database locked, retrying {attempt + 1}/{max_retries}...")
                    time.sleep(random.uniform(0.5, 2.0))
                    continue
                else:
                    print(f"Database error storing extinct player {name}: {e}")
                    return False
            except sqlite3.IntegrityError as e:
                if "UNIQUE constraint failed" in str(e):
                    print(f"Player {name} already exists in database")
                    return False
                else:
                    print(f"Integrity error storing extinct player {name}: {e}")
                    return False
            except Exception as e:
                print(f"Error storing extinct player {name}: {e}")
                return False
        
        return False

    def check_url_extinction_status(self, fut_gg_url):
        """Check if a specific player URL still shows EXTINCT"""
        try:
            headers = {
                'User-Agent': random.choice(self.user_agents),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
            }
            
            response = requests.get(fut_gg_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            page_text = soup.get_text().upper()
            
            # Look for explicit EXTINCT text
            if "EXTINCT" in page_text:
                return True
            
            # Look for price indicators
            has_coins = "COINS" in page_text
            has_market = "MARKET" in page_text
            has_price = "PRICE" in page_text
            has_buy = "BUY" in page_text
            
            # If no market indicators found, likely extinct
            if not any([has_coins, has_market, has_price, has_buy]):
                return True
            
            return False
            
        except Exception as e:
            print(f"Error checking URL {fut_gg_url}: {e}")
            return None

    def monitor_database_players(self):
        """Monitor players in database with priority-based checking"""
        while True:
            try:
                print("🔍 Checking database players with priority system...")
                
                extinct_players = []
                max_retries = 3
                
                for attempt in range(max_retries):
                    try:
                        conn = sqlite3.connect(self.db_path, timeout=30.0)
                        cursor = conn.cursor()
                        
                        cursor.execute('''
                            SELECT id, name, rating, fut_gg_url, status, 
                                   CASE 
                                       WHEN rating >= 90 THEN 5
                                       WHEN rating >= 85 THEN 4
                                       WHEN rating >= 80 THEN 3
                                       WHEN rating >= 75 THEN 2
                                       ELSE 1
                                   END as base_priority,
                                   last_checked
                            FROM extinct_players 
                            WHERE status = 'extinct'
                            ORDER BY 
                                base_priority DESC,
                                last_checked ASC
                            LIMIT 150
                        ''')
                        
                        rows = cursor.fetchall()
                        extinct_players = [(row[0], row[1], row[2], row[3], row[4], row[5]) for row in rows]
                        conn.close()
                        break
                        
                    except sqlite3.OperationalError as e:
                        if "database is locked" in str(e) and attempt < max_retries - 1:
                            print(f"Database locked during read, retrying {attempt + 1}/{max_retries}...")
                            time.sleep(random.uniform(1, 3))
                            continue
                        else:
                            print(f"Database error during monitoring: {e}")
                            time.sleep(60)
                            break
                
                if not extinct_players:
                    print("No extinct players to check in database")
                    time.sleep(180)
                    continue
                
                print(f"Checking {len(extinct_players)} extinct players (prioritized by rating/importance)...")
                
                status_changes = 0
                high_priority_checked = 0
                
                for player_id, name, rating, fut_gg_url, current_status, priority in extinct_players:
                    if rating >= 85:
                        high_priority_checked += 1
                    
                    print(f"Checking {name} ({rating}) [Priority: {priority}]...")
                    
                    is_extinct = self.check_url_extinction_status(fut_gg_url)
                    
                    if is_extinct is False and current_status == 'extinct':
                        if self.remove_available_player(player_id):
                            self.send_availability_alert({
                                'name': name,
                                'rating': rating,
                                'fut_gg_url': fut_gg_url,
                                'priority': priority
                            })
                            
                            status_changes += 1
                            print(f"✅ BACK TO MARKET (REMOVED): {name}")
                        
                    elif is_extinct is True:
                        self.update_last_checked(player_id)
                        print(f"🔥 Still extinct: {name}")
                        
                    else:
                        print(f"❓ Uncertain status: {name}")
                    
                    if rating >= 85:
                        time.sleep(random.uniform(1, 2))
                    else:
                        time.sleep(random.uniform(2, 4))
                
                print(f"✅ Monitoring cycle complete: {status_changes} players back in market")
                print(f"📊 High-priority players (85+) checked: {high_priority_checked}")
                time.sleep(180)
                
            except Exception as e:
                print(f"Error in monitoring cycle: {e}")
                time.sleep(60)

    def remove_available_player(self, player_id):
        """Remove player from database when they become available"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                conn = sqlite3.connect(self.db_path, timeout=30.0)
                cursor = conn.cursor()
                
                cursor.execute('DELETE FROM extinct_players WHERE id = ?', (player_id,))
                
                conn.commit()
                conn.close()
                return True
                
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    print(f"Database locked during player removal, retrying {attempt + 1}/{max_retries}...")
                    time.sleep(random.uniform(0.5, 2.0))
                    continue
                else:
                    print(f"Database error removing available player: {e}")
                    return False
            except Exception as e:
                print(f"Error removing available player: {e}")
                return False
        
        return False

    def update_last_checked(self, player_id):
        """Update last_checked timestamp for player with retry logic"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                conn = sqlite3.connect(self.db_path, timeout=30.0)
                cursor = conn.cursor()
                
                cursor.execute('''
                    UPDATE extinct_players 
                    SET last_checked = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (player_id,))
                
                conn.commit()
                conn.close()
                return True
                
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    print(f"Database locked during last_checked update, retrying {attempt + 1}/{max_retries}...")
                    time.sleep(random.uniform(0.5, 2.0))
                    continue
                else:
                    print(f"Database error updating last_checked: {e}")
                    return False
            except Exception as e:
                print(f"Error updating last_checked: {e}")
                return False
        
        return False

    def send_extinction_alert(self, player_data):
        """Send alert for newly extinct player"""
        club_name = player_data.get('club', 'Unknown Club')
        position = player_data.get('position', 'Unknown')
        
        message = f"EXTINCT: {player_data.get('name', 'Unknown')} ({player_data.get('rating', '?')}) - {club_name}"
        self.send_telegram_notification(message)
        
        if Config.DISCORD_WEBHOOK_URL:
            embed = {
                "title": f"{player_data.get('name', 'Unknown')} - EXTINCT",
                "color": 0xff0000,
                "timestamp": datetime.now().isoformat(),
                "fields": [
                    {
                        "name": "Rating",
                        "value": str(player_data.get('rating', '?')),
                        "inline": True
                    }
                ]
            }
            
            if club_name and club_name != 'Unknown Club' and club_name != 'Unknown':
                embed["fields"].append({
                    "name": "Club",
                    "value": club_name,
                    "inline": True
                })
            
            if position and position != 'Unknown':
                embed["fields"].append({
                    "name": "Position",
                    "value": position,
                    "inline": True
                })
            
            embed["fields"].append({
                "name": "Status",
                "value": "EXTINCT",
                "inline": True
            })
            
            if player_data.get('fut_gg_url'):
                embed["url"] = player_data.get('fut_gg_url')
            
            payload = {"embeds": [embed]}
            
            try:
                response = requests.post(Config.DISCORD_WEBHOOK_URL, json=payload)
                if response.status_code == 204:
                    print("✅ Discord extinction alert sent")
                else:
                    print(f"❌ Discord error: {response.status_code} - {response.text}")
            except Exception as e:
                print(f"❌ Discord error: {e}")
                
        time.sleep(2.0)

    def send_availability_alert(self, player_data):
        """Send alert for player back in market"""
        telegram_message = f"✅ BACK IN MARKET: {player_data.get('name', 'Unknown')} ({player_data.get('rating', '?')})"
        self.send_telegram_notification(telegram_message)
        
        if Config.DISCORD_WEBHOOK_URL:
            embed = {
                "title": f"✅ {player_data.get('name', 'Unknown')} Back in Market!",
                "description": f"This player is now available for purchase again",
                "color": 0x00ff00,
                "timestamp": datetime.now().isoformat(),
                "fields": [
                    {
                        "name": "🔄 Status",
                        "value": "Available",
                        "inline": True
                    },
                    {
                        "name": "⭐ Rating",
                        "value": str(player_data.get('rating', '?')),
                        "inline": True
                    },
                    {
                        "name": "💰 Action",
                        "value": "Ready to buy!",
                        "inline": True
                    }
                ],
                "footer": {
                    "text": "FUT.GG Extinct Monitor",
                    "icon_url": "https://www.fut.gg/favicon.ico"
                }
            }
            
            if player_data.get('fut_gg_url'):
                embed["url"] = player_data.get('fut_gg_url')
                embed["fields"].append({
                    "name": "🔗 Link",
                    "value": f"[View on FUT.GG]({player_data.get('fut_gg_url')})",
                    "inline": False
                })
            
            payload = {"embeds": [embed]}
            
            try:
                response = requests.post(Config.DISCORD_WEBHOOK_URL, json=payload)
                if response.status_code == 204:
                    print(f"✅ Discord availability alert sent for {player_data.get('name')}")
                else:
                    print(f"❌ Discord availability error for {player_data.get('name')}: {response.status_code}")
            except Exception as e:
                print(f"❌ Discord availability error for {player_data.get('name')}: {e}")
        
        time.sleep(2.0)

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
    
    def send_discord_notification(self, message, title="FUT.GG Extinct Monitor"):
        """Send general Discord notification"""
        if not Config.DISCORD_WEBHOOK_URL:
            return
        
        embed = {
            "title": title,
            "description": message,
            "color": 0x0099ff,
            "timestamp": datetime.now().isoformat()
        }
        
        payload = {"embeds": [embed]}
        
        try:
            response = requests.post(Config.DISCORD_WEBHOOK_URL, json=payload)
            if response.status_code == 204:
                print("✅ Discord notification sent")
            else:
                print(f"❌ Discord error: {response.status_code}")
        except Exception as e:
            print(f"❌ Discord error: {e}")
    
    def send_notification_to_all(self, message, title="FUT.GG Extinct Monitor"):
        """Send notification to both platforms"""
        self.send_telegram_notification(message)
        self.send_discord_notification(message, title)

    def run_discovery_and_monitoring(self):
        """Run discovery in separate thread, then start monitoring"""
        def discovery_thread():
            while True:
                try:
                    discovered = self.discover_extinct_players()
                    print(f"Discovery thread: Found {discovered} new extinct players")
                    time.sleep(1800)
                except Exception as e:
                    print(f"Discovery thread error: {e}")
                    time.sleep(300)
        
        discovery = threading.Thread(target=discovery_thread, daemon=True)
        discovery.start()
        print("🔍 Discovery thread started")
        
        self.discover_extinct_players()
        self.monitor_database_players()
    
    def run_complete_system(self):
        """Run the complete extinct monitoring system"""
        print("🚀 Starting FUT.GG Extinct Player Monitor with Smart Features!")
        sys.stdout.flush()
        
        self.check_and_send_startup_notification()
        self.run_discovery_and_monitoring()

if __name__ == "__main__":
    monitor = FutGGExtinctMonitor()
    monitor.run_complete_system()
