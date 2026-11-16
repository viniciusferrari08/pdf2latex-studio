#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d ".venv" ]; then
    echo "[!] Ambiente virtual .venv não encontrado em $SCRIPT_DIR"
    exit 1
fi

echo "=========================================="
echo " Iniciando PDF2LaTeX Studio (Streamlit)"
echo "=========================================="
exec .venv/bin/streamlit run app.py --server.address 127.0.0.1 --server.headless false
