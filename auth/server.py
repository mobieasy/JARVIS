"""Private SMS login and authenticated HTTP/WebSocket proxy for JARVIS."""
import contextlib
import hashlib
import hmac
import html
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import select
import socket
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SESSION = '__Host-jarvis_session'
PREAUTH = '__Host-jarvis_preauth'
OTP_SECONDS = 300
SESSION_SECONDS = 7 * 86400
IDLE_SECONDS = 12 * 3600
OWNER = 'owner'


def valid_origin(value):
    try:
        parts = urllib.parse.urlsplit(value)
        return bool(parts.scheme == 'https' and parts.hostname
                    and re.fullmatch(r'[A-Za-z0-9.-]+', parts.hostname)
                    and not parts.username and not parts.password
                    and not parts.path and not parts.query and not parts.fragment
                    and (parts.port is None or 1 <= parts.port <= 65535))
    except ValueError:
        return False


class Denied(Exception):
    def __init__(self, message='Unable to verify this code. Request a new one.', status=400):
        self.message, self.status = message, status


def normalize_phone(value):
    value = str(value).strip().replace(' ', '').replace('-', '')
    if re.fullmatch(r'[6-9][0-9]{9}', value):
        return '+91' + value
    if re.fullmatch(r'\+91[6-9][0-9]{9}', value):
        return value
    raise Denied('Enter a valid Indian mobile number.')


class Store:
    def __init__(self, path, secret, allowed, clock=time.time):
        self.path, self.secret, self.clock = str(path), secret.encode(), clock
        self.allowed = {normalize_phone(x) for x in allowed}
        with self.db() as db:
            db.executescript('''
              PRAGMA journal_mode=WAL;
              CREATE TABLE IF NOT EXISTS challenges(id TEXT PRIMARY KEY, phone TEXT, browser TEXT,
                  digest TEXT, expires REAL, attempts INTEGER DEFAULT 0, used INTEGER DEFAULT 0);
              CREATE TABLE IF NOT EXISTS sessions(digest TEXT PRIMARY KEY, expires REAL, touched REAL);
              CREATE TABLE IF NOT EXISTS events(kind TEXT, subject TEXT, ts REAL);
              CREATE INDEX IF NOT EXISTS event_lookup ON events(kind,subject,ts);
            ''')

    @contextlib.contextmanager
    def db(self):
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def digest(self, value):
        return hmac.new(self.secret, value.encode(), hashlib.sha256).hexdigest()

    def csrf(self, browser):
        return self.digest('csrf:' + browser)

    def _limit(self, db, kind, subject, limit, seconds):
        count = db.execute('SELECT count(*) FROM events WHERE kind=? AND subject=? AND ts>?',
                           (kind, subject, self.clock() - seconds)).fetchone()[0]
        if count >= limit:
            raise Denied('Too many attempts. Please wait before trying again.', 429)

    def reserve_send(self, phone, ip):
        if phone not in self.allowed:
            # Apply the IP limit to disallowed numbers as well.
            allowed = False
        else:
            allowed = True
        now, ipkey, phonekey = self.clock(), self.digest(ip), self.digest(phone)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM events WHERE ts<?', (now - 86400,))
            self._limit(db, 'ip_send', ipkey, 10, 3600)
            if allowed:
                self._limit(db, 'phone_send', phonekey, 1, 60)
                self._limit(db, 'phone_send', phonekey, 6, 3600)
                self._limit(db, 'phone_send', phonekey, 20, 86400)
            db.execute('INSERT INTO events VALUES(?,?,?)', ('ip_send', ipkey, now))
            if allowed:
                db.execute('INSERT INTO events VALUES(?,?,?)', ('phone_send', phonekey, now))
        if not allowed:
            raise Denied('Unable to send a login code to this number.', 403)

    def create_challenge(self, phone, browser, code):
        challenge = secrets.token_urlsafe(32)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM challenges WHERE expires<?', (self.clock() - 3600,))
            db.execute('UPDATE challenges SET used=1 WHERE phone=?', (self.digest(phone),))
            db.execute('INSERT INTO challenges(id,phone,browser,digest,expires) VALUES(?,?,?,?,?)',
                       (challenge, self.digest(phone), self.digest(browser),
                        self.digest(challenge + ':' + code), self.clock() + OTP_SECONDS))
        return challenge

    def verify(self, challenge, code, browser, ip):
        now, error, token = self.clock(), None, None
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            ipkey = self.digest(ip)
            db.execute('DELETE FROM events WHERE ts<?', (now - 86400,))
            self._limit(db, 'ip_verify', ipkey, 30, 900)
            db.execute('INSERT INTO events VALUES(?,?,?)', ('ip_verify', ipkey, now))
            row = db.execute('SELECT browser,digest,expires,attempts,used FROM challenges WHERE id=?',
                             (challenge,)).fetchone()
            if not row or row[0] != self.digest(browser) or row[2] <= now or row[4] or row[3] >= 5:
                error = Denied()
            else:
                db.execute('UPDATE challenges SET attempts=attempts+1 WHERE id=?', (challenge,))
                if not re.fullmatch(r'[0-9]{6}', str(code)) or not hmac.compare_digest(row[1], self.digest(challenge + ':' + code)):
                    error = Denied('Incorrect code. Check the SMS and try again.')
                else:
                    db.execute('UPDATE challenges SET used=1 WHERE id=?', (challenge,))
                    token = secrets.token_urlsafe(32)
                    db.execute('DELETE FROM sessions WHERE expires<? OR touched<?', (now, now - IDLE_SECONDS))
                    db.execute('INSERT INTO sessions VALUES(?,?,?)',
                               (self.digest(token), now + SESSION_SECONDS, now))
        if error:
            raise error
        return token

    def session(self, token, touch=False):
        if not token or len(token) > 128:
            return False
        now, digest = self.clock(), self.digest(token)
        with self.db() as db:
            row = db.execute('SELECT expires,touched FROM sessions WHERE digest=?', (digest,)).fetchone()
            valid = bool(row and row[0] > now and row[1] > now - IDLE_SECONDS)
            if valid and touch:
                db.execute('UPDATE sessions SET touched=? WHERE digest=?', (now, digest))
            return valid

    def logout(self, token):
        with self.db() as db:
            db.execute('DELETE FROM sessions WHERE digest=?', (self.digest(token),))


