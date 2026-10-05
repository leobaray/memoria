"""Coletor de exemplo: mede os serviços do systemd e põe o estado na ficha de cada um.
Copie pra <dados>/coletores/ e ajuste o mapa. Roda com `python3 coleta.py --seco` (mostra sem gravar)."""
import subprocess

# id da ficha -> unidade do systemd
SERVICOS = {
    "site": "nginx",
    "banco": "postgresql",
}
COMO = "coleta do systemd"


def coletar(c):
    for iid, unidade in SERVICOS.items():
        if iid not in c.todos:
            c.avisos.append(f"{iid}: está no coletor e não tem ficha")
            continue
        saida = subprocess.run(["systemctl", "show", unidade, "-p", "ActiveState", "-p", "ActiveEnterTimestamp"],
                               capture_output=True, text=True, timeout=30).stdout
        props = dict(l.split("=", 1) for l in saida.splitlines() if "=" in l)
        # fato fixo: só entra onde a ficha ainda diz "?"
        c.preencher(iid, "como_reiniciar", f"sudo systemctl restart {unidade}", c.hoje, COMO)
        # estado do momento: só sobrescreve, não vai pro diário nem pra história
        c.medir(iid, "estado na última coleta", f"{props.get('ActiveState')} desde {props.get('ActiveEnterTimestamp') or '?'}",
                c.agora.strftime("%Y-%m-%d %H:%M"), COMO, volatil=True)
