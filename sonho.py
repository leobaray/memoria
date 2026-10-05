#!/usr/bin/env python3
"""O sonho da memória. Toda madrugada (cron) ou na mão (`python3 sonho.py`):
 1. LÊ o que é novo: as conversas do Claude Code desde o último sonho, de cada máquina do config (só o texto).
 2. CONSOLIDA: manda pro modelo (claude -p, sem ferramentas) a conversa + o que a memória já tem dos itens citados;
    ele devolve operações (campo novo, item novo, caso, jeito certo, história, ligação, dúvida, remover velho).
 3. DÁ O CRÉDITO: liga cada ficha mandada ao que veio depois na conversa (ajudou, veio à toa, fez errar).
 4. FAXINA: revisa as fichas há mais tempo sem revisão, começando pelas que fizeram errar.
 5. APRENDE DEVAGAR: quando entrou caso novo, olha todos os casos e tira a regra geral.
 6. APLICA com trava: nada que pareça senha entra; cópia da base antes; tudo anotado no diário (diario/AAAA-MM-DD.md).
Contradição que ele não tem certeza vira "dúvida" na ficha: não decide sozinho.
Opções: --sem-faxina, --sem-licoes, --so-ler (mostra quantas falas leria e sai), --desde 2026-10-01T00:00:00Z
"""
import datetime, difflib, json, os, re, shlex, subprocess, sys, tarfile, time
from pathlib import Path

CODIGO = Path(__file__).resolve().parent
sys.path.insert(0, str(CODIGO))
import mem  # noqa: E402

RAIZ = mem.RAIZ
SONHO = mem.ESTADO
ESTADO = SONHO / "estado.json"
DIARIO = RAIZ / "diario"
DONO, EU = mem.CFG["dono"], mem.CFG["assistente"]
NOME = {"pessoa": DONO, "assistente": EU}
PEDACO = 60000      # caracteres de conversa por chamada
FAXINA_N = 8        # itens revisados por noite
HOJE = datetime.date.today().isoformat()
diario = {"aprendi": [], "ignorei": [], "li": [], "mudou": [], "novos": [], "casos": [], "jeito": [], "historia": [], "duvidas": [], "resolvidas": [], "recusei": [], "faxina": [], "credito": [], "licoes": [], "erros": []}


# ---------------------------------------------------------------- ler
def coletar(desde):
    """As falas novas de cada máquina do config. Máquina sem "ssh" é esta; com "ssh", o extrair.py vai pelo stdin.
    Máquina que não responde marca desde["_falhou"]: o ponteiro dela não anda e a parte dela fica pro próximo sonho."""
    falas = []
    for m in mem.CFG["conversas"]:
        maq = m["maquina"]
        d = desde.get(maq, "1970")
        try:
            if not m.get("ssh"):
                r = subprocess.run([sys.executable, str(CODIGO / "extrair.py")], capture_output=True, text=True, timeout=300,
                                   env={**os.environ, "DESDE": d, "MAQUINA": maq})
            else:
                py = m.get("python", "python3")
                cmd = (f"set MAQUINA={maq}&& set DESDE={d}&& {py} -" if m.get("shell") == "cmd"
                       else f"MAQUINA={shlex.quote(maq)} DESDE={shlex.quote(d)} {py} -")
                r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6", m["ssh"], cmd],
                                   stdin=open(CODIGO / "extrair.py"), capture_output=True, text=True, timeout=600)
            if r.returncode != 0:
                raise RuntimeError(r.stderr.strip()[:150])
            falas += [json.loads(l) for l in r.stdout.splitlines() if l.strip()]
        except Exception as e:
            diario["erros"].append(f"{maq}: não consegui ler as conversas (fica pro próximo sonho): {e!r}"[:200])
            desde.setdefault("_falhou", []).append(maq)
    return sorted(falas, key=lambda x: x["ts"])


def pedacos(falas):
    atual, tam = [], 0
    for f in falas:
        linha = f"[{f['ts'][:16].replace('T', ' ')} UTC · {f['maq']}/{f['proj'][-30:]}] {NOME.get(f['quem'], f['quem'])}: {f['texto']}"
        if tam + len(linha) > PEDACO and atual:
            yield "\n".join(atual)
            atual, tam = [], 0
        atual.append(linha)
        tam += len(linha)
    if atual:
        yield "\n".join(atual)


