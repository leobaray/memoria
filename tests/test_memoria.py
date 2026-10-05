"""Testes da memória. Rodam numa pasta de dados temporária, nunca nos dados de verdade:  python3 -m unittest discover -s tests
Sem rede e sem modelo: tudo que chama o claude ou o servidor de embeddings fica de fora (isso quem mede é a régua)."""
import datetime, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path

CODIGO = Path(__file__).resolve().parent.parent
TMP = tempfile.TemporaryDirectory()
os.environ["MEMORIA_DADOS"] = TMP.name
os.environ.pop("MEM_TESTE", None)
sys.path.insert(0, str(CODIGO))
import mem, sonho, coleta, regua  # noqa: E402

DADOS = Path(TMP.name)
HOJE = datetime.date.today().isoformat()


def ficha(iid, tipo, **k):
    f = {"id": iid, "tipo": tipo, "nome": k.pop("nome", iid), "chamado": k.pop("chamado", []), "resumo": k.pop("resumo", f"resumo de {iid}"),
         "campos": {c: "?" for c in mem.esqueleto(tipo)}, "proprio": {}, "jeito_certo": [], "ligacoes": [], "profunda": None}
    f["campos"].update(k.pop("campos", {}))
    f.update(k)
    (mem.BASE / f"{iid}.json").write_text(json.dumps(f, ensure_ascii=False, indent=1), encoding="utf-8")
    return f


def V(v, visto="2026-01-01", como="teste"):
    return {"v": v, "visto": visto, "como": como}


def ler(iid):
    return json.loads((mem.BASE / f"{iid}.json").read_text(encoding="utf-8"))


def puxar(texto, **env):
    return subprocess.run([sys.executable, str(CODIGO / "mem.py"), "puxar"], input=texto, capture_output=True, text=True,
                          env={**os.environ, **env}).stdout


class Base(unittest.TestCase):
    def setUp(self):
        for d in ("base", "profunda", "diario", "estado"):
            (DADOS / d).mkdir(exist_ok=True)
        for p in list(mem.BASE.glob("*.json")) + [mem.USO, mem.CREDITOS, DADOS / "envios.jsonl"]:
            p.unlink(missing_ok=True)
        for k in sonho.diario:
            sonho.diario[k].clear()
        ficha("impressora-sala", "aparelho", nome="Impressora da sala", chamado=["impressora da sala", "impressora"],
              campos={"ip": V("192.168.0.60")}, nao_e_quando=["impressora 3d"])
        ficha("servidor-a", "servidor", nome="Servidor A", chamado=["servidor a"], campos={"ip": V("192.168.0.10")})
        ficha("caso-a", "caso", chamado=["não imprime nada"], campos={"causa": V("fila presa")})
        ficha("caso-b", "caso", campos={"causa": V("porta errada")})


class OndeFicamOsDados(Base):
    def test_dados_fora_do_codigo(self):
        self.assertEqual(mem.DADOS, DADOS.resolve())
        self.assertNotIn(CODIGO, mem.DADOS.parents)

    def test_esqueleto_herda_e_instalacao_ganha(self):
        self.assertIn("o_que_e", mem.esqueleto("servidor"))   # veio do _base pela herança
        (DADOS / "esqueletos").mkdir(exist_ok=True)
        (DADOS / "esqueletos" / "bicho.json").write_text(json.dumps({"tipo": "bicho", "herda": None, "campos": {"patas": {"o_que": "quantas", "essencial": True}}}))
        try:
            self.assertEqual(list(mem.esqueleto("bicho")), ["patas"])
            self.assertIn("bicho", mem.tipos())
        finally:
            (DADOS / "esqueletos" / "bicho.json").unlink()


