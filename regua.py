#!/usr/bin/env python3
"""A régua da memória: a mesma lista de perguntas, com a resposta certa conferida na fonte, é feita toda noite pra
esta memória e, se o config tiver um Honcho pra comparar, pra ele também. Mede o que cada uma MANDARIA junto da mensagem:
 - nossa: `mem.py puxar` (com MEM_TESTE=1, pra não contar como uso);
 - Honcho (opcional): as conclusões por semelhança que o plugin dele injeta (top 10, distância até 0,6). Só busca,
   sem modelo de linguagem.
Nota de cada resposta (ninguém julga; é por padrão de texto, igual pros dois lados):
  acertou  = trouxe o fato certo e nada errado          misturou = trouxe o certo e também um errado/velho
  errou    = trouxe só o errado/velho                   calou    = não trouxe o fato (ou não trouxe nada)
Um trecho que diz o velho E o certo juntos ("era 2.8.1, agora 2.9.0") é correção, não erro.
Mostra também o outro lado: das fichas mandadas de verdade em 7 dias, quantas ajudaram (creditos.jsonl).

  regua.py            roda, grava <dados>/regua/resultados/AAAA-MM-DD.json, uma linha em regua/placar.jsonl e o diário
  regua.py --seco     roda e mostra, sem gravar
  regua.py placar     o placar de cada noite
  regua.py ver <id>   o que cada memória mandou pra uma pergunta, com a nota

Perguntas em <dados>/regua/perguntas.json (modelo em exemplos/): {"id","pergunta","certo":[regex…](todos têm que
aparecer),"errado":[regex…],"fonte"(onde a resposta foi conferida),"conferido"}. Regex em minúsculas e sem acento (o
texto é normalizado). Pergunta nova: sempre com a fonte conferida FORA da memória; cada correção da pessoa vira uma.
"""
import datetime, json, os, re, subprocess, sys, urllib.request
from pathlib import Path

CODIGO = Path(__file__).resolve().parent
sys.path.insert(0, str(CODIGO))
import mem, sentido  # noqa: E402

RAIZ = mem.RAIZ

REGUA = RAIZ / "regua"
PERGUNTAS, PLACAR, RESULTADOS = REGUA / "perguntas.json", REGUA / "placar.jsonl", REGUA / "resultados"
HONCHO = (mem.CFG.get("regua") or {}).get("honcho")   # {"url": "http://host:8000/v3", "workspace": "...", "peer": "...", "chave": "..."}
HONCHO_TOP, HONCHO_DIST = 10, 0.6   # o que o plugin do Honcho pro Claude Code usa
LADOS = ("nossa", "honcho") if HONCHO else ("nossa",)
NOTAS = ("acertou", "misturou", "errou", "calou")


def nossa(pergunta):
    r = subprocess.run([sys.executable, str(CODIGO / "mem.py"), "puxar"], input=pergunta, capture_output=True, text=True,
                       timeout=60, env={**os.environ, "MEM_TESTE": "1"})
    linhas = [l for l in r.stdout.splitlines() if l.strip()]
    return linhas[1:] if linhas and linhas[0].startswith("[memória") else linhas


def honcho(pergunta):
    chave = HONCHO.get("chave")
    if chave is None and (Path.home() / ".honcho" / "config.json").exists():   # a chave do plugin do Honcho, se houver
        chave = json.loads((Path.home() / ".honcho" / "config.json").read_text()).get("apiKey", "")
    req = urllib.request.Request(f"{HONCHO['url'].rstrip('/')}/workspaces/{HONCHO['workspace']}/conclusions/query", data=json.dumps({
        "query": pergunta, "top_k": HONCHO_TOP, "distance": HONCHO_DIST,
        "filters": {"observer_id": HONCHO["peer"], "observed_id": HONCHO["peer"]}}).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + (chave or "")})
    return [c["content"] for c in json.load(urllib.request.urlopen(req, timeout=60))]


def nota(trechos, p):
    ts = [mem.norm(t) for t in trechos]
    tudo = "\n".join(ts)
    certo = bool(ts) and all(re.search(c, tudo) for c in p["certo"])
    errado = any(re.search(e, t) and not any(re.search(c, t) for c in p["certo"]) for t in ts for e in p.get("errado", []))
    return "misturou" if certo and errado else "acertou" if certo else "errou" if errado else "calou"


def rodar():
    perguntas = json.loads(PERGUNTAS.read_text(encoding="utf-8"))
    try:   # modelo de embeddings frio não pode virar nota ruim: carrega antes, com calma
        sentido.embed(["régua"], timeout=60, keep_alive=sentido.FICA_CARREGADO)
        pc = True
    except Exception:
        pc = False if sentido.OLLAMA else None   # None = esta instalação não usa a busca pelo sentido
    res = []
    for p in perguntas:
        r = {"id": p["id"], "pergunta": p["pergunta"]}
        for lado, f in (("nossa", nossa), ("honcho", honcho)):
            if lado not in LADOS:
                continue
            try:
                trechos = f(p["pergunta"])
                r[lado] = {"nota": nota(trechos, p), "trechos": len(trechos), "tamanho": sum(len(t) for t in trechos), "mandou": trechos}
            except Exception as e:
                r[lado] = {"nota": "sem medir", "erro": repr(e)[:200], "mandou": []}
        res.append(r)
    return {"quando": datetime.datetime.now().isoformat(timespec="seconds"), "sentido": pc, "perguntas": len(res), "respostas": res}


