import hashlib
import math
import os
import re
import secrets
import sqlite3
from datetime import date, datetime, timedelta, timezone
from io import BytesIO

from flask import (Flask, Response, abort, g, redirect, render_template, request,
                   send_from_directory, session, url_for)
from flask_wtf.csrf import CSRFError, CSRFProtect
from markupsafe import escape
from PIL import Image, ImageOps
from werkzeug.security import check_password_hash, generate_password_hash

# O banco fica ao lado deste arquivo, de onde quer que o sistema seja ligado
# (na hospedagem online a pasta de trabalho é outra). OFICINA_DB troca o caminho nos testes.
DATABASE = os.environ.get("OFICINA_DB") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "oficina.db"
)

# As fotos ficam numa pasta ao lado do sistema, FORA da pasta pública (static): só quem
# entrou consegue vê-las, pela rota /fotos/<n>. OFICINA_FOTOS troca a pasta nos testes.
PASTA_FOTOS = os.environ.get("OFICINA_FOTOS") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fotos"
)
TIPOS_SERVICO = ("LATARIA", "PINTURA", "MECÂNICA", "ELÉTRICA", "SUSPENSÃO", "FREIOS",
                 "POLIMENTO E ESTÉTICA", "OUTRO")
MAX_PROBLEMA = 500                   # letras da descrição de um problema
MAX_VALOR_CENTAVOS = 100_000_000     # limite de sanidade: R$ 1.000.000,00 por serviço
DECISOES_APROVACAO = ("APROVADO", "RECUSADO")                  # história 6
FORMAS_APROVACAO = ("PESSOALMENTE", "TELEFONE", "WHATSAPP")    # como o cliente respondeu
NOMES_FORMAS_APROVACAO = {"PESSOALMENTE": "Pessoalmente", "TELEFONE": "Telefone", "WHATSAPP": "WhatsApp"}
MAX_OBS_APROVACAO = 300                                        # letras da observação
MAX_DIAS_PRAZO = 365                                           # história 7: prazo de até 1 ano à frente
MAX_MOTIVO_PRAZO = 300                                         # letras do motivo de mudar o prazo
# Horário de Brasília (o Brasil não tem mais horário de verão). O servidor trabalha em UTC,
# 3 horas à frente, e por isso o "hoje" do prazo é calculado com este fuso.
FUSO_BRASIL = timezone(timedelta(hours=-3))
UNIDADES_GARANTIA = ("DIAS", "MESES")                          # história 8
# Limite máximo de garantia (em meses) de cada tipo de serviço. São valores de partida: o dono
# ajusta cada um na tela "Garantia" (o ajuste fica no banco e vale no lugar destes).
LIMITES_PADRAO_MESES = {"LATARIA": 12, "PINTURA": 24, "MECÂNICA": 6, "ELÉTRICA": 6, "SUSPENSÃO": 12,
                        "FREIOS": 6, "POLIMENTO E ESTÉTICA": 3, "OUTRO": 12}
MAX_LIMITE_MESES = 120                                         # o dono pode ajustar cada limite de 1 a 120 meses
MAX_MOTIVO_DESFAZER = 300                                      # letras do motivo de desfazer uma entrega
MAX_CONDICOES = 1500                                           # letras das condições que cancelam a garantia
# Texto sugerido no fechamento da entrega (o dono pode editar antes de fechar).
CONDICOES_PADRAO = (
    "A garantia deixa de valer se:\n"
    "1) o veículo for aberto, consertado ou modificado por outra oficina ou pessoa;\n"
    "2) houver acidente, batida, enchente, mau uso ou falta de manutenção;\n"
    "3) forem usadas peças ou produtos que a oficina não indicou;\n"
    "4) o cliente não apresentar este comprovante.\n"
    "A garantia cobre somente os serviços listados neste comprovante, dentro do prazo indicado."
)
# Depois que o veículo é entregue, estas ações (envios de formulário) ficam bloqueadas.
TRAVADOS_APOS_ENTREGA = {"registrar_servico", "registrar_resolucao", "registrar_valor", "excluir_servico",
                         "registrar_aprovacao", "registrar_prazo", "registrar_garantia", "fechar_entrega"}
MAX_FOTOS = 10                       # fotos por cadastro
MAX_BYTES_FOTO = 8 * 1024 * 1024     # tamanho máximo de cada foto enviada
MAX_PIXELS_FOTO = 40_000_000         # evita imagens "bomba" que travariam o servidor
LADO_FOTO = 1600                     # a foto guardada é reduzida para caber nesse tamanho
LADO_MINIATURA = 320
FORMATOS_DE_FOTO = {"JPEG", "PNG", "WEBP", "GIF"}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 60 * 1024 * 1024     # tamanho máximo de um envio inteiro


# ---------- CHAVE SECRETA (protege o login) ----------
# Vem da variável OFICINA_SECRET (testes) ou do arquivo chave_secreta.txt, criado
# sozinho na primeira vez. Esse arquivo NÃO vai para o GitHub (.gitignore).
def carregar_chave():
    if os.environ.get("OFICINA_SECRET"):
        return os.environ["OFICINA_SECRET"]
    arquivo = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chave_secreta.txt")
    if not os.path.exists(arquivo):
        with open(arquivo, "w") as f:
            f.write(secrets.token_hex(32))
    with open(arquivo) as f:
        return f.read().strip()


app.secret_key = carregar_chave()

# Esta oficina divide o endereço com o sistema de varejo: sem um nome de cookie próprio,
# entrar em um sistema desconectaria o outro.
app.config["SESSION_COOKIE_NAME"] = "oficina_sessao"
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("OFICINA_HTTPS") == "1"   # ligado na hospedagem (https)
app.config["WTF_CSRF_TIME_LIMIT"] = None   # o token só vale enquanto a sessão (12 h) valer
app.permanent_session_lifetime = timedelta(hours=12)
csrf = CSRFProtect(app)

MAX_ERROS_LOGIN = 5          # senhas erradas seguidas...
MINUTOS_BLOQUEIO = 10        # ...bloqueiam o e-mail por tanto tempo
TIPOS = ("DONO", "FUNCIONARIO")
SENHA_FALSA = generate_password_hash("senha-falsa", method="pbkdf2:sha256")   # gasta o mesmo tempo se o e-mail não existe


