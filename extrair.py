#!/usr/bin/env python3
"""Extrai das conversas do Claude Code (~/.claude/projects/*/*.jsonl) só o texto: o que a pessoa escreveu e o que o
assistente respondeu, a partir de DESDE (ISO, UTC). Sem saída de ferramenta, sem hook, sem aviso do sistema. Uma linha
JSON por fala. Não importa nada do projeto de propósito: roda igual no Linux e no Windows, e em outra máquina vai pelo
stdin (`ssh maquina python - < extrair.py`). Env: DESDE, MAQUINA. O campo "quem" sai como "pessoa" ou "assistente"."""
import datetime, json, os, sys
from pathlib import Path

DESDE = os.environ.get("DESDE", "1970-01-01T00:00:00Z")
MAQ = os.environ.get("MAQUINA", "?")
raiz = Path.home() / ".claude" / "projects"
sys.stdout.reconfigure(encoding="utf-8")
# arquivo que não foi mexido desde DESDE não tem fala nova: pula sem ler (antes lia os ~860 MB todo dia); 1 h de folga
try:
    DESDE_SEG = datetime.datetime.fromisoformat(DESDE.replace("Z", "+00:00")).timestamp() - 3600
except ValueError:
    DESDE_SEG = 0

def texto_user(c):
    if isinstance(c, str):
        return c
    return "\n".join(x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text")


for f in raiz.glob("*/*.jsonl"):
    if "sonho" in f.parent.name:
        continue  # as conversas do próprio sonho não viram memória
    try:
        if f.stat().st_mtime < DESDE_SEG:
            continue
        with open(f, encoding="utf-8", errors="replace") as fh:
            for ln in fh:
                if '"timestamp"' not in ln:
                    continue
                try:
                    d = json.loads(ln)
                except Exception:
                    continue
                ts = d.get("timestamp") or ""
                if ts <= DESDE or d.get("isSidechain") or d.get("isMeta"):
                    continue
                # conversa de robô (claude -p, entrypoint sdk-*) não é a pessoa falando: se entrasse, viraria memória falsa
                if str(d.get("entrypoint", "")).startswith("sdk"):
                    continue
                msg = d.get("message") or {}
                if d.get("type") == "user":
                    t = texto_user(msg.get("content") or "").strip()
                    if not t or t.startswith("<") or "tool_use_id" in t:
                        continue
                    papel = "pessoa"
                elif d.get("type") == "assistant":
                    c = msg.get("content") or []
                    t = "\n".join(x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text").strip()
                    if not t:
                        continue
                    papel = "assistente"
                else:
                    continue
                print(json.dumps({"maq": MAQ, "proj": f.parent.name, "sessao": f.stem[:8], "ts": ts, "quem": papel,
                                  "texto": t[:4000]}, ensure_ascii=False))
    except OSError:
        continue
