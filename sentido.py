"""Busca pelo SENTIDO: segunda chance quando nenhuma palavra de chamada da ficha aparece na mensagem. Usa um modelo de
embeddings servido por um Ollama (config "sentido": {"url", "modelo", "fica_carregado"}); sem essa config, fica desligada
e a memória acha só pela palavra. Cache em <dados>/embeds.json (só recalcula a ficha que mudou).

O Ollama descarrega o modelo 5 min depois do último uso, e carregar de novo leva alguns segundos. A pergunta desiste em
2,5 s (não pode atrasar a mensagem) e o Ollama CANCELA a carga quando quem pediu desiste; sem cuidado, a busca só
funcionaria se outra coisa tivesse aquecido o modelo. Por isso a pergunta pede pro modelo ficar carregado e, se o
encontrar frio, um processo à parte carrega sem pressa pra próxima mensagem."""
import hashlib, json, math, subprocess, sys, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mem  # noqa: E402

CACHE = mem.RAIZ / "embeds.json"
CFG = mem.CFG.get("sentido") or {}
OLLAMA = CFG.get("url")
MODELO = CFG.get("modelo", "bge-m3")
FICA_CARREGADO = CFG.get("fica_carregado", "1h")


def texto_ficha(it):
    c = it.get("campos", {})
    pedacos = [it.get("nome", ""), it.get("resumo", ""), ", ".join(it.get("chamado", []))]
    for k in ("o_que_e", "sintoma", "para_que", "aparelho_ligado", "funcao", "o_que", "quer_dizer", "regra"):
        v = c.get(k)
        if isinstance(v, dict):
            pedacos.append(str(v.get("v", "")))
    pedacos += (it.get("jeito_certo") or [])[:1]
    return " | ".join(p for p in pedacos if p)[:1200]


def embed(textos, timeout=4, keep_alive=None):
    if not OLLAMA:
        raise RuntimeError("busca pelo sentido desligada (falta 'sentido' no config.json)")
    corpo = {"model": MODELO, "input": textos}
    if keep_alive:
        corpo["keep_alive"] = keep_alive
    req = urllib.request.Request(OLLAMA, data=json.dumps(corpo).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))["embeddings"]


def _norm(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def carregar():
    try:
        return json.loads(CACHE.read_text())
    except Exception:
        return {}


def atualizar(todos):
    """Calcula o vetor das fichas novas ou mudadas. Devolve quantas recalculou."""
    if not OLLAMA:
        return 0
    cache = carregar()
    falta = []
    for iid, it in todos.items():
        if it.get("tipo") == "mudanca":
            continue  # mudança só chega pelas ligações, não pelo sentido
        t = texto_ficha(it)
        h = hashlib.sha1(t.encode()).hexdigest()[:12]
        if cache.get(iid, {}).get("h") != h:
            falta.append((iid, h, t))
    for k in range(0, len(falta), 32):
        lote = falta[k:k + 32]
        for (iid, h, _), v in zip(lote, embed([t for _, _, t in lote], timeout=60)):
            cache[iid] = {"h": h, "v": [round(x, 5) for x in _norm(v)]}
    for iid in [i for i in cache if i not in todos]:
        del cache[iid]
    CACHE.write_text(json.dumps(cache))
    return len(falta)


def parecidos(texto, cache=None, timeout=2.5):
    """[(nota, id)] do mais parecido pro menos, pelo sentido da mensagem."""
    cache = cache if cache is not None else carregar()
    if not OLLAMA or not cache:
        return []
    try:
        q = _norm(embed([texto[:2000]], timeout=timeout, keep_alive=FICA_CARREGADO)[0])
    except Exception:
        aquecer()
        raise
    return sorted(((sum(a * b for a, b in zip(q, e["v"])), iid) for iid, e in cache.items()), reverse=True)


def aquecer():
    """Carrega o modelo num processo à parte, que sobrevive ao fim do puxar (e do ssh de quem chamou)."""
    try:
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "aquecer"], start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


if __name__ == "__main__" and sys.argv[1:] == ["aquecer"]:
    try:
        embed(["aquecer"], timeout=60, keep_alive=FICA_CARREGADO)
    except Exception:
        pass