# ---------- BANCO ----------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DATABASE)
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS veiculos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            responsavel TEXT,
            placa TEXT NOT NULL,
            marca TEXT,
            modelo TEXT,
            cor TEXT,
            ano TEXT,
            quilometragem TEXT,
            documento_deixado INTEGER NOT NULL
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS fotos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            veiculo_id INTEGER NOT NULL,
            arquivo TEXT NOT NULL,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS servicos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            veiculo_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            problema TEXT NOT NULL,
            registrado_por TEXT,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # História 6: cada decisão do cliente fica guardada (nunca é apagada nem sobrescrita);
    # a última é a que vale. "assinatura" identifica o orçamento que o cliente viu.
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS aprovacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            veiculo_id INTEGER NOT NULL,
            decisao TEXT NOT NULL,
            forma TEXT NOT NULL,
            observacao TEXT,
            total_centavos INTEGER NOT NULL,
            assinatura TEXT NOT NULL,
            registrado_por TEXT,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # História 7: cada prazo de entrega definido fica guardado (nunca é apagado nem sobrescrito);
    # o último é o que vale. "motivo" explica por que o prazo foi mudado.
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS prazos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            veiculo_id INTEGER NOT NULL,
            data_prevista TEXT NOT NULL,
            motivo TEXT,
            registrado_por TEXT,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # História 8: o fechamento da entrega (um por veículo) guarda uma "foto" do que foi combinado:
    # os serviços, valores e garantias na hora da entrega. O comprovante sai daqui, e por isso
    # nunca muda, mesmo que o cadastro seja mexido depois.
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS entregas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            veiculo_id INTEGER NOT NULL UNIQUE,
            data_entrega TEXT NOT NULL,
            condicoes TEXT,
            total_centavos INTEGER NOT NULL,
            entregue_por TEXT,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS entrega_itens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entrega_id INTEGER NOT NULL,
            servico_id INTEGER,
            tipo TEXT NOT NULL,
            problema TEXT NOT NULL,
            como_resolver TEXT,
            valor_centavos INTEGER NOT NULL,
            garantia_valor INTEGER NOT NULL,
            garantia_unidade TEXT NOT NULL,
            garantia_ate TEXT
        )
        """
    )
    # Limites de garantia ajustados pelo dono (o que não está aqui usa LIMITES_PADRAO_MESES)
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS limites_garantia (
            tipo TEXT PRIMARY KEY,
            meses INTEGER NOT NULL
        )
        """
    )
    # Entregas desfeitas: quando o dono desfaz uma entrega, a cópia dela vai para cá (com quem desfez,
    # quando e por quê) e some de "entregas", o que destrava o cadastro do veículo. Nada se perde.
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS entregas_desfeitas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            veiculo_id INTEGER NOT NULL,
            data_entrega TEXT NOT NULL,
            condicoes TEXT,
            total_centavos INTEGER NOT NULL,
            entregue_por TEXT,
            entregue_em TEXT,
            motivo TEXT NOT NULL,
            desfeita_por TEXT,
            desfeita_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS entrega_itens_desfeitos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entrega_desfeita_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            problema TEXT NOT NULL,
            como_resolver TEXT,
            valor_centavos INTEGER NOT NULL,
            garantia_valor INTEGER NOT NULL,
            garantia_unidade TEXT NOT NULL,
            garantia_ate TEXT
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            senha_hash TEXT NOT NULL,
            tipo TEXT NOT NULL,
            ativo INTEGER NOT NULL DEFAULT 1,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS tentativas_login (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            quando TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # Bancos criados antes da história 4 ainda não têm a coluna "como_resolver"
    colunas = [c[1] for c in db.execute("PRAGMA table_info(servicos)")]
    if "como_resolver" not in colunas:
        db.execute("ALTER TABLE servicos ADD COLUMN como_resolver TEXT")
    if "resolvido_por" not in colunas:
        db.execute("ALTER TABLE servicos ADD COLUMN resolvido_por TEXT")
    # Banco criado antes da história 5 ainda não tem a coluna do valor (em centavos)
    if "valor_centavos" not in colunas:
        db.execute("ALTER TABLE servicos ADD COLUMN valor_centavos INTEGER")
    # Banco criado antes da história 8 ainda não tem o tempo de garantia de cada serviço
    if "garantia_valor" not in colunas:
        db.execute("ALTER TABLE servicos ADD COLUMN garantia_valor INTEGER")
    if "garantia_unidade" not in colunas:
        db.execute("ALTER TABLE servicos ADD COLUMN garantia_unidade TEXT")
    db.commit()
    db.close()
    os.makedirs(PASTA_FOTOS, exist_ok=True)


# Cria as tabelas ao carregar o sistema (também na hospedagem, que não roda o bloco do final)
init_db()


# ---------- LOGIN: quem pode entrar e onde ----------

@app.before_request
def exigir_login():
    """Roda antes de toda página: só deixa passar quem entrou com e-mail e senha."""
    g.usuario = None
    if request.endpoint in (None, "static"):
        return None

    db = get_db()
    if db.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 0:
        # Sistema novo, sem nenhum usuário: só a tela de criar o dono
        if request.endpoint == "primeiro_acesso":
            return None
        return redirect(url_for("primeiro_acesso"))

    if request.endpoint in ("login", "primeiro_acesso"):
        return None

    usuario = None
    if session.get("usuario_id"):
        usuario = db.execute(
            "SELECT id, nome, email, tipo FROM usuarios WHERE id = ? AND ativo = 1",
            (session["usuario_id"],),
        ).fetchone()
    if not usuario:
        session.pop("usuario_id", None)
        return redirect(url_for("login"))
    g.usuario = usuario
    return None


@app.before_request
def travar_veiculo_entregue():
    """História 8: depois que o veículo é entregue, o cadastro dele não muda mais
    (serviços, valores, aprovação, prazo e garantia). O comprovante depende disso."""
    if request.method != "POST" or request.endpoint not in TRAVADOS_APOS_ENTREGA or g.get("usuario") is None:
        return None
    veiculo_id = (request.view_args or {}).get("id")
    if veiculo_id and get_db().execute("SELECT 1 FROM entregas WHERE veiculo_id = ?", (veiculo_id,)).fetchone():
        return pagina_veiculo(veiculo_id, ["Este veículo já foi entregue: o cadastro dele não pode mais ser alterado."]), 409
    return None


@app.context_processor
def dados_para_as_telas():
    return {"usuario": g.get("usuario")}


@app.errorhandler(CSRFError)
def token_invalido(erro):
    """Formulário sem o token de segurança (ou com um velho): volta ao login com aviso."""
    return redirect(url_for("login", expirou=1))


def entrar(usuario_id):
    session.clear()
    session.permanent = True
    session["usuario_id"] = usuario_id


def so_dono():
    if not g.usuario or g.usuario["tipo"] != "DONO":
        abort(403)


def conta_bloqueada(db, email):
    """True se este e-mail errou a senha vezes demais há pouco tempo."""
    erros = db.execute(
        "SELECT COUNT(*) FROM tentativas_login WHERE email = ? AND quando > datetime('now', ?)",
        (email, f"-{MINUTOS_BLOQUEIO} minutes"),
    ).fetchone()[0]
    return erros >= MAX_ERROS_LOGIN


def registrar_erro_de_login(db, email):
    db.execute("DELETE FROM tentativas_login WHERE quando < datetime('now', '-1 day')")
    db.execute("INSERT INTO tentativas_login (email) VALUES (?)", (email,))
    db.commit()


def validar_usuario(db, dados):
    """Confere os dados de um usuário novo. Devolve (erro, None) ou (None, dados_limpos)."""
    nome = " ".join(str(dados.get("nome", "")).split()).upper()
    email = str(dados.get("email", "")).strip().lower()
    senha = str(dados.get("senha", ""))
    tipo = str(dados.get("tipo", "FUNCIONARIO")).strip().upper()

    if sum(1 for letra in nome if letra.isalpha()) < 2 or len(nome) > 100:
        return "Digite o nome do usuário.", None
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) or len(email) > 120:
        return "Digite um e-mail válido.", None
    if tipo not in TIPOS:
        return "Escolha o tipo: Dono ou Funcionário.", None
    if len(senha) < 8:
        return "A senha precisa ter pelo menos 8 caracteres.", None
    if db.execute("SELECT 1 FROM usuarios WHERE email = ?", (email,)).fetchone():
        return "Já existe um usuário com este e-mail.", None
    return None, {"nome": nome, "email": email, "tipo": tipo,
                  "senha_hash": generate_password_hash(senha, method="pbkdf2:sha256")}


