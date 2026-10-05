# memória

*In English: [README.md](README.md).*

Uma memória de longo prazo pra um assistente de IA (feita pro Claude Code), desenhada a partir de como o cérebro
aprende: lembra fácil do que importa, sabe o que ainda não sabe, aprende com o resultado e tira regra geral de casos
parecidos. Roda em arquivos de texto, sem banco de dados e sem dependência além do Python.

A ideia central: **uma ficha por coisa**. Cada servidor, pessoa, projeto, regra ou problema resolvido tem uma ficha JSON, e
cada fato dentro dela guarda *quando* e *como* foi sabido. O que não se sabe fica marcado como `?`, em vez de ser inventado.

```json
{"id": "servidor-arquivos", "tipo": "servidor", "chamado": ["servidor de arquivos", "nas"],
 "campos": {"ip": {"v": "192.168.0.10", "visto": "2026-01-10", "como": "lido no servidor"},
            "versao": "?"}}
```

Quando a pessoa escreve "o servidor de arquivos tá lento", um gancho manda a mensagem pro `mem.py puxar`, que devolve a
ficha (e o que está ligado a ela) pra dentro do contexto da conversa.

## O que ela faz sozinha

| | o que é | no cérebro |
|---|---|---|
| **Puxar** (`mem.py puxar`) | acha as fichas pela palavra de chamada e, como segunda chance, pelo sentido | lembrar pela pista |
| **Sonho** (`sonho.py`, toda noite) | lê as conversas do dia, atualiza as fichas, registra casos e mudanças | o sono repassando o dia |
| **Recompensa** (no sonho) | julga cada ficha mandada pelo que veio depois: ajudou, veio à toa ou fez errar | dopamina: a surpresa do resultado |
| **Força de acesso** | quem ajuda vem primeiro; quem só vem à toa passa a vir só com o resumo. Nada é apagado | as duas forças: guardado e acesso |
| **Aprendiz lento** (no sonho) | olha todos os casos resolvidos e tira a regra que vale pra mais de um | o córtex generalizando |
| **Coleta** (`coleta.py`) | o que dá pra medir entra nas fichas sem depender de conversa | — |
| **Régua** (`regua.py`, toda noite) | faz perguntas de resposta conhecida e dá nota pro que a memória traria | aprender onde errou |

O estudo por trás do desenho está em [docs/como-o-cerebro-aprende.md](docs/como-o-cerebro-aprende.md).

## Travas

- **Segredo não entra.** Senha, token e documento pessoal são recusados na gravação; a ficha guarda só o caminho no cofre.
- **Detalhe não vira resumo.** Um valor que já existe só é trocado com `"troca": "corrige"`, e o antigo vai pra história.
- **Dúvida não é decidida no escuro.** Fica na ficha e aparece junto dela até alguém responder.
- **Regra geral precisa de prova.** Uma lição só nasce apoiada em dois ou mais casos que existem.
- **Teste não ensina errado.** Com `MEM_TESTE=1`, puxar não conta como uso; mensagem de robô (`/loop`) também não.

## Seus dados ficam fora deste repositório

O código não guarda nada de quem usa. Fichas, diário, configuração e estado ficam numa pasta de dados, procurada nesta
ordem: a variável `MEMORIA_DADOS`; a pasta `dados/` ao lado do código (ignorada pelo git); `~/.memoria`.

```
<dados>/
  config.json     nome da pessoa, máquinas, modelos (modelo em exemplos/config.exemplo.json)
  base/           uma ficha por coisa
  profunda/       a história de cada ficha e documentos guardados
  diario/         o que mudou em cada dia
  regua/          as perguntas da régua e o placar
  coletores/      o que a sua instalação mede (modelo em exemplos/coletor_exemplo.py)
  estado/         logs, ponteiros e cópias de antes de cada sonho
```

Pra ter o histórico de cada ficha, dê `git init` **na pasta dos dados** (um repositório seu, separado deste); o
`salvar_git.sh` grava nele.

## Começar

Precisa de Python 3 (testado no 3.12, só biblioteca padrão) e do Claude Code (o sonho chama `claude -p`).

```sh
git clone https://github.com/leobaray/memoria ~/memoria && cd ~/memoria
python3 mem.py iniciar                 # cria ~/.memoria com o config.json de modelo
$EDITOR ~/.memoria/config.json

# a primeira ficha (uma operação JSON por linha)
echo '{"op":"novo","id":"servidor-arquivos","tipo":"servidor","nome":"Servidor de arquivos","resumo":"NAS do escritório","chamado":["servidor de arquivos","nas"]}' | python3 mem.py anotar
echo '{"op":"campo","id":"servidor-arquivos","campo":"ip","v":"192.168.0.10","como":"lido no servidor"}' | python3 mem.py anotar

echo "o servidor de arquivos tá lento" | MEM_TESTE=1 python3 mem.py puxar
```

Depois: o gancho que puxa a cada mensagem ([exemplos/ganchos/memoria-puxar.sh](exemplos/ganchos/memoria-puxar.sh)) e os
agendamentos ([exemplos/crontab.txt](exemplos/crontab.txt)).

## Comandos

```
mem.py puxar | ver <id> | lacunas [id] | duvidas [id] | mudancas [id] | validar [--corrigir] | anotar | iniciar | onde
sonho.py  [--so-ler] [--sem-faxina] [--sem-licoes] [--desde <ISO>]
coleta.py [--seco]
regua.py  [--seco] | placar | ver <id>
```

As operações do `anotar` (as mesmas que o sonho usa) estão em [docs/operacoes.md](docs/operacoes.md): `novo`, `campo`, `remover`,
`jeito_certo`, `historia`, `caso`, `mudanca`, `ligacao`, `duvida`, `duvida_resolvida`, `credito`, `licao`, `chamado`,
`nao_e_quando`.

Os tipos de ficha são esqueletos em `esqueletos/` (com herança); a sua instalação pode acrescentar ou trocar um tipo pondo
o arquivo em `<dados>/esqueletos/`.

## Busca pelo sentido (opcional)

Com um [Ollama](https://ollama.com) servindo um modelo de embeddings (`bge-m3`), a memória acha a ficha mesmo quando
nenhuma palavra de chamada aparece na mensagem. Ligue em `config.json`:

```json
"sentido": {"url": "http://localhost:11434/api/embed", "modelo": "bge-m3", "fica_carregado": "1h"}
```

## Comparar com o Honcho (opcional)

Quem também usa o [Honcho](https://github.com/plastic-labs/honcho) pode pôr a régua pra fazer as mesmas perguntas às duas
memórias (`"regua": {"honcho": {"url": "…/v3", "workspace": "…", "peer": "…"}}`). A consulta é só busca, sem custo de modelo.

## Testes

```sh
python3 -m unittest discover -s tests
```

Rodam numa pasta de dados temporária, sem rede e sem modelo. O que depende do modelo (o sonho) e do que a memória traz
de verdade é medido pela régua, toda noite, nos dados reais.

## Limites conhecidos

- Os prompts, os nomes dos campos e a documentação estão em português.
- O sonho lê só conversas do Claude Code; conversa que acontece em outro lugar não entra nem recebe nota.
- A nota da régua é por padrão de texto: mede se o fato veio, não se a resposta final ficou boa.
- As forças precisam de algumas semanas de notas pra fazer diferença.

## Licença

MIT. Veja [LICENSE](LICENSE).