# ---------------------------------------------------------------- pensar
REGRAS = """Você é o SONHO da memória do «eu» («quem_sou»). Sua tarefa: ler o material abaixo e
devolver SÓ um array JSON de operações que deixam a memória certa e enxuta. A memória guarda o que é verdade sobre
COISAS (equipamentos, pessoas, lugares, serviços, projetos, casos resolvidos) — não guarda conversa, opinião passageira
nem o estado do momento (ligado/desligado agora).

Regras:
- NUNCA escreva senha, token, chave, cookie ou PIN. No máximo o CAMINHO no cofre (ex.: "cofre rede/roteador.env").
- NUNCA escreva dado pessoal de documento: CPF, RG, data de nascimento, endereço com rua e número, cartão, conta de banco
  (de ninguém, nem do «dono»). Bairro/cidade pode.
- Cada fato com "visto" (AAAA-MM-DD da conversa) e "como" (ex.: "o «dono» disse", "conferido por comando", "manual oficial").
- Prefira atualizar itens existentes (ids da lista). Só mande op campo pra um campo que JÁ TEM valor se a conversa traz
  informação nova ou CORRIGE a ficha — e aí marque "troca":"corrige". Reconfirmação ou resumo do que já está lá: não mande nada.
- As falas do «eu» pro «dono» são SIMPLIFICADAS de propósito: nunca troque um valor técnico detalhado da ficha por uma
  versão mais vaga tirada delas. A ficha detalhada vale mais que o resumo do chat.
- Se a própria conversa corrige algo dito antes ("na verdade…", "errei", "não é X, é Y"), vale só a correção. Na dúvida, op duvida.
- Jeito certo é AFIRMATIVO ("pra X, faça Y"), com a fonte quando houver. Não escreva "não faça".
- Problema resolvido com causa e solução = op caso. Erro meu vira jeito certo, não caso.
- Se a conversa contradiz a memória e você não tem certeza de qual vale: op duvida. Não chute.
- A dúvida fica na ficha (campo "duvidas") até alguém responder. Se a conversa (ou a própria ficha/história) responde uma
  dúvida que está lá, mande op duvida_resolvida com a resposta e, se mudar um valor, o op campo junto.
«regra_do_dono»- Se nada mudou, devolva [].

Operações (use só estas):
{"op":"campo","id":"pc-recepcao","campo":"sistema","v":"Windows 11 Pro","visto":"2026-10-01","como":"coleta"}   (campo vazio/"?" ou novo; fora do esqueleto vira 'só deste')
{"op":"campo","id":"pc-recepcao","campo":"ip","v":"192.168.0.130","visto":"2026-10-01","como":"DHCP","troca":"corrige"}   (substitui valor existente: só com "troca":"corrige")
{"op":"remover","id":"pc-recepcao","campo":"análise antiga","motivo":"superado: trocado em 30/09"}   (o valor vai pra história)
{"op":"novo","id":"impressora-x","tipo":"aparelho","nome":"…","resumo":"uma linha","chamado":["palavras que puxam"],"ligacoes":[["switch","ligado em"]]}
{"op":"jeito_certo","id":"…","texto":"…"}
{"op":"historia","id":"…","data":"2026-10-01","texto":"o que aconteceu, curto"}
{"op":"caso","id":"caso-…","resumo":"…","chamado":["sintoma em palavras de quem reclama"],"sintoma":"…","causa":"…","jeito_certo":"…","como_conferir":"…","quando":"2026-10-01","itens":["id1","id2"]}
{"op":"ligacao","id":"…","para":"…","tipo":"usado por"}
{"op":"duvida","id":"…","texto":"o que não sei decidir"}   (fica na ficha até ser resolvida; aparece quando a ficha é puxada)
{"op":"duvida_resolvida","id":"…","duvida":"começo do texto da dúvida, como está na ficha","resposta":"o que resolveu e de onde eu sei"}
{"op":"mudanca","id":"mud-20261001-…","quando":"2026-10-01 14:05","o_que":"…","por_que":"…","desfazer":"…","quem_autorizou":"OK do «dono»","verificado":"…","itens":["firewall"]}
   (toda alteração que o «eu» FEZ num sistema — config, serviço, regra, arquivo de sistema — com como desfazer)
{"op":"nao_e_quando","id":"relogio-ponto","frase":"a ponto de"}   (a ficha foi mandada à toa por causa dessa expressão: nunca mais por ela)
{"op":"chamado","id":"casa","frase":"minha casa"}   (o «dono» falou do item com essa palavra e a ficha não veio)
Tipos existentes: {tipos}
"""


def indice(todos):
    return "\n".join(f"{i} | {it['tipo']} | {it['nome']} | {it.get('resumo', '')[:120]}" for i, it in sorted(todos.items()))


def pensar(prompt):
    """Chama o modelo sem ferramentas e sem plugins (--setting-sources local) e devolve o array JSON da resposta. A pasta
    de trabalho tem "sonho" no nome de propósito: o extrair.py pula as conversas dela, pra o sonho não ler a si mesmo."""
    regra_do_dono = (f"- Fato ESTÁVEL sobre o {DONO} (jeito de falar, preferência, objetivo, pessoas, projetos) → ficha "
                     f"'{mem.CFG['ficha_do_dono']}' (op campo ou\n  jeito_certo). Só o que ele disse ou mostrou; nunca o que um robô "
                     "escreveu; nunca documento pessoal.\n") if mem.CFG["ficha_do_dono"] else ""
    prompt = (prompt.replace("«regra_do_dono»", regra_do_dono).replace("«quem_sou»", mem.CFG["quem_sou"])
              .replace("«dono»", DONO).replace("«eu»", EU))
    pasta = SONHO / "sonho"
    pasta.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([mem.CFG["claude"]["comando"], "-p", "--setting-sources", "local", "--model", mem.CFG["claude"]["modelo"]],
                       input=prompt, capture_output=True, text=True, timeout=1800, cwd=str(pasta))
    s = r.stdout.strip()
    a, b = s.find("["), s.rfind("]")
    if r.returncode != 0 or a < 0 or b < 0:
        raise RuntimeError(f"resposta sem JSON (rc={r.returncode}): {s[:200]} {r.stderr[:200]}")
    return json.loads(s[a:b + 1])


