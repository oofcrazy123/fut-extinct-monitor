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
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:89.0) Gecko/20100101 Firefox/89.0'
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
            
            # Main table for tracking extinct players
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
            
            # Add indexes for better performance
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
                f"🎯 Using database-driven tracking\n"
                f"⚡ Running on cloud infrastructure\n"
                f"⏰ Check interval: 5 minutes\n"
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

    def discover_extinct_players(self, max_pages=20):
        """Discover extinct players and store them in database"""
        print("🔍 Discovering extinct players...")
        discovered_count = 0
        
        for page in range(1, max_pages + 1):
            url = f"https://www.fut.gg/players/?page={page}&price__lte=0"
            
            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                }
                
                response = requests.get(url, headers=headers, timeout=30)
                response.raise_for_status()
                
                soup = BeautifulSoup(response.content, 'html.parser')
                player_links = soup.find_all('a', href=lambda x: x and '/players/' in str(x))
                
                if not player_links:
                    print(f"No more extinct players found at page {page}, stopping discovery")
                    break
                
                page_discovered = 0
                
                for link in player_links:
                    try:
                        href = link.get('href', '')
                        if not href or '/players/' not in href:
                            continue
                        
                        # Build full URL
                        if href.startswith('/'):
                            fut_gg_url = f"https://www.fut.gg{href}"
                        else:
                            fut_gg_url = href
                        
                        # Find player image to get name and rating
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
                                
                                # Store in database if not already tracked
                                if self.store_extinct_player(player_name, rating, fut_gg_url):
                                    discovered_count += 1
                                    page_discovered += 1
                    
                    except Exception as e:
                        continue
                
                print(f"Page {page}: Discovered {page_discovered} new extinct players")
                time.sleep(random.uniform(1, 2))
                
            except Exception as e:
                print(f"Error discovering extinct players on page {page}: {e}")
                break
        
        print(f"🎯 Discovery complete! Found {discovered_count} new extinct players")
        return discovered_count

    def store_extinct_player(self, name, rating, fut_gg_url):
        """Store extinct player in database with better error handling, return True if new"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                conn = sqlite3.connect(self.db_path, timeout=30.0)  # Add timeout
                cursor = conn.cursor()
                
                # Check if URL already exists
                cursor.execute('SELECT id FROM extinct_players WHERE fut_gg_url = ?', (fut_gg_url,))
                if cursor.fetchone():
                    conn.close()
                    return False  # Already exists
                
                # Get additional player info (but don't let it slow down too much)
                additional_info = {}
                try:
                    additional_info = self.get_additional_player_info(fut_gg_url)
                except:
                    pass  # Don't let info gathering break the storage
                
                club_name = additional_info.get('club', 'Unknown')
                position = additional_info.get('position', 'Unknown')
                
                # Insert new extinct player
                cursor.execute('''
                    INSERT OR IGNORE INTO extinct_players (name, rating, fut_gg_url, status, alert_sent)
                    VALUES (?, ?, ?, 'extinct', 1)
                ''', (name, rating, fut_gg_url))
                
                # Check if the insert actually happened
                if cursor.rowcount > 0:
                    conn.commit()
                    conn.close()
                    
                    print(f"🔥 NEW EXTINCTION: {name} ({rating}) - {club_name}")
                    
                    # Send immediate extinction alert with enhanced info
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
                    return False  # Insert was ignored (duplicate)
                
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    print(f"Database locked, retrying {attempt + 1}/{max_retries}...")
                    time.sleep(random.uniform(0.5, 2.0))  # Random backoff
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

    def update_last_checked(self, player_id):
        """Update last_checked timestamp for player"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE extinct_players 
                SET last_checked = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (player_id,))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            print(f"Error updating last_checked: {e}")

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
            
            # Look for extinct indicators
            extinct_elements = soup.find_all(class_="flex items-center justify-center grow shrink-0 gap-[0.1em]")
            
            for element in extinct_elements:
                text = element.get_text(strip=True).upper()
                if "EXTINCT" in text:
                    return True
            
            # Backup check
            page_text = soup.get_text().upper()
            if "EXTINCT" in page_text:
                return True
            
            return False  # No extinct indicators found
            
        except Exception as e:
            print(f"Error checking URL {fut_gg_url}: {e}")
            return None  # Uncertain due to error

    def monitor_database_players(self):
        """Monitor players in database for status changes with better concurrency handling"""
        while True:
            try:
                print("🔍 Checking database players for status changes...")
                
                # Get extinct players to check with better database handling
                extinct_players = []
                max_retries = 3
                
                for attempt in range(max_retries):
                    try:
                        conn = sqlite3.connect(self.db_path, timeout=30.0)
                        cursor = conn.cursor()
                        
                        cursor.execute('''
                            SELECT id, name, rating, fut_gg_url, status
                            FROM extinct_players 
                            WHERE status = 'extinct'
                            ORDER BY last_checked ASC
                            LIMIT 100
                        ''')
                        
                        extinct_players = cursor.fetchall()
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
                    time.sleep(300)
                    continue
                
                print(f"Checking {len(extinct_players)} extinct players...")
                
                status_changes = 0
                
                for player_id, name, rating, fut_gg_url, current_status in extinct_players:
                    print(f"Checking {name} ({rating})...")
                    
                    is_extinct = self.check_url_extinction_status(fut_gg_url)
                    
                    if is_extinct is False and current_status == 'extinct':
                        # Player is back in market!
                        if self.update_player_status(player_id, 'available'):
                            # Send availability alert
                            self.send_availability_alert({
                                'name': name,
                                'rating': rating,
                                'fut_gg_url': fut_gg_url
                            })
                            
                            status_changes += 1
                            print(f"✅ BACK TO MARKET: {name}")
                        
                    elif is_extinct is True:
                        # Still extinct, just update last_checked
                        self.update_last_checked(player_id)
                        print(f"🔥 Still extinct: {name}")
                        
                    else:
                        # Uncertain status
                        print(f"❓ Uncertain status: {name}")
                    
                    # Delay between checks
                    time.sleep(random.uniform(4, 7))
                
                print(f"✅ Monitoring cycle complete: {status_changes} players back in market")
                time.sleep(300)  # 5 minutes between cycles
                
            except Exception as e:
                print(f"Error in monitoring cycle: {e}")
                time.sleep(60)

    def update_player_status(self, player_id, new_status):
        """Update player status in database"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE extinct_players 
                SET status = ?, status_changed_at = CURRENT_TIMESTAMP, last_checked = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (new_status, player_id))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            print(f"Error updating player status: {e}")

    def extract_club_from_url(self, fut_gg_url):
        """Extract club name from fut.gg URL"""
        try:
            if not fut_gg_url or '/players/' not in fut_gg_url:
                return None
            
            # URLs often contain club info like /players/123-messi-barcelona/
            url_parts = fut_gg_url.split('/players/')
            if len(url_parts) > 1:
                player_part = url_parts[1].split('/')[0]  # Get the part after /players/
                
                # Extract potential club name from URL slug
                if '-' in player_part:
                    parts = player_part.split('-')
                    if len(parts) > 2:  # Usually format: id-playername-club
                        club_part = '-'.join(parts[2:])  # Everything after playername
                        club_name = club_part.replace('-', ' ').title()
                        return club_name
            
            return None
        except Exception as e:
            return None

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
            
            # Look for the paper div containing player info
            paper_div = soup.find('div', class_='paper !bg-darker-gray mb-4 !p-4 hidden md:block')
            
            if paper_div:
                # Find all the flex containers with labels
                flex_containers = paper_div.find_all('div', class_='flex justify-between')
                flex_containers.extend(paper_div.find_all('div', class_='flex justify-between flex-row mt-2'))
                
                for container in flex_containers:
                    # Find the label (text-lighter-gray div)
                    label_div = container.find('div', class_='text-lighter-gray')
                    if label_div:
                        label_text = label_div.get_text(strip=True)
                        
                        if label_text == 'Club':
                            # Get the next div which contains the club info
                            club_container = label_div.find_next_sibling('div')
                            if club_container:
                                club_link = club_container.find('a')
                                if club_link:
                                    # Extract club name from the link text
                                    club_name = club_link.get_text(strip=True)
                                    if club_name:
                                        info['club'] = club_name
                                else:
                                    # If no link, get text directly
                                    club_text = club_container.get_text(strip=True)
                                    if club_text:
                                        info['club'] = club_text
                        
                        elif label_text == 'Nation':
                            # Get nation info similarly
                            nation_container = label_div.find_next_sibling('div')
                            if nation_container:
                                nation_link = nation_container.find('a')
                                if nation_link:
                                    nation_name = nation_link.get_text(strip=True)
                                    if nation_name:
                                        info['nation'] = nation_name
            
            # Try to find position from the card display (usually visible as large text)
            # Look for position indicators like "GK", "ST", etc.
            page_text = soup.get_text()
            positions = ['GK', 'ST', 'CF', 'LW', 'RW', 'CAM', 'CM', 'CDM', 'LB', 'RB', 'CB', 'LWB', 'RWB', 'RM', 'LM']
            for pos in positions:
                # Look for position as standalone text (not part of other words)
                if f' {pos} ' in f' {page_text} ' or f'\n{pos}\n' in page_text:
                    info['position'] = pos
                    break
            
            return info
            
        except Exception as e:
            print(f"Error getting additional player info: {e}")
            return {}
        """Update last_checked timestamp for player"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE extinct_players 
                SET last_checked = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (player_id,))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            print(f"Error updating last_checked: {e}")

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
            
            # Add club info if available
            if club_name and club_name != 'Unknown Club' and club_name != 'Unknown':
                embed["fields"].append({
                    "name": "Club",
                    "value": club_name,
                    "inline": True
                })
            
            # Add position if available
            if position and position != 'Unknown':
                embed["fields"].append({
                    "name": "Position",
                    "value": position,
                    "inline": True
                })
            
            # Add status field
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
                requests.post(Config.DISCORD_WEBHOOK_URL, json=payload)
            except Exception as e:
                print(f"Discord error: {e}")

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
                    discovered = self.discover_extinct_players(max_pages=15)
                    print(f"Discovery thread: Found {discovered} new extinct players")
                    time.sleep(1800)  # Run discovery every 30 minutes
                except Exception as e:
                    print(f"Discovery thread error: {e}")
                    time.sleep(300)
        
        # Start discovery thread
        discovery = threading.Thread(target=discovery_thread, daemon=True)
        discovery.start()
        print("🔍 Discovery thread started")
        
        # Run initial discovery
        self.discover_extinct_players(max_pages=20)
        
        # Start monitoring loop
        self.monitor_database_players()
    
    def run_complete_system(self):
        """Run the complete extinct monitoring system"""
        print("🚀 Starting FUT.GG Extinct Player Monitor with Database tracking!")
        sys.stdout.flush()
        
        # Send startup notification
        self.check_and_send_startup_notification()
        
        # Start discovery and monitoring
        self.run_discovery_and_monitoring()

# Entry point
if __name__ == "__main__":
    monitor = FutGGExtinctMonitor()
    monitor.run_complete_system()
