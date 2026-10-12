"""Copia somente recursos públicos conhecidos para o CDN do Vercel."""
import shutil
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]


def build(base=BASE):
    for directory in ('static', 'assets'):
        # Não copiamos .env, bancos, backups ou configurações privadas.
        shutil.copytree(base / directory, base / 'public' / directory, dirs_exist_ok=True)


if __name__ == '__main__':
    build()