# ---------------------------------------------------------------- aplicar (com trava)
SEGREDO = re.compile(r"(senha|password|passwd|pin|token|api[_ ]?key|cookie)\s*[:=é]\s*(?!cofre|no cofre|<)[^\s,;]{3,}|"
                     r"\b(sk-|ghp_|xox[bp]-)[A-Za-z0-9]|\b\d{8,10}:AA[A-Za-z0-9_-]{20,}|"
                     r"(?<![/\w.-])(?=[A-Za-z0-9_]*\d)(?=[A-Za-z0-9_]*[A-Za-z])[A-Za-z0-9_]{32,}(?![/\w])", re.I)


CPF_DATA = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b|\bnasc\w*\b[^,;]{0,20}\d{1,2}/\d{1,2}/\d{2,4}", re.I)


def parece_segredo(op):
    # o id e as ligações são nomes meus (mud-20261001-…), não valor: ficam fora da checagem
    valores = {k: v for k, v in op.items() if k not in ("id", "itens", "ligacoes", "para")}
    t = json.dumps(valores, ensure_ascii=False)
    return bool(SEGREDO.search(t) or CPF_DATA.search(t))


def carregar(iid):
    p = mem.BASE / f"{iid}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def gravar(it):
    it["atualizado"] = HOJE
    (mem.BASE / f"{it['id']}.json").write_text(json.dumps(it, ensure_ascii=False, indent=1), encoding="utf-8")


def historia(iid, data, texto, it=None):
    """Anota na memória profunda. Se `it` vier, é o item que o chamador vai gravar: o caminho da profunda vai nele."""
    proprio_it = it is None
    it = it or carregar(iid)
    if not it:
        return
    pasta = RAIZ / (it.get("profunda") or f"profunda/{iid}")
    pasta.mkdir(parents=True, exist_ok=True)
    f = pasta / "memoria.md"
    if not f.exists():
        f.write_text(f"# {it['nome']} — memória profunda\n", encoding="utf-8")
    with f.open("a", encoding="utf-8") as fh:
        fh.write(f"\n- **{data}** (sonho de {HOJE}): {texto}\n")
    if not it.get("profunda"):
        it["profunda"] = f"profunda/{iid}"
        if proprio_it:
            gravar(it)


