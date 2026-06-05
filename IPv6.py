

from flask import Flask, jsonify, request, render_template

app = Flask(__name__)

# ─────────────────────────────────────────────
#  CONFIGURAÇÕES
# ─────────────────────────────────────────────

LOCALIDADES = [
    {"nome": "São Paulo",      "sigla": "SP",  "offset": 0},
    {"nome": "Rio de Janeiro", "sigla": "RJ",  "offset": 1},
    {"nome": "Curitiba",       "sigla": "CWB", "offset": 2},
    {"nome": "Recife",         "sigla": "REC", "offset": 3},
    {"nome": "Porto Alegre",   "sigla": "POA", "offset": 4},
]

TIPOS_REDE = [
    {"nome": "Residencial",       "codigo": "res",  "offset": 0},
    {"nome": "Corporativa",       "codigo": "corp", "offset": 1},
    {"nome": "Infraestrutura",    "codigo": "infra","offset": 2},
    {"nome": "Serviços Internos", "codigo": "svc",  "offset": 3},
    {"nome": "Anycast",           "codigo": "any",  "offset": 4},
]

# ─────────────────────────────────────────────
#  MANIPULAÇÃO IPv6
# ─────────────────────────────────────────────

def ipv6_para_inteiro(endereco: str) -> int:
    endereco = endereco.strip()
    if "::" in endereco:
        if endereco.count("::") > 1:
            raise ValueError(f"Mais de um '::' em: '{endereco}'")
        partes = endereco.split("::")
        esquerda = partes[0].split(":") if partes[0] else []
        direita  = partes[1].split(":") if partes[1] else []
        faltando = 8 - len(esquerda) - len(direita)
        if faltando < 0:
            raise ValueError(f"Grupos demais no endereço: '{endereco}'")
        grupos = esquerda + (["0"] * faltando) + direita
    else:
        grupos = endereco.split(":")

    if len(grupos) != 8:
        raise ValueError(f"IPv6 inválido: '{endereco}' ({len(grupos)} grupos, esperado 8)")

    resultado = 0
    for g in grupos:
        if not g:
            raise ValueError(f"Grupo vazio em: '{endereco}'")
        try:
            valor = int(g, 16)
        except ValueError:
            raise ValueError(f"Caractere inválido no grupo: '{g}'")
        if valor < 0 or valor > 0xFFFF:
            raise ValueError(f"Grupo fora do intervalo: '{g}'")
        resultado = (resultado << 16) | valor

    return resultado


def inteiro_para_ipv6(numero: int) -> str:
    if numero < 0 or numero > (2**128 - 1):
        raise ValueError("Número fora do intervalo IPv6")
    grupos = []
    for _ in range(8):
        grupos.append(f"{numero & 0xFFFF:04x}")
        numero >>= 16
    grupos.reverse()
    return ":".join(grupos)


def abreviar_ipv6(expandido: str) -> str:
    grupos = expandido.split(":")
    grupos = [g.lstrip("0") or "0" for g in grupos]

    melhor_inicio  = -1
    melhor_tamanho = 0
    inicio_atual   = -1
    tamanho_atual  = 0

    for i, g in enumerate(grupos):
        if g == "0":
            if inicio_atual == -1:
                inicio_atual  = i
                tamanho_atual = 1
            else:
                tamanho_atual += 1
            if tamanho_atual > melhor_tamanho:
                melhor_tamanho = tamanho_atual
                melhor_inicio  = inicio_atual
        else:
            inicio_atual  = -1
            tamanho_atual = 0

    if melhor_tamanho > 1:
        antes  = grupos[:melhor_inicio]
        depois = grupos[melhor_inicio + melhor_tamanho:]
        return ":".join(antes) + "::" + ":".join(depois)

    return ":".join(grupos)


def calcular_mascara(prefixo: int) -> int:
    if prefixo < 0 or prefixo > 128:
        raise ValueError(f"Prefixo inválido: {prefixo}")
    if prefixo == 0:
        return 0
    return ((1 << prefixo) - 1) << (128 - prefixo)


def endereco_de_rede(ip_int: int, prefixo: int) -> int:
    return ip_int & calcular_mascara(prefixo)


def prefixo_para_string(ip_int: int, prefixo: int) -> str:
    rede_int  = endereco_de_rede(ip_int, prefixo)
    expandido = inteiro_para_ipv6(rede_int)
    abreviado = abreviar_ipv6(expandido)
    return f"{abreviado}/{prefixo}"


# ─────────────────────────────────────────────
#  VALIDAÇÃO
# ─────────────────────────────────────────────

def validar_ipv6(endereco: str):
    if not endereco:
        return False, "Endereço vazio."
    permitidos = set("0123456789abcdefABCDEF:")
    invalidos = [c for c in endereco if c not in permitidos]
    if invalidos:
        return False, f"Caracteres inválidos: {''.join(set(invalidos))}"
    if endereco.count("::") > 1:
        return False, "Mais de um '::' encontrado."
    try:
        ipv6_para_inteiro(endereco)
        return True, ""
    except ValueError as e:
        return False, str(e)