def send_sms(config, phone, code):
    # Keep the existing DLT-registered wording, sender and template paired.
    payload = {'authkey': config['SMS_API_KEY'], 'mobiles': phone.removeprefix('+'),
               'message': config['SMS_MESSAGE'].replace('{OTP}', code),
               'sender': config['SMS_SENDER'], 'route': config['SMS_ROUTE'],
               'template_id': config['SMS_TEMPLATE_ID'], 'pe_id': config['SMS_ENTITY_ID']}
    request = urllib.request.Request(config['SMS_ENDPOINT'], data=json.dumps(payload).encode(),
                                     headers={'Content-Type': 'application/json', 'Accept': 'application/json'})
    # Never send credentials to an alternate host through an HTTP redirect.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=12) as response:
            body = json.loads(response.read(262144))
            status = str(body.get('status', body.get('code', ''))).lower().strip()
            message = str(body.get('message', '')).lower().strip()
            rejected = re.search(r'\b(error|fail|failed|invalid|unauthori[sz]ed|denied)\b',
                                 ' '.join(str(body.get(k, '')) for k in ('status','type','message','error')), re.I)
            return response.status == 200 and not rejected and (status in ('200', 'success') or message == 'success')
    except (OSError, ValueError, urllib.error.HTTPError):
        return False


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'JARVIS'

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, *args):
        pass  # Do not log mobile numbers, codes, cookies or request bodies.

    def cookies(self):
        jar = SimpleCookie()
        with contextlib.suppress(Exception):
            jar.load(self.headers.get('Cookie', ''))
        return {k: v.value for k, v in jar.items()}

    @property
    def store(self):
        return self.server.store

    def respond(self, status, data, content_type='application/json', headers=None):
        if isinstance(data, dict):
            data = json.dumps(data).encode()
        elif isinstance(data, str):
            data = data.encode()
        self.send_response(status)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if 'Connection' not in (headers or {}):
            self.send_header('Connection', 'close')
        self.close_connection = True
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(data)

    def ip(self):
        # Caddy overwrites this header; this service is loopback-only.
        value = self.headers.get('X-Forwarded-For', self.client_address[0]).split(',')[-1].strip()
        try:
            return str(ipaddress.ip_address(value))
        except ValueError:
            raise Denied('Invalid request.', 400)

    def origin(self):
        if self.headers.get('Origin') != self.server.origin:
            raise Denied('Refresh this page and try again.', 403)

    def body(self, maximum=8192):
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length < 1 or length > maximum or self.headers.get('Transfer-Encoding'):
                raise ValueError()
            return json.loads(self.rfile.read(length))
        except (ValueError, OSError):
            raise Denied('Invalid request.', 400)

    def csrf_check(self, token):
        self.origin()
        if not token or not hmac.compare_digest(self.headers.get('X-CSRF-Token', ''), self.store.csrf(token)):
            raise Denied('Refresh this page and try again.', 403)

    def html_page(self, page, token, cookies=None):
        nonce = secrets.token_urlsafe(24)
        text = Path(__file__).with_name(page).read_text().replace('__NONCE__', nonce).replace('__CSRF__', self.store.csrf(token))
        headers = {'Content-Security-Policy': "default-src 'none'; script-src 'nonce-" + nonce + "'; style-src 'nonce-" + nonce + "'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"}
        if cookies:
            headers['Set-Cookie'] = cookies
        self.respond(200, text, 'text/html; charset=utf-8', headers)

    def auth_routes(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == '/auth/health':
            self.respond(200, {'ok': True})
            return
        if path == '/auth/login' and self.command in ('GET', 'HEAD'):
            if self.store.session(self.cookies().get(SESSION)):
                self.respond(303, '', headers={'Location': '/'})
                return
            browser = self.cookies().get(PREAUTH, '')
            if not re.fullmatch(r'[A-Za-z0-9_-]{43}', browser):
                browser = secrets.token_urlsafe(32)
            self.html_page('login.html', browser, PREAUTH + '=' + browser + '; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=1200')
            return
        if path in ('/auth/account', '/auth/logout') and self.command in ('GET', 'HEAD'):
            token = self.cookies().get(SESSION)
            if not self.store.session(token):
                self.respond(303, '', headers={'Location': '/auth/login'})
            else:
                self.html_page('account.html', token)
            return
        if path == '/auth/logout' and self.command == 'POST':
            token = self.cookies().get(SESSION, '')
            self.csrf_check(token)
            self.store.logout(token)
            self.respond(200, {'ok': True}, headers={'Set-Cookie': SESSION + '=; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=0'})
            return
        if path not in ('/auth/request', '/auth/verify') or self.command != 'POST':
            raise Denied('Not found.', 404)
        browser = self.cookies().get(PREAUTH, '')
        self.csrf_check(browser)
        data = self.body()
        if not isinstance(data, dict):
            raise Denied('Invalid request.')
        if path == '/auth/request':
            phone = normalize_phone(data.get('phone', ''))
            self.store.reserve_send(phone, self.ip())
            code = str(secrets.randbelow(1000000)).zfill(6)
            if not self.server.sender(self.server.config, phone, code):
                raise Denied('SMS delivery is temporarily unavailable. Please try again later.', 502)
            challenge = self.store.create_challenge(phone, browser, code)
            self.respond(200, {'ok': True, 'challenge': challenge, 'expiresIn': OTP_SECONDS, 'retryAfter': 60})
        else:
            token = self.store.verify(str(data.get('challenge','')), str(data.get('code','')), browser, self.ip())
            destination = '/auth/account' if self.server.config.get('LOGIN_SUCCESS_PATH') == '/auth/account' else '/'
            self.respond(200, {'ok': True, 'redirect': destination}, headers={'Set-Cookie': SESSION + '=' + token + '; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=' + str(SESSION_SECONDS)})

    def upstream_headers(self, length=None, websocket=False):
        drop = {'authorization','proxy-authorization','x-jarvis-user','x-jarvis-authenticated','x-openclaw-scopes',
                'x-forwarded-for','x-forwarded-host','x-forwarded-proto','forwarded','x-real-ip','connection',
                'keep-alive','proxy-connection','te','trailer','transfer-encoding','upgrade','host','content-length'}
        headers = {k:v for k,v in self.headers.items() if k.lower() not in drop and '\r' not in v and '\n' not in v}
        cookie = self.cookies()
        cookie.pop(SESSION, None)
        cookie.pop(PREAUTH, None)
        headers.pop('Cookie', None)
        headers.pop('cookie', None)
        if cookie:
            headers['Cookie'] = '; '.join(k + '=' + v for k,v in cookie.items())
        headers.update({'Host': urllib.parse.urlsplit(self.server.origin).netloc,
                        'X-Forwarded-Host': urllib.parse.urlsplit(self.server.origin).netloc,
                        'X-Forwarded-Proto': 'https', 'X-Forwarded-For': self.ip(),
                        'X-Jarvis-User': OWNER, 'X-Jarvis-Authenticated': 'sms-otp'})
        if length is not None:
            headers['Content-Length'] = str(length)
        headers['Connection'] = 'Upgrade' if websocket else 'close'
        if websocket:
            headers['Upgrade'] = 'websocket'
        return headers

    def proxy(self):
        token = self.cookies().get(SESSION, '')
        websocket = self.headers.get('Upgrade','').lower() == 'websocket'
        if not self.store.session(token, touch=True):
            if not websocket and self.command in ('GET','HEAD') and 'text/html' in self.headers.get('Accept',''):
                self.respond(303, '', headers={'Location': '/auth/login'})
            else:
                raise Denied('Sign in with SMS to continue.', 401)
            return
        if websocket:
            self.origin()
            return self.proxy_websocket(token)
        if self.command not in ('GET', 'HEAD', 'OPTIONS'):
            self.origin()
        length = int(self.headers.get('Content-Length','0'))
        if length < 0 or length > 32*1024*1024 or self.headers.get('Transfer-Encoding'):
            raise Denied('Request is too large or unsupported.', 413)
        body = self.rfile.read(length) if length else None
        connection = http.client.HTTPConnection(*self.server.gateway_address,timeout=120)
        try:
            connection.request(self.command,self.path,body=body,headers=self.upstream_headers(length if body is not None else None))
            response = connection.getresponse()
            self.send_response(response.status)
            for key,value in response.getheaders():
                if key.lower() not in ('connection','transfer-encoding','keep-alive'):
                    self.send_header(key,value)
            self.send_header('Connection','close')
            self.end_headers()
            self.close_connection = True
            if self.command != 'HEAD':
                while data := response.read1(65536):
                    self.wfile.write(data)
                    self.wfile.flush()
        finally:
            connection.close()

    def proxy_websocket(self, token):
        with socket.create_connection(self.server.gateway_address,timeout=10) as upstream:
            headers = self.upstream_headers(websocket=True)
            request = 'GET ' + self.path + ' HTTP/1.1\r\n' + ''.join(k+': '+v+'\r\n' for k,v in headers.items()) + '\r\n'
            upstream.sendall(request.encode('latin-1'))
            response = b''
            while b'\r\n\r\n' not in response:
                data = upstream.recv(4096)
                if not data:
                    return
                response += data
                if len(response) > 65536:
                    raise OSError('Oversized handshake')
            self.connection.sendall(response)
            self.close_connection = True
            if not response.startswith(b'HTTP/1.1 101 '):
                return
            self.connection.settimeout(5)
            upstream.settimeout(5)
            touched = time.time()
            while self.store.session(token):
                ready,_,_ = select.select([self.connection,upstream],[],[],1)
                for source in ready:
                    data = source.recv(65536)
                    if not data:
                        return
                    (upstream if source is self.connection else self.connection).sendall(data)
                if ready and time.time()-touched > 60:
                    self.store.session(token,touch=True)
                    touched = time.time()
            # Session expiry/logout also closes established WebSockets.
            with contextlib.suppress(OSError):
                self.connection.shutdown(socket.SHUT_RDWR)

    def dispatch(self):
        self.connection.settimeout(20)
        try:
            if self.path.startswith('/auth/'):
                self.auth_routes()
            else:
                self.proxy()
        except Denied as error:
            self.close_connection = True
            self.respond(error.status, {'ok': False, 'message': error.message}, headers={'Connection':'close'})
        except (OSError, ValueError, sqlite3.Error):
            self.close_connection = True
            with contextlib.suppress(OSError):
                self.respond(502, {'ok':False,'message':'Connection unavailable. Please try again.'},headers={'Connection':'close'})

    do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = dispatch


class LimitedServer(ThreadingHTTPServer):
    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(48)
        super().__init__(*args, **kwargs)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request,address)
        finally:
            self.slots.release()


