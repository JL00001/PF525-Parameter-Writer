#!/usr/bin/env nix-shell
#!nix-shell -i bash -p "python3.withPackages (ps: with ps; [pandas openpyxl tkinter pip])"
# Launches GUI.py on NixOS: pulls pandas/openpyxl/tkinter/pip from nixpkgs (one
# merged environment, so nothing shadows its tkinter-enabled python3 - see the
# README for why a nested `nix-shell -p ...pip` or a plain venv breaks this),
# then pip-installs pycomm3 (not in nixpkgs) into ./pylibs on first run.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

if ! PYTHONPATH="$PWD/pylibs" python3 -c "import pycomm3" 2>/dev/null; then
    echo "Installing pycomm3 into ./pylibs ..."
    pip install --target=./pylibs pycomm3
fi

exec env PYTHONPATH="$PWD/pylibs" python3 GUI.py