class Puxar(Base):
    def test_casa_frase_exata_vale_mais_que_palavra(self):
        it = ler("impressora-sala")
        self.assertGreater(mem.casa("a impressora da sala parou", it), mem.casa("a impressora parou", it))
        self.assertEqual(mem.casa("quero uma impressora 3d", it), 0)   # nao_e_quando cancela
        self.assertEqual(mem.casa("bom dia", it), 0)

    def test_puxar_traz_a_ficha_e_teste_nao_conta_uso(self):
        out = puxar("a impressora da sala parou", MEM_TESTE="1")
        self.assertIn("192.168.0.60", out)
        self.assertFalse(mem.USO.exists())
        self.assertFalse((DADOS / "envios.jsonl").exists())

    def test_uso_de_verdade_conta_e_robo_nao(self):
        puxar("a impressora da sala parou")
        self.assertEqual(json.loads(mem.USO.read_text())["impressora-sala"]["vezes"], 1)
        self.assertEqual(len((DADOS / "envios.jsonl").read_text().splitlines()), 1)
        self.assertIn("192.168.0.60", puxar("/loop conferir a impressora da sala"))
        self.assertEqual(json.loads(mem.USO.read_text())["impressora-sala"]["vezes"], 1)

    def test_nada_citado_nao_imprime_nada(self):
        self.assertEqual(puxar("bom dia, tudo certo?", MEM_TESTE="1"), "")

    def test_pacote_divide_o_limite(self):
        blocos = [("g", "[g]\n" + "\n".join("x" * 60 for _ in range(150))), ("p1", "[p1]\n" + "y" * 400), ("p2", "[p2]\n" + "z" * 600)]
        out = mem.encaixar("CAB", blocos, 6000)
        self.assertLessEqual(len(out), 6000)
        self.assertIn(blocos[1][1], out)   # os pequenos vão inteiros
        self.assertIn(blocos[2][1], out)
        self.assertIn("mem.py ver g", out)   # o grande é cortado com o aviso de onde ler o resto
        self.assertEqual(mem.encaixar("CAB", blocos[1:], 6000), "CAB\n\n" + blocos[1][1] + "\n\n" + blocos[2][1])

    def test_campo_do_assunto_vem_primeiro(self):
        linhas = ["- cor: azul", "- encaixes de memória: 2", "- peso: 3 kg"]
        self.assertEqual(mem.por_assunto(linhas, mem.fortes_de("quantos encaixes tem?"))[0], "- encaixes de memória: 2")
        self.assertEqual(mem.por_assunto(linhas, set()), linhas)

    def test_duvida_aparece_com_a_ficha(self):
        sonho.aplicar({"op": "duvida", "id": "impressora-sala", "texto": "Ela é colorida?"})
        self.assertIn("Ela é colorida?", puxar("a impressora da sala", MEM_TESTE="1"))

    def test_ficha_que_so_vem_a_toa_vem_so_com_o_resumo(self):
        mem.CREDITOS.write_text("\n".join(json.dumps({"quando": time.strftime("%Y-%m-%dT%H:%M"), "id": "impressora-sala", "nota": "a_toa"}) for _ in range(4)) + "\n")
        out = puxar("a impressora da sala parou", MEM_TESTE="1")
        self.assertIn("só o resumo", out)
        self.assertNotIn("192.168.0.60", out)


class Forca(Base):
    def linha(self, iid, nota, dias=0):
        return json.dumps({"quando": time.strftime("%Y-%m-%dT%H:%M", time.localtime(time.time() - dias * 86400)), "id": iid, "nota": nota})

    def test_formula(self):
        L = self.linha
        mem.CREDITOS.write_text("\n".join([L("a", "ajudou")] * 4 + [L("b", "a_toa")] * 3 + [L("c", "a_toa")] * 2 + [L("d", "a_toa", 90)] * 3
                                          + [L("e", "errou")] * 2 + [L("f", "ajudou"), L("f", "a_toa")]) + "\n")
        f = mem.forcas()
        self.assertGreater(f["a"], 0.7)
        self.assertLess(f["b"], mem.ACESSO_BAIXO)            # 3 vindas à toa sem ajuda: cai
        self.assertGreaterEqual(f["c"], mem.ACESSO_BAIXO)    # 2 ainda não decidem
        self.assertGreater(f["d"], 0.4)                      # nota de 90 dias quase não pesa
        self.assertLess(f["e"], mem.ACESSO_BAIXO)            # fazer errar pesa o dobro
        self.assertAlmostEqual(f["f"], 0.5)
        self.assertNotIn("sem-nota", f)                      # sem prova = 0,5 pra quem pergunta com .get(id, 0.5)