def aplicar(op):
    if parece_segredo(op):
        diario["recusei"].append(f"{op.get('op')} em {op.get('id')}: parecia senha/segredo, não gravei")
        return
    o, iid = op.get("op"), op.get("id", "")
    if not re.match(r"^[a-z0-9][a-z0-9-]*$", iid or ""):
        diario["erros"].append(f"id inválido: {iid!r}")
        return
    if o == "novo":
        if carregar(iid):
            return
        tipo = op.get("tipo")
        if not mem.arquivo_do_esqueleto(tipo):
            diario["duvidas"].append(f"{iid}: queria criar tipo novo '{tipo}' — fica pra decidir com o {DONO}")
            return
        gravar({"id": iid, "tipo": tipo, "nome": op.get("nome", iid), "chamado": op.get("chamado", []), "resumo": op.get("resumo", ""),
                "campos": {k: "?" for k in mem.esqueleto(tipo)}, "proprio": {}, "jeito_certo": [],
                "ligacoes": op.get("ligacoes", []), "profunda": None})
        diario["novos"].append(f"{iid} ({tipo}): {op.get('resumo', '')}")
        return
    if o == "mudanca":
        if carregar(iid):
            return
        q = op.get("quando", HOJE)
        V = lambda k: {"v": op[k], "visto": q[:10], "como": "conversa"} if op.get(k) else "?"
        gravar({"id": iid, "tipo": "mudanca", "nome": op.get("o_que", iid)[:90], "chamado": [], "resumo": op.get("o_que", "")[:160],
                "campos": {"quando": V("quando"), "o_que": V("o_que"), "por_que": V("por_que"), "desfazer": V("desfazer"),
                           "quem_autorizou": V("quem_autorizou"), "verificado": V("verificado")},
                "proprio": {}, "jeito_certo": [], "ligacoes": [[i, "mexeu em"] for i in op.get("itens", []) if carregar(i)], "profunda": None})
        diario["mudou"].append(f"mudança registrada: {q} · {op.get('o_que', '')[:100]}")
        return
    if o == "caso":
        if carregar(iid):
            return
        V = lambda k: {"v": op.get(k, "?"), "visto": op.get("quando", HOJE), "como": "conversa"} if op.get(k) else "?"
        gravar({"id": iid, "tipo": "caso", "nome": op.get("resumo", iid), "chamado": op.get("chamado", []), "resumo": op.get("resumo", ""),
                "campos": {"sintoma": V("sintoma"), "quando": V("quando"), "causa": V("causa"), "jeito_certo": V("jeito_certo"),
                           "como_conferir": V("como_conferir"), "desfazer": "?"},
                "proprio": {}, "jeito_certo": [op["jeito_certo"]] if op.get("jeito_certo") else [],
                "ligacoes": [[i, "aconteceu em"] for i in op.get("itens", []) if carregar(i)], "profunda": None})
        diario["casos"].append(f"{iid}: {op.get('resumo')} → {op.get('jeito_certo')}")
        return
    if o == "licao":
        # o aprendiz lento (05/10/2026): regra geral só nasce apoiada em 2+ casos que existem; caso novo que cabe numa
        # lição que já existe só entra no apoio dela (o texto não muda sozinho)
        casos = [c for c in dict.fromkeys(op.get("casos") or []) if (carregar(c) or {}).get("tipo") == "caso"]
        it = carregar(iid)
        if it:
            if it.get("tipo") != "licao":
                diario["erros"].append(f"licao: {iid} já existe e não é lição")
                return
            novos = [c for c in casos if [c, "tirada de"] not in it.get("ligacoes", [])]
            if novos:
                it["ligacoes"] += [[c, "tirada de"] for c in novos]
                gravar(it)
                diario["licoes"].append(f"{iid}: ganhou apoio de {', '.join(novos)} (agora {len(it['ligacoes'])} casos)")
            return
        regra = (op.get("regra") or "").strip()
        if len(casos) < 2 or not regra or not iid.startswith("licao-"):
            diario["licoes"].append(f"recusada ({iid}): precisa de 2 casos que existem e do id licao-…; veio {len(casos)} — {regra[:100]}")
            return
        V = lambda k: {"v": op[k].strip(), "visto": HOJE, "como": f"tirada de {len(casos)} casos pelo sonho"} if (op.get(k) or "").strip() else "?"
        gravar({"id": iid, "tipo": "licao", "nome": "Regra geral: " + iid[6:].replace("-", " "), "chamado": [c.strip().lower() for c in op.get("chamado") or [] if len(c.split()) >= 3],   # sintoma solto ("sumiu") puxaria à toa; a lição já chega junto dos casos dela
                "resumo": regra[:300], "campos": {"regra": V("regra"), "quando_vale": V("quando_vale"), "quando_nao_vale": V("quando_nao_vale")},
                "proprio": {}, "jeito_certo": [], "ligacoes": [[c, "tirada de"] for c in casos], "profunda": None})
        diario["licoes"].append(f"{iid} (de {', '.join(casos)}): {regra}")
        return
    it = carregar(iid)
    if not it and o == "duvida":
        diario["duvidas"].append(f"{iid} (sem ficha): {op.get('texto', '')}")
        return
    if not it:
        # o texto vai junto pro diário: uma história anotada num id digitado errado já se perdeu assim
        perto = difflib.get_close_matches(iid, [p.stem for p in mem.BASE.glob("*.json")], n=3, cutoff=0.5)
        conteudo = op.get("texto") or op.get("v") or op.get("duvida") or ""
        diario["erros"].append(f"{o} em item que não existe: {iid}" + (f" (seria: {', '.join(perto)}?)" if perto else "")
                               + (f" — não gravei: {str(conteudo)[:300]}" if conteudo else ""))
        return
    if o == "campo":
        c = op.get("campo")
        novo = {"v": op.get("v"), "visto": op.get("visto", HOJE), "como": op.get("como", "conversa")}
        lugar = "campos" if c in mem.esqueleto(it["tipo"]) else "proprio"
        velho = it.setdefault(lugar, {}).get(c)
        if isinstance(velho, dict) and velho.get("v") == novo["v"]:
            velho["visto"] = max(velho.get("visto", ""), novo["visto"])  # reconfirmado
            gravar(it)
            return
        if isinstance(velho, dict) and op.get("troca") != "corrige":
            diario["ignorei"].append(f"{iid} · {c}: já tenho '{str(velho.get('v'))[:70]}'; a conversa não marcou como correção ('{str(novo['v'])[:70]}')")
            return
        if isinstance(velho, dict):
            historia(iid, velho.get("visto", "?"), f"{c} era: {velho.get('v')} (trocado por: {novo['v']})", it)
        it[lugar][c] = novo
        gravar(it)
        diario["mudou"].append(f"{iid} · {c}: {mem.txt(velho) if velho else '(novo)'} → {novo['v']}")
    elif o == "remover":
        c = op.get("campo")
        for lugar in ("proprio", "campos"):
            if c in it.get(lugar, {}):
                velho = it[lugar].pop(c) if lugar == "proprio" else it[lugar][c]
                if lugar == "campos":
                    it[lugar][c] = "?"
                historia(iid, (velho or {}).get("visto", "?") if isinstance(velho, dict) else "?",
                         f"{c}: {mem.txt(velho)} — tirado da base: {op.get('motivo', '')}", it)
                gravar(it)
                diario["mudou"].append(f"{iid} · {c}: tirado da base ({op.get('motivo', '')})")
                break
    elif o == "jeito_certo":
        t = op.get("texto", "").strip()
        if t and t not in it.setdefault("jeito_certo", []):
            it["jeito_certo"].append(t)
            gravar(it)
            diario["jeito"].append(f"{iid}: {t}")
    elif o == "historia":
        historia(iid, op.get("data", HOJE), op.get("texto", ""))
        diario["historia"].append(f"{iid}: {op.get('texto', '')[:140]}")
    elif o == "ligacao":
        par = [op.get("para"), op.get("tipo", "ligado a")]
        if carregar(par[0]) and par not in it.setdefault("ligacoes", []):
            it["ligacoes"].append(par)
            gravar(it)
            diario["mudou"].append(f"{iid} → {par[0]} ({par[1]})")
    elif o in ("nao_e_quando", "chamado"):
        frase = (op.get("frase") or "").strip().lower()
        lista = it.setdefault(o, [])
        if frase and len(frase) >= 3 and frase not in lista:
            lista.append(frase)
            gravar(it)
            diario["aprendi"].append(f"{iid}: {'não mandar mais quando aparecer' if o == 'nao_e_quando' else 'mandar também quando aparecer'} '{frase}'")
    elif o == "duvida":
        # a dúvida mora na ficha até ser resolvida (05/10/2026: no diário elas ficavam esquecidas)
        t = (op.get("texto") or "").strip()
        lista = it.setdefault("duvidas", [])
        if t and all(mem.norm(t) != mem.norm(d["texto"]) for d in lista):
            lista.append({"texto": t, "desde": HOJE})
            gravar(it)
            diario["duvidas"].append(f"{iid}: {t}")
    elif o == "credito":
        # a recompensa (05/10/2026): o que aconteceu DEPOIS que a ficha foi mandada. Fica em creditos.jsonl; "errou" vira
        # dúvida na ficha e a põe na frente da fila da faxina (o cérebro aprende mais onde errou a previsão).
        nota = op.get("nota")
        if nota not in mem.NOTAS_CREDITO:
            diario["erros"].append(f"credito em {iid}: nota desconhecida {nota!r}")
            return
        porque = (op.get("porque") or "").strip()[:300]
        with mem.CREDITOS.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"quando": datetime.datetime.now().isoformat(timespec="minutes"), "id": iid, "nota": nota,
                                 "porque": porque, "msg": "" if "pessoal" in porque.lower() else (op.get("msg") or "")[:80]}, ensure_ascii=False) + "\n")
        diario["credito"].append(f"{iid}: {mem.NOTAS_CREDITO[nota]}" + (f" — {porque}" if porque else ""))
        if nota == "errou" and (op.get("fato") or "").strip():
            aplicar({"op": "duvida", "id": iid, "texto": f"Esta ficha me levou a erro em {HOJE}: {op['fato'].strip()[:300]} Conferir na fonte e corrigir."})
    elif o == "duvida_resolvida":
        trecho = mem.norm(op.get("duvida") or "").strip()
        lista = it.get("duvidas", [])
        achou = [d for d in lista if trecho and (mem.norm(d["texto"]).startswith(trecho) or trecho in mem.norm(d["texto"]))]
        if len(achou) != 1:
            diario["erros"].append(f"duvida_resolvida em {iid}: {'nenhuma' if not achou else 'mais de uma'} dúvida casa com "
                                   f"'{op.get('duvida', '')[:80]}' — resposta não gravada: {op.get('resposta', '')[:200]}")
            return
        d = achou[0]
        lista.remove(d)
        if not lista:
            it.pop("duvidas", None)
        historia(iid, HOJE, f"dúvida (desde {d.get('desde', '?')}): {d['texto']} → resolvida: {op.get('resposta', '')}", it)
        gravar(it)
        diario["resolvidas"].append(f"{iid}: {d['texto'][:120]} → {op.get('resposta', '')}")