def validar_bloco_ipv6(bloco: str):
    if "/" not in bloco:
        return False, "Use 'endereço/prefixo'.", "", 0
    partes = bloco.split("/")
    if len(partes) != 2:
        return False, "Formato inválido.", "", 0
    endereco = partes[0]
    try:
        prefixo = int(partes[1])
    except ValueError:
        return False, "Prefixo não é um inteiro.", "", 0
    if prefixo < 0 or prefixo > 128:
        return False, f"Prefixo {prefixo} fora do intervalo (0–128).", "", 0
    valido, motivo = validar_ipv6(endereco)
    if not valido:
        return False, motivo, "", 0
    return True, "", endereco, prefixo


# ─────────────────────────────────────────────
#  ALGORITMOS DE ALOCAÇÃO
# ─────────────────────────────────────────────

def alocar_leftmost(base_int, base_pfx, alvo_pfx, quantidade):
    if alvo_pfx < base_pfx:
        raise ValueError("Prefixo alvo deve ser >= prefixo base.")
    rede  = endereco_de_rede(base_int, base_pfx)
    passo = 1 << (128 - alvo_pfx)
    redes = []
    for _ in range(quantidade):
        redes.append((rede, alvo_pfx))
        rede += passo
    return redes


def alocar_rightmost(base_int, base_pfx, alvo_pfx, quantidade):
    if alvo_pfx < base_pfx:
        raise ValueError("Prefixo alvo deve ser >= prefixo base.")
    bloco_sz = 1 << (128 - base_pfx)
    sub_sz   = 1 << (128 - alvo_pfx)
    base     = endereco_de_rede(base_int, base_pfx)
    fim      = base + bloco_sz
    redes    = []
    cur      = fim - sub_sz
    for _ in range(quantidade):
        redes.append((cur, alvo_pfx))
        cur -= sub_sz
    redes.reverse()
    return redes


# ─────────────────────────────────────────────
#  PLANEJAMENTO HIERÁRQUICO
# ─────────────────────────────────────────────

def gerar_plano(bloco_principal: str) -> dict:
    valido, motivo, endereco, prefixo = validar_bloco_ipv6(bloco_principal)
    if not valido:
        raise ValueError(motivo)
    if prefixo != 32:
        raise ValueError("O planejador hierárquico requer um bloco /32.")

    base     = endereco_de_rede(ipv6_para_inteiro(endereco), 32)
    p48      = 1 << (128 - 48)
    p56      = 1 << (128 - 56)
    p64      = 1 << (128 - 64)
    plano    = {"bloco_principal": prefixo_para_string(base, 32), "localidades": []}

    for loc in LOCALIDADES:
        loc_int = base + loc["offset"] * p48
        redes   = []
        for tipo in TIPOS_REDE:
            tipo_int = loc_int + tipo["offset"] * p56
            exemplos = [prefixo_para_string(tipo_int + k * p64, 64) for k in range(4)]
            anycast  = prefixo_para_string(tipo_int + 255 * p64, 64)
            redes.append({
                "tipo":    tipo["nome"],
                "codigo":  tipo["codigo"],
                "bloco56": prefixo_para_string(tipo_int, 56),
                "exemplos_64":       exemplos,
                "anycast_reservado": anycast,
            })
        plano["localidades"].append({
            "nome":    loc["nome"],
            "sigla":   loc["sigla"],
            "bloco48": prefixo_para_string(loc_int, 48),
            "redes":   redes,
        })
    return plano


# ─────────────────────────────────────────────
#  ROTAS DA API
# ─────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/validar", methods=["POST"])
def api_validar():
    data    = request.json
    entrada = (data.get("endereco") or "").strip()

    if "/" in entrada:
        valido, motivo, endereco, prefixo = validar_bloco_ipv6(entrada)
        if not valido:
            return jsonify({"ok": False, "erro": motivo})
        ip_int    = ipv6_para_inteiro(endereco)
        rede_int  = endereco_de_rede(ip_int, prefixo)
        expandido = inteiro_para_ipv6(rede_int)
        abreviado = abreviar_ipv6(expandido)
        bloco_sz  = 1 << (128 - prefixo)
        subredes  = (1 << (64 - prefixo)) if prefixo <= 64 else 0
        return jsonify({
            "ok": True, "tipo": "bloco",
            "rede":      f"{abreviado}/{prefixo}",
            "expandido": f"{expandido}/{prefixo}",
            "tamanho":   f"2^{128 - prefixo} = {bloco_sz:,} endereços",
            "subredes64": f"{subredes:,}" if subredes else "—",
        })
    else:
        valido, motivo = validar_ipv6(entrada)
        if not valido:
            return jsonify({"ok": False, "erro": motivo})
        ip_int    = ipv6_para_inteiro(entrada)
        expandido = inteiro_para_ipv6(ip_int)
        abreviado = abreviar_ipv6(expandido)
        return jsonify({
            "ok": True, "tipo": "endereco",
            "expandido": expandido,
            "abreviado": abreviado,
        })


