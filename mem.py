#!/usr/bin/env python3
"""Memória por fichas pra um assistente de IA: uma ficha JSON por coisa (com quando e como cada fato foi sabido, e o que
ainda não se sabe), esqueleto por tipo, ligações entre fichas e uma memória profunda por pasta.

  mem.py puxar            stdin = texto da mensagem -> pacote do que foi citado + resumo do que está ligado (pro hook)
  mem.py ver <id>         item inteiro + o que está ligado + o que tem na memória profunda
  mem.py lacunas [id]     campos "?" (não sei ainda), essenciais primeiro
  mem.py validar          confere todo item contra o esqueleto do tipo; --corrigir põe "?" no campo que falta
  mem.py mudancas [id]    linha do tempo do que eu mexi (com como desfazer); com id, só o que tocou o item
  mem.py iniciar          cria a pasta dos dados (config.json de modelo, pastas, .gitignore) se ainda não existe
  mem.py onde             mostra a pasta dos dados em uso
  mem.py duvidas [id]     dúvidas em aberto (moram na ficha, campo "duvidas"; aparecem quando a ficha é puxada)
  mem.py anotar           stdin = uma operação JSON por linha (as mesmas do sonho: mudanca, campo, caso, jeito_certo,
                          historia, ligacao, novo, duvida, duvida_resolvida, credito…) — grava com as travas do sonho (sem senha;
                          valor existente só com "troca":"corrige") e anota no diário do dia. É o jeito de registrar uma
                          mudança na hora.

Valor de campo: {"v": ..., "visto": "AAAA-MM-DD", "como": "de onde eu sei"}  |  "?" = não sei ainda  |  "-" = não se aplica
Senha NUNCA entra aqui: só o caminho no cofre.
MEM_TESTE=1 no ambiente: o puxar responde igual, mas não conta uso nem grava em envios.jsonl (pra testar sem ensinar
errado o sonho, que aprende com esses dois arquivos).

Onde ficam os dados (fichas, diário, estado): NUNCA dentro do que o git do código acompanha. Nesta ordem:
  1. a variável de ambiente MEMORIA_DADOS;  2. a pasta dados/ ao lado deste arquivo (ignorada pelo git), se existir;
  3. ~/.memoria.   O que é de cada instalação (nome do dono, máquinas, modelos) fica em <dados>/config.json.
"""
import json, os, re, sys, time, unicodedata
from pathlib import Path

CODIGO = Path(__file__).resolve().parent


def _pasta_dos_dados():
    if os.environ.get("MEMORIA_DADOS"):
        return Path(os.environ["MEMORIA_DADOS"]).expanduser().resolve()
    if (CODIGO / "dados").is_dir():
        return CODIGO / "dados"
    return Path.home() / ".memoria"


RAIZ = DADOS = _pasta_dos_dados()   # RAIZ é sempre a pasta dos DADOS; o código fica em CODIGO
PADRAO = {
    "dono": "dono",                          # o nome da pessoa que conversa com o assistente (entra nos prompts: "o <dono> disse")
    "assistente": "assistente",              # o nome do assistente
    "quem_sou": "um assistente de IA",       # uma frase sobre o assistente e o trabalho dele (entra no prompt do sonho)
    "ficha_do_dono": "",                     # id da ficha da pessoa, se houver (fatos estáveis sobre ela vão pra lá)
    "rotulo": "",                            # como o pacote se apresenta ("servidor:/caminho"); vazio = a pasta dos dados
    "robo": [r"^\s*/loop\b", r"<<autonomous-loop"],   # mensagem que casa com isso não conta como uso
    "valor_que_nao_e_segredo": ["cofre", "padr", "ler "],   # depois de "senha:", esses começos são um caminho, não a senha
    "claude": {"comando": "claude", "modelo": "opus"},   # quem pensa no sonho (claude -p)
    "conversas": [{"maquina": "local"}],     # de onde o sonho lê as conversas; outra máquina: {"maquina","ssh","python"}
    "sentido": None,                         # busca pelo sentido: {"url": ".../api/embed", "modelo": "bge-m3", "fica_carregado": "1h"}
    "regua": {"honcho": None},               # comparar com um Honcho: {"url": ".../v3", "workspace": "...", "peer": "..."}
    "depois_do_sonho": [],                   # comandos extras; cada linha que imprimirem começando com ALERTA vai pro diário
}