# ---------------------------------------------------------------- recompensa: o que aconteceu depois de cada envio
def ligar_envios(envios, falas, maximo=40):
    """Pra cada envio (as fichas que a memória mandou junto de uma mensagem), acha essa mensagem na conversa e pega o que
    veio depois: a resposta do assistente e a fala seguinte da pessoa. É a "marca" esperando a recompensa: sem saber o que
    aconteceu depois, não dá pra dizer se a ficha ajudou. Envio de robô ou sem conversa correspondente fica de fora."""
    junta = lambda t: " ".join((t or "").split())
    sessoes = {}
    for f in falas:
        sessoes.setdefault((f["maq"], f["proj"], f["sessao"]), []).append(f)
    casos = []
    for e in envios:
        chave = junta(e.get("msg"))[:120]
        if len(chave) < 15 or mem.ROBO.search(e.get("msg", "")) or not e.get("mandou"):
            continue
        try:
            quando = datetime.datetime.strptime(e["ts"], "%Y-%m-%d %H:%M").astimezone(datetime.timezone.utc)
        except Exception:
            continue
        melhor = None
        for lst in sessoes.values():
            for n, f in enumerate(lst):
                if f["quem"] != "pessoa" or junta(f["texto"])[:len(chave)] != chave:
                    continue
                dist = abs((datetime.datetime.fromisoformat(f["ts"].replace("Z", "+00:00")) - quando).total_seconds())
                if dist <= 600 and (melhor is None or dist < melhor[0]):
                    melhor = (dist, lst, n)
        if not melhor:
            continue
        _, lst, n = melhor
        depois, do_leo = [], 0
        for f in lst[n + 1:n + 8]:
            do_leo += f["quem"] == "pessoa"
            depois.append(f"{NOME.get(f['quem'], f['quem'])}: {junta(f['texto'])[:1500 if f['quem'] == 'assistente' else 700]}")
            if do_leo == 2:
                break
        if depois:
            casos.append({"msg": junta(e["msg"])[:300], "fichas": list(e["mandou"]), "depois": depois})
    return casos[-maximo:]


