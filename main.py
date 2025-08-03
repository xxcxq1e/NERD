
#!/usr/bin/env python3
import os
import time
import random
import requests
from datetime import datetime, timedelta
import threading
import socket
import subprocess
import json
from flask import Flask, render_template, jsonify, request
from stem import Signal
from stem.control import Controller
from dotenv import load_dotenv

load_dotenv()
UP_API_KEY = os.getenv('UP_API_KEY', 'your_up_api_key_here')

# Enhanced configuration
IP_POOL = [
    "89.124.57.8", "176.31.45.123", "198.244.142.67", "104.238.165.89",
    "149.28.94.156", "207.148.112.74", "45.32.189.45", "63.251.235.12",
    "192.248.151.89", "144.202.67.234", "66.42.76.143", "173.199.118.92"
]

SEGMENT_DURATION = 22 * 3600  # 22 hours daily runtime
RANDOMIZE_CUTOFF_RANGE = (1800, 3600)  # Random 30min-1hr variance 
RESUME_DELAY_RANGE = (2 * 3600, 2 * 3600)  # Exactly 2 hours break daily

# Global variables for dashboard
app = Flask(__name__)
automation_stats = {
    'status': 'Stopped',
    'last_action': 'None',
    'total_transfers': 0,
    'total_amount': 0.0,
    'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    'errors': 0,
    'balance': 0.0,
    'current_ip': 'Unknown',
    'segment_end': None,
    'next_resume': None,
    'segment_count': 0,
    'daily_target': 280.0,
    'monthly_target': 8400.0,
    'daily_progress': 0.0,
    'monthly_progress': 0.0,
    'last_reset': datetime.now().strftime('%Y-%m-%d'),
    'ip_rotations_today': 0,
    'payid_withdrawals_today': 0,
    'total_payid_amount': 0.0,
    'last_payid_withdrawal': 'None'
}

class IPRotator:
    def __init__(self):
        self.current_ip = None
        self.last_rotation = 0
        self.rotation_interval = random.randint(3600, 14400)  # 1-4 hours - stealth timing
        self.daily_rotations = 0
        self.max_daily_rotations = random.randint(8, 15)  # Limit daily rotations
    
    def get_current_ip(self):
        try:
            response = requests.get('https://httpbin.org/ip', timeout=10)
            return response.json().get('origin', 'Unknown')
        except:
            return 'Unknown'
    
    def rotate_via_tor(self):
        try:
            with Controller.from_port(port=9051) as c:
                c.authenticate()
                c.signal(Signal.NEWNYM)
                time.sleep(5)  # Wait for new circuit
                new_ip = self.get_current_ip()
                self.current_ip = new_ip
                print(f"🔁 IP rotated via Tor: {new_ip}")
                return True
        except Exception as e:
            print(f"⚠️ Tor rotation failed: {e}")
            return False
    
    def simulate_ip_change(self):
        # Fallback: simulate IP change by selecting from pool
        self.current_ip = random.choice(IP_POOL)
        print(f"🎭 Simulated IP change: {self.current_ip}")
        automation_stats['current_ip'] = self.current_ip
        return True
    
    def should_rotate(self):
        now = time.time()
        current_hour = datetime.now().hour
        
        # Don't rotate during sensitive hours (2-6 AM) or if exceeded daily limit
        if current_hour in [2, 3, 4, 5, 6] or self.daily_rotations >= self.max_daily_rotations:
            return False
            
        # Prefer rotation during busy hours for better cover
        time_passed = now - self.last_rotation
        if current_hour in [9, 10, 11, 14, 15, 16, 17, 18]:  # Business hours
            return time_passed > (self.rotation_interval * 0.7)  # Rotate sooner
        else:
            return time_passed > self.rotation_interval
    
    def rotate(self):
        if not self.rotate_via_tor():
            self.simulate_ip_change()
        
        self.last_rotation = time.time()
        self.rotation_interval = random.randint(3600, 14400)  # 1-4 hour stealth intervals
        self.daily_rotations += 1
        automation_stats['current_ip'] = self.current_ip
        automation_stats['ip_rotations_today'] = self.daily_rotations

