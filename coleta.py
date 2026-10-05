#!/usr/bin/env python3
"""Coleta: o que é MEDIDO entra nas fichas sozinho, sem depender de conversa.

Cada instalação mede coisas diferentes (um painel de rede, um firewall, o systemd, uma planilha), então o que medir fica
em coletores: arquivos `<dados>/coletores/*.py`, cada um com uma função `coletar(c)`. Este programa entrega o `c` (as
fichas e as ferramentas abaixo), roda os coletores em ordem alfabética e grava o resultado com as regras da memória:

  c.medir(id, campo, valor, visto, como)        valor medido. Igual ao da ficha: só renova o "visto". Diferente: troca, e o
                                                valor velho vai pra história (profunda). volatil=True: estado do momento,
                                                só sobrescreve, sem história nem diário.
  c.preencher(id, campo, valor, visto, como)    fato fixo: só entra onde está "?" ou onde um coletor pôs antes (c.fontes).
                                                Nunca passa por cima do que veio de conversa.
  c.item(id)        a ficha (dict) pra ler ou mexer;  c.todos  todas as fichas como estavam no começo
  c.tocados[id] = {...}; c.mudou.append("id · ficha nova: …")    cria uma ficha
  c.avisos.append("…")                          vai pro diário, seção Avisos
  c.secoes["Título"] = ["linha", …]             seção própria no diário
  c.estado                                      dict que fica guardado de uma coleta pra outra (por coletor, livre)
  c.resumo["chave"] = valor                     entra no resumo da última coleta
  c.hoje, c.agora, c.seco

O que mudou vai pro diário do dia. Um coletor que quebra vira aviso e não derruba os outros.
Uso: python3 coleta.py [--seco]     (--seco mostra o que mudaria, sem gravar)      Exemplo: exemplos/coletor_exemplo.py"""
import datetime, importlib.util, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mem  # noqa: E402

ESTADO = mem.ESTADO / "coleta-estado.json"


class Coleta:
    def __init__(self, seco=False):
        self.seco = seco
        self.agora = datetime.datetime.now()
        self.hoje = self.agora.strftime("%Y-%m-%d")
        self.todos = mem.itens()
        self.mudou, self.avisos, self.renovados = [], [], set()
        self.tocados = {}   # id -> ficha (gravada no fim, se mudou)
        self.secoes, self.resumo = {}, {}
        self.fontes = ["coleta"]   # começos de "como" que marcam valor posto por coletor (o preencher pode trocar)
        self.estado = json.loads(ESTADO.read_text(encoding="utf-8")) if ESTADO.exists() else {}

    def item(self, iid):
        if iid not in self.tocados:
            self.tocados[iid] = json.loads((mem.BASE / f"{iid}.json").read_text(encoding="utf-8"))
        return self.tocados[iid]

    def historia(self, it, texto):
        pasta = mem.RAIZ / (it.get("profunda") or f"profunda/{it['id']}")
        if not self.seco:
            pasta.mkdir(parents=True, exist_ok=True)
            f = pasta / "memoria.md"
            if not f.exists():
                f.write_text(f"# {it['nome']} — memória profunda\n", encoding="utf-8")
            with f.open("a", encoding="utf-8") as fh:
                fh.write(f"\n- **{self.hoje}** (coleta automática): {texto}\n")
        it["profunda"] = it.get("profunda") or f"profunda/{it['id']}"

    def medir(self, iid, campo, valor, visto, como, volatil=False):
        if valor in (None, "", "None"):
            return
        it = self.item(iid)
        lugar = "campos" if campo in mem.esqueleto(it["tipo"]) else "proprio"
        velho = it.setdefault(lugar, {}).get(campo)
        novo = {"v": valor, "visto": visto, "como": como}
        if isinstance(velho, dict) and str(velho.get("v")).strip() == str(valor).strip():
            if velho.get("visto", "") < visto:
                velho["visto"] = visto
                self.renovados.add(iid)
            return
        it[lugar][campo] = novo
        if volatil:
            self.renovados.add(iid)
            return
        if isinstance(velho, dict):
            self.historia(it, f"{campo}: era '{velho.get('v')}' (visto {velho.get('visto')}, {velho.get('como')}); a coleta mediu '{valor}'")
            self.mudou.append(f"{iid} · {campo}: {velho.get('v')} → {valor}")
        else:
            self.mudou.append(f"{iid} · {campo}: (não sei ainda) → {valor}")

    def preencher(self, iid, campo, valor, visto, como):
        if valor in (None, ""):
            return
        v = self.item(iid).get("campos", {}).get(campo, self.item(iid).get("proprio", {}).get(campo))
        if v in (None, "?") or (isinstance(v, dict) and str(v.get("como", "")).startswith(tuple(self.fontes))):
            self.medir(iid, campo, valor, visto, como)

    def gravar(self):
        for iid, it in self.tocados.items():
            if iid in self.renovados or any(m.startswith(iid + " ·") for m in self.mudou):
                it["atualizado"] = self.hoje
                (mem.BASE / f"{iid}.json").write_text(json.dumps(it, ensure_ascii=False, indent=1), encoding="utf-8")
        self.estado["ultima"] = self.agora.isoformat(timespec="seconds")
        self.estado["ultima_resumo"] = {"mudou": len(self.mudou), "renovados": len(self.renovados), "avisos": len(self.avisos),
                                        **self.resumo}
        ESTADO.parent.mkdir(parents=True, exist_ok=True)
        ESTADO.write_text(json.dumps(self.estado, ensure_ascii=False, indent=1), encoding="utf-8")
        secoes = {"O que mudou": self.mudou, **self.secoes, "Avisos": self.avisos}
        if any(secoes.values()):
            (mem.RAIZ / "diario").mkdir(exist_ok=True)
            with (mem.RAIZ / "diario" / f"{self.hoje}.md").open("a", encoding="utf-8") as fh:
                fh.write(f"\n# Coleta automática {self.agora:%d/%m/%Y %H:%M}\n")
                for titulo, linhas in secoes.items():
                    if linhas:
                        fh.write(f"## {titulo}\n" + "".join(f"- {l}\n" for l in linhas))


def coletores():
    return sorted((mem.RAIZ / "coletores").glob("[!_]*.py"))


def rodar(seco=False):
    c = Coleta(seco)
    for arq in coletores():
        try:
            spec = importlib.util.spec_from_file_location(f"coletor_{arq.stem}", arq)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.coletar(c)
        except Exception as e:
            c.avisos.append(f"coletor {arq.name} quebrou: {e!r}"[:300])
    return c


def main():
    seco = "--seco" in sys.argv
    if not coletores():
        print(f"nenhum coletor em {mem.RAIZ / 'coletores'} (modelo: exemplos/coletor_exemplo.py)")
        return
    c = rodar(seco)
    if seco:
        print(json.dumps({"mudou": c.mudou, "renovados": len(c.renovados), "avisos": c.avisos, "secoes": c.secoes, "resumo": c.resumo},
                         ensure_ascii=False, indent=1))
        return
    c.gravar()
    print(f"{c.agora:%Y-%m-%d %H:%M} mudou {len(c.mudou)}, renovou {len(c.renovados)} fichas, {len(c.avisos)} avisos")


if __name__ == "__main__":
    main()
