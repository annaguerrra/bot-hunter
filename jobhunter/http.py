"""Prazo por requisição para buscas em funções temporárias, sem estado global."""
import time
from contextlib import contextmanager
from contextvars import ContextVar
import requests

_deadline = ContextVar('hunter_http_deadline', default=None)


class SearchDeadlineExceeded(RuntimeError):
    def __init__(self):
        super().__init__('O tempo desta busca terminou. Resultados concluídos foram preservados; refine os filtros para continuar.')


def checkpoint():
    value = _deadline.get()
    if value is not None and time.monotonic() >= value:
        raise SearchDeadlineExceeded()


@contextmanager
def deadline(seconds=None):
    token = _deadline.set(time.monotonic() + seconds if seconds is not None else None)
    try:
        yield
    finally:
        _deadline.reset(token)


def _request(method, url, **kwargs):
    checkpoint()
    expires = _deadline.get()
    if expires is not None:
        # Reserva tempo para ler/processar a resposta e gravar os resultados no Neon.
        remaining = expires - time.monotonic()
        if remaining <= 2:
            raise SearchDeadlineExceeded()
        timeout = kwargs.get('timeout', (5, 20))
        connect, read = timeout if isinstance(timeout, tuple) else (timeout, timeout)
        budget = max(.1, (remaining - 1) / 2)
        kwargs['timeout'] = (min(connect, budget), min(read, budget))
    return getattr(requests, method)(url, **kwargs)


def get(url, **kwargs):
    return _request('get', url, **kwargs)


def post(url, **kwargs):
    return _request('post', url, **kwargs)
