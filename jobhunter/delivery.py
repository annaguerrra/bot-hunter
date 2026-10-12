"""Ritmo de envio para respeitar limites de chats Telegram."""
import hashlib
import threading
import time


class TelegramPacer:
    def __init__(self, clock=time.monotonic, sleep=time.sleep):
        self.clock, self.sleep = clock, sleep
        self.last = {}
        self.lock = threading.Lock()

    def send(self, sender, token, chat_id, message):
        # Não guarda o token em texto nas chaves do controle de ritmo.
        identity = hashlib.sha256((token + ':' + str(chat_id)).encode()).hexdigest()
        interval = 3.1 if str(chat_id).startswith('-') else 1.1
        with self.lock:
            now = self.clock()
            self.last = {key: value for key, value in self.last.items() if now - value < 60}
            wait = interval - (now - self.last[identity]) if identity in self.last else 0
            if wait > 0:
                self.sleep(wait)
            # Falhas também consomem uma tentativa; o histórico só marca sucessos.
            self.last[identity] = self.clock()
            return sender(token, chat_id, message)