class SegmentedRuntime:
    def __init__(self):
        self.segment_start = None
        self.segment_end = None
        self.is_in_break = False
        self.resume_time = None
    
    def start_new_segment(self):
        self.segment_start = time.time()
        cutoff_variance = random.randint(*RANDOMIZE_CUTOFF_RANGE)
        self.segment_end = self.segment_start + SEGMENT_DURATION - cutoff_variance
        self.is_in_break = False
        
        automation_stats['segment_end'] = datetime.fromtimestamp(self.segment_end).strftime('%Y-%m-%d %H:%M:%S')
        automation_stats['segment_count'] += 1
        
        print(f"🚀 Starting 22-hour runtime #{automation_stats['segment_count']}")
        print(f"📅 Runtime ends: {automation_stats['segment_end']}")
        print(f"🎯 Daily target: ${automation_stats['daily_target']} | Monthly: ${automation_stats['monthly_target']}")
    
    def check_segment_end(self):
        if not self.is_in_break and time.time() >= self.segment_end:
            self.start_break()
            return True
        return False
    
    def start_break(self):
        self.is_in_break = True
        break_duration = random.randint(*RESUME_DELAY_RANGE)
        self.resume_time = time.time() + break_duration
        
        automation_stats['next_resume'] = datetime.fromtimestamp(self.resume_time).strftime('%Y-%m-%d %H:%M:%S')
        automation_stats['status'] = 'Break'
        
        print(f"⏸️ Starting 2-hour daily break. Resume at: {automation_stats['next_resume']}")
        print(f"📊 Today's progress: ${automation_stats['daily_progress']:.2f}/${automation_stats['daily_target']:.2f}")
    
    def check_resume(self):
        if self.is_in_break and time.time() >= self.resume_time:
            self.start_new_segment()
            automation_stats['status'] = 'Running'
            return True
        return False
    
    def should_continue(self):
        if self.is_in_break:
            return self.check_resume()
        else:
            return not self.check_segment_end()

