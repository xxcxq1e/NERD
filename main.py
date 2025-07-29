
#!/usr/bin/env python3
import os
import time
import random
import requests
from datetime import datetime
import threading
from flask import Flask, render_template, jsonify
from stem import Signal
from stem.control import Controller
from dotenv import load_dotenv

load_dotenv()
UP_API_KEY = os.getenv('UP_API_KEY', 'your_up_api_key_here')

# Global variables for dashboard
app = Flask(__name__)
automation_stats = {
    'status': 'Stopped',
    'last_action': 'None',
    'total_transfers': 0,
    'total_amount': 0.0,
    'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    'errors': 0,
    'balance': 0.0
}

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
                automation_stats['last_action'] = f"${amount:.2f} from {_from} to {_to}: {desc}"
                automation_stats['last_update'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                print(f"✅ Transfer successful: ${amount:.2f} from {_from} to {_to}")
            else:
                print(f"❌ Transfer failed: {response.status_code}")
                automation_stats['errors'] += 1
                
            return response
        except Exception as e:
            print(f"❌ Transfer error: {e}")
            automation_stats['errors'] += 1
            return None

def rotate_ip():
    try:
        with Controller.from_port(port=9051) as c:
            c.authenticate()
            c.signal(Signal.NEWNYM)
            print("🔁 IP rotated via Tor!")
    except Exception as e:
        print(f"⚠️ Tor rotation failed: {e}")

def run_automation():
    global automation_stats
    print("🚀 Starting Up Bank Automation...")
    automation_stats['status'] = 'Running'

    try:
        bank = UpBank()
    except Exception as e:
        print(f"💥 Setup failed: {e}")
        automation_stats['status'] = 'Failed'
        automation_stats['errors'] += 1
        return

    while automation_stats['status'] == 'Running':
        try:
            now = int(time.time())
            if now % 21600 < 60:
                rotate_ip()

            action = random.choice(['micro', 'spend', 'interest'])

            if action == 'micro':
                bank.transfer(0.01, "TRANSACTIONAL", "SAVER", "Micro-transfer")
                delay = random.randint(300, 1800)

            elif action == 'spend':
                amount = round(random.uniform(5, 50), 2)
                desc = random.choice(["Woolworths", "Uber", "Amazon", "Netflix"])
                bank.transfer(amount, "TRANSACTIONAL", "EXTERNAL", desc)
                delay = random.randint(3600, 7200)

            elif action == 'interest':
                balance = bank.get_balance('SAVER')
                automation_stats['balance'] = balance
                interest_amt = round(balance * 0.0001, 2)
                if interest_amt > 0:
                    bank.transfer(interest_amt, "SAVER", "TRANSACTIONAL", "Interest")
                delay = 86400

            print(f"✅ Action: {action}, sleeping {delay} sec...")
            time.sleep(delay)

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
    if automation_stats['status'] != 'Running':
        automation_stats['status'] = 'Starting'
        thread = threading.Thread(target=run_automation, daemon=True)
        thread.start()
        return jsonify({'message': 'Automation started'})
    return jsonify({'message': 'Already running'})

@app.route('/api/stop')
def stop_automation():
    automation_stats['status'] = 'Stopped'
    return jsonify({'message': 'Automation stopped'})

if __name__ == "__main__":
    # Create templates directory and dashboard
    os.makedirs('templates', exist_ok=True)
    
    # Start Flask server
    print("🌐 Starting dashboard on http://0.0.0.0:5000")
    app.run(host='0.0.0.0', port=5000, debug=False)