@app.route("/login", methods=["GET", "POST"])
def login():
    erro = "Sua sessão expirou. Tente entrar de novo." if request.args.get("expirou") else None
    email = ""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()[:120]
        senha = request.form.get("senha", "")
        db = get_db()
        if conta_bloqueada(db, email):
            erro = f"Muitas tentativas erradas. Aguarde {MINUTOS_BLOQUEIO} minutos e tente de novo."
        else:
            usuario = db.execute("SELECT * FROM usuarios WHERE email = ?", (email,)).fetchone()
            senha_certa = check_password_hash(usuario["senha_hash"] if usuario else SENHA_FALSA, senha)
            if not usuario or not senha_certa:
                registrar_erro_de_login(db, email)
                erro = "E-mail ou senha errados."
            elif not usuario["ativo"]:
                erro = "Este usuário está bloqueado. Fale com o dono da oficina."
            else:
                db.execute("DELETE FROM tentativas_login WHERE email = ?", (email,))
                db.commit()
                entrar(usuario["id"])
                return redirect(url_for("index"))
    return render_template("login.html", modo="login", erro=erro, email=email)


@app.route("/primeiro-acesso", methods=["GET", "POST"])
def primeiro_acesso():
    """Só funciona enquanto não existe nenhum usuário: cria o DONO da oficina.
    Na hospedagem, pede também o código de instalação (OFICINA_CODIGO_INICIAL),
    para ninguém tomar o sistema antes do dono."""
    db = get_db()
    if db.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] > 0:
        return redirect(url_for("login"))

    codigo_certo = os.environ.get("OFICINA_CODIGO_INICIAL", "")
    erro = None
    dados = {"nome": "", "email": ""}
    if request.method == "POST":
        dados = {"nome": request.form.get("nome", ""), "email": request.form.get("email", ""),
                 "senha": request.form.get("senha", ""), "tipo": "DONO"}
        if codigo_certo and not secrets.compare_digest(
                request.form.get("codigo", "").strip().encode(), codigo_certo.encode()):
            erro = "Código de instalação errado."
        elif request.form.get("senha", "") != request.form.get("senha2", ""):
            erro = "As duas senhas não são iguais."
        else:
            erro, limpos = validar_usuario(db, dados)
            if not erro:
                # O "WHERE NOT EXISTS" garante um único dono mesmo com dois envios ao mesmo tempo
                criado = db.execute(
                    "INSERT INTO usuarios (nome, email, senha_hash, tipo) "
                    "SELECT ?, ?, ?, ? WHERE NOT EXISTS (SELECT 1 FROM usuarios)",
                    (limpos["nome"], limpos["email"], limpos["senha_hash"], limpos["tipo"]),
                )
                db.commit()
                if criado.rowcount == 0:
                    return redirect(url_for("login"))
                novo = db.execute("SELECT id FROM usuarios WHERE email = ?", (limpos["email"],)).fetchone()
                entrar(novo["id"])
                return redirect(url_for("index"))
    return render_template("login.html", modo="primeiro", erro=erro, nome=dados.get("nome", ""),
                           email=dados.get("email", ""), pede_codigo=bool(codigo_certo))


@app.route("/sair", methods=["POST"])
def sair():
    session.clear()
    return redirect(url_for("login"))


# ---------- USUÁRIOS (só o dono) ----------

@app.route("/usuarios", methods=["GET", "POST"])
def usuarios():
    so_dono()
    db = get_db()
    erro = None
    dados = {}
    if request.method == "POST":
        dados = {k: request.form.get(k, "") for k in ("nome", "email", "senha", "tipo")}
        erro, limpos = validar_usuario(db, dados)
        if not erro:
            db.execute("INSERT INTO usuarios (nome, email, senha_hash, tipo) VALUES (?, ?, ?, ?)",
                       (limpos["nome"], limpos["email"], limpos["senha_hash"], limpos["tipo"]))
            db.commit()
            return redirect(url_for("usuarios"))
    lista = db.execute("SELECT id, nome, email, tipo, ativo FROM usuarios ORDER BY nome").fetchall()
    return render_template("usuarios.html", lista=lista, erro=erro,
                           dados={"nome": dados.get("nome", ""), "email": dados.get("email", ""),
                                  "tipo": dados.get("tipo", "FUNCIONARIO")})


@app.route("/usuarios/<int:id>/alternar", methods=["POST"])
def alternar_usuario(id):
    """Bloqueia ou desbloqueia o acesso de alguém."""
    so_dono()
    if id == g.usuario["id"]:
        abort(400)
    db = get_db()
    db.execute("UPDATE usuarios SET ativo = 1 - ativo WHERE id = ?", (id,))
    db.commit()
    return redirect(url_for("usuarios"))


# ---------- VEÍCULOS ----------

def assinatura_orcamento(servicos):
    """Impressão digital do orçamento: muda se um serviço entrar, sair ou mudar de valor.
    Serve para saber se a aprovação do cliente ainda vale para o orçamento de hoje."""
    texto = "|".join(f"{s['id']}:{s['valor_centavos']}" for s in sorted(servicos, key=lambda s: s["id"]))
    return hashlib.sha256(texto.encode()).hexdigest()[:16]


def situacao_aprovacao(servicos, ultima):
    """Em que pé está a aprovação do cliente. Devolve (chave, texto).
    'ultima' é a decisão mais recente registrada (ou None)."""
    if not servicos:
        return "SEM_ORCAMENTO", "Sem orçamento"
    if any(s["valor_centavos"] is None for s in servicos):
        return "INCOMPLETO", "Orçamento incompleto"
    if not ultima:
        return "AGUARDANDO", "Aguardando o cliente"
    if ultima["assinatura"] != assinatura_orcamento(servicos):
        return "DESATUALIZADA", "Orçamento mudou: precisa de nova decisão"
    if ultima["decisao"] == "APROVADO":
        return "APROVADO", "Aprovado pelo cliente"
    return "RECUSADO", "Recusado pelo cliente"


def situacoes_dos_veiculos(db, veiculos):
    """Situação da aprovação de cada veículo da lista, com poucas consultas ao banco."""
    servicos = {}
    for s in db.execute("SELECT id, veiculo_id, valor_centavos FROM servicos ORDER BY id"):
        servicos.setdefault(s["veiculo_id"], []).append(s)
    ultimas = {}
    for a in db.execute("SELECT veiculo_id, decisao, assinatura FROM aprovacoes ORDER BY id"):
        ultimas[a["veiculo_id"]] = a          # a última linha de cada veículo é a que vale
    return {v["id"]: situacao_aprovacao(servicos.get(v["id"], []), ultimas.get(v["id"])) for v in veiculos}