def creditar(envios, falas, regras):
    """Lê o que aconteceu depois de cada ficha mandada e dá o crédito (op credito). Devolve quantos envios julgou."""
    casos = ligar_envios(envios, falas)
    if not casos:
        return 0
    todos = mem.itens()
    blocos = []
    for n, c in enumerate(casos, 1):
        fichas = "\n".join(f"  - {i}: {todos[i].get('resumo', '')[:200]}" for i in c["fichas"] if i in todos)
        blocos.append(f"## Envio {n}\nMensagem do «dono»: {c['msg']}\nFichas que a memória mandou junto:\n{fichas}\nO que veio depois:\n"
                      + "\n".join(f"  {d}" for d in c["depois"]))
    prompt = (f"{regras}\n\n# RECOMPENSA: abaixo, cada mensagem do «dono», as fichas que a memória mandou junto dela e o que veio DEPOIS "
              "(a resposta do «eu» e a fala seguinte do «dono»). Pra cada ficha de cada envio, diga o que aconteceu, com UMA op:\n"
              '{"op":"credito","id":"<id da ficha>","nota":"ajudou","porque":"uma frase","msg":"começo da mensagem"}\n'
              "- ajudou: a resposta usou um fato ou jeito certo dessa ficha e o «dono» seguiu em frente (ou aprovou).\n"
              "- a_toa: a ficha não tinha a ver com o que foi feito; a resposta não usou nada dela.\n"
              '- errou: a resposta usou algo dessa ficha e o «dono» (ou a realidade, na própria conversa) mostrou que estava errado ou '
              'velho. Aí inclua também "fato":"o que a ficha dizia e o que era o certo".\n'
              "No 'porque', diga só o que a ficha fez ou deixou de fazer; nunca conte assunto pessoal da conversa (sentimentos, família, "
              "dinheiro): escreva 'conversa pessoal' e pronto.\n"
              "Se não dá pra saber (resposta que não mostra o que usou, conversa cortada), não mande nada pra essa ficha. Não chute: "
              "crédito errado ensina errado.\n\n" + "\n\n".join(blocos) + "\n\nDevolva só o array JSON de operações (só credito).")
    for op in pensar(prompt):
        if op.get("op") == "credito":
            aplicar(op)
    return len(casos)


# ---------------------------------------------------------------- o aprendiz lento: regra geral de casos parecidos
def aprender_devagar(regras, maximo=5):
    """O aprendiz rápido grava cada caso separado; este olha TODOS os casos juntos e tira a regra que vale pra mais de um
    (no cérebro: o córtex, que aprende devagar misturando o novo com o velho). No máximo `maximo` por noite."""
    todos = mem.itens()
    V = lambda it, k: (it["campos"].get(k) or {}).get("v", "?") if isinstance(it["campos"].get(k), dict) else "?"
    casos = "\n".join(f"{i} | {it['resumo'][:140]} | causa: {str(V(it, 'causa'))[:260]} | jeito certo: {str(V(it, 'jeito_certo'))[:260]}"
                      for i, it in sorted(todos.items()) if it["tipo"] == "caso")
    licoes = "\n".join(f"{i} | {V(it, 'regra')} | apoiada em: {', '.join(a for a, _ in it.get('ligacoes', []))}"
                       for i, it in sorted(todos.items()) if it["tipo"] == "licao") or "(nenhuma ainda)"
    prompt = (f"{regras}\n\n# O APRENDIZ LENTO: abaixo estão todos os casos resolvidos e as regras gerais (lições) que já existem. Procure "
              "um PADRÃO que se repete em 2 ou mais casos: o mesmo TIPO de causa ou o mesmo tipo de engano (não basta ser o mesmo "
              "aparelho). Pra cada padrão novo, uma op:\n"
              '{"op":"licao","id":"licao-nome-curto","regra":"a regra geral, afirmativa, em uma ou duas frases (antes de X, conferir Y)",'
              '"quando_vale":"em que situação lembrar","quando_nao_vale":"o limite dela","chamado":["sintoma geral, nas palavras de quem reclama"],'
              '"casos":["caso-a","caso-b"]}\n'
              "- A regra tem que servir pra um caso NOVO que ainda não aconteceu; se só repete o jeito certo de um caso, não é lição.\n"
              "- Só o que os casos sustentam: não invente causa nem generalize de um caso só.\n"
              "- Se um caso cabe numa lição que já existe e não está no apoio dela, mande a op com o MESMO id e só esse caso em casos.\n"
              f"- No máximo {maximo}; as mais fortes (mais casos) primeiro. Se não há padrão novo, devolva [].\n\n"
              f"# Lições que já existem\n{licoes}\n\n# Casos resolvidos\n{casos}\n\nDevolva só o array JSON de operações (só licao).")
    n = 0
    for op in pensar(prompt):
        if op.get("op") == "licao" and n < maximo:
            aplicar(op)
            n += 1
    return n


