# Operações

Toda mudança na memória é uma operação JSON. O sonho devolve operações; à mão, uma por linha no `mem.py anotar`:

```sh
echo '{"op":"campo","id":"servidor-arquivos","campo":"versao","v":"25.10","como":"conferido no servidor"}' | python3 mem.py anotar
```

Todas passam pelas mesmas travas (nada que pareça senha ou documento pessoal entra) e são anotadas no diário do dia.
`id` é sempre o da ficha, em minúsculas com hífen.

| op | pra quê | campos |
|---|---|---|
| `novo` | criar uma ficha | `tipo` (um esqueleto), `nome`, `resumo`, `chamado` (palavras que puxam), `ligacoes` |
| `campo` | pôr um fato | `campo`, `v`, `visto` (AAAA-MM-DD), `como` (de onde se sabe). Campo que já tem valor só troca com `"troca":"corrige"`; o antigo vai pra história. Campo fora do esqueleto vira "só deste" |
| `remover` | tirar um fato superado | `campo`, `motivo` (o valor vai pra história) |
| `jeito_certo` | como fazer, afirmativo | `texto` |
| `historia` | anotar na memória profunda | `data`, `texto` |
| `caso` | problema resolvido | `resumo`, `chamado` (o sintoma, nas palavras de quem reclama), `sintoma`, `causa`, `jeito_certo`, `como_conferir`, `quando`, `itens` (fichas envolvidas) |
| `mudanca` | o que o assistente alterou num sistema | `quando`, `o_que`, `por_que`, `desfazer`, `quem_autorizou`, `verificado`, `itens` |
| `ligacao` | ligar duas fichas | `para`, `tipo` ("usado por", "ligado em"…). Escrita de um lado só; aparece nos dois |
| `duvida` | o que não dá pra decidir | `texto`. Fica na ficha e aparece junto dela até ser resolvida |
| `duvida_resolvida` | fechar uma dúvida | `duvida` (começo do texto, tem que casar com uma só), `resposta` (vai pra história) |
| `credito` | o que aconteceu depois que a ficha foi mandada | `nota`: `ajudou`, `a_toa` ou `errou`; `porque`; com `errou`, `fato` (vira dúvida na ficha) |
| `licao` | regra geral tirada de casos | `id` começando com `licao-`, `regra`, `quando_vale`, `quando_nao_vale`, `chamado`, `casos` (2 ou mais que existam). Lição que já existe só ganha o caso novo no apoio |
| `chamado` | a ficha devia ter vindo com essa palavra | `frase` |
| `nao_e_quando` | a ficha veio à toa por causa dessa expressão | `frase` |

## Valor de um campo

`{"v": valor, "visto": "AAAA-MM-DD", "como": "de onde eu sei"}`. `"?"` = ainda não sei. `"-"` = não se aplica.
