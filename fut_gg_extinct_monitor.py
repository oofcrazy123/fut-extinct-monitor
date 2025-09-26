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
        """Initialize SQLite database for extinct card monitoring"""
        print(f"🔧 Initializing database at: {self.db_path}")
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS cards (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    rating INTEGER,
                    position TEXT,
                    club TEXT,
                    nation TEXT,
                    league TEXT,
                    card_type TEXT,
                    fut_gg_url TEXT UNIQUE,
                    fut_gg_id TEXT,
                    extinction_status TEXT DEFAULT 'unknown',
                    last_check TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_checked TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS extinct_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    card_id INTEGER,
                    platform TEXT,
                    extinct_status BOOLEAN DEFAULT 1,
                    alert_sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    resolved_at TIMESTAMP NULL,
                    FOREIGN KEY (card_id) REFERENCES cards (id)
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS startup_locks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    startup_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    instance_id TEXT UNIQUE
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS card_status_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    card_id INTEGER,
                    status_type TEXT,
                    status_value TEXT,
                    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (card_id) REFERENCES cards (id)
                )
            ''')
            
            # Add indexes for better performance
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_extinction_status ON cards(extinction_status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_last_checked ON cards(last_checked)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_name ON cards(name)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_created_at ON cards(created_at)')
            
            conn.commit()
            
            cursor.execute('SELECT COUNT(*) FROM cards')
            existing_cards = cursor.fetchone()[0]
            print(f"📊 Database initialized! Existing cards: {existing_cards}")
            
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
                f"🎯 Using URL-based tracking for precise detection\n"
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

    def scrape_extinct_players_with_urls(self, max_pages=50):
        """
        Scrape extinct players and capture their specific fut.gg URLs
        """
        extinct_players = []
        
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
                
                # Find all player links on the page
                player_links = soup.find_all('a', href=lambda x: x and '/players/' in str(x))
                
                if not player_links:
                    print(f"No more extinct players found at page {page}, stopping")
                    break
                
                print(f"Page {page}: Found {len(player_links)} player links")
                
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
                            # Try to find img in the parent container
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
                                
                                card_data = {
                                    'name': player_name,
                                    'rating': rating,
                                    'fut_gg_url': fut_gg_url,
                                    'appears_extinct': True  # All players on this URL are extinct
                                }
                                
                                extinct_players.append(card_data)
                    
                    except Exception as e:
                        continue
                
                time.sleep(random.uniform(1, 2))
                
            except Exception as e:
                print(f"Error scraping extinct page {page}: {e}")
                break
        
        print(f"Found {len(extinct_players)} total extinct players with URLs")
        return extinct_players

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
            
            # Look for extinct indicators in the specific class
            extinct_elements = soup.find_all(class_="flex items-center justify-center grow shrink-0 gap-[0.1em]")
            
            for element in extinct_elements:
                text = element.get_text(strip=True).upper()
                if "EXTINCT" in text:
                    return True
            
            # Also check for any element containing "EXTINCT" as backup
            page_text = soup.get_text().upper()
            if "EXTINCT" in page_text:
                return True
            
            return False  # No extinct indicators found
            
        except Exception as e:
            print(f"Error checking URL {fut_gg_url}: {e}")
            return None  # Uncertain due to error

    def monitor_extinct_players_by_url(self):
        """Monitor specific player URLs for extinction status changes"""
        tracked_urls = {}  # Format: {fut_gg_url: {'name': name, 'rating': rating, 'status': 'extinct'/'available'}}
        cycle_count = 0
        
        while True:
            try:
                cycle_count += 1
                print(f"Starting URL-based monitoring cycle #{cycle_count}...")
                
                # Step 1: Discover new extinct players and their URLs
                print("📡 Discovering new extinct players...")
                current_extinct = self.scrape_extinct_players_with_urls(max_pages=10)
                
                newly_extinct = []
                for player in current_extinct:
                    url = player['fut_gg_url']
                    if url not in tracked_urls:
                        newly_extinct.append(player)
                        tracked_urls[url] = {
                            'name': player['name'],
                            'rating': player['rating'],
                            'status': 'extinct'
                        }
                        print(f"🔥 NEW EXTINCTION: {player['name']} ({player['rating']})")
                
                # Step 2: Check sample of previously extinct URLs
                extinct_urls = [url for url, data in tracked_urls.items() if data['status'] == 'extinct']
                no_longer_extinct = []
                
                if extinct_urls:
                    # Sample up to 20 URLs to check per cycle
                    sample_size = min(20, len(extinct_urls))
                    sample_urls = random.sample(extinct_urls, sample_size)
                    
                    print(f"🔍 Checking {len(sample_urls)} previously extinct URLs...")
                    
                    for url in sample_urls:
                        player_data = tracked_urls[url]
                        print(f"Checking {player_data['name']} ({player_data['rating']})...")
                        
                        is_extinct = self.check_url_extinction_status(url)
                        
                        if is_extinct is False:  # Explicitly not extinct
                            no_longer_extinct.append({
                                'name': player_data['name'],
                                'rating': player_data['rating'],
                                'fut_gg_url': url
                            })
                            tracked_urls[url]['status'] = 'available'
                            print(f"✅ BACK TO MARKET: {player_data['name']}")
                        elif is_extinct is True:
                            print(f"🔥 Still extinct: {player_data['name']}")
                        else:
                            print(f"❓ Uncertain status: {player_data['name']}")
                        
                        # Delay between URL checks
                        time.sleep(random.uniform(3, 5))
                
                # Step 3: Send alerts for changes
                if newly_extinct:
                    self.send_extinction_alerts(newly_extinct)
                
                if no_longer_extinct:
                    self.send_availability_alerts(no_longer_extinct)
                
                # Cycle summary
                total_tracked = len(tracked_urls)
                extinct_count = sum(1 for data in tracked_urls.values() if data['status'] == 'extinct')
                available_count = total_tracked - extinct_count
                
                print(f"✅ Cycle #{cycle_count} complete:")
                print(f"   🔥 New extinctions: {len(newly_extinct)}")
                print(f"   ✅ Back to market: {len(no_longer_extinct)}")
                print(f"   📊 Total tracked URLs: {total_tracked} ({extinct_count} extinct, {available_count} available)")
                
                time.sleep(300)  # 5 minute intervals
                
            except Exception as e:
                print(f"Monitoring error: {e}")
                time.sleep(60)

    def send_extinction_alerts(self, newly_extinct_cards):
        """Send individual clean alerts for each newly extinct player"""
        if not newly_extinct_cards:
            return
        
        print(f"Sending individual alerts for {len(newly_extinct_cards)} extinct players...")
        
        # Send individual notification for each extinct player
        for card in newly_extinct_cards:
            # Clean format: just name and rating
            message = f"EXTINCT: {card.get('name', 'Unknown')} ({card.get('rating', '?')})"
            
            # Send to Telegram
            self.send_telegram_notification(message)
            
            # Send to Discord  
            if Config.DISCORD_WEBHOOK_URL:
                embed = {
                    "title": "Player Extinct",
                    "description": f"{card.get('name', 'Unknown')} - Rating {card.get('rating', '?')}",
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
                            "value": str(card.get('rating', '?')),
                            "inline": True
                        }
                    ]
                }
                
                # Add URL if available
                if card.get('fut_gg_url'):
                    embed["url"] = card.get('fut_gg_url')
                
                payload = {"embeds": [embed]}
                
                try:
                    response = requests.post(Config.DISCORD_WEBHOOK_URL, json=payload)
                    if response.status_code == 204:
                        print(f"Individual Discord alert sent for {card.get('name')}")
                    else:
                        print(f"Discord error for {card.get('name')}: {response.status_code}")
                except Exception as e:
                    print(f"Discord error for {card.get('name')}: {e}")
            
            # Small delay between individual notifications to avoid spam
            time.sleep(2)
        
        # Send a clean summary if multiple players went extinct
        if len(newly_extinct_cards) > 1:
            summary = f"Summary: {len(newly_extinct_cards)} players went extinct"
            self.send_telegram_notification(summary)
            
            if Config.DISCORD_WEBHOOK_URL:
                summary_embed = {
                    "title": "Extinction Summary",
                    "description": f"{len(newly_extinct_cards)} players went extinct",
                    "color": 0xff6600,
                    "timestamp": datetime.now().isoformat()
                }
                summary_payload = {"embeds": [summary_embed]}
                
                try:
                    requests.post(Config.DISCORD_WEBHOOK_URL, json=summary_payload)
                except Exception as e:
                    print(f"Discord summary error: {e}")
        
        print(f"Completed sending {len(newly_extinct_cards)} individual extinction alerts")
    
    def send_availability_alerts(self, no_longer_extinct_cards):
        """Send enhanced alerts for players no longer extinct"""
        if not no_longer_extinct_cards:
            return
        
        # Send individual Discord embeds for each player back in market
        for card in no_longer_extinct_cards:
            # Enhanced Telegram message
            telegram_message = f"✅ BACK IN MARKET: {card.get('name', 'Unknown')} ({card.get('rating', '?')})"
            self.send_telegram_notification(telegram_message)
            
            # Enhanced Discord embed for each player
            if Config.DISCORD_WEBHOOK_URL:
                embed = {
                    "title": f"✅ {card.get('name', 'Unknown')} Back in Market!",
                    "description": f"This player is now available for purchase again",
                    "color": 0x00ff00,  # Green color for positive news
                    "timestamp": datetime.now().isoformat(),
                    "fields": [
                        {
                            "name": "🔄 Status",
                            "value": "Available",
                            "inline": True
                        },
                        {
                            "name": "⭐ Rating",
                            "value": str(card.get('rating', '?')),
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
                
                # Add player URL if available
                if card.get('fut_gg_url'):
                    embed["url"] = card.get('fut_gg_url')
                    embed["fields"].append({
                        "name": "🔗 Link",
                        "value": f"[View on FUT.GG]({card.get('fut_gg_url')})",
                        "inline": False
                    })
                
                payload = {"embeds": [embed]}
                
                try:
                    response = requests.post(Config.DISCORD_WEBHOOK_URL, json=payload)
                    if response.status_code == 204:
                        print(f"Individual Discord availability alert sent for {card.get('name')}")
                    else:
                        print(f"Discord error for {card.get('name')}: {response.status_code}")
                except Exception as e:
                    print(f"Discord error for {card.get('name')}: {e}")
            
            # Small delay between notifications
            time.sleep(2)
        
        # Send summary if multiple players became available
        if len(no_longer_extinct_cards) > 1:
            summary_message = f"✅ SUMMARY: {len(no_longer_extinct_cards)} players are back in market!"
            self.send_telegram_notification(summary_message)
            
            if Config.DISCORD_WEBHOOK_URL:
                # Create a summary embed with all players
                player_list = []
                for card in no_longer_extinct_cards[:10]:  # Limit to 10 in summary
                    player_list.append(f"✅ **{card.get('name', 'Unknown')}** ({card.get('rating', '?')})")
                
                if len(no_longer_extinct_cards) > 10:
                    player_list.append(f"... and {len(no_longer_extinct_cards) - 10} more!")
                
                summary_embed = {
                    "title": f"🎉 {len(no_longer_extinct_cards)} Players Back in Market!",
                    "description": "\n".join(player_list),
                    "color": 0x00ff88,  # Bright green
                    "timestamp": datetime.now().isoformat(),
                    "fields": [
                        {
                            "name": "💡 Tip",
                            "value": "These players were previously extinct and are now available for purchase!",
                            "inline": False
                        }
                    ],
                    "footer": {
                        "text": "FUT.GG Extinct Monitor - Market Update",
                        "icon_url": "https://www.fut.gg/favicon.ico"
                    }
                }
                
                summary_payload = {"embeds": [summary_embed]}
                
                try:
                    requests.post(Config.DISCORD_WEBHOOK_URL, json=summary_payload)
                    print(f"Discord summary sent for {len(no_longer_extinct_cards)} available players")
                except Exception as e:
                    print(f"Discord summary error: {e}")
        
        print(f"Completed sending availability alerts for {len(no_longer_extinct_cards)} players")

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
    
    def run_complete_system(self):
        """Run the complete extinct monitoring system using URL-based tracking"""
        print("🚀 Starting FUT.GG Extinct Player Monitor with URL-based tracking!")
        print("🐛 DEBUG: run_complete_system called")
        sys.stdout.flush()
        
        # Send startup notification
        print("🐛 DEBUG: About to send startup notification")
        sys.stdout.flush()
        self.check_and_send_startup_notification()
        print("🐛 DEBUG: Startup notification sent")
        sys.stdout.flush()
        
        # Start the URL-based monitoring
        print("🔥 Starting URL-based extinct monitoring...")
        sys.stdout.flush()
        try:
            print("🐛 DEBUG: About to call monitor_extinct_players_by_url()")
            sys.stdout.flush()
            self.monitor_extinct_players_by_url()
            print("🐛 DEBUG: monitor_extinct_players_by_url() returned")
            sys.stdout.flush()
        except Exception as e:
            print(f"⚠️ Error in monitoring: {e}")
            sys.stdout.flush()
            import traceback
            traceback.print_exc()
            sys.stdout.flush()

# Entry point
if __name__ == "__main__":
    monitor = FutGGExtinctMonitor()
    monitor.run_complete_system()
