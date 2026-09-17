#!/bin/bash
# Duplo clique neste arquivo abre a dashboard no navegador.
cd "$(dirname "$0")" || exit 1
exec python3 servidor.py