def placar(resultado):
    out = {}
    for lado in LADOS:
        notas = [r[lado]["nota"] for r in resultado["respostas"]]
        medidas = [r[lado] for r in resultado["respostas"] if r[lado]["nota"] != "sem medir"]
        out[lado] = {n: notas.count(n) for n in NOTAS + ("sem medir",) if notas.count(n)}
        out[lado]["tamanho_medio"] = round(sum(m["tamanho"] for m in medidas) / len(medidas)) if medidas else 0
    out["creditos_7d"] = creditos_7d()
    return out


def creditos_7d():
    """O outro lado da régua: das fichas que a memória mandou de verdade nos últimos 7 dias e o sonho julgou, quantas
    ajudaram. A régua de perguntas mede se o fato certo veio; isto mede quanto veio junto sem precisar."""
    desde = (datetime.datetime.now() - datetime.timedelta(days=7)).isoformat(timespec="minutes")
    out = dict.fromkeys(mem.NOTAS_CREDITO, 0)
    if mem.CREDITOS.exists():
        for ln in mem.CREDITOS.read_text(encoding="utf-8").splitlines():
            try:
                c = json.loads(ln)
                if c["quando"] >= desde:
                    out[c["nota"]] += 1
            except Exception:
                continue
    return out


def sem_sentido(d):
    """Aviso pro placar: a medição foi feita com o servidor de embeddings fora (a nota da nossa tende a cair)."""
    return " · SEM A BUSCA PELO SENTIDO" if d.get("sentido", d.get("pc_ligado", True)) is False else ""


def frase(pl, n):
    f = lambda d: ", ".join(f"{d.get(k, 0)} {k}" for k in NOTAS) + (f", {d['sem medir']} sem medir" if d.get("sem medir") else "")
    return [f"nossa memória: {f(pl['nossa'])} (manda em média {pl['nossa']['tamanho_medio']} caracteres)"] + (
        [f"Honcho: {f(pl['honcho'])} (manda em média {pl['honcho']['tamanho_medio']} caracteres)"] if "honcho" in pl else []) + (
        [f"fichas mandadas de verdade em 7 dias: {c['ajudou']} ajudaram, {c['a_toa']} vieram à toa, {c['errou']} fizeram errar"]
        if (c := pl.get("creditos_7d")) and sum(c.values()) else [])


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd != "placar" and not PERGUNTAS.exists():
        sys.exit(f"faltam as perguntas: {PERGUNTAS} (modelo em exemplos/perguntas.exemplo.json)")
    if cmd == "placar":
        for ln in PLACAR.read_text(encoding="utf-8").splitlines() if PLACAR.exists() else []:
            d = json.loads(ln)
            print(d["quando"][:16].replace("T", " "), f"· {d['perguntas']} perguntas" + sem_sentido(d))
            for l in frase(d["placar"], d["perguntas"]):
                print("   ", l)
        return
    if cmd == "ver" and len(sys.argv) > 2:
        p = next((x for x in json.loads(PERGUNTAS.read_text(encoding="utf-8")) if x["id"] == sys.argv[2]), None)
        if not p:
            sys.exit(f"não existe a pergunta {sys.argv[2]}")
        print(f"{p['pergunta']}\n  certo: {p['certo']}  errado: {p.get('errado', [])}\n  fonte: {p['fonte']}")
        for lado, f in (("nossa", nossa), ("honcho", honcho)):
            if lado not in LADOS:
                continue
            trechos = f(p["pergunta"])
            print(f"\n== {lado}: {nota(trechos, p)} ({len(trechos)} trechos)")
            for t in trechos:
                print("  ", t[:300])
        return
    resultado = rodar()
    pl = placar(resultado)
    linhas = frase(pl, resultado["perguntas"])
    print(f"{resultado['quando'][:16].replace('T', ' ')} · {resultado['perguntas']} perguntas" + sem_sentido(resultado))
    for l in linhas:
        print("  ", l)
    for r in resultado["respostas"]:
        if r["nossa"]["nota"] != "acertou" or "--tudo" in sys.argv:
            print(f"   {r['id']}: nossa {r['nossa']['nota']}" + (f" · Honcho {r['honcho']['nota']}" if "honcho" in r else "") + f" — {r['pergunta']}")
    if "--seco" in sys.argv:
        return
    hoje = resultado["quando"][:10]
    RESULTADOS.mkdir(parents=True, exist_ok=True)
    (RESULTADOS / f"{hoje}.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
    with PLACAR.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"quando": resultado["quando"], "sentido": resultado["sentido"], "perguntas": resultado["perguntas"],
                             "placar": pl}, ensure_ascii=False) + "\n")
    falhas = [f"{r['id']} ({r['nossa']['nota']}): {r['pergunta']}" for r in resultado["respostas"] if r["nossa"]["nota"] != "acertou"]
    (RAIZ / "diario").mkdir(exist_ok=True)
    with (RAIZ / "diario" / f"{hoje}.md").open("a", encoding="utf-8") as fh:
        fh.write(f"\n# Régua {resultado['quando'][11:16]} ({resultado['perguntas']} perguntas" + sem_sentido(resultado) + ")\n" + "".join(f"- {l}\n" for l in linhas)
                 + ("## Onde a nossa não acertou\n" + "".join(f"- {x}\n" for x in falhas) if falhas else ""))


if __name__ == "__main__":
    main()