@app.route("/api/hierarquia", methods=["POST"])
def api_hierarquia():
    data  = request.json
    bloco = (data.get("bloco") or "2804:1f4a::/32").strip()
    try:
        plano = gerar_plano(bloco)
        return jsonify({"ok": True, "plano": plano})
    except ValueError as e:
        return jsonify({"ok": False, "erro": str(e)})


@app.route("/api/subdividir", methods=["POST"])
def api_subdividir():
    data      = request.json
    bloco     = (data.get("bloco") or "").strip()
    novo_pfx  = data.get("novo_prefixo")
    max_ex    = min(int(data.get("max_exibir", 32)), 256)

    valido, motivo, endereco, prefixo = validar_bloco_ipv6(bloco)
    if not valido:
        return jsonify({"ok": False, "erro": motivo})

    try:
        novo_pfx = int(novo_pfx)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "erro": "Prefixo alvo inválido."})

    if novo_pfx < prefixo or novo_pfx > 128:
        return jsonify({"ok": False, "erro": f"Prefixo deve estar entre /{prefixo} e /128."})

    total    = 1 << (novo_pfx - prefixo)
    exibir   = min(total, max_ex)
    base     = endereco_de_rede(ipv6_para_inteiro(endereco), prefixo)
    passo    = 1 << (128 - novo_pfx)
    subredes = [prefixo_para_string(base + i * passo, novo_pfx) for i in range(exibir)]

    return jsonify({
        "ok": True,
        "bloco_original": prefixo_para_string(base, prefixo),
        "total":   total,
        "exibindo": exibir,
        "subredes": subredes,
    })


@app.route("/api/alocar", methods=["POST"])
def api_alocar():
    data      = request.json
    bloco     = (data.get("bloco") or "").strip()
    alvo_pfx  = data.get("prefixo_alvo")
    quantidade = min(int(data.get("quantidade", 5)), 256)
    algoritmo = data.get("algoritmo", "left")

    valido, motivo, endereco, prefixo = validar_bloco_ipv6(bloco)
    if not valido:
        return jsonify({"ok": False, "erro": motivo})

    try:
        alvo_pfx = int(alvo_pfx)
        base_int = ipv6_para_inteiro(endereco)
        if algoritmo == "left":
            redes = alocar_leftmost(base_int, prefixo, alvo_pfx, quantidade)
        else:
            redes = alocar_rightmost(base_int, prefixo, alvo_pfx, quantidade)
        resultado = [prefixo_para_string(ip, pfx) for ip, pfx in redes]
        return jsonify({"ok": True, "redes": resultado, "algoritmo": algoritmo})
    except (ValueError, TypeError) as e:
        return jsonify({"ok": False, "erro": str(e)})


@app.route("/api/clientes", methods=["POST"])
def api_clientes():
    data  = request.json
    bloco = (data.get("bloco") or "2804:1f4a::/32").strip()
    qty   = min(int(data.get("quantidade", 5)), 50)
    try:
        plano     = gerar_plano(bloco)
        resultado = []
        for loc in plano["localidades"]:
            rede_res = next(r for r in loc["redes"] if r["codigo"] == "res")
            v = validar_bloco_ipv6(rede_res["bloco56"])
            if not v[0]:
                continue
            base  = endereco_de_rede(ipv6_para_inteiro(v[2]), v[3])
            redes = alocar_leftmost(base, v[3], 64, qty)
            resultado.append({
                "localidade": loc["nome"],
                "sigla":      loc["sigla"],
                "bloco_res":  rede_res["bloco56"],
                "clientes":   [prefixo_para_string(ip, pfx) for ip, pfx in redes],
            })
        return jsonify({"ok": True, "localidades": resultado})
    except ValueError as e:
        return jsonify({"ok": False, "erro": str(e)})


@app.route("/api/anycast", methods=["POST"])
def api_anycast():
    data  = request.json
    bloco = (data.get("bloco") or "2804:1f4a::/32").strip()
    try:
        plano     = gerar_plano(bloco)
        resultado = []
        for loc in plano["localidades"]:
            any_rede = next(r for r in loc["redes"] if r["codigo"] == "any")
            resultado.append({
                "localidade": loc["nome"],
                "sigla":      loc["sigla"],
                "bloco56":    any_rede["bloco56"],
                "anycast":    any_rede["anycast_reservado"],
            })
        return jsonify({"ok": True, "anycast": resultado})
    except ValueError as e:
        return jsonify({"ok": False, "erro": str(e)})


# ─────────────────────────────────────────────
#  INICIALIZAÇÃO
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("\n  IPv6 Manager — Backend Flask")
    print("  Acesse: http://localhost:5000\n")
    app.run(debug=True, port=5000)
