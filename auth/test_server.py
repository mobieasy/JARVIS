import concurrent.futures
import http.client
import json
from pathlib import Path
import re
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, MagicMock
from server import valid_origin, Store, Denied, make_server, send_sms, SESSION, SESSION_SECONDS, IDLE_SECONDS


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.now = 10000
        self.path = Path(self.tmp.name)/'auth.db'
        self.store = Store(self.path,'test-secret-'*8,['9000000001'],lambda:self.now)

    def tearDown(self):
        self.tmp.cleanup()

    def challenge(self):
        return self.store.create_challenge('+919000000001','browser','123456')

    def test_code_is_single_use_and_browser_bound(self):
        challenge=self.challenge()
        with self.assertRaises(Denied): self.store.verify(challenge,'123456','other','1.2.3.4')
        token=self.store.verify(challenge,'123456','browser','1.2.3.4')
        self.assertTrue(self.store.session(token))
        with self.assertRaises(Denied): self.store.verify(challenge,'123456','browser','1.2.3.4')
        with self.store.db() as db:
            self.assertNotIn('123456',str(db.execute('SELECT * FROM challenges').fetchall()))
            self.assertNotIn(token,str(db.execute('SELECT * FROM sessions').fetchall()))

    def test_expiry_wrong_attempt_limit_and_resend(self):
        challenge=self.challenge()
        for _ in range(5):
            with self.assertRaises(Denied): self.store.verify(challenge,'000000','browser','1.2.3.4')
        with self.assertRaises(Denied): self.store.verify(challenge,'123456','browser','1.2.3.4')
        old=self.challenge()
        fresh=self.challenge()
        with self.assertRaises(Denied): self.store.verify(old,'123456','browser','1.2.3.4')
        self.now+=301
        with self.assertRaises(Denied): self.store.verify(fresh,'123456','browser','1.2.3.4')

    def test_parallel_verification_has_only_one_winner(self):
        challenge=self.challenge()
        def verify(_):
            try: return bool(self.store.verify(challenge,'123456','browser','1.2.3.4'))
            except Denied: return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(sum(pool.map(verify,range(4))),1)

    def test_limits_survive_restart_and_failed_delivery(self):
        self.store.reserve_send('+919000000001','1.2.3.4')
        again=Store(self.path,'test-secret-'*8,['9000000001'],lambda:self.now)
        with self.assertRaises(Denied) as error: again.reserve_send('+919000000001','1.2.3.4')
        self.assertEqual(error.exception.status,429)
        self.now+=61
        again.reserve_send('+919000000001','1.2.3.4')
        for _ in range(8):
            with self.assertRaises(Denied): again.reserve_send('+919000000002','1.2.3.4')
        with self.assertRaises(Denied) as error: again.reserve_send('+919000000002','1.2.3.4')
        self.assertEqual(error.exception.status,429)

    def test_session_persistence_logout_idle_and_absolute_expiry(self):
        token=self.store.verify(self.challenge(),'123456','browser','1.2.3.4')
        again=Store(self.path,'test-secret-'*8,['9000000001'],lambda:self.now)
        self.assertTrue(again.session(token))
        again.logout(token)
        self.assertFalse(self.store.session(token))
        token=self.store.verify(self.challenge(),'123456','browser','1.2.3.4')
        self.now+=IDLE_SECONDS+1
        self.assertFalse(self.store.session(token))
        token=self.store.verify(self.challenge(),'123456','browser','1.2.3.4')
        self.now+=SESSION_SECONDS+1
        self.assertFalse(self.store.session(token,touch=True))


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.config={'PUBLIC_ORIGIN':'https://jarvis.example.com','AUTH_DB':str(Path(self.tmp.name)/'auth.db'),
                     'AUTH_SECRET':'secret-'*10,'ALLOWED_PHONES':'9000000001'}
        self.sent=[]
        def sender(_,phone,code): self.sent.append((phone,code)); return True
        self.server=make_server(self.config,sender=sender,address=('127.0.0.1',0))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        status,headers,body=self.request('GET','/auth/login')
        self.assertEqual(status,200)
        self.cookie=headers['Set-Cookie'].split(';')[0]
        self.csrf=re.search(r'name="csrf-token" content="([^"]+)',body.decode()).group(1)

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()

    def request(self,method,path,data=None,headers=None):
        connection=http.client.HTTPConnection(*self.server.server_address,timeout=5)
        connection.request(method,path,body=json.dumps(data) if data is not None else None,headers=headers or {})
        response=connection.getresponse();result=(response.status,dict(response.getheaders()),response.read());connection.close();return result

    def browser_headers(self):
        return {'Cookie':self.cookie,'Origin':self.config['PUBLIC_ORIGIN'],'X-CSRF-Token':self.csrf,'Content-Type':'application/json'}

    def login(self):
        status,_,body=self.request('POST','/auth/request',{'phone':'9000000001'},self.browser_headers())
        self.assertEqual(status,200)
        challenge=json.loads(body)['challenge']
        status,headers,_=self.request('POST','/auth/verify',{'challenge':challenge,'code':self.sent[-1][1]},self.browser_headers())
        self.assertEqual(status,200)
        cookie=headers['Set-Cookie'];self.assertIn('Secure',cookie);self.assertIn('HttpOnly',cookie);self.assertIn('SameSite=Lax',cookie)
        return cookie.split(';')[0]

    def test_csrf_denies_without_sms_and_forged_identity_cannot_login(self):
        headers=self.browser_headers();headers['Origin']='https://attacker.invalid'
        self.assertEqual(self.request('POST','/auth/request',{'phone':'9000000001'},headers)[0],403)
        self.assertEqual(self.sent,[])
        self.assertEqual(self.request('POST','/auth/request',{'phone':'9000000002'},self.browser_headers())[0],403)
        self.assertEqual(self.sent,[])
        status,_,_=self.request('POST','/tools/invoke',{}, {'X-Jarvis-User':'owner','X-Jarvis-Authenticated':'sms-otp'})
        self.assertEqual(status,401)

    def test_session_login_logout_and_csrf(self):
        cookie=self.login()
        self.assertEqual(self.request('GET','/auth/account',headers={'Cookie':cookie})[0],200)
        self.assertEqual(self.request('POST','/auth/logout',{}, {'Cookie':cookie})[0],403)
        status,_,body=self.request('GET','/auth/account',headers={'Cookie':cookie})
        csrf=re.search(r'name="csrf-token" content="([^"]+)',body.decode()).group(1)
        self.assertEqual(self.request('POST','/auth/logout',{}, {'Cookie':cookie,'Origin':self.config['PUBLIC_ORIGIN'],'X-CSRF-Token':csrf})[0],200)
        self.assertEqual(self.request('GET','/auth/account',headers={'Cookie':cookie})[0],303)

    def test_failed_provider_does_not_create_valid_challenge(self):
        self.server.sender=lambda *_:False
        status,_,body=self.request('POST','/auth/request',{'phone':'9000000001'},self.browser_headers())
        self.assertEqual(status,502);self.assertNotIn('challenge',json.loads(body))
        with self.server.store.db() as db: self.assertEqual(db.execute('SELECT count(*) FROM challenges').fetchone()[0],0)

    def test_websocket_header_stripping_and_logout_disconnect(self):
        cookie=self.login()
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen();listener.settimeout(5)
        self.server.gateway_address=listener.getsockname()
        captured=[]
        def fake_gateway():
            with listener.accept()[0] as connection:
                connection.settimeout(5);data=b''
                while b'\r\n\r\n' not in data: data+=connection.recv(4096)
                captured.append(data.decode())
                connection.sendall(b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n')
                data=connection.recv(4)
                if data: connection.sendall(data)
                with contextlib.suppress(OSError): connection.recv(1)
        import contextlib
        worker=threading.Thread(target=fake_gateway,daemon=True);worker.start()
        with socket.create_connection(self.server.server_address,timeout=5) as client:
            client.settimeout(5)
            client.sendall(('GET / HTTP/1.1\r\nHost: jarvis.example.com\r\nOrigin: '+self.config['PUBLIC_ORIGIN']+'\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nCookie: '+cookie+'\r\nX-Jarvis-User: attacker\r\nX-Openclaw-Scopes: operator.admin\r\nAuthorization: Bearer stolen\r\n\r\n').encode())
            response=client.recv(4096);self.assertIn(b'101 Switching',response)
            client.sendall(b'PING');self.assertEqual(client.recv(4),b'PING')
            self.assertIn('X-Jarvis-User: owner',captured[0]);self.assertNotIn('attacker',captured[0]);self.assertNotIn('stolen',captured[0]);self.assertNotIn(SESSION,captured[0]);self.assertNotIn('operator.admin',captured[0])
            self.server.store.logout(cookie.split('=',1)[1])
            self.assertEqual(client.recv(1),b'')
        worker.join(5);listener.close()


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.config={'SMS_API_KEY':'fake-test-key','SMS_ENDPOINT':'https://apitxt.com/api/sendMsg',
                     'SMS_MESSAGE':'Your existing OTP is {OTP}.','SMS_SENDER':'TEST',
                     'SMS_ROUTE':'4','SMS_TEMPLATE_ID':'test-template','SMS_ENTITY_ID':'test-entity'}

    def result(self, body, status=200):
        response=MagicMock();response.status=status;response.read.return_value=json.dumps(body).encode()
        opener=MagicMock();opener.open.return_value.__enter__.return_value=response
        return opener

    def test_provider_requires_positive_acceptance_and_exact_payload(self):
        opener=self.result({'status':200,'message':'success'})
        with patch('server.urllib.request.build_opener',return_value=opener):
            self.assertTrue(send_sms(self.config,'+919000000001','012345'))
        request=opener.open.call_args.args[0]
        body=json.loads(request.data)
        self.assertEqual(body['mobiles'],'919000000001')
        self.assertEqual(body['message'],'Your existing OTP is 012345.')
        self.assertEqual(body['template_id'],'test-template')

    def test_rejection_unknown_response_and_transport_failure_fail_closed(self):
        for body,status in [({'status':200,'message':'invalid template'},200),({},200),({'status':200,'message':'success'},500)]:
            with patch('server.urllib.request.build_opener',return_value=self.result(body,status)):
                self.assertFalse(send_sms(self.config,'+919000000001','012345'))
        opener=MagicMock();opener.open.side_effect=TimeoutError()
        with patch('server.urllib.request.build_opener',return_value=opener):
            self.assertFalse(send_sms(self.config,'+919000000001','012345'))


if __name__=='__main__': unittest.main()


class OriginTests(unittest.TestCase):
    def test_generic_https_origin(self):
        self.assertTrue(valid_origin('https://assistant.example.org'))
        self.assertTrue(valid_origin('https://assistant.example.org:8443'))

    def test_rejects_non_origin_values(self):
        for value in ['http://assistant.example.org', 'https://user:pass@example.org',
                      'https://example.org/path', 'https://example.org?x=1',
                      'https://example.org#fragment', 'https://', 'https://bad host',
                      'https://example.org:99999']:
            with self.subTest(value=value):
                self.assertFalse(valid_origin(value))