def hoje_brasil(agora_utc=None):
    """A data de hoje no Brasil. ('agora_utc' só existe para os testes.)"""
    agora_utc = agora_utc or datetime.now(timezone.utc)
    return agora_utc.astimezone(FUSO_BRASIL).date()


def formatar_data(texto_iso):
    """'2026-10-15' vira '15/10/2026'."""
    return datetime.strptime(texto_iso, "%Y-%m-%d").strftime("%d/%m/%Y")


def situacao_prazo(data_prevista, hoje):
    """Situação do prazo de entrega. 'data_prevista' é um texto AAAA-MM-DD (ou None).
    Devolve (chave, texto)."""
    if not data_prevista:
        return "SEM_PRAZO", "Sem prazo definido"
    dias = (datetime.strptime(data_prevista, "%Y-%m-%d").date() - hoje).days
    if dias < 0:
        return "ATRASADO", f"Atrasado há {-dias} dia{'s' if dias != -1 else ''}"
    if dias == 0:
        return "HOJE", "Entrega hoje"
    if dias == 1:
        return "PROXIMO", "Entrega amanhã"
    return ("PROXIMO" if dias <= 3 else "NO_PRAZO"), f"Faltam {dias} dias"


def prazos_dos_veiculos(db, veiculos):
    """Situação da entrega de cada veículo da lista (prazo ou 'entregue'), com poucas consultas."""
    ultimos = {}
    for p in db.execute("SELECT veiculo_id, data_prevista FROM prazos ORDER BY id"):
        ultimos[p["veiculo_id"]] = p["data_prevista"]       # a última linha de cada veículo é a que vale
    entregues = {e["veiculo_id"]: e["data_entrega"] for e in db.execute("SELECT veiculo_id, data_entrega FROM entregas")}
    hoje = hoje_brasil()
    resultado = {}
    for v in veiculos:
        if v["id"] in entregues:
            resultado[v["id"]] = ("ENTREGUE", f"Entregue em {formatar_data(entregues[v['id']])}")
        else:
            resultado[v["id"]] = situacao_prazo(ultimos.get(v["id"]), hoje)
    return resultado


# ---------- GARANTIA E ENTREGA (história 8) ----------

def somar_meses(data, meses):
    """Soma meses de calendário a uma data. Se o dia não existir no mês de destino, usa o último dia
    do mês (ex.: 31/01 + 1 mês = 28/02 ou 29/02)."""
    mes_total = data.month - 1 + meses
    ano, mes = data.year + mes_total // 12, mes_total % 12 + 1
    for dia in (data.day, 30, 29, 28):
        try:
            return date(ano, mes, dia)
        except ValueError:
            continue
    raise ValueError("data inválida")   # nunca acontece: o dia 28 existe em todo mês


def fim_da_garantia(data_entrega, valor, unidade):
    """Data em que a garantia termina, contada a partir da data de entrega.
    Devolve None quando o serviço não tem garantia (tempo 0). A garantia vale ATÉ essa data."""
    if not valor:
        return None
    if unidade == "MESES":
        return somar_meses(data_entrega, valor)
    return data_entrega + timedelta(days=valor)


def texto_garantia(valor, unidade):
    """'Sem garantia', '1 mês', '12 meses', '1 dia' ou '90 dias'."""
    if valor is None:
        return "-"
    if valor == 0:
        return "Sem garantia"
    if unidade == "MESES":
        return f"{valor} {'mês' if valor == 1 else 'meses'}"
    return f"{valor} {'dia' if valor == 1 else 'dias'}"


def limites_de_garantia(db):
    """Limite máximo de garantia (em meses) de cada tipo de serviço: o que o dono ajustou ou o padrão."""
    limites = dict(LIMITES_PADRAO_MESES)
    for linha in db.execute("SELECT tipo, meses FROM limites_garantia"):
        if linha["tipo"] in limites:
            limites[linha["tipo"]] = linha["meses"]
    return limites


def limite_em(unidade, meses):
    """O limite (dado em meses) na unidade pedida. Em dias, arredonda para cima: 12 meses = 365 dias."""
    return meses if unidade == "MESES" else math.ceil(meses * 365 / 12)


def texto_limite(meses):
    """'24 meses (730 dias)'."""
    return f"{meses} {'mês' if meses == 1 else 'meses'} ({limite_em('DIAS', meses)} dias)"


def situacao_garantia(garantia_ate, hoje):
    """Situação da garantia de um serviço entregue. Devolve (chave, texto)."""
    if not garantia_ate:
        return "SEM_GARANTIA", "Sem garantia"
    if datetime.strptime(garantia_ate, "%Y-%m-%d").date() < hoje:
        return "VENCIDA", f"Venceu em {formatar_data(garantia_ate)}"
    return "VIGENTE", f"Vigente até {formatar_data(garantia_ate)}"


def pagina_inicial(erros=None, dados=None):
    """Desenha a tela de cadastro com a lista de veículos e as fotos de cada um."""
    db = get_db()
    veiculos = db.execute("SELECT * FROM veiculos ORDER BY id DESC").fetchall()
    fotos = {}
    for foto in db.execute("SELECT id, veiculo_id FROM fotos ORDER BY id"):
        fotos.setdefault(foto["veiculo_id"], []).append(foto["id"])
    return render_template("index.html", veiculos=veiculos, fotos=fotos, erros=erros or [],
                           dados=dados or {}, max_fotos=MAX_FOTOS,
                           max_mb=MAX_BYTES_FOTO // (1024 * 1024),
                           situacoes=situacoes_dos_veiculos(db, veiculos),
                           prazos=prazos_dos_veiculos(db, veiculos))


@app.route("/")
def index():
    return pagina_inicial()


@app.errorhandler(413)
def envio_grande_demais(erro):
    """O envio inteiro passou do limite. Resposta simples, sem dados do sistema."""
    texto = ("Os arquivos enviados passaram do tamanho permitido. "
             f"Envie até {MAX_FOTOS} fotos de até {MAX_BYTES_FOTO // (1024 * 1024)} MB cada.")
    voltar = escape(url_for("index"))
    return Response(f'<meta charset="UTF-8"><p>{texto}</p><p><a href="{voltar}">Voltar</a></p>',
                    status=413, mimetype="text/html")


# ---------- FOTOS DOS VEÍCULOS ----------

