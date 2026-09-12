#!/bin/zsh
# CognitioFlow — double-click to start. Opens in its own window, ready to tile beside Claude.
cd "$(dirname "$0")" || exit 1

if [ ! -d .venv ]; then
  echo "Setting up for the first time..."
  python3 -m venv .venv || { echo "Python 3 not found. Install from python.org, then try again."; read; exit 1; }
  source .venv/bin/activate
  pip install --quiet --upgrade pip
  pip install --quiet -r requirements.txt
else
  source .venv/bin/activate
  pip install --quiet -r requirements.txt 2>/dev/null
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "No .env yet — opening it. Paste your API key after ANTHROPIC_API_KEY= , save, then run this again."
  open -e .env
  read
  exit 0
fi

# Free the port if an old instance is still running
lsof -ti:8000 | xargs kill -9 2>/dev/null

URL="http://localhost:8000"
(
  sleep 3
  CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
  if [ -x "$CHROME" ]; then
    # App-mode: no tabs, no address bar — a clean window you can tile
    "$CHROME" --app="$URL" --window-size=1180,1000 >/dev/null 2>&1 &
  else
    open -a Safari "$URL"
  fi
) &

echo ""
echo "CognitioFlow is starting. Window opens in a moment."
echo "Tile it: hold the green button, choose Tile Window to Right of Screen."
echo "Leave this Terminal window open. Press Ctrl-C here to stop."
echo ""
python run.py