class Anotar(Base):
    def test_campo_novo_reconfirmacao_e_troca(self):
        sonho.aplicar({"op": "campo", "id": "servidor-a", "campo": "versao", "v": "1.0", "visto": "2026-02-01", "como": "conferido"})
        self.assertEqual(ler("servidor-a")["campos"]["versao"]["v"], "1.0")
        sonho.aplicar({"op": "campo", "id": "servidor-a", "campo": "versao", "v": "1.0", "visto": "2026-03-01"})
        self.assertEqual(ler("servidor-a")["campos"]["versao"]["visto"], "2026-03-01")   # igual: só renova o visto
        sonho.aplicar({"op": "campo", "id": "servidor-a", "campo": "versao", "v": "uma versão aí"})
        self.assertEqual(ler("servidor-a")["campos"]["versao"]["v"], "1.0")              # sem "troca": não troca
        self.assertTrue(sonho.diario["ignorei"])
        sonho.aplicar({"op": "campo", "id": "servidor-a", "campo": "versao", "v": "2.0", "troca": "corrige"})
        self.assertEqual(ler("servidor-a")["campos"]["versao"]["v"], "2.0")
        self.assertIn("versao era: 1.0", (DADOS / "profunda" / "servidor-a" / "memoria.md").read_text())   # o velho vai pra história

    def test_campo_fora_do_esqueleto_vira_so_deste(self):
        sonho.aplicar({"op": "campo", "id": "servidor-a", "campo": "cor do gabinete", "v": "preto"})
        self.assertEqual(ler("servidor-a")["proprio"]["cor do gabinete"]["v"], "preto")

    def test_segredo_e_documento_sao_recusados(self):
        for op in ({"op": "campo", "id": "servidor-a", "campo": "acesso", "v": "senha: abc12345"},
                   {"op": "jeito_certo", "id": "servidor-a", "texto": "usar o token = ghp_abcdefgh12345"},
                   {"op": "campo", "id": "servidor-a", "campo": "dono", "v": "CPF 123.456.789-09"}):
            sonho.aplicar(op)
        self.assertEqual(len(sonho.diario["recusei"]), 3)
        self.assertEqual(ler("servidor-a")["campos"]["acesso"], "?")
        sonho.aplicar({"op": "campo", "id": "servidor-a", "campo": "senha_no_cofre", "v": "cofre rede/servidor.env"})
        self.assertEqual(ler("servidor-a")["campos"]["senha_no_cofre"]["v"], "cofre rede/servidor.env")   # o caminho pode

    def test_item_que_nao_existe_guarda_o_texto(self):
        sonho.aplicar({"op": "historia", "id": "servidor-b", "texto": "texto que não pode se perder"})
        self.assertIn("texto que não pode se perder", sonho.diario["erros"][0])
        self.assertIn("servidor-a", sonho.diario["erros"][0])   # sugere o id parecido

    def test_tipo_desconhecido_vira_duvida(self):
        sonho.aplicar({"op": "novo", "id": "x", "tipo": "nave-espacial", "nome": "X"})
        self.assertFalse((mem.BASE / "x.json").exists())
        self.assertTrue(sonho.diario["duvidas"])

    def test_duvida_mora_na_ficha_ate_resolver(self):
        d = {"op": "duvida", "id": "servidor-a", "texto": "Quantos discos ele tem?"}
        sonho.aplicar(d)
        sonho.aplicar({**d, "texto": "quantos discos ele tem?"})   # repetida não duplica
        sonho.aplicar({"op": "duvida", "id": "servidor-a", "texto": "Quantos pentes ele tem?"})
        self.assertEqual(len(ler("servidor-a")["duvidas"]), 2)
        sonho.aplicar({"op": "duvida_resolvida", "id": "servidor-a", "duvida": "quantos", "resposta": "x"})   # casa com as duas: não grava
        self.assertEqual(len(ler("servidor-a")["duvidas"]), 2)
        sonho.aplicar({"op": "duvida_resolvida", "id": "servidor-a", "duvida": "Quantos discos", "resposta": "4, contados"})
        self.assertEqual([x["texto"] for x in ler("servidor-a")["duvidas"]], ["Quantos pentes ele tem?"])
        self.assertIn("4, contados", (DADOS / "profunda" / "servidor-a" / "memoria.md").read_text())

    def test_credito_e_erro_vira_duvida(self):
        sonho.aplicar({"op": "credito", "id": "servidor-a", "nota": "ajudou", "porque": "usou o ip"})
        sonho.aplicar({"op": "credito", "id": "servidor-a", "nota": "inventada"})
        sonho.aplicar({"op": "credito", "id": "servidor-a", "nota": "errou", "porque": "ip velho", "fato": "dizia .10 e era .11."})
        self.assertEqual(mem.creditos()["servidor-a"], {"ajudou": 1, "a_toa": 0, "errou": 1})
        self.assertIn("dizia .10 e era .11.", ler("servidor-a")["duvidas"][0]["texto"])
        self.assertIn("servidor-a", mem.ultimo_erro())

    def test_credito_de_conversa_pessoal_nao_guarda_a_mensagem(self):
        sonho.aplicar({"op": "credito", "id": "servidor-a", "nota": "a_toa", "porque": "conversa pessoal", "msg": "desabafo"})
        self.assertEqual(json.loads(mem.CREDITOS.read_text().splitlines()[-1])["msg"], "")

    def test_licao_precisa_de_dois_casos(self):
        L = {"op": "licao", "id": "licao-conferir-a-porta", "regra": "Antes de culpar a impressora, conferir a fila e a porta.", "chamado": ["sumiu", "parou de imprimir de novo"]}
        sonho.aplicar({**L, "casos": ["caso-a", "caso-inventado"]})
        self.assertFalse((mem.BASE / "licao-conferir-a-porta.json").exists())
        sonho.aplicar({**L, "casos": ["caso-a", "caso-b"]})
        li = ler("licao-conferir-a-porta")
        self.assertEqual(li["chamado"], ["parou de imprimir de novo"])   # sintoma solto de uma palavra não vira chamada
        ficha("caso-c", "caso")
        sonho.aplicar({**L, "regra": "outro texto", "casos": ["caso-c"]})   # caso novo só reforça; o texto não muda
        li = ler("licao-conferir-a-porta")
        self.assertEqual(len(li["ligacoes"]), 3)
        self.assertIn("conferir a fila", li["campos"]["regra"]["v"])
        self.assertIn("Regra geral que saiu de casos como este", mem.bloco(mem.itens(), "caso-a"))

    def test_validar(self):
        self.assertEqual(mem.validar(), 0)
        f = ler("servidor-a")
        f["campos"]["campo_que_nao_existe"] = V("x")
        del f["campos"]["ip"]
        (mem.BASE / "servidor-a.json").write_text(json.dumps(f))
        self.assertEqual(mem.validar(), 1)
        mem.validar(corrigir=True)
        f = ler("servidor-a")
        self.assertEqual(f["campos"]["ip"], "?")
        self.assertIn("campo_que_nao_existe", f["proprio"])