def preparar_foto(arquivo):
    """Confere uma foto enviada e a prepara para guardar.
    Devolve (erro, None) ou (None, (foto_grande, miniatura)), as duas em JPEG.
    - só aceita imagem de verdade (confere o conteúdo, não o nome do arquivo);
    - gira conforme o celular e REMOVE os dados escondidos da foto (como a localização GPS);
    - reduz o tamanho, para o sistema não ficar pesado."""
    nome = (arquivo.filename or "foto")[:60]
    dados = arquivo.read(MAX_BYTES_FOTO + 1)
    if len(dados) > MAX_BYTES_FOTO:
        return f'A foto "{nome}" é grande demais (máximo {MAX_BYTES_FOTO // (1024 * 1024)} MB).', None
    invalida = f'O arquivo "{nome}" não é uma foto válida. Use JPG, PNG, WEBP ou GIF.'
    try:
        imagem = Image.open(BytesIO(dados))
        if imagem.format not in FORMATOS_DE_FOTO:
            return invalida, None
        if imagem.width * imagem.height > MAX_PIXELS_FOTO:
            return f'A foto "{nome}" tem resolução alta demais.', None
        imagem.load()                                   # lê a imagem inteira (pega arquivos cortados)
        imagem = ImageOps.exif_transpose(imagem)        # endireita a foto, como o celular mostrava
        if imagem.mode in ("RGBA", "LA") or (imagem.mode == "P" and "transparency" in imagem.info):
            imagem = imagem.convert("RGBA")
            fundo = Image.new("RGB", imagem.size, "white")
            fundo.paste(imagem, mask=imagem.split()[-1])
            imagem = fundo
        else:
            imagem = imagem.convert("RGB")
        saidas = []
        for lado in (LADO_FOTO, LADO_MINIATURA):
            copia = imagem.copy()
            copia.thumbnail((lado, lado))
            memoria = BytesIO()
            copia.save(memoria, "JPEG", quality=85, optimize=True)   # sem EXIF: nada de GPS
            saidas.append(memoria.getvalue())
    except Exception:    # arquivo estragado, formato estranho, etc.
        return invalida, None
    return None, tuple(saidas)


def guardar_fotos(db, veiculo_id, fotos, criados):
    """Grava os arquivos das fotos e registra no banco.
    Cada arquivo é anotado em 'criados' assim que nasce, para dar para apagar tudo se algo falhar no meio."""
    for grande, miniatura in fotos:
        codigo = secrets.token_hex(16)     # nome sorteado: o nome original nunca vira caminho
        for sufixo, conteudo in (("", grande), ("_m", miniatura)):
            caminho = os.path.join(PASTA_FOTOS, f"{codigo}{sufixo}.jpg")
            criados.append(caminho)
            with open(caminho, "wb") as f:
                f.write(conteudo)
        db.execute("INSERT INTO fotos (veiculo_id, arquivo) VALUES (?, ?)", (veiculo_id, codigo))


def enviar_foto(id, sufixo):
    linha = get_db().execute("SELECT arquivo FROM fotos WHERE id = ?", (id,)).fetchone()
    if not linha:
        abort(404)
    resposta = send_from_directory(PASTA_FOTOS, f"{linha['arquivo']}{sufixo}.jpg", mimetype="image/jpeg")
    resposta.headers["Cache-Control"] = "private, max-age=86400"    # só o navegador de quem entrou guarda
    resposta.headers["X-Content-Type-Options"] = "nosniff"
    return resposta


@app.route("/fotos/<int:id>")
def foto(id):
    return enviar_foto(id, "")


@app.route("/fotos/<int:id>/miniatura")
def foto_miniatura(id):
    return enviar_foto(id, "_m")