# ---------------------------------------------------------------- escrever o diário
def escrever_diario(n_falas, fontes):
    DIARIO.mkdir(exist_ok=True)
    titulos = [("mudou", "O que mudou"), ("novos", "Itens novos"), ("casos", "Casos novos (já sei resolver)"),
               ("jeito", "Jeito certo aprendido"), ("historia", "Pra história"), ("faxina", "Faxina (revisei)"),
               ("licoes", "Regras gerais tiradas de casos parecidos (o aprendiz lento)"),
               ("credito", "Recompensa: o que ajudou, o que veio à toa, o que me fez errar"),
               ("duvidas", "Dúvidas — não decidi sozinho (ficam na ficha até alguém responder)"), ("resolvidas", "Dúvidas resolvidas"), ("ignorei", "Não troquei (a ficha já tinha mais detalhe)"), ("aprendi", "Aprendi quando mandar (e quando não)"), ("recusei", "Recusei (parecia senha)"), ("erros", "Problemas do sonho")]
    uso = json.loads(mem.USO.read_text()) if mem.USO.exists() else {}
    top = sorted(uso.items(), key=lambda kv: -kv[1].get("vezes", 0))[:8]
    linhas = [f"# Sonho de {datetime.datetime.now():%d/%m/%Y %H:%M}", "",
              f"Li {n_falas} falas novas ({', '.join(f'{k}: {v}' for k, v in fontes.items()) or 'nada'}).", ""]
    for k, t in titulos:
        if diario[k]:
            linhas += [f"## {t}", *[f"- {x}" for x in diario[k]], ""]
    if top:
        linhas += ["## Mais lembrados (puxados pelas mensagens)", *[f"- {i}: {u['vezes']}×" for i, u in top], ""]
    f = DIARIO / f"{HOJE}.md"
    with f.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(linhas) + "\n")
    return f


