
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
    'daily_target': 200.0,
    'monthly_target': 6000.0,
    'daily_progress': 0.0,
    'monthly_progress': 0.0,
    'last_reset': datetime.now().strftime('%Y-%m-%d'),
    'ip_rotations_today': 0
}

class IPRotator:
    def __init__(self):
        self.current_ip = None
        self.last_rotation = 0
        self.rotation_interval = random.randint(1800, 10800)  # 30 minutes to 3 hours - completely random
    
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
        return (now - self.last_rotation) > self.rotation_interval
    
    def rotate(self):
        if not self.rotate_via_tor():
            self.simulate_ip_change()
        
        self.last_rotation = time.time()
        self.rotation_interval = random.randint(1800, 10800)  # Completely random 30min-3hr intervals
        automation_stats['current_ip'] = self.current_ip

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
                automation_stats['last_reset'] = today
                print(f"🔄 Daily reset - New target: ${automation_stats['daily_target']}")

            # IP rotation check - completely automatic and random
            if ip_rotator.should_rotate():
                ip_rotator.rotate()
                automation_stats['ip_rotations_today'] += 1
                print(f"🔄 IP rotation #{automation_stats['ip_rotations_today']} today")
            
            # Main automation logic
            action = random.choice(['micro', 'spend', 'interest', 'balance_check'])

            if action == 'micro':
                bank.transfer(0.01, "TRANSACTIONAL", "SAVER", "Micro-transfer")
                delay = random.randint(300, 1800)

            elif action == 'spend':
                amount = round(random.uniform(5, 50), 2)
                desc = random.choice(["Woolworths", "Uber", "Amazon", "Netflix", "Coles", "JB Hi-Fi"])
                bank.transfer(amount, "TRANSACTIONAL", "EXTERNAL", desc)
                delay = random.randint(3600, 7200)

            elif action == 'interest':
                balance = bank.get_balance('SAVER')
                automation_stats['balance'] = balance
                interest_amt = round(balance * 0.0001, 2)
                if interest_amt > 0:
                    bank.transfer(interest_amt, "SAVER", "TRANSACTIONAL", "Interest")
                delay = random.randint(43200, 86400)  # 12-24 hours

            elif action == 'balance_check':
                balance = bank.get_balance('TRANSACTIONAL')
                automation_stats['balance'] = balance
                automation_stats['last_action'] = f"Balance check: ${balance:.2f}"
                delay = random.randint(1800, 3600)  # 30-60 minutes

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
def dashboard():
    return render_template('dashboard.html')

@app.route('/api/stats')
def api_stats():
    return jsonify(automation_stats)

@app.route('/api/start')
def start_automation():
    if automation_stats['status'] not in ['Running', 'Break']:
        automation_stats['status'] = 'Starting'
        thread = threading.Thread(target=run_automation, daemon=True)
        thread.start()
        return jsonify({'message': 'Automation started'})
    return jsonify({'message': 'Already running'})

@app.route('/api/stop')
def stop_automation():
    automation_stats['status'] = 'Stopped'
    return jsonify({'message': 'Automation stopped'})

@app.route('/api/force_ip_rotation')
def force_ip_rotation():
    if 'ip_rotator' in globals():
        ip_rotator.rotate()
        return jsonify({'message': f'IP rotated to {automation_stats["current_ip"]}'})
    return jsonify({'message': 'IP rotator not available'})

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
    
    # Start Flask server
    print("🌐 Starting enhanced dashboard on http://0.0.0.0:5000")
    print("🔧 Features: IP rotation, segmented runtime, enhanced automation")
    app.run(host='0.0.0.0', port=5000, debug=False)