def make_server(config, store=None, sender=send_sms, address=('127.0.0.1',18889)):
    server = LimitedServer(address, Handler)
    server.daemon_threads = True
    server.origin, server.config, server.sender = config['PUBLIC_ORIGIN'], config, sender
    server.gateway_address = ('127.0.0.1',18789)
    server.store = store or Store(config['AUTH_DB'], config['AUTH_SECRET'], config['ALLOWED_PHONES'].split(','))
    return server


if __name__ == '__main__':
    config = dict(os.environ)
    for field in ('PUBLIC_ORIGIN','AUTH_DB','AUTH_SECRET','ALLOWED_PHONES','SMS_API_KEY','SMS_MESSAGE',
                  'SMS_ENDPOINT','SMS_SENDER','SMS_ROUTE','SMS_TEMPLATE_ID','SMS_ENTITY_ID'):
        if not config.get(field):
            raise SystemExit('Missing required auth configuration: ' + field)
    if len(config['AUTH_SECRET']) < 40 or not valid_origin(config['PUBLIC_ORIGIN']):
        raise SystemExit('Invalid authentication configuration')
    if urllib.parse.urlsplit(config['SMS_ENDPOINT']).netloc != 'apitxt.com' or not config['SMS_ENDPOINT'].startswith('https://'):
        raise SystemExit('Unexpected SMS endpoint')
    make_server(config).serve_forever()
