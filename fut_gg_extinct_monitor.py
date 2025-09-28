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
        self.last_hourly_summary = datetime.now() - timedelta(hours=1)  # Allow immediate first summary
    
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
                    last_seen_on_filtered TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_checked TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status_changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    consecutive_missing_count INTEGER DEFAULT 0,
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
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_first_detected ON extinct_players(first_detected)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_last_seen ON extinct_players(last_seen_on_filtered)')
            
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
                f"⭐ Monitoring 81+ rated players only\n"
                f"📊 Hourly extinct summaries enabled\n"
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
        """Discover extinct players and store them in database - Only 81+ rated players"""
        print("🔍 Discovering extinct players (81+ rating only)...")
        discovered_count = 0
        page = 1
        consecutive_no_new_players = 0
        
        # First pass: collect all players to detect duplicates
        all_players = []
        
        print("📊 First pass: Collecting all players and club info to detect outdated transfers...")
        
        while True:
            if max_pages and page > max_pages:
                print(f"Reached maximum page limit ({max_pages}), stopping collection")
                break
            if page > 200:
                print("Reached safety limit of 200 pages, stopping collection")
                break
                
            # Use the filtered URL for 81+ rating only
            url = f"https://www.fut.gg/players/?page={page}&price__lte=0&overall__gte=81"
            
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
                        print(f"Found 3 consecutive empty pages, stopping collection at page {page}")
                        break
                    
                    page += 1
                    time.sleep(random.uniform(1, 2))
                    continue
                
                page_collected = 0
                
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
                                    # Only process 81+ rated players
                                    if rating < 81:
                                        continue
                                except ValueError:
                                    continue
                                
                                # Get basic club info from the link if possible
                                club_hint = "Unknown"
                                try:
                                    # Try to get club from nearby elements or URL patterns
                                    club_container = link.find_parent(['div', 'article']).find('img', alt=lambda x: x and any(club in str(x).lower() for club in ['psg', 'milan', 'madrid', 'barcelona', 'liverpool', 'city', 'united', 'arsenal', 'chelsea', 'tottenham']) if x)
                                    if club_container and club_container != img:
                                        club_hint = club_container.get('alt', 'Unknown')
                                except:
                                    pass
                                
                                all_players.append({
                                    'name': player_name,
                                    'rating': rating,
                                    'url': fut_gg_url,
                                    'club_hint': club_hint
                                })
                                page_collected += 1
                    
                    except Exception as e:
                        continue
                
                print(f"Page {page}: Collected {page_collected} players")
                
                if page_collected == 0:
                    consecutive_no_new_players += 1
                    if consecutive_no_new_players >= 10:
                        print(f"Found 10 consecutive pages with no new players, stopping collection")
                        break
                else:
                    consecutive_no_new_players = 0
                
                page += 1
                time.sleep(random.uniform(1, 2))
                
            except Exception as e:
                print(f"Error collecting players on page {page}: {e}")
                consecutive_no_new_players += 1
                page += 1
                time.sleep(random.uniform(2, 4))
                continue
        
        print(f"📊 Collection complete! Found {len(all_players)} total players across {page-1} pages")
        
        # Second pass: identify transfer duplicates and true duplicates
        print("🔍 Second pass: Filtering out transfer duplicates and true duplicates...")
        
        # Group players by name+rating to find potential duplicates
        name_rating_groups = {}
        for player in all_players:
            key = f"{player['name']}_{player['rating']}"
            if key not in name_rating_groups:
                name_rating_groups[key] = []
            name_rating_groups[key].append(player)
        
        # Filter logic
        unique_players = []
        filtered_count = 0
        transfer_filtered = []
        
        for key, players in name_rating_groups.items():
            if len(players) == 1:
                # No duplicates, keep it
                unique_players.append(players[0])
            else:
                # Multiple players with same name+rating
                # Check if they have different clubs (transfer situation)
                
                # For now, skip ALL duplicates regardless of club
                # This avoids the PSG Donnarumma vs Milan Donnarumma issue
                filtered_count += len(players)
                if len(transfer_filtered) < 3:
                    transfer_filtered.append(f"{players[0]['name']} ({players[0]['rating']}) - {len(players)} versions")
        
        if transfer_filtered:
            print(f"⏭️ Filtering out transfer/duplicate cards: {', '.join(transfer_filtered)}")
            if filtered_count > len(transfer_filtered):
                print(f"⏭️ ...and {filtered_count - len(transfer_filtered)} more cards with multiple versions")
        
        print(f"✅ Filtered out {filtered_count} cards with multiple versions (transfer duplicates + true duplicates)")
        print(f"📊 {len(unique_players)} unique players remain (only players with single versions)")
        print(f"ℹ️  Note: This avoids outdated transfer cards like PSG Donnarumma that don't exist in-game")
        
        # Third pass: store unique players
        print("💾 Third pass: Storing unique extinct players...")
        
        for player in unique_players:
            if self.store_extinct_player(player['name'], player['rating'], player['url']):
                discovered_count += 1
                time.sleep(1)  # Small delay between storing players
        
        print(f"🎯 Discovery complete! Found {discovered_count} new unique extinct players (81+)")
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
                
                # Check if this exact URL already exists
                cursor.execute('SELECT id FROM extinct_players WHERE fut_gg_url = ?', (fut_gg_url,))
                if cursor.fetchone():
                    conn.close()
                    return False
                
                if rating < 81:
                    print(f"⏭️ Skipping {name} ({rating}) - Below 81 rating threshold")
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
        """Monitor with time-based separation and conservative alerting"""
        while True:
            try:
                print("🔍 Checking filtered URL with conservative monitoring...")
                
                # Get all currently extinct player URLs from filtered pages (81+ only)
                current_extinct_urls = set()
                
                for page in range(1, 50):  # Increased scope to reduce false positives
                    try:
                        url = f"https://www.fut.gg/players/?page={page}&price__lte=0&overall__gte=81"
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
                            print(f"No more players on filtered page {page}, stopping scan")
                            break
                        
                        for link in player_links:
                            href = link.get('href', '')
                            if href and '/players/' in href:
                                if href.startswith('/'):
                                    fut_gg_url = f"https://www.fut.gg{href}"
                                else:
                                    fut_gg_url = href
                                current_extinct_urls.add(fut_gg_url)
                        
                        time.sleep(random.uniform(0.5, 1.0))
                        
                    except Exception as e:
                        print(f"Error scanning filtered page {page}: {e}")
                        break
                
                print(f"Found {len(current_extinct_urls)} players currently on filtered pages")
                
                # Get tracked players that are old enough to monitor (30+ minutes old)
                conn = sqlite3.connect(self.db_path, timeout=30.0)
                cursor = conn.cursor()
                
                # Update last_seen_on_filtered for players still on filtered pages
                cursor.execute('''
                    UPDATE extinct_players 
                    SET last_seen_on_filtered = CURRENT_TIMESTAMP, consecutive_missing_count = 0
                    WHERE fut_gg_url IN ({})
                '''.format(','.join('?' * len(current_extinct_urls))), list(current_extinct_urls))
                
                # Get players eligible for monitoring (30+ minutes old)
                cursor.execute('''
                    SELECT id, name, rating, fut_gg_url, consecutive_missing_count, first_detected
                    FROM extinct_players 
                    WHERE status = 'extinct'
                    AND datetime(first_detected, '+30 minutes') < datetime('now')
                ''')
                
                eligible_players = cursor.fetchall()
                conn.commit()
                conn.close()
                
                print(f"Checking {len(eligible_players)} players (30+ minutes old)")
                
                # Check which eligible players are missing from current filtered pages
                players_potentially_back = []
                
                for player_id, name, rating, fut_gg_url, missing_count, first_detected in eligible_players:
                    if fut_gg_url not in current_extinct_urls:
                        # Player missing from filtered pages
                        new_missing_count = missing_count + 1
                        players_potentially_back.append({
                            'id': player_id,
                            'name': name,
                            'rating': rating,
                            'fut_gg_url': fut_gg_url,
                            'missing_count': new_missing_count
                        })
                        
                        # Update missing count
                        conn = sqlite3.connect(self.db_path, timeout=30.0)
                        cursor = conn.cursor()
                        cursor.execute('''
                            UPDATE extinct_players 
                            SET consecutive_missing_count = ?
                            WHERE id = ?
                        ''', (new_missing_count, player_id))
                        conn.commit()
                        conn.close()
                
                # Only alert if player has been missing for 3+ consecutive checks
                confirmed_back_in_market = []
                for player in players_potentially_back:
                    if player['missing_count'] >= 3:
                        confirmed_back_in_market.append(player)
                        print(f"✅ CONFIRMED BACK TO MARKET: {player['name']} (missing {player['missing_count']} cycles)")
                    else:
                        print(f"⏳ Potentially back: {player['name']} (missing {player['missing_count']}/3 cycles)")
                
                # Remove confirmed players and send alerts
                for player in confirmed_back_in_market:
                    if self.remove_available_player(player['id']):
                        self.send_availability_alert({
                            'name': player['name'],
                            'rating': player['rating'],
                            'fut_gg_url': player['fut_gg_url']
                        })
                
                still_extinct = len(eligible_players) - len(confirmed_back_in_market)
                print(f"✅ Conservative monitoring complete: {len(confirmed_back_in_market)} confirmed back in market, {still_extinct} still extinct")
                
                # Check if it's time to send hourly summary
                self.check_and_send_hourly_summary()
                
                time.sleep(600)  # 10 minutes between cycles (longer to be more conservative)
                
            except Exception as e:
                print(f"Error in monitoring cycle: {e}")
                time.sleep(120)

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

    def check_and_send_hourly_summary(self):
        """Send hourly summary of all extinct cards in database"""
        now = datetime.now()
        
        # Check if an hour has passed since last summary
        if now - self.last_hourly_summary >= timedelta(hours=1):
            try:
                conn = sqlite3.connect(self.db_path, timeout=30.0)
                cursor = conn.cursor()
                
                # Get all extinct players, ordered by rating descending
                cursor.execute('''
                    SELECT name, rating, fut_gg_url
                    FROM extinct_players 
                    WHERE status = 'extinct'
                    ORDER BY rating DESC, name ASC
                ''')
                
                extinct_players = cursor.fetchall()
                conn.close()
                
                if extinct_players:
                    # Format the summary message
                    summary_lines = [f"📊 **HOURLY EXTINCT SUMMARY** ({len(extinct_players)} cards)\n"]
                    
                    # Group by rating for better readability
                    current_rating = None
                    for name, rating, url in extinct_players:
                        if current_rating != rating:
                            if current_rating is not None:
                                summary_lines.append("")  # Add spacing between rating groups
                            summary_lines.append(f"⭐ **{rating} Rating:**")
                            current_rating = rating
                        
                        summary_lines.append(f"🔥 {name}")
                    
                    # Split into chunks if message is too long (Telegram has 4096 char limit)
                    full_message = "\n".join(summary_lines)
                    
                    if len(full_message) <= 4000:  # Safe margin
                        self.send_notification_to_all(full_message, "📊 Hourly Extinct Summary")
                    else:
                        # Split into multiple messages
                        chunks = []
                        current_chunk = [f"📊 **HOURLY EXTINCT SUMMARY** ({len(extinct_players)} cards) - Part 1\n"]
                        current_length = len(current_chunk[0])
                        part_num = 1
                        
                        for line in summary_lines[1:]:  # Skip the header we already added
                            if current_length + len(line) + 1 > 3500:  # Safe margin for next part
                                chunks.append("\n".join(current_chunk))
                                part_num += 1
                                current_chunk = [f"📊 **HOURLY EXTINCT SUMMARY** - Part {part_num}\n", line]
                                current_length = len(current_chunk[0]) + len(line) + 1
                            else:
                                current_chunk.append(line)
                                current_length += len(line) + 1
                        
                        # Add the last chunk
                        chunks.append("\n".join(current_chunk))
                        
                        # Send all chunks
                        for i, chunk in enumerate(chunks):
                            self.send_notification_to_all(chunk, f"📊 Hourly Summary ({i+1}/{len(chunks)})")
                            if i < len(chunks) - 1:  # Don't sleep after last message
                                time.sleep(2)  # Small delay between parts
                    
                    print(f"✅ Hourly summary sent: {len(extinct_players)} extinct cards")
                else:
                    summary_message = "📊 **HOURLY EXTINCT SUMMARY**\n\n🎉 No extinct cards currently tracked!"
                    self.send_notification_to_all(summary_message, "📊 Hourly Extinct Summary")
                    print("✅ Hourly summary sent: No extinct cards")
                
                self.last_hourly_summary = now
                
            except Exception as e:
                print(f"❌ Error sending hourly summary: {e}")

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
        """Send alert for newly extinct player (81+ only)"""
        rating = player_data.get('rating', 0)
        
        # Double-check rating threshold before sending alert
        if rating < 81:
            print(f"⏭️ Skipping alert for {player_data.get('name')} ({rating}) - Below 81 rating threshold")
            return
        
        club_name = player_data.get('club', 'Unknown Club')
        position = player_data.get('position', 'Unknown')
        
        message = f"🔥 EXTINCT: {player_data.get('name', 'Unknown')} ({player_data.get('rating', '?')}) - {club_name}"
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
                    time.sleep(1800)  # 30 minutes between discovery runs
                except Exception as e:
                    print(f"Discovery thread error: {e}")
                    time.sleep(300)
        
        discovery = threading.Thread(target=discovery_thread, daemon=True)
        discovery.start()
        print("🔍 Discovery thread started")
        
        # Initial discovery
        self.discover_extinct_players()
        
        # Start monitoring
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