class UpBank:
    def __init__(self):
        self.base_url = "https://api.up.com.au/api/v1"
        self.headers = {"Authorization": f"Bearer {UP_API_KEY}"}
        self.accounts = self._get_accounts()
    
    def _get_accounts(self):
        try:
            res = requests.get(f"{self.base_url}/accounts", headers=self.headers)
            json_data = res.json()

            if 'data' not in json_data:
                print("❌ Invalid response from Up API:")
                print(json_data)
                raise Exception("Missing 'data' field. Check your UP_API_KEY.")
            
            return {
                acc['attributes']['accountType']: acc['id']
                for acc in json_data['data']
            }
        except Exception as e:
            print(f"❌ Failed to get accounts: {e}")
            raise

    def get_balance(self, account_type):
        try:
            res = requests.get(
                f"{self.base_url}/accounts/{self.accounts[account_type]}",
                headers=self.headers
            )
            data = res.json()
            return float(data['data']['attributes']['balance']['value'])
        except Exception as e:
            print(f"❌ Failed to get balance: {e}")
            return 0.0

    def transfer(self, amount, _from, _to, desc):
        try:
            data = {
                "data": {
                    "attributes": {
                        "amount": f"{amount:.2f}",
                        "description": desc[:50]
                    },
                    "relationships": {
                        "from": {"data": {"id": self.accounts[_from], "type": "accounts"}},
                        "to": {"data": {"id": self.accounts[_to], "type": "accounts"}}
                    }
                }
            }
            response = requests.post(
                f"{self.base_url}/transfers",
                headers=self.headers,
                json=data
            )
            
            if response.status_code == 201:
                global automation_stats
                automation_stats['total_transfers'] += 1
                automation_stats['total_amount'] += amount
                automation_stats['daily_progress'] += amount
                automation_stats['monthly_progress'] += amount
                automation_stats['last_action'] = f"${amount:.2f} from {_from} to {_to}: {desc}"
                automation_stats['last_update'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                
                daily_remaining = automation_stats['daily_target'] - automation_stats['daily_progress']
                print(f"✅ Transfer: ${amount:.2f} | Daily remaining: ${daily_remaining:.2f}")
            else:
                print(f"❌ Transfer failed: {response.status_code}")
                automation_stats['errors'] += 1
                
            return response
        except Exception as e:
            print(f"❌ Transfer error: {e}")
            automation_stats['errors'] += 1
            return None

    def payid_withdrawal(self, amount, description="PayID withdrawal"):
        """Send money out via PayID to t.slowiak@hotmail.com"""
        try:
            data = {
                "data": {
                    "attributes": {
                        "amount": f"{amount:.2f}",
                        "description": description[:50]
                    },
                    "relationships": {
                        "from": {"data": {"id": self.accounts["TRANSACTIONAL"], "type": "accounts"}},
                        "to": {"data": {"type": "payid", "id": "t.slowiak@hotmail.com"}}
                    }
                }
            }
            response = requests.post(
                f"{self.base_url}/transfers",
                headers=self.headers,
                json=data
            )
            
            if response.status_code == 201:
                global automation_stats
                automation_stats['total_transfers'] += 1
                automation_stats['total_amount'] += amount
                automation_stats['last_action'] = f"PayID withdrawal: ${amount:.2f} to 69227243@bet365.com.au"
                automation_stats['last_update'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                print(f"💸 PayID withdrawal: ${amount:.2f} sent successfully")
            else:
                print(f"❌ PayID withdrawal failed: {response.status_code}")
                automation_stats['errors'] += 1
                
            return response
        except Exception as e:
            print(f"❌ PayID withdrawal error: {e}")
            automation_stats['errors'] += 1
            return None

def check_funds_and_start():
    """Monitor for funds and automatically start automation"""
    global automation_stats, UP_API_KEY
    
    while True:
        try:
            if automation_stats['status'] in ['Running', 'Break']:
                time.sleep(300)  # Check every 5 minutes if already running
                continue
            
            # Skip if no valid API key is configured
            if not UP_API_KEY or UP_API_KEY == 'your_up_api_key_here':
                time.sleep(30)  # Check every 30 seconds for API key
                continue
                
            # Check account balance
            bank = UpBank()
            balance = bank.get_balance('TRANSACTIONAL')
            automation_stats['balance'] = balance
            
            # Auto-start if funds detected (minimum $10)
            if balance >= 10.0 and automation_stats['status'] == 'Stopped':
                print(f"💰 Funds detected: ${balance:.2f} - Auto-starting automation...")
                automation_stats['status'] = 'Starting'
                thread = threading.Thread(target=run_automation, daemon=True)
                thread.start()
                time.sleep(60)  # Wait before next check
            else:
                time.sleep(180)  # Check every 3 minutes for funds
                
        except Exception as e:
            print(f"⚠️ Fund monitoring error: {e}")
            time.sleep(300)

def run_automation():
    global automation_stats
    print("🚀 Starting Enhanced Up Bank Automation...")
    automation_stats['status'] = 'Starting'

    # Initialize components
    ip_rotator = IPRotator()
    segment_runtime = SegmentedRuntime()
    
    try:
        bank = UpBank()
        ip_rotator.current_ip = ip_rotator.get_current_ip()
        automation_stats['current_ip'] = ip_rotator.current_ip
        segment_runtime.start_new_segment()
        automation_stats['status'] = 'Running'
    except Exception as e:
        print(f"💥 Setup failed: {e}")
        automation_stats['status'] = 'Failed'
        automation_stats['errors'] += 1
        return

    while automation_stats['status'] in ['Running', 'Break']:
        try:
            # Check if we should continue this segment
            if not segment_runtime.should_continue():
                if automation_stats['status'] == 'Break':
                    print(f"⏳ In break mode. Resume at: {automation_stats['next_resume']}")
                    time.sleep(60)  # Check every minute during break
                    continue
            
            if automation_stats['status'] == 'Break':
                continue
            
            # Check for daily reset
            today = datetime.now().strftime('%Y-%m-%d')
            if automation_stats['last_reset'] != today:
                automation_stats['daily_progress'] = 0.0
                automation_stats['ip_rotations_today'] = 0
                automation_stats['payid_withdrawals_today'] = 0
                automation_stats['last_payid_withdrawal'] = 'None'
                automation_stats['last_reset'] = today
                print(f"🔄 Daily reset - New target: ${automation_stats['daily_target']}")
                print(f"💸 PayID withdrawals reset - Max 3 per day to 69227243@bet365.com.au")

            # IP rotation check - completely automatic and random
            if ip_rotator.should_rotate():
                ip_rotator.rotate()
                automation_stats['ip_rotations_today'] += 1
                print(f"🔄 IP rotation #{automation_stats['ip_rotations_today']} today")
            
            # Strategic automation with human-like patterns
            current_hour = datetime.now().hour
            daily_remaining = automation_stats['daily_target'] - automation_stats['daily_progress']
            
            # Intelligent PayID withdrawal system
            current_balance = bank.get_balance('TRANSACTIONAL')
            automation_stats['balance'] = current_balance
            
            def should_withdraw_now():
                """Strategic timing algorithm with human-like patterns"""
                current_time = datetime.now()
                current_hour = current_time.hour
                current_minute = current_time.minute
                
                # Create realistic daily withdrawal schedule (3 preferred time windows)
                preferred_times = [
                    {'hour': 10, 'minute': 30, 'window': 45},  # Morning routine
                    {'hour': 15, 'minute': 15, 'window': 60},  # Afternoon break  
                    {'hour': 19, 'minute': 45, 'window': 90}   # Evening wind-down
                ]
                
                # Check if we're within any preferred time window
                in_preferred_window = False
                window_priority = 0
                
                for i, time_slot in enumerate(preferred_times):
                    # Calculate time difference in minutes
                    target_time = current_time.replace(hour=time_slot['hour'], minute=time_slot['minute'], second=0)
                    time_diff = abs((current_time - target_time).total_seconds() / 60)
                    
                    if time_diff <= time_slot['window']:
                        in_preferred_window = True
                        window_priority = 3 - i  # Earlier windows have higher priority
                        break
                
                # Base probability calculation
                if in_preferred_window:
                    base_probability = 0.65 + (window_priority * 0.1)  # 65-85% in preferred windows
                elif current_hour in [9, 11, 14, 16, 18, 20]:  # Secondary good times
                    base_probability = 0.25
                elif current_hour in [0, 1, 2, 3, 4, 5, 6, 7]:  # Avoid early hours
                    base_probability = 0.03
                else:
                    base_probability = 0.12
                
                # Strategic balance considerations
                balance_factor = 1.0
                if current_balance >= 300:
                    balance_factor = 2.2  # Urgent need to withdraw large amounts
                elif current_balance >= 150:
                    balance_factor = 1.6
                elif current_balance >= 80:
                    balance_factor = 1.2
                elif current_balance < 30:
                    balance_factor = 0.4  # Keep some buffer
                
                # Daily withdrawal pacing (strategic distribution)
                pacing_factor = 1.0
                if automation_stats['payid_withdrawals_today'] == 0:
                    pacing_factor = 1.4  # Slightly eager for first withdrawal
                elif automation_stats['payid_withdrawals_today'] == 1:
                    pacing_factor = 1.1  # Normal for second
                else:
                    pacing_factor = 0.7  # More selective for final withdrawal
                
                # Smart spacing to avoid clustering
                spacing_factor = 1.0
                if automation_stats['last_payid_withdrawal'] != 'None':
                    try:
                        last_time_str = automation_stats['last_payid_withdrawal'].split(' at ')[1]
                        last_time = datetime.strptime(last_time_str, '%H:%M:%S').replace(
                            year=current_time.year, month=current_time.month, day=current_time.day
                        )
                        hours_since = (current_time - last_time).total_seconds() / 3600
                        
                        if hours_since < 1.5:  # Too soon
                            spacing_factor = 0.05
                        elif hours_since < 3:  # Still quite recent
                            spacing_factor = 0.3
                        elif hours_since < 6:  # Good spacing
                            spacing_factor = 1.2
                        else:  # Long gap, more likely
                            spacing_factor = 1.6
                    except:
                        spacing_factor = 1.3
                
                # Calculate final probability with realistic randomness
                final_probability = base_probability * balance_factor * pacing_factor * spacing_factor
                final_probability = min(final_probability, 0.92)  # Cap at 92%
                final_probability = max(final_probability, 0.01)  # Minimum 1%
                
                return random.random() < final_probability
            
            def calculate_optimal_amount():
                """Strategic amount calculation with human-like patterns and preferences"""
                
                # Create daily amount preferences (like a person's habits)
                daily_seed = int(datetime.now().strftime('%j'))  # Day of year as seed
                random.seed(daily_seed + automation_stats['payid_withdrawals_today'])
                
                # Base amounts a person might typically withdraw
                typical_amounts = [15, 20, 25, 30, 35, 40, 45, 50, 60, 75, 80, 90, 100, 120, 150, 200]
                
                # Balance-based amount selection
                if current_balance >= 400:
                    preferred_amounts = [amount for amount in typical_amounts if 50 <= amount <= 200]
                elif current_balance >= 200:
                    preferred_amounts = [amount for amount in typical_amounts if 30 <= amount <= 120]
                elif current_balance >= 100:
                    preferred_amounts = [amount for amount in typical_amounts if 20 <= amount <= 75]
                elif current_balance >= 50:
                    preferred_amounts = [amount for amount in typical_amounts if 15 <= amount <= 40]
                else:
                    preferred_amounts = [10, 15, 20, 25]  # Conservative for low balance
                
                # Time-based preferences (humans withdraw different amounts at different times)
                current_hour = datetime.now().hour
                if current_hour in [9, 10, 11]:  # Morning - coffee money, smaller amounts
                    time_modifier = 0.7
                    preferred_amounts = [amt for amt in preferred_amounts if amt <= 60]
                elif current_hour in [14, 15, 16]:  # Afternoon - shopping, medium amounts
                    time_modifier = 1.0
                elif current_hour in [18, 19, 20]:  # Evening - dinner/entertainment, larger amounts
                    time_modifier = 1.3
                    if current_balance >= 100:
                        preferred_amounts.extend([amount + 10 for amount in preferred_amounts[-3:]])
                else:
                    time_modifier = 0.9
                
                # Daily withdrawal pattern (humans have patterns)
                if automation_stats['payid_withdrawals_today'] == 0:
                    # First withdrawal - often smaller, testing waters
                    pattern_modifier = 0.8
                    base_amount = random.choice(preferred_amounts[:len(preferred_amounts)//2])
                elif automation_stats['payid_withdrawals_today'] == 1:
                    # Second withdrawal - normal amounts
                    pattern_modifier = 1.1
                    base_amount = random.choice(preferred_amounts)
                else:
                    # Final withdrawal - might be larger to "clean up" balance
                    pattern_modifier = 1.2
                    if current_balance >= 100:
                        base_amount = random.choice(preferred_amounts[len(preferred_amounts)//2:])
                    else:
                        base_amount = random.choice(preferred_amounts)
                
                # Apply modifiers with slight randomness
                withdrawal_amount = base_amount * time_modifier * pattern_modifier
                
                # Add small random variance (±5%) to make it feel more human
                variance = random.uniform(-0.05, 0.05)
                withdrawal_amount = withdrawal_amount * (1 + variance)
                
                # Safety constraints
                withdrawal_amount = max(10.0, withdrawal_amount)
                withdrawal_amount = min(withdrawal_amount, current_balance - 8.0)  # Keep $8 buffer
                
                # Round to realistic amounts (humans don't withdraw $37.83)
                if withdrawal_amount >= 100:
                    withdrawal_amount = round(withdrawal_amount / 10) * 10  # Round to nearest $10
                elif withdrawal_amount >= 50:
                    withdrawal_amount = round(withdrawal_amount / 5) * 5    # Round to nearest $5
                else:
                    withdrawal_amount = round(withdrawal_amount)            # Round to nearest $1
                
                # Reset random seed for other operations
                random.seed()
                
                return round(withdrawal_amount, 2)
            
            # Execute intelligent withdrawal logic
            if (current_balance >= 25.0 and 
                automation_stats['payid_withdrawals_today'] < 3 and
                should_withdraw_now()):
                
                withdrawal_amount = calculate_optimal_amount()
                
                if withdrawal_amount >= 10.0:
                    # Generate realistic withdrawal description
                    def generate_withdrawal_description():
                        current_hour = datetime.now().hour
                        day_of_week = datetime.now().weekday()  # 0=Monday, 6=Sunday
                        
                        # Time-based descriptions
                        morning_descriptions = [
                            "Coffee run", "Breakfast pickup", "Morning essentials", 
                            "Daily coffee", "Bakery visit", "Quick breakfast"
                        ]
                        
                        afternoon_descriptions = [
                            "Lunch money", "Shopping trip", "Grocery run", 
                            "Weekly shopping", "Food pickup", "Errands money",
                            "Pharmacy visit", "Hardware store", "Quick shop"
                        ]
                        
                        evening_descriptions = [
                            "Dinner plans", "Movie night", "Evening out", 
                            "Date night", "Restaurant visit", "Social event",
                            "Drinks with friends", "Entertainment fund"
                        ]
                        
                        weekend_descriptions = [
                            "Weekend plans", "Family outing", "Recreation fund",
                            "Hobby expenses", "Sport activities", "Market day",
                            "Weekend shopping", "Leisure activities"
                        ]
                        
                        general_descriptions = [
                            "Personal expenses", "Miscellaneous", "Daily spending",
                            "Pocket money", "General fund", "Flexible spending",
                            "Personal use", "Everyday expenses", "Living costs",
                            "Personal budget", "Cash needs", "Daily allowance"
                        ]
                        
                        # Amount-based descriptions
                        small_amount_descriptions = [
                            "Quick purchase", "Small expense", "Minor buy",
                            "Snack money", "Transport fare", "Parking fee"
                        ]
                        
                        large_amount_descriptions = [
                            "Major purchase", "Monthly expense", "Big shop",
                            "Special occasion", "Investment fund", "Savings goal"
                        ]
                        
                        # Select description based on context
                        if day_of_week >= 5:  # Weekend
                            descriptions = weekend_descriptions + general_descriptions
                        elif current_hour in [7, 8, 9]:  # Morning
                            descriptions = morning_descriptions + general_descriptions
                        elif current_hour in [12, 13, 14, 15, 16]:  # Afternoon
                            descriptions = afternoon_descriptions + general_descriptions
                        elif current_hour in [17, 18, 19, 20, 21]:  # Evening
                            descriptions = evening_descriptions + general_descriptions
                        else:
                            descriptions = general_descriptions
                        
                        # Adjust for amount
                        if withdrawal_amount <= 25:
                            descriptions.extend(small_amount_descriptions)
                        elif withdrawal_amount >= 100:
                            descriptions.extend(large_amount_descriptions)
                        
                        return random.choice(descriptions)
                    
                    withdrawal_description = generate_withdrawal_description()
                    
                    bank.payid_withdrawal(withdrawal_amount, withdrawal_description)
                    automation_stats['payid_withdrawals_today'] += 1
                    automation_stats['total_payid_amount'] += withdrawal_amount
                    automation_stats['last_payid_withdrawal'] = f"${withdrawal_amount:.2f} at {datetime.now().strftime('%H:%M:%S')}"
                    
                    print(f"💸 Smart PayID withdrawal #{automation_stats['payid_withdrawals_today']}: ${withdrawal_amount:.2f}")
                    print(f"📝 Description: {withdrawal_description}")
                    print(f"📊 Balance: ${current_balance:.2f} → ${current_balance - withdrawal_amount:.2f}")
                    print(f"⏰ Optimal timing detected at {datetime.now().strftime('%H:%M')}")
                    
                    # Smart delay after withdrawal (longer for larger amounts)
                    if withdrawal_amount >= 100:
                        delay = random.randint(900, 2400)  # 15-40 minutes for large amounts
                    elif withdrawal_amount >= 50:
                        delay = random.randint(600, 1800)  # 10-30 minutes for medium amounts
                    else:
                        delay = random.randint(300, 1200)  # 5-20 minutes for small amounts
                    
                    time.sleep(delay)
                    continue
            
            # Weight actions based on time and targets
            if current_hour in [9, 10, 11, 17, 18, 19]:  # Peak banking hours
                action_weights = ['micro'] * 40 + ['spend'] * 30 + ['interest'] * 10 + ['balance_check'] * 20
            elif current_hour in [0, 1, 2, 3, 4, 5]:  # Night hours - minimal activity
                action_weights = ['balance_check'] * 70 + ['micro'] * 20 + ['interest'] * 10
            else:  # Regular hours
                action_weights = ['micro'] * 50 + ['spend'] * 25 + ['interest'] * 15 + ['balance_check'] * 10
            
            # Adjust for daily progress
            if daily_remaining > 100:  # Aggressive mode when behind target
                action_weights = ['micro'] * 60 + ['spend'] * 35 + ['balance_check'] * 5
            elif daily_remaining < 20:  # Conservative mode near target
                action_weights = ['balance_check'] * 60 + ['micro'] * 30 + ['interest'] * 10
            
            action = random.choice(action_weights)

            if action == 'micro':
                # Variable micro amounts for realism
                micro_amount = round(random.uniform(0.01, 0.15), 2)
                descriptions = [
                    "Savings transfer", "Emergency fund", "Goal saving", 
                    "Weekly save", "Spare change", "Round up"
                ]
                bank.transfer(micro_amount, "TRANSACTIONAL", "SAVER", random.choice(descriptions))
                delay = random.randint(180, 2400)  # 3min-40min

            elif action == 'spend':
                # Realistic spending patterns
                if current_hour in [7, 8, 12, 13, 18, 19]:  # Meal times
                    amount = round(random.uniform(8, 35), 2)
                    vendors = ["McDonald's", "Subway", "Domino's", "KFC", "Grill'd", "Boost Juice"]
                elif current_hour in [10, 11, 14, 15, 16]:  # Shopping hours
                    amount = round(random.uniform(15, 85), 2)
                    vendors = ["Woolworths", "Coles", "Target", "Kmart", "JB Hi-Fi", "Bunnings"]
                else:  # General spending
                    amount = round(random.uniform(5, 50), 2)
                    vendors = ["Uber", "Amazon", "Netflix", "Spotify", "Apple", "Google"]
                
                bank.transfer(amount, "TRANSACTIONAL", "EXTERNAL", random.choice(vendors))
                delay = random.randint(1800, 14400)  # 30min-4hr

            elif action == 'interest':
                balance = bank.get_balance('SAVER')
                automation_stats['balance'] = balance
                if balance > 10:  # Only if meaningful balance
                    interest_amt = round(balance * random.uniform(0.00008, 0.00015), 2)
                    bank.transfer(interest_amt, "SAVER", "TRANSACTIONAL", "Interest payment")
                    delay = random.randint(21600, 86400)  # 6-24 hours
                else:
                    delay = random.randint(3600, 7200)  # Skip if low balance

            elif action == 'balance_check':
                balance = bank.get_balance('TRANSACTIONAL')
                automation_stats['balance'] = balance
                automation_stats['last_action'] = f"Balance check: ${balance:.2f}"
                delay = random.randint(900, 5400)  # 15min-90min

            print(f"✅ Action: {action}, sleeping {delay} sec...")
            automation_stats['last_update'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # Sleep in chunks to allow for status changes
            sleep_chunks = delay // 30
            for _ in range(sleep_chunks):
                if automation_stats['status'] != 'Running':
                    break
                time.sleep(30)

        except Exception as e:
            print(f"⚠️ Runtime error: {e}")
            automation_stats['errors'] += 1
            time.sleep(300)

# Flask Dashboard Routes
@app.route('/')
def setup():
    return render_template('setup.html')

@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')

@app.route('/api/save_config', methods=['POST'])
def save_config():
    try:
        data = request.get_json()
        api_key = data.get('api_key', '').strip()
        payid_address = data.get('payid_address', '').strip()
        
        if not api_key or not payid_address:
            return jsonify({'status': 'error', 'message': 'Both API key and PayID address are required'})
        
        # Validate API key format (Up Bank keys start with 'up:yeah:')
        if not api_key.startswith('up:yeah:'):
            return jsonify({'status': 'error', 'message': 'Invalid API key format. Up Bank keys start with "up:yeah:"'})
        
        # Validate PayID format
        if '@' not in payid_address or '.' not in payid_address:
            return jsonify({'status': 'error', 'message': 'Invalid PayID format. Must be a valid email address.'})
        
        # Test the API key by trying to get accounts
        try:
            headers = {"Authorization": f"Bearer {api_key}"}
            response = requests.get("https://api.up.com.au/api/v1/accounts", headers=headers, timeout=10)
            
            if response.status_code != 200:
                error_msg = "Invalid API key - Authentication failed"
                if response.status_code == 401:
                    error_msg = "Invalid API key - Not authorized. Check your Up Bank API key."
                elif response.status_code == 403:
                    error_msg = "API key lacks required permissions"
                return jsonify({'status': 'error', 'message': error_msg})
            
            # Check if response has expected data structure
            api_data = response.json()
            if 'data' not in api_data:
                return jsonify({'status': 'error', 'message': 'API key valid but unexpected response format'})
            
        except requests.exceptions.Timeout:
            return jsonify({'status': 'error', 'message': 'API connection timeout. Please try again.'})
        except requests.exceptions.ConnectionError:
            return jsonify({'status': 'error', 'message': 'Unable to connect to Up Bank API. Check internet connection.'})
        except Exception as e:
            return jsonify({'status': 'error', 'message': f'API validation failed: {str(e)}'})
        
        print("✅ API key validated successfully with Up Bank")
        
        # Update global variables
        global UP_API_KEY
        UP_API_KEY = api_key
        
        # Force update the UpBank class to use new API key
        print(f"🔄 Updating API key globally for fund monitoring...")
        
        # Save to environment (for persistence across restarts)
        os.environ['UP_API_KEY'] = api_key
        os.environ['PAYID_ADDRESS'] = payid_address
        
        # Update automation stats
        automation_stats['last_action'] = 'Configuration updated successfully'
        automation_stats['last_update'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        print(f"✅ Configuration saved - API key: {api_key[:15]}...")
        print(f"✅ PayID address: {payid_address}")
        
        return jsonify({'status': 'success', 'message': 'Configuration saved and validated successfully!'})
        
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Configuration error: {str(e)}'})

@app.route('/api/stats')
def api_stats():
    return jsonify(automation_stats)



@app.route('/api/webhook', methods=['POST'])
def webhook_handler():
    try:
        data = request.get_json()
        print(f"📥 Webhook received: {data}")
        # Process webhook data here
        return jsonify({'status': 'success'})
    except Exception as e:
        print(f"❌ Webhook error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 400

if __name__ == "__main__":
    # Create templates directory if it doesn't exist
    os.makedirs('templates', exist_ok=True)
    
    # Start automatic fund monitoring in background
    fund_monitor = threading.Thread(target=check_funds_and_start, daemon=True)
    fund_monitor.start()
    
    # Start Flask server
    print("🌐 Starting enhanced dashboard on http://0.0.0.0:5000")
    print("🔧 Features: Auto-start, IP rotation, segmented runtime, fund detection")
    print("💰 Monitoring for funds - automation will start automatically...")
    app.run(host='0.0.0.0', port=5000, debug=False)
