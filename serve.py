"""Servidor local para o inicializador de um clique."""
import argparse
from waitress import serve
from web import create_app

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=5000)
    args = parser.parse_args()
    serve(create_app(), host='127.0.0.1', port=args.port, threads=8)