class Recompensa(Base):
    def fala(self, quem, texto, minuto):
        return {"maq": "m", "proj": "p", "sessao": "s", "quem": quem, "texto": texto, "ts": f"2026-01-10T12:{minuto:02d}:00.000Z"}

    def test_liga_o_envio_ao_que_veio_depois(self):
        local = datetime.datetime(2026, 1, 10, 12, 0, tzinfo=datetime.timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
        falas = [self.fala("pessoa", "a impressora da sala parou de novo", 0), self.fala("assistente", "Reiniciei a fila dela.", 1),
                 self.fala("pessoa", "boa, voltou", 2), self.fala("pessoa", "outra coisa", 3)]
        envios = [{"ts": local, "msg": "a impressora da sala parou de novo", "mandou": {"impressora-sala": ["impressora"]}},
                  {"ts": local, "msg": "/loop conferir a impressora da sala agora", "mandou": {"impressora-sala": ["impressora"]}},
                  {"ts": local, "msg": "mensagem que não está na conversa nenhuma", "mandou": {"servidor-a": []}}]
        casos = sonho.ligar_envios(envios, falas)
        self.assertEqual(len(casos), 1)
        self.assertEqual(casos[0]["fichas"], ["impressora-sala"])
        self.assertEqual(len(casos[0]["depois"]), 3)   # para na 2ª fala da pessoa
        self.assertTrue(casos[0]["depois"][1].endswith("boa, voltou"))


class Conversa(unittest.TestCase):
    def test_hora_da_fala_vai_na_hora_local(self):
        utc = datetime.datetime(2026, 1, 10, 16, 18, tzinfo=datetime.timezone.utc)
        self.assertEqual(sonho.hora_local("2026-01-10T16:18:00.000Z"), utc.astimezone().strftime("%Y-%m-%d %H:%M"))
        self.assertEqual(sonho.hora_local("sem data"), "sem data")
        linha = next(sonho.pedacos([{"ts": "2026-01-10T16:18:00.000Z", "maq": "m", "proj": "p", "quem": "pessoa", "texto": "oi"}]))
        self.assertNotIn("UTC", linha)
        self.assertIn(utc.astimezone().strftime("%H:%M"), linha)


class Coleta(Base):
    def test_medir_e_preencher(self):
        c = coleta.Coleta()
        c.medir("servidor-a", "ip", "192.168.0.10", HOJE, "medição")       # igual: só renova o visto
        self.assertEqual(c.mudou, [])
        self.assertIn("servidor-a", c.renovados)
        c.medir("servidor-a", "ip", "192.168.0.11", HOJE, "medição")       # diferente: troca e guarda o velho
        self.assertEqual(len(c.mudou), 1)
        c.medir("servidor-a", "estado agora", "ligado há 3 h", HOJE, "medição", volatil=True)
        self.assertEqual(len(c.mudou), 1)                                  # estado do momento não vai pro diário
        c.preencher("servidor-a", "versao", "9", HOJE, "coleta fixa")      # estava "?": entra
        c.preencher("servidor-a", "ip", "10.0.0.1", HOJE, "coleta fixa")   # o ip veio de "medição" (não é de coletor): fica
        c.gravar()
        f = ler("servidor-a")
        self.assertEqual((f["campos"]["ip"]["v"], f["campos"]["versao"]["v"]), ("192.168.0.11", "9"))
        self.assertIn("era '192.168.0.10'", (DADOS / "profunda" / "servidor-a" / "memoria.md").read_text())
        self.assertIn("servidor-a · ip", (DADOS / "diario" / f"{HOJE}.md").read_text())

    def test_seco_nao_grava(self):
        c = coleta.Coleta(seco=True)
        c.medir("servidor-a", "ip", "192.168.0.99", HOJE, "medição")
        self.assertEqual(ler("servidor-a")["campos"]["ip"]["v"], "192.168.0.10")

    def test_coletor_que_quebra_vira_aviso(self):
        (DADOS / "coletores").mkdir(exist_ok=True)
        (DADOS / "coletores" / "ruim.py").write_text("def coletar(c):\n    raise RuntimeError('quebrei')\n")
        (DADOS / "coletores" / "bom.py").write_text("def coletar(c):\n    c.medir('servidor-a', 'versao', '7', c.hoje, 'coleta de teste')\n")
        try:
            c = coleta.rodar(seco=True)
            self.assertEqual(len(c.mudou), 1)
            self.assertIn("quebrei", c.avisos[0])
        finally:
            for p in (DADOS / "coletores").glob("*.py"):
                p.unlink()


class Regua(unittest.TestCase):
    P = {"certo": [r"2\.9\.0"], "errado": [r"2\.8\.1"]}

    def test_notas(self):
        self.assertEqual(regua.nota(["versão 2.9.0"], self.P), "acertou")
        self.assertEqual(regua.nota(["versão 2.9.0", "versão 2.8.1"], self.P), "misturou")
        self.assertEqual(regua.nota(["versão 2.8.1"], self.P), "errou")
        self.assertEqual(regua.nota(["nada a ver"], self.P), "calou")
        self.assertEqual(regua.nota([], self.P), "calou")
        self.assertEqual(regua.nota(["era 2.8.1, agora 2.9.0"], self.P), "acertou")   # correção não é erro

    def test_todos_os_certos_tem_que_aparecer_e_acento_nao_importa(self):
        p = {"certo": [r"ramal 31", r"\*2"], "errado": []}
        self.assertEqual(regua.nota(["ligar pro Ramal 31"], p), "calou")
        self.assertEqual(regua.nota(["ligar pro Ramal 31", "digitar *2"], p), "acertou")
        self.assertEqual(regua.nota(["irmã do dono"], {"certo": [r"irma"], "errado": []}), "acertou")


class Extrair(unittest.TestCase):
    def test_so_o_texto_da_pessoa_e_do_assistente(self):
        with tempfile.TemporaryDirectory() as casa:
            proj = Path(casa) / ".claude" / "projects" / "-um-projeto"
            proj.mkdir(parents=True)
            (Path(casa) / ".claude" / "projects" / "-pasta-do-sonho").mkdir()
            L = lambda **k: json.dumps({"timestamp": "2026-01-10T12:00:00.000Z", **k})
            (proj / "abc12345.jsonl").write_text("\n".join([
                L(type="user", message={"content": "oi, tudo certo?"}),
                L(type="assistant", message={"content": [{"type": "text", "text": "tudo"}, {"type": "tool_use", "name": "x"}]}),
                L(type="user", message={"content": "<system-reminder>aviso</system-reminder>"}),
                L(type="user", message={"content": "fala de subagente"}, isSidechain=True),
                L(type="user", message={"content": "prompt de robô"}, entrypoint="sdk-cli"),
                L(type="user", message={"content": "antiga"}, timestamp="2025-01-01T00:00:00.000Z")]) + "\n")
            (Path(casa) / ".claude" / "projects" / "-pasta-do-sonho" / "x.jsonl").write_text(L(type="user", message={"content": "do sonho"}) + "\n")
            r = subprocess.run([sys.executable, str(CODIGO / "extrair.py")], capture_output=True, text=True,
                               env={**os.environ, "HOME": casa, "USERPROFILE": casa, "DESDE": "2026-01-01T00:00:00Z", "MAQUINA": "m"})
            falas = [json.loads(l) for l in r.stdout.splitlines()]
            self.assertEqual([(f["quem"], f["texto"]) for f in falas], [("pessoa", "oi, tudo certo?"), ("assistente", "tudo")])


if __name__ == "__main__":
    unittest.main()
