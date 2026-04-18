#!/usr/bin/env bash
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"

cd ~/candace-ai-agent/qq-ai-bridge || exit 1
nvm use 22.22.1 >/dev/null || exit 1

python bridge.py
