# memoria

Long-term memory for an AI coding assistant (built for Claude Code), designed around how the brain learns: it recalls what matters, knows what it does not know yet, learns from outcomes, and derives general rules from similar cases. Plain text files, no database, standard-library Python only.

*Leia em português: [README.pt-BR.md](README.pt-BR.md). The code, prompts and field names are in Portuguese.*

## Context

An assistant that works on the same infrastructure every day keeps relearning the same facts, and when it does remember, it cannot tell a fact it measured yesterday from one somebody mentioned a month ago. Conversation-level memory stores what was said; it does not keep one authoritative answer per thing, and it happily returns the stale version next to the current one.

The core idea here is **one card per thing**. Every server, person, project, rule or solved problem has a JSON card, and each fact on it records *when* and *how* it was learned. What is unknown is marked `?` instead of being guessed.

```json
{"id": "servidor-arquivos", "tipo": "servidor", "chamado": ["servidor de arquivos", "nas"],
 "campos": {"ip": {"v": "192.168.0.10", "visto": "2026-01-10", "como": "read on the server"},
            "versao": "?"}}
```

When the user writes "the file server is slow", a hook pipes the message to `mem.py puxar`, which returns the card (and what is linked to it) into the conversation context.

## What it does on its own

| | what it is | in the brain |
|---|---|---|
| **Recall** (`mem.py puxar`) | finds cards by trigger words and, as a second chance, by meaning (embeddings) | cue-based retrieval |
| **Dream** (`sonho.py`, nightly) | reads the day's conversations, updates cards, records solved cases and changes | sleep replaying the day |
| **Reward** (in the dream) | grades every card that was sent by what happened next: helped, came for nothing, or misled | dopamine: the surprise of the outcome |
| **Access strength** | cards that help come first; cards that only come for nothing shrink to a one-line summary. Nothing is ever deleted | storage strength vs. retrieval strength |
| **Slow learner** (in the dream) | looks at all solved cases together and extracts the rule that holds for more than one | the cortex generalising |
| **Collection** (`coleta.py`) | whatever can be measured goes into the cards without depending on conversation | — |
| **Ruler** (`regua.py`, nightly) | asks questions with known answers and grades what the memory would have returned | learning where the prediction failed |

The study behind the design is in [docs/como-o-cerebro-aprende.md](docs/como-o-cerebro-aprende.md) (Portuguese).

## Guard rails

- **Secrets stay out.** Passwords, tokens and personal documents are refused at write time; a card stores only the path in the vault.
- **Detail never degrades into a summary.** An existing value is only replaced when marked `"troca": "corrige"`, and the old one goes to the card's history.
- **Doubts are not settled in the dark.** They live on the card and show up with it until someone answers.
- **A general rule needs evidence.** A lesson is only created when backed by two or more existing cases.
- **Testing does not teach the wrong thing.** With `MEM_TESTE=1`, recall does not count as usage; neither do scripted prompts (`/loop`).

## Your data stays out of this repository

The code holds nothing about whoever uses it. Cards, diary, configuration and state live in a data folder, looked up in this order: the `MEMORIA_DADOS` variable; a `dados/` folder next to the code (git-ignored); `~/.memoria`.

```
<data>/
  config.json     your name, machines, models (template in exemplos/config.exemplo.json)
  base/           one card per thing
  profunda/       each card's history and stored documents
  diario/         what changed each day
  regua/          the ruler's questions and scoreboard
  coletores/      what your installation measures (template in exemplos/coletor_exemplo.py)
  estado/         logs, pointers and a copy of the cards before each dream
```

To keep the history of every card, run `git init` **inside the data folder** (a repository of your own, separate from this one); `salvar_git.sh` commits to it.

## Getting started

Requires Python 3 (tested on 3.12, standard library only) and Claude Code (the dream calls `claude -p`).

```sh
git clone https://github.com/leobaray/memoria ~/memoria && cd ~/memoria
python3 mem.py iniciar                 # creates ~/.memoria with a template config.json
$EDITOR ~/.memoria/config.json

# the first card (one JSON operation per line)
echo '{"op":"novo","id":"servidor-arquivos","tipo":"servidor","nome":"Servidor de arquivos","resumo":"NAS do escritório","chamado":["servidor de arquivos","nas"]}' | python3 mem.py anotar
echo '{"op":"campo","id":"servidor-arquivos","campo":"ip","v":"192.168.0.10","como":"lido no servidor"}' | python3 mem.py anotar

echo "o servidor de arquivos tá lento" | MEM_TESTE=1 python3 mem.py puxar
```

Then install the hook that recalls on every message ([exemplos/ganchos/memoria-puxar.sh](exemplos/ganchos/memoria-puxar.sh)) and the schedules ([exemplos/crontab.txt](exemplos/crontab.txt)).

## Commands

```
mem.py puxar | ver <id> | lacunas [id] | duvidas [id] | mudancas [id] | validar [--corrigir] | anotar | iniciar | onde
sonho.py  [--so-ler] [--sem-faxina] [--sem-licoes] [--desde <ISO>]
coleta.py [--seco]
regua.py  [--seco] | placar | ver <id>
```

Every change to the memory is a JSON operation, the same ones the dream emits; they are listed in [docs/operacoes.md](docs/operacoes.md). Card types are skeletons in `esqueletos/` (with inheritance); an installation can add or override a type by dropping a file in `<data>/esqueletos/`.

## Optional pieces

**Recall by meaning.** With an [Ollama](https://ollama.com) instance serving an embedding model (`bge-m3`), a card is found even when none of its trigger words appear in the message:

```json
"sentido": {"url": "http://localhost:11434/api/embed", "modelo": "bge-m3", "fica_carregado": "1h"}
```

**Side-by-side with Honcho.** If you also run [Honcho](https://github.com/plastic-labs/honcho), the ruler can ask both memories the same questions (`"regua": {"honcho": {"url": "…/v3", "workspace": "…", "peer": "…"}}`). The query is search only, with no language-model cost.

## Tests

```sh
python3 -m unittest discover -s tests
```

They run against a temporary data folder, with no network and no model. Whatever depends on the model (the dream) and on what the memory really returns is measured by the ruler, every night, on real data.

## Known limits

- Prompts, field names and most documentation are in Portuguese.
- The dream only reads Claude Code conversations; anything said elsewhere is neither learned nor graded.
- The ruler grades by text pattern: it measures whether the fact came back, not whether the final answer was good.
- Access strength needs a few weeks of grades before it makes a visible difference.

## License

MIT. See [LICENSE](LICENSE).