def _config():
    cfg = json.loads(json.dumps(PADRAO))
    try:
        meu = json.loads((DADOS / "config.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        meu = {}
    for k, v in meu.items():
        cfg[k] = {**cfg[k], **v} if isinstance(cfg.get(k), dict) and isinstance(v, dict) else v
    return cfg


CFG = _config()
BASE, USO = RAIZ / "base", RAIZ / "uso.json"
ESQ = [RAIZ / "esqueletos", CODIGO / "esqueletos"]   # o da instalação ganha do que vem com o código
ESTADO = RAIZ / "estado"   # logs, ponteiros e cópias de antes de cada sonho; não é memória
CREDITOS = RAIZ / "creditos.jsonl"   # a recompensa: o que aconteceu depois de cada ficha mandada (sonho.py, op credito)
NOTAS_CREDITO = {"ajudou": "ajudou", "a_toa": "veio à toa", "errou": "me fez errar"}
LIMITE_PACOTE = 6000
SENTIDO_MIN = 0.55   # calibrado 02/10: certos 0,56–0,67; conversa à toa até 0,49
SENTIDO_MAX_ITENS = 2
# Regra e projeto têm texto mais genérico e apareciam à toa entre 0,55 e 0,59 (medido em 05/10 nas 80 mensagens reais
# dos envios); pra eles a nota mínima pelo sentido é maior. Pela palavra de chamada continuam vindo normalmente.
SENTIDO_MIN_TIPO = {"regra": 0.60, "projeto": 0.60}
# Mensagem de robô (o /loop repete o mesmo texto toda hora): responde igual, mas não conta como lembrança nem entra
# nos envios que o sonho revisa. Em 05/10/2026 o /loop do modo autônomo era quase todo o "mais lembrados".
ROBO = re.compile("|".join(CFG["robo"]) or r"(?!)", re.I)


def norm(t):
    t = unicodedata.normalize("NFKD", (t or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def itens():
    return {json.loads(p.read_text(encoding="utf-8"))["id"]: json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(BASE.glob("*.json"))}


def arquivo_do_esqueleto(tipo):
    return next((p for p in (d / f"{tipo}.json" for d in ESQ) if p.exists()), None)


def tipos():
    return sorted({p.stem for d in ESQ for p in d.glob("*.json") if not p.stem.startswith("_")})


def esqueleto(tipo):
    campos, t = {}, tipo
    while t:
        p = arquivo_do_esqueleto(t)
        if not p:
            break
        e = json.loads(p.read_text(encoding="utf-8"))
        campos = {**e["campos"], **campos}
        t = e.get("herda")
    return campos


def ligacoes(todos, iid):
    """Saindo do item e chegando nele (a ligação é escrita de um lado só)."""
    out = [(alvo, tipo, "→") for alvo, tipo in todos[iid].get("ligacoes", [])]
    for oid, o in todos.items():
        for alvo, tipo in o.get("ligacoes", []):
            if alvo == iid:
                out.append((oid, tipo, "←"))
    return out


def txt(v):
    if v == "?":
        return "? (não sei ainda)"
    if v == "-":
        return "— (não se aplica)"
    if isinstance(v, dict):
        extra = ", ".join(x for x in (v.get("visto") and f"visto {v['visto']}", v.get("como")) if x)
        return f"{v.get('v')}" + (f"  [{extra}]" if extra else "")
    return str(v)


PALAVRA_FRACA = {"qual", "quais", "como", "onde", "quando", "quem", "para", "pela", "pelo", "esse", "essa", "este", "esta", "isso",
                 "aqui", "tambem", "ainda", "mais", "muito", "pode", "posso", "tem", "tinha", "esta", "estao", "fica", "fazer", "faco",
                 "sobre", "entre", "depois", "antes", "agora", "hoje", "voce", "dele", "dela", "numa", "num", "uma", "com", "que", "nao"}


def fortes_de(texto):
    """As palavras que dizem o assunto da mensagem (4+ letras, sem as de ligação)."""
    return {w for w in re.findall(r"[a-z0-9]{4,}", norm(texto))} - PALAVRA_FRACA


def por_assunto(linhas, fortes):
    """Põe na frente as linhas que falam do assunto da mensagem; o resto fica na ordem de sempre. Quando a ficha é
    grande e o pacote corta o fim, o que sobra é o que responde (achado pela régua em 05/10/2026)."""
    if not fortes:
        return linhas
    return sorted(linhas, key=lambda l: -len(fortes & set(re.findall(r"[a-z0-9]{4,}", norm(l)))))


def bloco(todos, iid, completo=True, desfazer=False, fortes=None):
    """desfazer=True (mem.py ver): cada mudança traz o comando de desfazer. No puxar fica uma linha por mudança,
    porque os comandos de desfazer, sozinhos, estouravam o pacote (05/10/2026)."""
    it = todos[iid]
    esq = esqueleto(it["tipo"])
    linhas = [f"## {it['nome']} (`{iid}`, {it['tipo']})", it.get("resumo", "")]
    if completo:
        fatos = [f"- {k}: {txt(v)}" for k, v in it.get("campos", {}).items() if v != "?"]
        fatos += [f"- {k} (só deste): {txt(v)}" for k, v in it.get("proprio", {}).items()]
        linhas += por_assunto(fatos, fortes)
        if it.get("jeito_certo"):
            linhas.append("Jeito certo:")
            linhas += por_assunto([f"  - {j}" for j in it["jeito_certo"]], fortes)
        falta = [k for k, v in it.get("campos", {}).items() if v == "?"]
        if falta:
            ess = [k for k in falta if esq.get(k, {}).get("essencial")]
            linhas.append(f"Não sei ainda: {', '.join(ess + [k for k in falta if k not in ess])}")
        if it.get("duvidas"):
            linhas.append("Dúvida em aberto (se a conversa responder, anotar com op duvida_resolvida):")
            linhas += [f"  - {d['texto']} (desde {d.get('desde', '?')})" for d in it["duvidas"]]
    lig = ligacoes(todos, iid)
    casos = [(o, t) for o, t, _ in lig if o in todos and todos[o]["tipo"] == "caso"]
    mudancas = sorted({o for o, t, _ in lig if o in todos and todos[o]["tipo"] == "mudanca"},
                      key=lambda o: (_quando(todos[o]), o), reverse=True)
    licoes = sorted({o for o, t, _ in lig if o in todos and todos[o]["tipo"] == "licao"})
    outros = [(o, t) for o, t, _ in lig if not (o in todos and todos[o]["tipo"] in ("caso", "mudanca", "licao"))]
    if licoes:
        linhas.append("Regra geral que saiu de casos como este:")
        linhas += [f"  - {todos[o]['resumo']} (de {len(todos[o].get('ligacoes', []))} casos; `{o}`)" for o in licoes]
    if casos:
        ja = [f"  - {todos[o]['resumo']} → {(todos[o].get('jeito_certo') or [''])[0]} (`{o}`)" for o, _ in casos]
        # caso que fala do assunto da mensagem sobe pra logo depois do resumo: numa ficha grande, o corte do pacote
        # levava embora justamente o problema já resolvido (achado pela régua em 05/10/2026)
        do_assunto = [l for l in ja if fortes and fortes & set(re.findall(r"[a-z0-9]{4,}", norm(l)))]
        if do_assunto:
            linhas[2:2] = ["Já aconteceu parecido (e já sei resolver):"] + do_assunto
        resto = [l for l in ja if l not in do_assunto]
        if resto:
            linhas.append("Já aconteceu (e já sei resolver):")
            linhas += resto
    if mudancas and it["tipo"] != "mudanca":
        linhas.append(f"O que eu já mexi aqui ({len(mudancas)}; as últimas):")
        for o in mudancas[:3]:
            m = todos[o]
            d = m["campos"].get("desfazer")
            if desfazer:
                linhas.append(f"  - {_quando(m)} · {m['resumo']}" + (f" — desfazer: {d['v']}" if isinstance(d, dict) else "") + f" (`{o}`)")
            else:
                r = m["resumo"] if len(m["resumo"]) <= 110 else m["resumo"][:109] + "…"
                linhas.append(f"  - {_quando(m)} · {r} (`{o}`)")
        if not desfazer:
            linhas.append("  (como desfazer cada uma: `mem.py ver <id da mudança>`)")
    if outros:
        por_tipo = {}
        for o, t in outros:
            por_tipo.setdefault(t, []).append(o)
        linhas.append("Ligado a:")
        for t, lst in por_tipo.items():
            if len(lst) > 6:
                linhas.append(f"  - {t}: " + ", ".join(todos[o]["nome"] if o in todos else o for o in lst))
            else:
                for o in lst:
                    linhas.append(f"  - {t}: {todos[o]['resumo'] if o in todos else o + ' (sem ficha ainda)'} (`{o}`)")
    if completo and it.get("profunda"):
        linhas.append(f"Memória profunda: {RAIZ / it['profunda']}/ (`mem.py ver {iid}`)")
    return "\n".join(l for l in linhas if l)


def _quando(it):
    q = it.get("campos", {}).get("quando")
    return q.get("v", "") if isinstance(q, dict) else ""


def mudancas(iid=None):
    """Linha do tempo do que eu mexi (substitui o antigo MUDANCAS.md); com id, só o que tocou aquele item."""
    todos = itens()
    lista = [i for i, it in todos.items() if it["tipo"] == "mudanca"]
    if iid:
        lista = [i for i in lista if any(a == iid for a, _ in todos[i].get("ligacoes", []))]
    for i in sorted(lista, key=lambda i: _quando(todos[i])):
        m = todos[i]
        c = m["campos"]
        d = c.get("desfazer")
        print(f"{_quando(m)} · {m['resumo']}  [{', '.join(a for a, _ in m.get('ligacoes', []))}]")
        if isinstance(d, dict):
            print(f"      desfazer: {d['v']}")


def casa(texto, it):
    t = norm(texto)
    if any(norm(n) in t for n in it.get("nao_e_quando", [])):
        return 0
    # nota = tamanho do que casou: "ramal 31" (mais específico) vale mais que "ramal".
    # Frase com 2+ palavras fortes (3+ letras) também casa se TODAS aparecem na mensagem, mesmo separadas
    # ("etiqueta errada" casa com "a etiqueta do Alysson tá saindo errada"), valendo menos que a frase exata.
    nota = 0
    for a in it.get("chamado", []):
        na = norm(a)
        if re.search(r"(?<![\w])" + re.escape(na) + r"(?![\w])", t):
            nota += len(a)
            continue
        fortes = [w for w in re.findall(r"\w+", na) if len(w) >= 3]
        if len(fortes) >= 2 and all(re.search(r"(?<![\w])" + re.escape(w) + r"(?![\w])", t) for w in fortes):
            nota += int(len(a) * 0.7)
    return nota


def creditos():
    """{id: {"ajudou": n, "a_toa": n, "errou": n}} somando creditos.jsonl."""
    out = {}
    if CREDITOS.exists():
        for ln in CREDITOS.read_text(encoding="utf-8").splitlines():
            try:
                c = json.loads(ln)
                out.setdefault(c["id"], dict.fromkeys(NOTAS_CREDITO, 0))[c["nota"]] += 1
            except Exception:
                continue
    return out


MEIA_VIDA_DIAS = 30    # nota de 30 dias atrás pesa metade; a de 60, um quarto: prova velha vai sumindo sozinha
ACESSO_BAIXO = 0.30    # abaixo disso a ficha vem só com o resumo (precisa de umas 3 vindas à toa sem nenhuma ajuda)


def forcas(agora=None):
    """A força de ACESSO de cada ficha, de 0 a 1 (05/10/2026). 0,5 = ainda sem prova. Sobe quando a ficha ajudou, desce
    quando veio à toa (fazer errar pesa o dobro). A ficha em si nunca some: essa é a força de GUARDADO, que não cai.
    Conta com 2 a favor e 2 contra de saída, pra uma ou duas notas não decidirem nada sozinhas."""
    agora = agora or time.time()
    soma = {}
    if CREDITOS.exists():
        for ln in CREDITOS.read_text(encoding="utf-8").splitlines():
            try:
                c = json.loads(ln)
                dias = max(agora - time.mktime(time.strptime(c["quando"][:16], "%Y-%m-%dT%H:%M")), 0) / 86400
            except Exception:
                continue
            peso = 0.5 ** (dias / MEIA_VIDA_DIAS)
            s = soma.setdefault(c["id"], [0.0, 0.0])
            if c.get("nota") == "ajudou":
                s[0] += peso
            elif c.get("nota") in ("a_toa", "errou"):
                s[1] += peso * (2 if c["nota"] == "errou" else 1)
    return {i: (a + 2) / (a + t + 4) for i, (a, t) in soma.items()}


def ultimo_erro():
    """{id: quando} da última vez que cada ficha me fez errar."""
    out = {}
    if CREDITOS.exists():
        for ln in CREDITOS.read_text(encoding="utf-8").splitlines():
            try:
                c = json.loads(ln)
            except Exception:
                continue
            if c.get("nota") == "errou":
                out[c["id"]] = max(out.get(c["id"], ""), c.get("quando", ""))
    return out


def contar_uso(ids):
    try:
        u = json.loads(USO.read_text()) if USO.exists() else {}
        for i in ids:
            u.setdefault(i, {"vezes": 0})
            u[i]["vezes"] += 1
            u[i]["ultimo"] = time.strftime("%Y-%m-%d %H:%M")
        USO.write_text(json.dumps(u, ensure_ascii=False, indent=1))
    except Exception:
        pass


def puxar():
    texto = sys.stdin.read()
    todos = itens()
    forca = forcas()
    # a nota da palavra vezes a força: entre duas fichas que casam parecido, vem primeiro a que costuma ajudar
    notas = sorted(((casa(texto, it) * (0.5 + forca.get(iid, 0.5)), iid) for iid, it in todos.items()), reverse=True)
    achados = []
    for n, iid in notas:
        if n <= 0 or len(achados) == 3:
            break
        # já aparece como vizinho (resumo) de um achado mais forte: não repete inteiro
        if any(iid in {o for o, _, _ in ligacoes(todos, a)} for a in achados):
            continue
        achados.append(iid)
    # 2ª chance pelo SENTIDO (embeddings): só quando a palavra achou pouco, e nunca o que já veio ou está ligado
    por_sentido = {}
    t_norm = norm(texto)
    if len(achados) < 2 and len([w for w in re.findall(r"\w+", t_norm) if len(w) >= 3]) >= 3:
        try:
            import sentido
            ja = set(achados) | {o for a in achados for o, _, _ in ligacoes(todos, a)}
            for nota, iid in sentido.parecidos(texto):
                if nota < SENTIDO_MIN or len(por_sentido) >= SENTIDO_MAX_ITENS:
                    break
                it = todos.get(iid)
                if not it or iid in ja or any(norm(n) in t_norm for n in it.get("nao_e_quando", [])):
                    continue
                # ficha que costuma vir à toa precisa parecer mais com a mensagem pra vir pelo sentido
                if nota < SENTIDO_MIN_TIPO.get(it["tipo"], SENTIDO_MIN) + max(0.5 - forca.get(iid, 0.5), 0) * 0.1:
                    continue
                por_sentido[iid] = round(nota, 3)
                achados.append(iid)
        except Exception:
            pass  # servidor de embeddings fora: fica só a busca por palavra
    if not achados:
        return
    registrar = not ROBO.search(texto) and os.environ.get("MEM_TESTE") != "1"
    if registrar:
        contar_uso(achados)
    try:  # registro do que foi mandado e por quê — o sonho revisa e aprende quando NÃO mandar
        if registrar:
            t = norm(texto)
            por = {i: ([f"sentido {por_sentido[i]}"] if i in por_sentido else
                       [a for a in todos[i].get("chamado", []) if re.search(r"(?<![\w])" + re.escape(norm(a)) + r"(?![\w])", t)]) for i in achados}
            with (RAIZ / "envios.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"ts": time.strftime("%Y-%m-%d %H:%M"), "msg": texto[:300], "mandou": por}, ensure_ascii=False) + "\n")
    except Exception:
        pass
    cab = f"[memória — {CFG['rotulo'] or RAIZ}; é o que eu sei da última vez que vi, não o estado ao vivo]"
    fortes = fortes_de(texto)
    blocos = []
    for iid in achados:
        if forca.get(iid, 0.5) < ACESSO_BAIXO and iid not in por_sentido:
            it = todos[iid]   # vem só o resumo: continua lembrada, mas não gasta o espaço das outras
            blocos.append((iid, f"## {it['nome']} (`{iid}`, {it['tipo']})\n{it.get('resumo', '')}\n(só o resumo: nas últimas vezes esta "
                                f"ficha veio à toa; inteira com `mem.py ver {iid}`)"))
        else:
            blocos.append((iid, bloco(todos, iid, fortes=fortes)))
    print(encaixar(cab, blocos, LIMITE_PACOTE))


def encaixar(cab, blocos, limite):
    """Junta os blocos sem passar do limite e sem deixar um bloco grande engolir os outros (05/10/2026: a ficha da
    própria memória, sozinha, passava de 6.000 caracteres e cortava tudo que vinha depois). Bloco que cabe na sua parte
    vai inteiro; a sobra vai pros maiores; bloco grande é cortado no fim de uma linha, com o aviso de onde ler o resto."""
    sep = "\n\n"
    if len(cab) + sum(len(sep) + len(b) for _, b in blocos) <= limite:
        return sep.join([cab] + [b for _, b in blocos])
    aviso = "\n…(cortado; `mem.py ver {}` pro resto)"
    resta = limite - len(cab) - len(sep) * len(blocos)
    cotas, pendentes = {}, sorted(blocos, key=lambda x: len(x[1]))
    while pendentes:
        parte = resta // len(pendentes)
        iid, b = pendentes[0]
        if len(b) <= parte:
            cotas[iid] = len(b)
            resta -= len(b)
            pendentes.pop(0)
        else:
            for iid, _ in pendentes:
                cotas[iid] = parte
            break
    saida = [cab]
    for iid, b in blocos:
        if len(b) > cotas[iid]:
            av = aviso.format(iid)
            corte = b[:max(cotas[iid] - len(av), 0)]
            corte = corte[:corte.rfind("\n")] if "\n" in corte else corte
            b = corte + av
        saida.append(b)
    return sep.join(saida)


def ver(iid):
    todos = itens()
    if iid not in todos:
        print(f"não existe: {iid}. Itens: {', '.join(todos)}")
        return 1
    print(bloco(todos, iid, desfazer=True))
    c = creditos().get(iid)
    if c:
        print("Depois de mandada: " + ", ".join(f"{NOTAS_CREDITO[k]} {v}×" for k, v in c.items() if v)
              + f" · força de acesso {forcas().get(iid, 0.5):.2f} (0,5 = sem prova; abaixo de {ACESSO_BAIXO:.2f} vem só o resumo)")
    p = todos[iid].get("profunda")
    if p:
        print(f"\n--- memória profunda ({p}) ---")
        for f in sorted((RAIZ / p).rglob("*")):
            if f.is_file():
                print(f"  {f.relative_to(RAIZ)}  ({f.stat().st_size // 1024} KB)")
    if os.environ.get("MEM_TESTE") != "1":
        contar_uso([iid])


def duvidas(iid=None):
    """Dúvidas em aberto, da mais antiga pra mais nova. Resolver: mem.py anotar com op duvida_resolvida."""
    lista = [(d.get("desde", "?"), i, d["texto"]) for i, it in itens().items() if not iid or i == iid
             for d in it.get("duvidas", [])]
    for desde, i, t in sorted(lista):
        print(f"{desde} · {i}: {t}")
    if not lista:
        print("nenhuma dúvida em aberto" + (f" em {iid}" if iid else ""))


def lacunas(iid=None):
    todos = itens()
    for i, it in todos.items():
        if iid and i != iid:
            continue
        esq = esqueleto(it["tipo"])
        falta = [k for k, v in it.get("campos", {}).items() if v == "?"]
        if falta:
            ess = [k for k in falta if esq.get(k, {}).get("essencial")]
            print(f"{i}: essenciais {ess or '-'} · outros {[k for k in falta if k not in ess] or '-'}")


def validar(corrigir=False):
    problemas = 0
    for p in sorted(BASE.glob("*.json")):
        it = json.loads(p.read_text(encoding="utf-8"))
        esq = esqueleto(it["tipo"])
        if not esq:
            print(f"{it['id']}: tipo sem esqueleto: {it['tipo']}")
            problemas += 1
            continue
        faltando = [k for k in esq if k not in it.get("campos", {})]
        sobrando = [k for k in it.get("campos", {}) if k not in esq]
        if faltando or sobrando:
            problemas += 1
            print(f"{it['id']}: falta {faltando} · fora do esqueleto {sobrando} (vai pra 'proprio')")
            if corrigir:
                for k in faltando:
                    it.setdefault("campos", {})[k] = "?"
                for k in sobrando:
                    it.setdefault("proprio", {})[k] = it["campos"].pop(k)
                p.write_text(json.dumps(it, ensure_ascii=False, indent=1), encoding="utf-8")
        for v in list(it.get("campos", {}).values()) + list(it.get("proprio", {}).values()):
            s = json.dumps(v, ensure_ascii=False).lower()
            # aponta pra onde está (cofre, campo da central, padrão de fábrica) é ok; valor literal não
            if re.search(r"(senha|password|pass)\s*[:=]\s*(?!" + "|".join(map(re.escape, CFG["valor_que_nao_e_segredo"])) + r")\S{3,}", s) and "cofre" not in s:
                print(f"{it['id']}: PARECE TER SENHA em texto — tirar e pôr o caminho do cofre")
                problemas += 1
    print(f"{problemas} problema(s)")
    return 1 if problemas and not corrigir else 0


def iniciar():
    """Prepara a pasta dos dados de uma instalação nova. Não mexe no que já existe."""
    for d in ("base", "profunda", "diario", "regua", "coletores", "estado"):
        (DADOS / d).mkdir(parents=True, exist_ok=True)
    for nome, modelo in (("config.json", CODIGO / "exemplos" / "config.exemplo.json"), (".gitignore", CODIGO / "exemplos" / "gitignore-dos-dados")):
        if not (DADOS / nome).exists() and modelo.exists():
            (DADOS / nome).write_text(modelo.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"dados em {DADOS}\nedite {DADOS / 'config.json'}; pra ter histórico das fichas: git -C {DADOS} init")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "iniciar":
        iniciar()
    elif cmd == "onde":
        print(DADOS)
    elif cmd == "puxar":
        puxar()
    elif cmd == "ver" and len(sys.argv) > 2:
        sys.exit(ver(sys.argv[2]))
    elif cmd == "anotar":
        import sonho
        ESTADO.mkdir(parents=True, exist_ok=True)
        for linha in sys.stdin:
            if linha.strip():
                sonho.aplicar(json.loads(linha))
        feito = {k: v for k, v in sonho.diario.items() if v}
        for k, v in feito.items():
            for x in v:
                print(f"{k}: {x}")
        try:
            import sentido
            sentido.atualizar(itens())  # o sentido das fichas que mudaram
        except Exception:
            pass
        if feito:
            (RAIZ / "diario").mkdir(exist_ok=True)
            with (RAIZ / "diario" / f"{time.strftime('%Y-%m-%d')}.md").open("a", encoding="utf-8") as fh:
                fh.write(f"\n## Anotado na hora ({time.strftime('%H:%M')})\n" + "\n".join(f"- {k}: {x}" for k, v in feito.items() for x in v) + "\n")
    elif cmd == "mudancas":
        mudancas(sys.argv[2] if len(sys.argv) > 2 else None)
    elif cmd == "duvidas":
        duvidas(sys.argv[2] if len(sys.argv) > 2 else None)
    elif cmd == "lacunas":
        lacunas(sys.argv[2] if len(sys.argv) > 2 else None)
    elif cmd == "validar":
        sys.exit(validar("--corrigir" in sys.argv))
    else:
        print(__doc__)