@app.route("/veiculos", methods=["POST"])
def cadastrar_veiculo():
    dados = {
        "responsavel": request.form.get("responsavel", "").strip(),
        "placa": request.form.get("placa", "").strip(),
        "marca": request.form.get("marca", "").strip(),
        "modelo": request.form.get("modelo", "").strip(),
        "cor": request.form.get("cor", "").strip(),
        "ano": request.form.get("ano", "").strip(),
        "quilometragem": request.form.get("quilometragem", "").strip(),
    }
    documento_deixado = request.form.get("documento_deixado") == "on"

    erros = []
    if not dados["placa"]:
        erros.append("A placa é obrigatória.")
    if not documento_deixado:
        erros.append(
            "É obrigatório marcar que o documento do carro "
            "(original ou cópia impressa) foi deixado na oficina."
        )

    # Fotos (opcionais): confere todas antes de guardar qualquer coisa
    arquivos = [a for a in request.files.getlist("fotos") if a and a.filename]
    preparadas = []
    if len(arquivos) > MAX_FOTOS:
        erros.append(f"Envie no máximo {MAX_FOTOS} fotos de uma vez.")
    else:
        for arquivo in arquivos:
            erro_foto, pronta = preparar_foto(arquivo)
            if erro_foto:
                erros.append(erro_foto)
            else:
                preparadas.append(pronta)
    if erros and arquivos:
        erros.append("Por segurança do navegador, as fotos precisam ser escolhidas de novo.")

    if erros:
        return pagina_inicial(erros, dados)

    db = get_db()
    criados = []
    try:
        cursor = db.execute(
            """
            INSERT INTO veiculos
                (responsavel, placa, marca, modelo, cor, ano, quilometragem, documento_deixado)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                dados["responsavel"],
                dados["placa"],
                dados["marca"],
                dados["modelo"],
                dados["cor"],
                dados["ano"],
                dados["quilometragem"],
                1,
            ),
        )
        guardar_fotos(db, cursor.lastrowid, preparadas, criados)
        db.commit()
    except Exception:
        db.rollback()
        for caminho in criados:     # não deixa foto "órfã" no disco
            if os.path.exists(caminho):
                os.remove(caminho)
        raise
    return redirect(url_for("index"))


# ---------- PROBLEMAS E TIPOS DE SERVIÇO (por veículo) ----------

def buscar_veiculo(db, id):
    veiculo = db.execute("SELECT * FROM veiculos WHERE id = ?", (id,)).fetchone()
    if not veiculo:
        abort(404)
    return veiculo


def pagina_veiculo(id, erros=None, dados=None):
    db = get_db()
    veiculo = buscar_veiculo(db, id)
    servicos = db.execute("SELECT * FROM servicos WHERE veiculo_id = ? ORDER BY id", (id,)).fetchall()
    fotos = [f["id"] for f in db.execute("SELECT id FROM fotos WHERE veiculo_id = ? ORDER BY id", (id,))]
    total_centavos = sum(s["valor_centavos"] or 0 for s in servicos)
    faltam = sum(1 for s in servicos if s["valor_centavos"] is None)
    orcamento_completo = bool(servicos) and faltam == 0
    aprovacoes = db.execute("SELECT * FROM aprovacoes WHERE veiculo_id = ? ORDER BY id DESC", (id,)).fetchall()
    situacao, situacao_texto = situacao_aprovacao(servicos, aprovacoes[0] if aprovacoes else None)
    prazos = db.execute("SELECT * FROM prazos WHERE veiculo_id = ? ORDER BY id DESC", (id,)).fetchall()
    hoje = hoje_brasil()
    prazo_chave, prazo_texto = situacao_prazo(prazos[0]["data_prevista"] if prazos else None, hoje)
    # História 8: entrega fechada (com o que foi combinado) e garantias ainda não informadas
    entrega = db.execute("SELECT * FROM entregas WHERE veiculo_id = ?", (id,)).fetchone()
    itens = []
    if entrega:
        prazo_chave, prazo_texto = "ENTREGUE", f"Entregue em {formatar_data(entrega['data_entrega'])}"
        itens = [dict(i, situacao=situacao_garantia(i["garantia_ate"], hoje))
                 for i in db.execute("SELECT * FROM entrega_itens WHERE entrega_id = ? ORDER BY id", (entrega["id"],))]
    sem_garantia_informada = sum(1 for s in servicos if s["garantia_valor"] is None)
    desfeitas = db.execute("SELECT * FROM entregas_desfeitas WHERE veiculo_id = ? ORDER BY id DESC", (id,)).fetchall()
    return render_template("veiculo.html", veiculo=veiculo, servicos=servicos, fotos=fotos,
                           desfeitas=desfeitas, max_motivo_desfazer=MAX_MOTIVO_DESFAZER,
                           limites=limites_de_garantia(db), texto_limite=texto_limite,
                           entrega=entrega, itens=itens, sem_garantia_informada=sem_garantia_informada,
                           unidades_garantia=UNIDADES_GARANTIA, texto_garantia=texto_garantia,
                           condicoes_padrao=CONDICOES_PADRAO, max_condicoes=MAX_CONDICOES,
                           prazos=prazos, prazo_chave=prazo_chave, prazo_texto=prazo_texto,
                           aprovado_vigente=(situacao == "APROVADO"), hoje_iso=hoje.isoformat(),
                           maximo_iso=(hoje + timedelta(days=MAX_DIAS_PRAZO)).isoformat(),
                           formatar_data=formatar_data, max_motivo=MAX_MOTIVO_PRAZO,
                           tipos=TIPOS_SERVICO, max_problema=MAX_PROBLEMA,
                           erros=erros or [], dados=dados or {},
                           total_centavos=total_centavos, faltam_valor=faltam,
                           orcamento_completo=orcamento_completo, formatar_dinheiro=formatar_dinheiro,
                           aprovacoes=aprovacoes, situacao=situacao, situacao_texto=situacao_texto,
                           assinatura=assinatura_orcamento(servicos), decisoes=DECISOES_APROVACAO,
                           formas=FORMAS_APROVACAO, nomes_formas=NOMES_FORMAS_APROVACAO,
                           max_obs=MAX_OBS_APROVACAO)


@app.route("/veiculos/<int:id>")
def ver_veiculo(id):
    return pagina_veiculo(id)


@app.route("/veiculos/<int:id>/servicos", methods=["POST"])
def registrar_servico(id):
    db = get_db()
    buscar_veiculo(db, id)
    tipo = request.form.get("tipo", "").strip().upper()
    problema = " ".join(request.form.get("problema", "").split())

    erros = []
    if tipo not in TIPOS_SERVICO:
        erros.append("Escolha o tipo de serviço.")
    if sum(1 for letra in problema if letra.isalpha()) < 3:
        erros.append("Descreva o problema encontrado no veículo.")
    elif len(problema) > MAX_PROBLEMA:
        erros.append(f"A descrição do problema pode ter no máximo {MAX_PROBLEMA} letras.")
    if erros:
        return pagina_veiculo(id, erros, {"tipo": tipo, "problema": problema})

    db.execute("INSERT INTO servicos (veiculo_id, tipo, problema, registrado_por) VALUES (?, ?, ?, ?)",
               (id, tipo, problema, g.usuario["nome"]))
    db.commit()
    return redirect(url_for("ver_veiculo", id=id))


@app.route("/veiculos/<int:id>/servicos/<int:servico_id>/resolucao", methods=["POST"])
def registrar_resolucao(id, servico_id):
    """História 4: anota como o problema será resolvido (dá para editar depois)."""
    db = get_db()
    buscar_veiculo(db, id)
    servico = db.execute("SELECT id FROM servicos WHERE id = ? AND veiculo_id = ?",
                         (servico_id, id)).fetchone()
    if not servico:
        abort(404)
    texto = " ".join(request.form.get("como_resolver", "").split())

    erros = []
    if sum(1 for letra in texto if letra.isalpha()) < 3:
        erros.append("Descreva como o problema será resolvido.")
    elif len(texto) > MAX_PROBLEMA:
        erros.append(f"A descrição de como resolver pode ter no máximo {MAX_PROBLEMA} letras.")
    if erros:
        return pagina_veiculo(id, erros)

    db.execute("UPDATE servicos SET como_resolver = ?, resolvido_por = ? WHERE id = ?",
               (texto, g.usuario["nome"], servico_id))
    db.commit()
    return redirect(url_for("ver_veiculo", id=id))


def interpretar_valor(texto):
    """Lê um valor em reais digitado pelo usuário (ex: "150,00", "150.00" ou "150").
    Devolve os centavos (inteiro) ou None se o texto não for um valor válido (vazio, negativo,
    zero ou com letras)."""
    texto = texto.strip().upper().replace("R$", "").replace(" ", "")
    if not texto:
        return None
    if "," in texto:
        inteiro, _, centavos = texto.rpartition(",")
        inteiro = inteiro.replace(".", "")
    elif "." in texto and len(texto.rsplit(".", 1)[1]) == 2:
        inteiro, _, centavos = texto.rpartition(".")
        inteiro = inteiro.replace(".", "")
    else:
        inteiro, centavos = texto.replace(".", ""), "00"
    if not inteiro.isdigit() or len(centavos) != 2 or not centavos.isdigit():
        return None
    valor = int(inteiro) * 100 + int(centavos)
    if valor <= 0 or valor > MAX_VALOR_CENTAVOS:
        return None
    return valor


def formatar_dinheiro(centavos, com_simbolo=True):
    """Formata centavos como "R$ 1.234,56" (ou só "1.234,56", sem o símbolo)."""
    reais, cents = divmod(centavos, 100)
    texto = f"{reais:,}".replace(",", ".")
    valor = f"{texto},{cents:02d}"
    return f"R$ {valor}" if com_simbolo else valor


@app.route("/veiculos/<int:id>/servicos/<int:servico_id>/valor", methods=["POST"])
def registrar_valor(id, servico_id):
    """História 5: define o valor (em R$) de um serviço, para montar o orçamento.
    Só o dono define ou corrige o valor."""
    so_dono()
    db = get_db()
    buscar_veiculo(db, id)
    servico = db.execute("SELECT id FROM servicos WHERE id = ? AND veiculo_id = ?",
                         (servico_id, id)).fetchone()
    if not servico:
        abort(404)
    centavos = interpretar_valor(request.form.get("valor", ""))

    if centavos is None:
        return pagina_veiculo(id, ["Informe um valor válido para o serviço (exemplo: 150,00)."])

    db.execute("UPDATE servicos SET valor_centavos = ? WHERE id = ?", (centavos, servico_id))
    db.commit()
    return redirect(url_for("ver_veiculo", id=id))


@app.route("/veiculos/<int:id>/aprovacao", methods=["POST"])
def registrar_aprovacao(id):
    """História 6: registra se o cliente aprovou ou recusou o orçamento.
    Dono e funcionário podem registrar (quem atendeu o cliente). Cada decisão fica guardada
    com quem registrou, quando, como o cliente respondeu e o valor total que ele viu."""
    db = get_db()
    buscar_veiculo(db, id)
    servicos = db.execute("SELECT * FROM servicos WHERE veiculo_id = ? ORDER BY id", (id,)).fetchall()
    decisao = request.form.get("decisao", "").strip().upper()
    forma = request.form.get("forma", "").strip().upper()
    observacao = " ".join(request.form.get("observacao", "").split())

    erros = []
    if not servicos or any(s["valor_centavos"] is None for s in servicos):
        erros.append("A decisão do cliente só pode ser registrada com o orçamento completo "
                     "(todos os serviços com valor).")
    elif request.form.get("assinatura", "") != assinatura_orcamento(servicos):
        erros.append("O orçamento mudou enquanto você registrava. Confira os valores e registre de novo.")
    if decisao not in DECISOES_APROVACAO:
        erros.append("Escolha se o cliente aprovou ou recusou o orçamento.")
    if forma not in FORMAS_APROVACAO:
        erros.append("Escolha como o cliente respondeu (pessoalmente, telefone ou WhatsApp).")
    if len(observacao) > MAX_OBS_APROVACAO:
        erros.append(f"A observação pode ter no máximo {MAX_OBS_APROVACAO} letras.")
    if erros:
        return pagina_veiculo(id, erros)

    total = sum(s["valor_centavos"] for s in servicos)
    db.execute("INSERT INTO aprovacoes (veiculo_id, decisao, forma, observacao, total_centavos, "
               "assinatura, registrado_por) VALUES (?, ?, ?, ?, ?, ?, ?)",
               (id, decisao, forma, observacao or None, total, assinatura_orcamento(servicos),
                g.usuario["nome"]))
    db.commit()
    return redirect(url_for("ver_veiculo", id=id))


@app.route("/veiculos/<int:id>/prazo", methods=["POST"])
def registrar_prazo(id):
    """História 7: o dono define (ou muda) o prazo de entrega prometido ao cliente.
    Só vale depois que o cliente aprovou o orçamento. Mudar um prazo já definido exige o motivo.
    Cada prazo fica no histórico, e o último é o que vale."""
    so_dono()
    db = get_db()
    buscar_veiculo(db, id)
    servicos = db.execute("SELECT * FROM servicos WHERE veiculo_id = ? ORDER BY id", (id,)).fetchall()
    ultima_aprovacao = db.execute("SELECT * FROM aprovacoes WHERE veiculo_id = ? ORDER BY id DESC LIMIT 1",
                                  (id,)).fetchone()
    atual = db.execute("SELECT * FROM prazos WHERE veiculo_id = ? ORDER BY id DESC LIMIT 1", (id,)).fetchone()
    texto = request.form.get("data_prevista", "").strip()
    motivo = " ".join(request.form.get("motivo", "").split())
    hoje = hoje_brasil()

    erros = []
    if situacao_aprovacao(servicos, ultima_aprovacao)[0] != "APROVADO":
        erros.append("O prazo de entrega só pode ser definido depois que o cliente aprovar o orçamento.")
    data = None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", texto):
        try:
            data = datetime.strptime(texto, "%Y-%m-%d").date()
        except ValueError:
            data = None
    if data is None:
        erros.append("Escolha a data de entrega.")
    elif data < hoje:
        erros.append("O prazo não pode ser uma data que já passou.")
    elif data > hoje + timedelta(days=MAX_DIAS_PRAZO):
        erros.append(f"O prazo pode ser no máximo daqui a {MAX_DIAS_PRAZO} dias.")
    elif atual and data.isoformat() == atual["data_prevista"]:
        erros.append("Essa já é a data do prazo atual.")
    elif atual and sum(1 for letra in motivo if letra.isalpha()) < 3:
        erros.append("Para mudar o prazo, explique o motivo.")
    if len(motivo) > MAX_MOTIVO_PRAZO:
        erros.append(f"O motivo pode ter no máximo {MAX_MOTIVO_PRAZO} letras.")
    if erros:
        return pagina_veiculo(id, erros)

    db.execute("INSERT INTO prazos (veiculo_id, data_prevista, motivo, registrado_por) VALUES (?, ?, ?, ?)",
               (id, data.isoformat(), motivo or None, g.usuario["nome"]))
    db.commit()
    return redirect(url_for("ver_veiculo", id=id))


@app.route("/veiculos/<int:id>/servicos/<int:servico_id>/garantia", methods=["POST"])
def registrar_garantia(id, servico_id):
    """História 8: o dono informa o tempo de garantia de um serviço, em dias ou meses
    (0 quer dizer 'sem garantia'). Dá para corrigir até a entrega ser fechada."""
    so_dono()
    db = get_db()
    buscar_veiculo(db, id)
    servico = db.execute("SELECT tipo FROM servicos WHERE id = ? AND veiculo_id = ?", (servico_id, id)).fetchone()
    if not servico:
        abort(404)
    unidade = request.form.get("unidade", "").strip().upper()
    texto = request.form.get("valor", "").strip()
    limite_meses = limites_de_garantia(db).get(servico["tipo"], MAX_LIMITE_MESES)

    erro = None
    if unidade not in UNIDADES_GARANTIA:
        erro = "Escolha se o tempo de garantia é em dias ou em meses."
    elif not re.fullmatch(r"\d{1,4}", texto):
        erro = "Informe o tempo de garantia com um número inteiro (use 0 para 'sem garantia')."
    elif int(texto) > limite_em(unidade, limite_meses):
        erro = f"O limite de garantia para {servico['tipo']} é {texto_limite(limite_meses)}."
    if erro:
        return pagina_veiculo(id, [erro])

    db.execute("UPDATE servicos SET garantia_valor = ?, garantia_unidade = ? WHERE id = ?",
               (int(texto), unidade, servico_id))
    db.commit()
    return redirect(url_for("ver_veiculo", id=id))


@app.route("/limites-garantia", methods=["GET", "POST"])
def limites_garantia():
    """O dono ajusta o limite máximo de garantia (em meses) de cada tipo de serviço.
    O limite vale na hora de informar a garantia de um serviço; garantias já informadas não mudam."""
    so_dono()
    db = get_db()
    erros = []
    valores = limites_de_garantia(db)
    if request.method == "POST":
        novos = {}
        valores = {}
        for i, tipo in enumerate(TIPOS_SERVICO):
            texto = request.form.get(f"meses_{i}", "").strip()
            valores[tipo] = texto
            if re.fullmatch(r"\d{1,3}", texto) and 1 <= int(texto) <= MAX_LIMITE_MESES:
                novos[tipo] = int(texto)
            else:
                erros.append(f"{tipo}: informe um número inteiro de meses, de 1 a {MAX_LIMITE_MESES}.")
        if not erros:
            for tipo, meses in novos.items():
                db.execute("INSERT OR REPLACE INTO limites_garantia (tipo, meses) VALUES (?, ?)", (tipo, meses))
            db.commit()
            return redirect(url_for("limites_garantia", salvo=1))
    em_dias = {tipo: (texto_limite(int(v)) if re.fullmatch(r"\d{1,3}", str(v)) and 1 <= int(v) <= MAX_LIMITE_MESES else "-")
               for tipo, v in valores.items()}
    return render_template("limites.html", tipos=TIPOS_SERVICO, valores=valores, erros=erros, em_dias=em_dias,
                           salvo=bool(request.args.get("salvo")), padrao=LIMITES_PADRAO_MESES,
                           max_meses=MAX_LIMITE_MESES)


@app.route("/veiculos/<int:id>/entrega/desfazer", methods=["POST"])
def desfazer_entrega(id):
    """O dono desfaz uma entrega fechada (por engano ou para corrigir algo). O motivo é obrigatório.
    A cópia da entrega vai para o histórico de entregas desfeitas (nada se perde) e o cadastro do
    veículo destrava. O comprovante que o cliente já recebeu deixa de valer: ao fechar de novo, sai outro."""
    so_dono()
    db = get_db()
    buscar_veiculo(db, id)
    entrega = db.execute("SELECT * FROM entregas WHERE veiculo_id = ?", (id,)).fetchone()
    motivo = " ".join(request.form.get("motivo", "").split())

    erros = []
    if not entrega:
        erros.append("Este veículo não está entregue: não há entrega para desfazer.")
    if sum(1 for letra in motivo if letra.isalpha()) < 3:
        erros.append("Explique o motivo de desfazer a entrega.")
    elif len(motivo) > MAX_MOTIVO_DESFAZER:
        erros.append(f"O motivo pode ter no máximo {MAX_MOTIVO_DESFAZER} letras.")
    if erros:
        return pagina_veiculo(id, erros)

    try:
        cursor = db.execute(
            "INSERT INTO entregas_desfeitas (veiculo_id, data_entrega, condicoes, total_centavos, entregue_por, "
            "entregue_em, motivo, desfeita_por) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (id, entrega["data_entrega"], entrega["condicoes"], entrega["total_centavos"], entrega["entregue_por"],
             entrega["criado_em"], motivo, g.usuario["nome"]))
        db.execute(
            "INSERT INTO entrega_itens_desfeitos (entrega_desfeita_id, tipo, problema, como_resolver, valor_centavos, "
            "garantia_valor, garantia_unidade, garantia_ate) SELECT ?, tipo, problema, como_resolver, valor_centavos, "
            "garantia_valor, garantia_unidade, garantia_ate FROM entrega_itens WHERE entrega_id = ? ORDER BY id",
            (cursor.lastrowid, entrega["id"]))
        db.execute("DELETE FROM entrega_itens WHERE entrega_id = ?", (entrega["id"],))
        db.execute("DELETE FROM entregas WHERE id = ?", (entrega["id"],))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return redirect(url_for("ver_veiculo", id=id))


def limpar_condicoes(texto):
    """Mantém as quebras de linha, mas tira espaços repetidos e linhas vazias."""
    linhas = (" ".join(linha.split()) for linha in texto.replace("\r", "").split("\n"))
    return "\n".join(linha for linha in linhas if linha)


@app.route("/veiculos/<int:id>/entrega", methods=["POST"])
def fechar_entrega(id):
    """História 8: o dono fecha a entrega do veículo. Só com o orçamento aprovado, o tempo de garantia
    informado em TODOS os serviços e as condições que cancelam a garantia. A data de entrega é hoje.
    Fica guardada uma cópia do que foi combinado (o comprovante sai dela) e o cadastro é travado."""
    so_dono()
    db = get_db()
    buscar_veiculo(db, id)
    servicos = db.execute("SELECT * FROM servicos WHERE veiculo_id = ? ORDER BY id", (id,)).fetchall()
    ultima_aprovacao = db.execute("SELECT * FROM aprovacoes WHERE veiculo_id = ? ORDER BY id DESC LIMIT 1",
                                  (id,)).fetchone()
    condicoes = limpar_condicoes(request.form.get("condicoes", ""))
    hoje = hoje_brasil()

    erros = []
    if situacao_aprovacao(servicos, ultima_aprovacao)[0] != "APROVADO":
        erros.append("A entrega só pode ser fechada depois que o cliente aprovar o orçamento.")
    elif request.form.get("assinatura", "") != assinatura_orcamento(servicos):
        erros.append("O orçamento mudou enquanto você fechava a entrega. Confira os valores e tente de novo.")
    faltam = sum(1 for s in servicos if s["garantia_valor"] is None)
    if faltam:
        erros.append("Informe o tempo de garantia de todos os serviços antes de fechar a entrega "
                     f"(falta{'m' if faltam != 1 else ''} {faltam}).")
    if any(s["garantia_valor"] for s in servicos) and sum(1 for letra in condicoes if letra.isalpha()) < 20:
        erros.append("Escreva as condições que cancelam a garantia (aparecem no comprovante do cliente).")
    if len(condicoes) > MAX_CONDICOES:
        erros.append(f"As condições podem ter no máximo {MAX_CONDICOES} letras.")
    if erros:
        return pagina_veiculo(id, erros, {"condicoes": condicoes})

    total = sum(s["valor_centavos"] for s in servicos)
    try:
        cursor = db.execute("INSERT INTO entregas (veiculo_id, data_entrega, condicoes, total_centavos, entregue_por) "
                            "VALUES (?, ?, ?, ?, ?)",
                            (id, hoje.isoformat(), condicoes or None, total, g.usuario["nome"]))
        for s in servicos:
            ate = fim_da_garantia(hoje, s["garantia_valor"], s["garantia_unidade"])
            db.execute("INSERT INTO entrega_itens (entrega_id, servico_id, tipo, problema, como_resolver, "
                       "valor_centavos, garantia_valor, garantia_unidade, garantia_ate) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (cursor.lastrowid, s["id"], s["tipo"], s["problema"], s["como_resolver"], s["valor_centavos"],
                        s["garantia_valor"], s["garantia_unidade"], ate.isoformat() if ate else None))
        db.commit()
    except sqlite3.IntegrityError:      # dois cliques ao mesmo tempo: só um fecha a entrega
        db.rollback()
        return pagina_veiculo(id, ["Este veículo já foi entregue."]), 409
    return redirect(url_for("comprovante", id=id))


@app.route("/veiculos/<int:id>/comprovante")
def comprovante(id):
    """Comprovante de entrega e garantia, para imprimir e entregar ao cliente."""
    db = get_db()
    veiculo = buscar_veiculo(db, id)
    entrega = db.execute("SELECT * FROM entregas WHERE veiculo_id = ?", (id,)).fetchone()
    if not entrega:
        abort(404)
    hoje = hoje_brasil()
    itens = [dict(i, situacao=situacao_garantia(i["garantia_ate"], hoje))
             for i in db.execute("SELECT * FROM entrega_itens WHERE entrega_id = ? ORDER BY id", (entrega["id"],))]
    aprovacao = db.execute("SELECT * FROM aprovacoes WHERE veiculo_id = ? ORDER BY id DESC LIMIT 1", (id,)).fetchone()
    return render_template("comprovante.html", veiculo=veiculo, entrega=entrega, itens=itens, aprovacao=aprovacao,
                           formatar_data=formatar_data, formatar_dinheiro=formatar_dinheiro,
                           texto_garantia=texto_garantia, nomes_formas=NOMES_FORMAS_APROVACAO)


@app.route("/veiculos/<int:id>/servicos/<int:servico_id>/excluir", methods=["POST"])
def excluir_servico(id, servico_id):
    """Só o dono apaga um problema registrado por engano."""
    so_dono()
    db = get_db()
    db.execute("DELETE FROM servicos WHERE id = ? AND veiculo_id = ?", (servico_id, id))
    db.commit()
    return redirect(url_for("ver_veiculo", id=id))


if __name__ == "__main__":
    app.run(debug=True)
