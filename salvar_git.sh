#!/bin/sh
# Guarda no git DOS DADOS (não no do código) tudo que mudou na memória. Uso: salvar_git.sh "motivo"
# Pro cron: depois do sonho e da coleta, e de hora em hora pras anotações feitas durante o dia.
# Só faz algo se a pasta dos dados for um repositório git (git -C "$(python3 mem.py onde)" init).
aqui=$(cd "$(dirname "$0")" && pwd)
dados=$(python3 "$aqui/mem.py" onde) || exit 1
cd "$dados" || exit 1
[ -d .git ] || exit 0
git add -A
git diff --cached --quiet && exit 0
n=$(git diff --cached --name-only | wc -l)
git commit -q -m "memória: ${1:-anotações do dia} ($n arquivos)" -m "Gravado por salvar_git.sh em $(date "+%d/%m/%Y %H:%M")."
