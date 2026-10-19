"""Disposable-test-only verified TLS bridge to the user's MailDev on 1025.

No production configuration or trust store is changed. The bridge binds only
loopback, creates a temporary localhost certificate, and forwards SMTP only to
localhost:1025. The preview worker trusts that exact certificate. The existing
production SMTP implementation still performs TLS and hostname verification.
"""
from pathlib import Path
import select,socket,ssl,subprocess,threading


class MailDevBridge:
    def __init__(self,directory):
        directory=Path(directory);self.certificate=directory/'maildev-localhost.pem';key=directory/'maildev-localhost.key'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-keyout',str(key),'-out',str(self.certificate),'-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost,IP:127.0.0.1'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        key.chmod(0o600)
        self.context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);self.context.load_cert_chain(self.certificate,key)
        self.socket=socket.socket();self.socket.bind(('127.0.0.1',0));self.socket.listen();self.socket.settimeout(0.25);self.port=self.socket.getsockname()[1]
        self.stopped=threading.Event();self.thread=threading.Thread(target=self.accept,daemon=True);self.thread.start()

    def accept(self):
        while not self.stopped.is_set():
            try:connection,_=self.socket.accept()
            except socket.timeout:continue
            except OSError:break
            threading.Thread(target=self.forward,args=(connection,),daemon=True).start()

    def forward(self,connection):
        try:
            connection.settimeout(10)
            with self.context.wrap_socket(connection,server_side=True) as client,socket.create_connection(('localhost',1025),timeout=10) as maildev:
                while not self.stopped.is_set():
                    ready,_,_=select.select([client,maildev],[],[],0.25)
                    for source in ready:
                        data=source.recv(65536)
                        if not data:return
                        (maildev if source is client else client).sendall(data)
                    # SSLSocket may have decrypted bytes buffered after select.
                    while client.pending():maildev.sendall(client.recv(65536))
        except (OSError,ssl.SSLError):pass
        finally:connection.close()

    def close(self):
        self.stopped.set();self.socket.close();self.thread.join(timeout=1)
