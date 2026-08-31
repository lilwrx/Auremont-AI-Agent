#!/bin/bash

set -e

echo "=== AI20K Project Setup ==="

python3 -c "import sys; assert sys.version_info >= (3, 11), 'Python 3.11+ required'"
echo "Python version OK"

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env — please edit with your API keys"
fi

mkdir -p data/chroma

echo "Setup complete! Run: uvicorn src.main:app --reload"
