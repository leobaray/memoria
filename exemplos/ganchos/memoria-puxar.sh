#!/bin/bash
# Gancho UserPromptSubmit do Claude Code: manda o texto de cada mensagem pra memória e devolve o pacote do que foi
# citado, que entra no contexto da conversa. Sem nada citado, não imprime nada. Nunca trava a mensagem: desiste em 5 s.
#
# Instalar: copie pra ~/.claude/hooks/, ajuste MEMORIA e registre no ~/.claude/settings.json:
#   "hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "bash \"$HOME/.claude/hooks/memoria-puxar.sh\"", "timeout": 8}]}]}
# Memória em outra máquina: troque a última linha por
#   printf '%s' "$prompt" | timeout 5 ssh -o ConnectTimeout=2 -o BatchMode=yes servidor 'python3 /caminho/mem.py puxar' 2>/dev/null
MEMORIA="$HOME/memoria"

# robô que roda `claude -p` e não deve contar como uso: exporte MEMORIA_SEM_GANCHO=1 no lançador dele
[ -n "$MEMORIA_SEM_GANCHO" ] && exit 0
entrada=$(cat)
prompt=$(printf '%s' "$entrada" | python3 -c "import sys,json; sys.stdout.write(json.load(sys.stdin).get('prompt',''))" 2>/dev/null)
[ -z "$prompt" ] && exit 0
# aviso do sistema (tarefa em segundo plano terminou etc.) não é a pessoa falando
case "$prompt" in *"<task-notification>"*|*"SYSTEM NOTIFICATION"*) exit 0 ;; esac
printf '%s' "$prompt" | timeout 5 python3 "$MEMORIA/mem.py" puxar 2>/dev/null
exit 0