# ---------------------------------------------------------------- principal
def main():
    SONHO.mkdir(parents=True, exist_ok=True)
    est = json.loads(ESTADO.read_text()) if ESTADO.exists() else {}
    # máquina sem ponteiro (primeiro sonho, ou máquina nova no config): começa de hoje
    maquinas = [m["maquina"] for m in mem.CFG["conversas"]]
    hoje0 = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
    desde = {**dict.fromkeys(maquinas, hoje0), **est.get("desde", {})}
    if "--desde" in sys.argv:
        desde = dict.fromkeys(maquinas, sys.argv[sys.argv.index("--desde") + 1])
    falas = coletar(desde)
    fontes = {}
    for f in falas:
        fontes[f["maq"]] = fontes.get(f["maq"], 0) + 1
    print(f"falas novas: {len(falas)} {fontes}")
    if "--so-ler" in sys.argv:
        return
    with tarfile.open(SONHO / f"backup-{datetime.datetime.now():%Y%m%d-%H%M}.tgz", "w:gz") as tar:
        tar.add(mem.BASE, arcname="base")
    tipos = ", ".join(mem.tipos())
    regras = REGRAS.replace("{tipos}", tipos)
    pedaco_falhou = False   # 02/10/2026: o login do claude caiu, os pedaços falharam e o ponteiro andou assim mesmo (falas perdidas)
    for pedaco in pedacos(falas):
        todos = mem.itens()
        citados = sorted(((mem.casa(pedaco, it), iid) for iid, it in todos.items()), reverse=True)
        citados = [iid for n, iid in citados if n > 0][:15]
        detalhe = "\n".join(json.dumps(todos[i], ensure_ascii=False) for i in citados)
        prompt = (f"{regras}\n\n# Itens que a memória já tem (id | tipo | nome | resumo)\n{indice(todos)}\n\n"
                  f"# Como estão hoje os itens citados nesta conversa\n{detalhe}\n\n# Conversa nova («dono» e «eu»)\n{pedaco}\n\n"
                  "Devolva só o array JSON de operações.")
        try:
            for op in pensar(prompt):
                aplicar(op)
        except Exception as e:
            diario["erros"].append(f"pedaço da conversa não processado: {e!r}"[:300])
            pedaco_falhou = True
    # o que a memória mandou desde o último sonho: aprender quando NÃO mandar (e o que faltou mandar)
    env_f = RAIZ / "envios.jsonl"
    if env_f.exists() and env_f.stat().st_size:
        try:   # a recompensa vem antes: usa os mesmos envios, ligados ao que aconteceu depois na conversa
            lidos = [json.loads(l) for l in env_f.read_text(encoding="utf-8").splitlines() if l.strip()]
            n_jul = creditar(lidos, falas, regras)
            if n_jul:
                diario["li"].append(f"recompensa: julguei {n_jul} envio(s) pelo que veio depois")
        except Exception as e:
            diario["erros"].append(f"recompensa não rodou: {e!r}"[:300])
        envios = env_f.read_text(encoding="utf-8")[-40000:]
        todos = mem.itens()
        prompt = (f"{regras}\n\n# APRENDER QUANDO MANDAR: abaixo, cada mensagem do «dono» e as fichas que a memória mandou junto (e a "
                  f"palavra que disparou). Se a ficha não tinha nada a ver (palavra usada em outro sentido, ex.: 'a ponto de' puxou o relógio "
                  f"de ponto; ou 'sentido 0.5x' que trouxe coisa sem relação), devolva op nao_e_quando com a EXPRESSÃO que deu o falso alarme (curta, como aparece na mensagem). Se a mensagem "
                  f"falava claramente de um item e ele não veio, op chamado com a palavra. Na dúvida, nada.\n\n# Itens (id | tipo | nome | resumo)\n"
                  f"{indice(todos)}\n\n# Envios\n{envios}\n\nDevolva só o array JSON de operações (só nao_e_quando e chamado).")
        try:
            for op in pensar(prompt):
                if op.get("op") in ("nao_e_quando", "chamado"):
                    aplicar(op)
            env_f.rename(SONHO / f"envios-{datetime.datetime.now():%Y%m%d-%H%M}.jsonl")
        except Exception as e:
            diario["erros"].append(f"revisão dos envios não rodou: {e!r}"[:300])
    if "--sem-faxina" not in sys.argv:
        todos = mem.itens()
        revisados = est.get("revisado", {})
        # mudança é registro do que eu fiz, quase nada pra faxinar: fica fora e as outras fichas voltam em ~17 dias, não ~29 (05/10/2026)
        # quem me fez errar depois da última revisão vai pra frente da fila
        errou = {i: q for i, q in mem.ultimo_erro().items() if q[:10] >= revisados.get(i, "")}
        fila = sorted((i for i in todos if todos[i]["tipo"] != "mudanca"), key=lambda i: (i not in errou, revisados.get(i, "")))[:FAXINA_N]
        detalhe = "\n\n".join(json.dumps(todos[i], ensure_ascii=False) + "\n(história: " +
                              ((RAIZ / todos[i]["profunda"] / "memoria.md").read_text(encoding="utf-8")[-3000:]
                               if todos[i].get("profunda") and (RAIZ / todos[i]["profunda"] / "memoria.md").exists() else "nenhuma") + ")"
                              for i in fila)
        prompt = (f"{regras}\n\n# FAXINA: revise estes itens como quem relembra antes de dormir. Procure: fato superado ou que contradiz outro "
                  f"do mesmo item (remover/campo + historia), 'não faça' que devia ser jeito certo afirmativo (jeito_certo), campo '?' que a "
                  f"própria ficha ou história já responde (campo), dúvida da ficha que a própria ficha ou história já responde (duvida_resolvida), resumo desatualizado (campo 'resumo' NÃO existe: use historia pra anotar). "
                  f"Não invente nada que não esteja no texto.\n\n# Itens que a memória tem\n{indice(todos)}\n\n# Itens a revisar\n{detalhe}\n\n"
                  "Devolva só o array JSON de operações.")
        try:
            antes = len(diario["mudou"]) + len(diario["jeito"])
            for op in pensar(prompt):
                aplicar(op)
            diario["faxina"].append(f"{', '.join(fila)} ({len(diario['mudou']) + len(diario['jeito']) - antes} mudanças)")
            for i in fila:
                revisados[i] = HOJE
            est["revisado"] = revisados
        except Exception as e:
            diario["erros"].append(f"faxina não rodou: {e!r}"[:300])
    if "--sem-licoes" not in sys.argv:
        ids_casos = sorted(i for i, it in mem.itens().items() if it["tipo"] == "caso")
        if len(ids_casos) >= 2 and ids_casos != est.get("licoes_casos"):   # só quando entrou (ou saiu) algum caso
            try:
                aprender_devagar(regras)
                est["licoes_casos"] = ids_casos
            except Exception as e:
                diario["erros"].append(f"aprendiz lento não rodou: {e!r}"[:300])
    subprocess.run([sys.executable, str(CODIGO / "mem.py"), "validar", "--corrigir"], capture_output=True)
    for cmd in mem.CFG["depois_do_sonho"]:   # manutenções de cada instalação; o que elas avisam entra no diário
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=900, shell=isinstance(cmd, str))
            alertas = [l.strip() for l in r.stdout.splitlines() if l.strip().upper().startswith("ALERTA")]
            diario["erros"] += alertas
            if r.returncode != 0 and not alertas:
                diario["erros"].append(f"depois do sonho, não rodou ({cmd}): {(r.stderr or r.stdout).strip()[-200:]}")
        except Exception as e:
            diario["erros"].append(f"depois do sonho, não rodou ({cmd}): {e!r}"[:300])
    try:
        import sentido
        n = sentido.atualizar(mem.itens())
        if n:
            diario["mudou"].append(f"sentido recalculado de {n} ficha(s)")
    except Exception as e:
        diario["erros"].append(f"sentido não atualizou (servidor de embeddings fora?): {e!r}"[:200])
    if pedaco_falhou:
        diario["erros"].append("não avancei o ponteiro de leitura: o próximo sonho relê estas falas")
    if falas and not pedaco_falhou:
        for maq in maquinas:
            ts = [f["ts"] for f in falas if f["maq"] == maq]
            if ts and maq not in desde.get("_falhou", []):
                desde[maq] = max(ts)
    desde.pop("_falhou", None)
    est["desde"] = desde
    est["ultimo_sonho"] = datetime.datetime.now().isoformat(timespec="seconds")
    ESTADO.write_text(json.dumps(est, ensure_ascii=False, indent=1))
    print("diário:", escrever_diario(len(falas), fontes))


if __name__ == "__main__":
    main()
