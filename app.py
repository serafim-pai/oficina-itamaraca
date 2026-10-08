import hashlib
import math
import os
import re
import secrets
import sqlite3
import unicodedata
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from urllib.parse import quote, quote_plus

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
MAX_MOTIVO_EXCLUIR = 300                                        # letras do motivo de excluir um veículo
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
                         "registrar_aprovacao", "registrar_prazo", "registrar_garantia", "fechar_entrega",
                         "adicionar_fotos", "excluir_foto", "trocar_foto",
                         "adicionar_fotos_problema", "excluir_foto_problema", "registrar_etapa",
                         "usar_peca", "devolver_peca", "registrar_referencia", "registrar_dados_veiculo",
                         "editar_problema"}
MAX_DADO_VEICULO = 40                # letras de marca, modelo, cor e quilometragem do veículo
MAX_PECA_BUSCA = 100                 # letras do nome da peça pesquisada na Web
MAX_REFERENCIA = 300                 # letras da anotação "número original / onde comprar"
# Sites onde a pesquisa de peça é aberta (em outra aba). {q} é o texto da pesquisa já codificado.
SITES_BUSCA = {
    "GOOGLE": ("Número original (Google)", "https://www.google.com/search?q={q}"),
    "MERCADOLIVRE": ("Mercado Livre", "https://lista.mercadolivre.com.br/{q}"),
    "IMAGENS": ("Fotos da peça (Google Imagens)", "https://www.google.com/search?tbm=isch&q={q}"),
    "CHASSI": ("Pelo chassi (Google)", "https://www.google.com/search?q={q}"),     # só aparece com chassi cadastrado
}
MAX_FOTOS = 10                       # fotos por envio (no cadastro ou ao adicionar depois)
MAX_FOTOS_PROBLEMA = 5               # fotos de um mesmo problema/serviço
MAX_FOTOS_VEICULO = 20               # fotos de um veículo, no total
MAX_BYTES_FOTO = 8 * 1024 * 1024     # tamanho máximo de cada foto enviada
MAX_PIXELS_FOTO = 40_000_000         # evita imagens "bomba" que travariam o servidor
LADO_FOTO = 1600                     # a foto guardada é reduzida para caber nesse tamanho
LADO_MINIATURA = 320
FORMATOS_DE_FOTO = {"JPEG", "PNG", "WEBP", "GIF"}
TIPOS_ESTOQUE = ("PEÇA", "TINTA")    # história 9: estoque de peças e tintas (sempre em unidades inteiras)
MAX_NOME_ITEM = 80                   # letras do nome de um item do estoque
MAX_QUANTIDADE = 100_000             # limite de sanidade para quantidades de estoque
MAX_MOTIVO_ESTOQUE = 200             # letras da observação de uma movimentação
MAX_TEXTO_ITEM = 40                  # letras da categoria, do fabricante e do código de um item
MAX_APLICACOES = 40                  # carros em que um item serve (uma linha para cada)
# Sugestões de categoria (o usuário pode escrever outra). Seguem o tipo de catálogo de autopeças.
CATEGORIAS_SUGERIDAS = ("Pastilha de freio", "Lona de freio", "Sapata de freio", "Disco de freio", "Tambor de freio",
                        "Cilindro de freio", "Fluido de freio", "Kit de embreagem", "Disco de embreagem",
                        "Platô de embreagem", "Filtro", "Correia", "Amortecedor", "Vela", "Lâmpada", "Tinta",
                        "Verniz", "Massa", "Outra")

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
    # Registro do que foi feito com as fotos depois do cadastro (adicionar, trocar, excluir): quem e quando.
    # A imagem apagada NÃO é guardada; fica só o registro de que aconteceu.
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS fotos_historico (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            veiculo_id INTEGER NOT NULL,
            foto_id INTEGER NOT NULL,
            acao TEXT NOT NULL,
            feita_por TEXT,
            feita_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
    # Etapas do serviço (aguardando início, em reparo, pronto para retirada): cada mudança fica guardada
    # (quem e quando) e a última é a que vale. Sem nenhuma linha, o veículo está "aguardando início".
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS etapas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            veiculo_id INTEGER NOT NULL,
            etapa TEXT NOT NULL,
            registrado_por TEXT,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # Veículos excluídos: o veículo e tudo que era dele somem, mas fica o registro de que existiu,
    # quem excluiu, quando e por quê.
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS veiculos_excluidos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            veiculo_id INTEGER NOT NULL,
            placa TEXT,
            responsavel TEXT,
            motivo TEXT NOT NULL,
            excluido_por TEXT,
            excluido_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # História 9: estoque de peças e tintas. Cada item guarda quantidade (inteira), mínimo para o aviso de estoque
    # baixo, custo e preço de venda (em centavos). Toda mudança de quantidade vira uma linha em
    # estoque_movimentos (nunca apagada): quem, quando e por quê.
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS estoque_itens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            tipo TEXT NOT NULL,
            quantidade INTEGER NOT NULL DEFAULT 0,
            minimo INTEGER NOT NULL DEFAULT 0,
            custo_centavos INTEGER NOT NULL DEFAULT 0,
            preco_centavos INTEGER NOT NULL,
            ativo INTEGER NOT NULL DEFAULT 1,
            criado_por TEXT,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS estoque_movimentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            variacao INTEGER NOT NULL,
            saldo_apos INTEGER NOT NULL,
            motivo TEXT,
            veiculo_id INTEGER,
            servico_id INTEGER,
            registrado_por TEXT,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # Em quais carros cada item serve (uma linha por marca/modelo, com anos opcionais)
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS estoque_aplicacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            marca TEXT NOT NULL,
            modelo TEXT NOT NULL,
            ano_de INTEGER,
            ano_ate INTEGER
        )
        """
    )
    # Peças/tintas usadas em um serviço: guardam nome, preço e custo da hora do uso (mudar o preço do
    # estoque depois não mexe no orçamento já feito).
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS servico_pecas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            servico_id INTEGER NOT NULL,
            veiculo_id INTEGER NOT NULL,
            item_id INTEGER NOT NULL,
            nome TEXT NOT NULL,
            quantidade INTEGER NOT NULL,
            preco_centavos INTEGER NOT NULL,
            custo_centavos INTEGER NOT NULL,
            registrado_por TEXT,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # Cópia das peças de cada serviço na hora da entrega (o comprovante sai daqui)
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS entrega_pecas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entrega_item_id INTEGER NOT NULL,
            nome TEXT NOT NULL,
            quantidade INTEGER NOT NULL,
            preco_centavos INTEGER NOT NULL
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
    # Categoria, fabricante e código de cada item do estoque (bancos criados antes não têm)
    colunas_itens = [c[1] for c in db.execute("PRAGMA table_info(estoque_itens)")]
    for coluna in ("categoria", "fabricante", "codigo"):
        if coluna not in colunas_itens:
            db.execute(f"ALTER TABLE estoque_itens ADD COLUMN {coluna} TEXT")
    # História 9: soma (em centavos) das peças usadas no serviço; entra no orçamento junto com o valor do serviço
    if "pecas_centavos" not in colunas:
        db.execute("ALTER TABLE servicos ADD COLUMN pecas_centavos INTEGER NOT NULL DEFAULT 0")
    for tabela in ("entrega_itens", "entrega_itens_desfeitos"):
        if "pecas_centavos" not in [c[1] for c in db.execute(f"PRAGMA table_info({tabela})")]:
            db.execute(f"ALTER TABLE {tabela} ADD COLUMN pecas_centavos INTEGER NOT NULL DEFAULT 0")
    # Peça de referência de cada serviço: número original e onde comprar (só anotação, não entra no orçamento)
    if "referencia_peca" not in colunas:
        db.execute("ALTER TABLE servicos ADD COLUMN referencia_peca TEXT")
    # Telefone (WhatsApp) do cliente, só dígitos com DDD; opcional
    colunas_veiculos = [c[1] for c in db.execute("PRAGMA table_info(veiculos)")]
    if "telefone" not in colunas_veiculos:
        db.execute("ALTER TABLE veiculos ADD COLUMN telefone TEXT")
    # Chassi do veículo (opcional): ajuda a achar a peça certa, que muda conforme a versão do carro
    if "chassi" not in colunas_veiculos:
        db.execute("ALTER TABLE veiculos ADD COLUMN chassi TEXT")
    # Motor do veículo (cilindrada e potência, como "1.8 8v 99cv"): a peça certa muda conforme o motor
    if "motor" not in colunas_veiculos:
        db.execute("ALTER TABLE veiculos ADD COLUMN motor TEXT")
    # Fotos da entrega: "momento" diz quando a foto foi tirada. ENTRADA (as que já existiam), ENTREGA, ou
    # ENTREGA_DESFEITA (as da entrega que depois foi desfeita; ficam guardadas, ligadas a ela).
    colunas_fotos = [c[1] for c in db.execute("PRAGMA table_info(fotos)")]
    if "momento" not in colunas_fotos:
        db.execute("ALTER TABLE fotos ADD COLUMN momento TEXT NOT NULL DEFAULT 'ENTRADA'")
    if "entrega_desfeita_id" not in colunas_fotos:
        db.execute("ALTER TABLE fotos ADD COLUMN entrega_desfeita_id INTEGER")
    # Fotos de um problema/serviço: momento PROBLEMA, ligadas ao serviço por "servico_id"
    if "servico_id" not in colunas_fotos:
        db.execute("ALTER TABLE fotos ADD COLUMN servico_id INTEGER")
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


@app.after_request
def cabecalhos_de_seguranca(resposta):
    """Pedem ao navegador para se proteger (tela dentro de outro site, tipo de arquivo trocado)."""
    resposta.headers.setdefault("X-Frame-Options", "DENY")
    resposta.headers.setdefault("X-Content-Type-Options", "nosniff")
    resposta.headers.setdefault("Referrer-Policy", "same-origin")
    return resposta


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
    # As peças só entram na conta quando existem: assim as aprovações antigas continuam valendo.
    texto = "|".join(f"{s['id']}:{s['valor_centavos']}" + (f"+{s['pecas_centavos']}" if s["pecas_centavos"] else "")
                     for s in sorted(servicos, key=lambda s: s["id"]))
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
    for s in db.execute("SELECT id, veiculo_id, valor_centavos, pecas_centavos FROM servicos ORDER BY id"):
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


@app.template_filter("hora_brasil")
def hora_brasil(texto_utc):
    """Mostra uma data e hora guardada pelo banco (sempre em UTC, 'AAAA-MM-DD HH:MM:SS') no horário de
    Brasília: '2026-10-06 00:30:30' vira '05/10/2026 21:30'. Vazio vira '-'; se o texto não for uma
    data e hora, é mostrado como veio (melhor isso do que quebrar a tela)."""
    if not texto_utc:
        return "-"
    try:
        utc = datetime.strptime(str(texto_utc), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return str(texto_utc)
    return utc.astimezone(FUSO_BRASIL).strftime("%d/%m/%Y %H:%M")


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


# ---------- ETAPAS DO SERVIÇO ----------

# Etapas na ordem em que acontecem. Sem registro, o veículo está na primeira.
ETAPAS = {
    "AGUARDANDO_INICIO": "Aguardando início",
    "EM_REPARO": "Em reparo",
    "PRONTO": "Pronto para retirada",
}
# De onde dá para ir para onde. Voltar uma etapa serve para corrigir um engano.
MUDANCAS_DE_ETAPA = {
    "AGUARDANDO_INICIO": ("EM_REPARO",),
    "EM_REPARO": ("PRONTO", "AGUARDANDO_INICIO"),
    "PRONTO": ("EM_REPARO",),
}


def etapa_atual(db, veiculo_id):
    linha = db.execute("SELECT etapa FROM etapas WHERE veiculo_id = ? ORDER BY id DESC LIMIT 1",
                       (veiculo_id,)).fetchone()
    return linha["etapa"] if linha and linha["etapa"] in ETAPAS else "AGUARDANDO_INICIO"


def etapas_dos_veiculos(db, veiculos):
    """Etapa de cada veículo da lista, com poucas consultas. Veículo entregue aparece como 'Entregue'."""
    ultimas = {}
    for e in db.execute("SELECT veiculo_id, etapa FROM etapas ORDER BY id"):
        ultimas[e["veiculo_id"]] = e["etapa"]               # a última linha de cada veículo é a que vale
    entregues = {e["veiculo_id"] for e in db.execute("SELECT veiculo_id FROM entregas")}
    resultado = {}
    for v in veiculos:
        if v["id"] in entregues:
            resultado[v["id"]] = ("ETAPA_ENTREGUE", "Entregue")
        else:
            chave = ultimas.get(v["id"], "AGUARDANDO_INICIO")
            chave = chave if chave in ETAPAS else "AGUARDANDO_INICIO"
            resultado[v["id"]] = (f"ETAPA_{chave}", ETAPAS[chave])
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


def veiculo_combina_com_busca(veiculo, busca):
    """Busca na lista de veículos: cada palavra digitada precisa aparecer em algum destes dados do veículo:
    placa, responsável, marca, modelo, cor, ano, chassi ou telefone. Não importa maiúscula, acento, hífen
    nem espaço (ABC-1D23 acha ABC1D23; "joao" acha JOÃO)."""
    campos = ("placa", "responsavel", "marca", "modelo", "cor", "ano", "motor", "chassi", "telefone")
    texto = "|".join(normalizar(veiculo[c]) for c in campos)
    palavras = [normalizar(p) for p in busca.split()]
    return all(p in texto for p in palavras if p)


def pagina_inicial(erros=None, dados=None):
    """Desenha a tela de cadastro com a lista de veículos e as fotos de cada um."""
    db = get_db()
    cadastrado = None
    excluido = request.args.get("excluido", "")[:20] if request.method == "GET" else ""
    if request.method == "GET" and request.args.get("cadastrado", "").isdigit():
        cadastrado = db.execute("SELECT id, placa FROM veiculos WHERE id = ?",
                                (int(request.args["cadastrado"]),)).fetchone()
    veiculos = db.execute("SELECT * FROM veiculos ORDER BY id DESC").fetchall()
    total_veiculos = len(veiculos)
    busca = " ".join(request.args.get("q", "").split())[:60] if request.method == "GET" else ""
    if busca:
        veiculos = [v for v in veiculos if veiculo_combina_com_busca(v, busca)]
    fotos = {}
    for foto in db.execute("SELECT id, veiculo_id FROM fotos WHERE momento = 'ENTRADA' ORDER BY id"):
        fotos.setdefault(foto["veiculo_id"], []).append(foto["id"])
    return render_template("index.html", busca=busca, total_veiculos=total_veiculos,
                           veiculos=veiculos, fotos=fotos, erros=erros or [],
                           dados=dados or {}, cadastrado=cadastrado, excluido=excluido, max_fotos=MAX_FOTOS,
                           max_mb=MAX_BYTES_FOTO // (1024 * 1024),
                           situacoes=situacoes_dos_veiculos(db, veiculos),
                           prazos=prazos_dos_veiculos(db, veiculos),
                           etapas=etapas_dos_veiculos(db, veiculos))


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


def gravar_arquivos_da_foto(grande, miniatura, criados):
    """Grava a foto grande e a miniatura no disco e devolve o código sorteado que identifica o par.
    Cada arquivo é anotado em 'criados' assim que nasce, para dar para apagar tudo se algo falhar no meio."""
    codigo = secrets.token_hex(16)     # nome sorteado: o nome original nunca vira caminho
    for sufixo, conteudo in (("", grande), ("_m", miniatura)):
        caminho = os.path.join(PASTA_FOTOS, f"{codigo}{sufixo}.jpg")
        criados.append(caminho)
        with open(caminho, "wb") as f:
            f.write(conteudo)
    return codigo


def apagar_arquivos(caminhos):
    for caminho in caminhos:
        try:
            os.remove(caminho)
        except FileNotFoundError:
            pass


def apagar_arquivos_da_foto(codigo):
    apagar_arquivos([os.path.join(PASTA_FOTOS, f"{codigo}{sufixo}.jpg") for sufixo in ("", "_m")])


def guardar_fotos(db, veiculo_id, fotos, criados, momento="ENTRADA"):
    """Grava os arquivos das fotos e registra no banco. 'momento' é ENTRADA (o estado em que o carro
    chegou) ou ENTREGA (o estado em que o carro saiu)."""
    for grande, miniatura in fotos:
        codigo = gravar_arquivos_da_foto(grande, miniatura, criados)
        db.execute("INSERT INTO fotos (veiculo_id, arquivo, momento) VALUES (?, ?, ?)", (veiculo_id, codigo, momento))


def preparar_fotos_enviadas(campo):
    """Lê as fotos enviadas num campo do formulário. Devolve (erros, fotos_prontas, quantas_foram_enviadas)."""
    arquivos = [a for a in request.files.getlist(campo) if a and a.filename]
    erros, prontas = [], []
    if len(arquivos) > MAX_FOTOS:
        erros.append(f"Envie no máximo {MAX_FOTOS} fotos de uma vez.")
    else:
        for arquivo in arquivos:
            erro_foto, pronta = preparar_foto(arquivo)
            if erro_foto:
                erros.append(erro_foto)
            else:
                prontas.append(pronta)
    return erros, prontas, len(arquivos)


def anotar_foto(db, veiculo_id, foto_id, acao):
    db.execute("INSERT INTO fotos_historico (veiculo_id, foto_id, acao, feita_por) VALUES (?, ?, ?, ?)",
               (veiculo_id, foto_id, acao, g.usuario["nome"]))


def enviar_foto(id, sufixo):
    linha = get_db().execute("SELECT arquivo FROM fotos WHERE id = ?", (id,)).fetchone()
    if not linha:
        abort(404)
    resposta = send_from_directory(PASTA_FOTOS, f"{linha['arquivo']}{sufixo}.jpg", mimetype="image/jpeg")
    # Só o navegador de quem entrou guarda, mas sempre confere se a foto mudou (uma foto trocada
    # continua com o mesmo endereço, e não pode aparecer a antiga). A conferência é barata (304).
    resposta.headers["Cache-Control"] = "private, no-cache"
    resposta.headers["X-Content-Type-Options"] = "nosniff"
    return resposta


@app.route("/fotos/<int:id>")
def foto(id):
    return enviar_foto(id, "")


@app.route("/fotos/<int:id>/miniatura")
def foto_miniatura(id):
    return enviar_foto(id, "_m")


@app.route("/veiculos/<int:id>/fotos", methods=["POST"])
def adicionar_fotos(id):
    """Acrescenta fotos a um veículo já cadastrado. Dono e funcionário podem. Tudo ou nada: se uma
    foto for recusada, nenhuma é guardada."""
    db = get_db()
    buscar_veiculo(db, id)
    arquivos = [a for a in request.files.getlist("fotos") if a and a.filename]
    existentes = db.execute("SELECT COUNT(*) FROM fotos WHERE veiculo_id = ? AND momento = 'ENTRADA'", (id,)).fetchone()[0]
    erros, preparadas = [], []
    if not arquivos:
        erros.append("Escolha pelo menos uma foto para adicionar.")
    elif len(arquivos) > MAX_FOTOS:
        erros.append(f"Envie no máximo {MAX_FOTOS} fotos de uma vez.")
    elif existentes + len(arquivos) > MAX_FOTOS_VEICULO:
        erros.append(f"Cada veículo pode ter no máximo {MAX_FOTOS_VEICULO} fotos (este já tem {existentes}).")
    else:
        for arquivo in arquivos:
            erro_foto, pronta = preparar_foto(arquivo)
            if erro_foto:
                erros.append(erro_foto)
            else:
                preparadas.append(pronta)
    if erros:
        return pagina_veiculo(id, erros)

    criados = []
    try:
        guardar_fotos(db, id, preparadas, criados)
        novas = db.execute("SELECT id FROM fotos WHERE veiculo_id = ? ORDER BY id DESC LIMIT ?",
                           (id, len(preparadas))).fetchall()
        for nova in novas:
            anotar_foto(db, id, nova["id"], "ADICIONADA")
        db.commit()
    except Exception:
        db.rollback()
        apagar_arquivos(criados)      # não deixa foto "órfã" no disco
        raise
    return redirect(url_for("ver_veiculo", id=id))


def buscar_servico_do_veiculo(db, id, servico_id):
    servico = db.execute("SELECT * FROM servicos WHERE id = ? AND veiculo_id = ?", (servico_id, id)).fetchone()
    if not servico:
        abort(404)
    return servico


@app.route("/veiculos/<int:id>/servicos/<int:servico_id>/fotos", methods=["POST"])
def adicionar_fotos_problema(id, servico_id):
    """Anexa fotos a um problema registrado (mostram o que foi encontrado). Dono e funcionário podem.
    Tudo ou nada: se uma foto for recusada, nenhuma é guardada."""
    db = get_db()
    buscar_veiculo(db, id)
    buscar_servico_do_veiculo(db, id, servico_id)
    arquivos = [a for a in request.files.getlist("fotos") if a and a.filename]
    existentes = db.execute("SELECT COUNT(*) FROM fotos WHERE servico_id = ? AND momento = 'PROBLEMA'",
                            (servico_id,)).fetchone()[0]
    erros, preparadas = [], []
    if not arquivos:
        erros.append("Escolha pelo menos uma foto para anexar ao problema.")
    elif existentes + len(arquivos) > MAX_FOTOS_PROBLEMA:
        erros.append(f"Cada problema pode ter no máximo {MAX_FOTOS_PROBLEMA} fotos (este já tem {existentes}).")
    else:
        for arquivo in arquivos:
            erro_foto, pronta = preparar_foto(arquivo)
            if erro_foto:
                erros.append(erro_foto)
            else:
                preparadas.append(pronta)
    if erros:
        return pagina_veiculo(id, erros)

    criados = []
    try:
        for grande, miniatura in preparadas:
            codigo = gravar_arquivos_da_foto(grande, miniatura, criados)
            cursor = db.execute("INSERT INTO fotos (veiculo_id, arquivo, momento, servico_id) "
                                "VALUES (?, ?, 'PROBLEMA', ?)", (id, codigo, servico_id))
            anotar_foto(db, id, cursor.lastrowid, "ADICIONADA")
        db.commit()
    except Exception:
        db.rollback()
        apagar_arquivos(criados)      # não deixa foto "órfã" no disco
        raise
    return redirect(url_for("ver_veiculo", id=id))


@app.route("/veiculos/<int:id>/servicos/<int:servico_id>/fotos/<int:foto_id>/excluir", methods=["POST"])
def excluir_foto_problema(id, servico_id, foto_id):
    """Só o dono apaga a foto de um problema. Fica o registro de quem e quando."""
    so_dono()
    db = get_db()
    buscar_veiculo(db, id)
    foto_do_problema = db.execute(
        "SELECT * FROM fotos WHERE id = ? AND veiculo_id = ? AND servico_id = ? AND momento = 'PROBLEMA'",
        (foto_id, id, servico_id)).fetchone()
    if not foto_do_problema:
        abort(404)
    db.execute("DELETE FROM fotos WHERE id = ?", (foto_id,))
    anotar_foto(db, id, foto_id, "EXCLUIDA")
    db.commit()
    apagar_arquivos_da_foto(foto_do_problema["arquivo"])      # só depois de gravar no banco
    return redirect(url_for("ver_veiculo", id=id))


def buscar_foto_do_veiculo(db, id, foto_id):
    """A foto de ENTRADA, desde que seja mesmo deste veículo (senão 404). As fotos da entrega são
    prova do estado em que o carro saiu e não podem ser trocadas nem excluídas."""
    foto_do_veiculo = db.execute("SELECT * FROM fotos WHERE id = ? AND veiculo_id = ? AND momento = 'ENTRADA'",
                                 (foto_id, id)).fetchone()
    if not foto_do_veiculo:
        abort(404)
    return foto_do_veiculo


@app.route("/veiculos/<int:id>/fotos/<int:foto_id>/excluir", methods=["POST"])
def excluir_foto(id, foto_id):
    """Só o dono apaga uma foto (elas servem de prova do estado do carro). Fica o registro de quem e quando."""
    so_dono()
    db = get_db()
    buscar_veiculo(db, id)
    foto_do_veiculo = buscar_foto_do_veiculo(db, id, foto_id)
    db.execute("DELETE FROM fotos WHERE id = ?", (foto_id,))
    anotar_foto(db, id, foto_id, "EXCLUIDA")
    db.commit()
    apagar_arquivos_da_foto(foto_do_veiculo["arquivo"])      # só depois de gravar no banco
    return redirect(url_for("ver_veiculo", id=id))


@app.route("/veiculos/<int:id>/fotos/<int:foto_id>/trocar", methods=["POST"])
def trocar_foto(id, foto_id):
    """Só o dono troca uma foto por outra. A foto nova ocupa o mesmo lugar (mesmo número); a antiga é apagada.
    Se algo falhar, a antiga continua intacta."""
    so_dono()
    db = get_db()
    buscar_veiculo(db, id)
    foto_do_veiculo = buscar_foto_do_veiculo(db, id, foto_id)
    arquivos = [a for a in request.files.getlist("foto") if a and a.filename]
    if not arquivos:
        return pagina_veiculo(id, ["Escolha a foto que vai ficar no lugar da atual."])
    if len(arquivos) > 1:
        return pagina_veiculo(id, ["Para trocar, envie uma foto só."])
    erro_foto, pronta = preparar_foto(arquivos[0])
    if erro_foto:
        return pagina_veiculo(id, [erro_foto])

    criados = []
    try:
        codigo = gravar_arquivos_da_foto(pronta[0], pronta[1], criados)
        db.execute("UPDATE fotos SET arquivo = ?, criado_em = CURRENT_TIMESTAMP WHERE id = ?", (codigo, foto_id))
        anotar_foto(db, id, foto_id, "TROCADA")
        db.commit()
    except Exception:
        db.rollback()
        apagar_arquivos(criados)
        raise
    apagar_arquivos_da_foto(foto_do_veiculo["arquivo"])      # a antiga só some depois que a nova está salva
    return redirect(url_for("ver_veiculo", id=id))


def normalizar_telefone(texto):
    """Aceita "(11) 98765-4321", "11987654321", "+55 11 98765-4321" etc.
    Devolve (telefone_só_com_dígitos_e_DDD, None), ("", None) se vier vazio, ou (None, mensagem de erro)."""
    digitos = "".join(c for c in texto if c.isdigit())
    if not digitos:
        return "", None
    if len(digitos) in (12, 13) and digitos.startswith("55"):
        digitos = digitos[2:]
    if len(digitos) not in (10, 11) or digitos[0] == "0":
        return None, "Telefone inválido: informe o DDD e o número (exemplo: (81) 98765-4321)."
    return digitos, None


def formatar_telefone(digitos):
    if not digitos:
        return "-"
    if len(digitos) == 11:
        return f"({digitos[:2]}) {digitos[2:7]}-{digitos[7:]}"
    return f"({digitos[:2]}) {digitos[2:6]}-{digitos[6:]}"


MAX_LINK_WHATSAPP = 1800     # tamanho máximo do texto já codificado no link (os links muito longos falham)


def link_whatsapp(veiculo, servicos, total_centavos):
    """Link que abre o WhatsApp com o orçamento já escrito. Sem telefone, o WhatsApp pede para escolher o contato.
    Quem envia é a pessoa, tocando em "enviar" no WhatsApp: o sistema não manda nada sozinho."""
    nome = (veiculo["responsavel"] or "").strip()
    carro = " ".join(p for p in (veiculo["marca"], veiculo["modelo"], veiculo["cor"]) if p)
    abertura = f"Olá{', ' + nome if nome else ''}! Aqui é da Oficina Itamaracá.\n"
    abertura += f"Segue o orçamento do veículo {carro + ' ' if carro else ''}placa {veiculo['placa']}:\n"
    fim = (f"\n*Total: {formatar_dinheiro(total_centavos)}*\n\n"
           "Você aprova o orçamento? Responda *APROVADO* ou *RECUSADO*.")
    linhas = [f"• {s['tipo'].capitalize()}: {' '.join(s['problema'].split())[:100]} - "
              f"{formatar_dinheiro(s['valor_centavos'] + s['pecas_centavos'])}" for s in servicos]
    incluidas = list(linhas)
    while True:
        mais = len(linhas) - len(incluidas)
        corpo = "\n".join(incluidas) + (f"\n... e mais {mais} serviço{'s' if mais != 1 else ''}" if mais else "")
        texto = abertura + corpo + "\n" + fim
        if len(quote(texto)) <= MAX_LINK_WHATSAPP or not incluidas:
            break
        incluidas.pop()
    base = f"https://wa.me/55{veiculo['telefone']}" if veiculo["telefone"] else "https://wa.me/"
    return f"{base}?text={quote(texto)}"


def link_whatsapp_pronto(veiculo):
    """Link do WhatsApp com o aviso de que o veículo está pronto para retirada (a pessoa confere e envia)."""
    nome = (veiculo["responsavel"] or "").strip()
    carro = " ".join(p for p in (veiculo["marca"], veiculo["modelo"], veiculo["cor"]) if p)
    texto = (f"Olá{', ' + nome if nome else ''}! Aqui é da Oficina Itamaracá.\n"
             f"O seu veículo {carro + ' ' if carro else ''}placa {veiculo['placa']} está *pronto para retirada*.\n"
             "Qualquer dúvida, é só responder esta mensagem. Obrigado!")
    base = f"https://wa.me/55{veiculo['telefone']}" if veiculo["telefone"] else "https://wa.me/"
    return f"{base}?text={quote(texto)}"


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
        "motor": " ".join(request.form.get("motor", "").split()),
    }
    dados["chassi"], erro_chassi = interpretar_chassi(request.form.get("chassi", ""))
    telefone, erro_telefone = normalizar_telefone(request.form.get("telefone", ""))
    dados["telefone"] = request.form.get("telefone", "").strip()
    documento_deixado = request.form.get("documento_deixado") == "on"

    erros = []
    if erro_telefone:
        erros.append(erro_telefone)
    if erro_chassi:
        erros.append(erro_chassi)
    if len(dados["motor"]) > MAX_DADO_VEICULO:
        erros.append(f"O motor pode ter no máximo {MAX_DADO_VEICULO} letras (exemplo: 1.8 8v 99cv).")
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
                (responsavel, placa, marca, modelo, cor, ano, quilometragem, documento_deixado, telefone, chassi, motor)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                telefone,
                dados["chassi"] or None,
                dados["motor"] or None,
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
    return redirect(url_for("index", cadastrado=cursor.lastrowid) + "#cadastrado")


# ---------- PROBLEMAS E TIPOS DE SERVIÇO (por veículo) ----------

def interpretar_chassi(texto):
    """Chassi (opcional): só letras e números, de 6 a 17 caracteres (carros mais antigos têm menos). Os de 17
    caracteres nunca usam as letras I, O e Q. Devolve (chassi em maiúsculas ou "", erro ou None)."""
    chassi = "".join(texto.split()).upper()
    if not chassi:
        return "", None
    if not (chassi.isascii() and chassi.isalnum()) or not 6 <= len(chassi) <= 17:
        return chassi, "O chassi deve ter de 6 a 17 letras e números, sem espaços nem símbolos (exemplo: 9BGKS08R0NB123456)."
    if len(chassi) == 17 and any(letra in "IOQ" for letra in chassi):
        return chassi, "Chassi de 17 caracteres não usa as letras I, O e Q: confira se não são o número 1 ou 0."
    return chassi, None


def buscar_veiculo(db, id):
    veiculo = db.execute("SELECT * FROM veiculos WHERE id = ?", (id,)).fetchone()
    if not veiculo:
        abort(404)
    return veiculo


def pagina_veiculo(id, erros=None, dados=None):
    db = get_db()
    veiculo = buscar_veiculo(db, id)
    servicos = db.execute("SELECT * FROM servicos WHERE veiculo_id = ? ORDER BY id", (id,)).fetchall()
    fotos = [f["id"] for f in db.execute("SELECT id FROM fotos WHERE veiculo_id = ? AND momento = 'ENTRADA' ORDER BY id", (id,))]
    fotos_entrega = [f["id"] for f in db.execute("SELECT id FROM fotos WHERE veiculo_id = ? AND momento = 'ENTREGA' ORDER BY id", (id,))]
    fotos_problemas = {}                 # fotos de cada problema, agrupadas pelo serviço
    for f in db.execute("SELECT id, servico_id FROM fotos WHERE veiculo_id = ? AND momento = 'PROBLEMA' ORDER BY id", (id,)):
        fotos_problemas.setdefault(f["servico_id"], []).append(f["id"])
    fotos_desfeitas = {}                 # fotos de entregas desfeitas, agrupadas pela entrega a que pertenciam
    for f in db.execute("SELECT id, entrega_desfeita_id FROM fotos WHERE veiculo_id = ? AND momento = 'ENTREGA_DESFEITA' ORDER BY id", (id,)):
        fotos_desfeitas.setdefault(f["entrega_desfeita_id"], []).append(f["id"])
    total_centavos = sum((s["valor_centavos"] or 0) + s["pecas_centavos"] for s in servicos)
    pecas_servicos = {}                  # peças usadas em cada serviço
    for p in db.execute("SELECT * FROM servico_pecas WHERE veiculo_id = ? ORDER BY id", (id,)):
        pecas_servicos.setdefault(p["servico_id"], []).append(p)
    itens_estoque = db.execute("SELECT * FROM estoque_itens WHERE ativo = 1 AND quantidade > 0 "
                               "ORDER BY tipo, nome").fetchall()
    grupos_estoque = agrupar_por_aplicacao(itens_estoque, aplicacoes_dos_itens(db), veiculo)
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
    historico_fotos = db.execute("SELECT * FROM fotos_historico WHERE veiculo_id = ? ORDER BY id DESC", (id,)).fetchall()
    historico_etapas = db.execute("SELECT * FROM etapas WHERE veiculo_id = ? ORDER BY id DESC", (id,)).fetchall()
    etapa = etapa_atual(db, id)
    pecas_entrega = {}                   # peças de cada item da entrega fechada
    if entrega:
        for p in db.execute("SELECT ep.* FROM entrega_pecas ep JOIN entrega_itens ei "
                            "ON ei.id = ep.entrega_item_id WHERE ei.entrega_id = ? ORDER BY ep.id", (entrega["id"],)):
            pecas_entrega.setdefault(p["entrega_item_id"], []).append(p)
    return render_template("veiculo.html", max_dado_veiculo=MAX_DADO_VEICULO, sites_busca=SITES_BUSCA, max_peca_busca=MAX_PECA_BUSCA,
                           max_referencia=MAX_REFERENCIA, pecas_servicos=pecas_servicos, itens_estoque=itens_estoque,
                           grupos_estoque=grupos_estoque,
                           pecas_entrega=pecas_entrega, etapa=etapa, etapas=ETAPAS, historico_etapas=historico_etapas,
                           proximas_etapas=MUDANCAS_DE_ETAPA[etapa],
                           link_whatsapp_pronto=(link_whatsapp_pronto(veiculo)
                                                 if etapa == "PRONTO" and not entrega else None), veiculo=veiculo, servicos=servicos, fotos=fotos,
                           fotos_entrega=fotos_entrega, fotos_desfeitas=fotos_desfeitas,
                           historico_fotos=historico_fotos, max_fotos=MAX_FOTOS, max_fotos_veiculo=MAX_FOTOS_VEICULO,
                           max_mb=MAX_BYTES_FOTO // (1024 * 1024),
                           desfeitas=desfeitas, max_motivo_desfazer=MAX_MOTIVO_DESFAZER,
                           max_motivo_excluir=MAX_MOTIVO_EXCLUIR, fotos_problemas=fotos_problemas,
                           max_fotos_problema=MAX_FOTOS_PROBLEMA, formatar_telefone=formatar_telefone,
                           link_whatsapp=(link_whatsapp(veiculo, servicos, total_centavos)
                                          if orcamento_completo and not entrega else None),
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


@app.route("/veiculos/<int:id>/servicos/<int:servico_id>/problema", methods=["POST"])
def editar_problema(id, servico_id):
    """Corrige o tipo e a descrição de um problema registrado, sem perder fotos, valor, garantia nem peças.
    Dono e funcionário podem, até a entrega. O orçamento e a aprovação do cliente não mudam (só o texto muda).
    Mudar o tipo muda o limite de garantia: se a garantia já informada passar do limite do novo tipo, nada é salvo."""
    db = get_db()
    buscar_veiculo(db, id)
    servico = db.execute("SELECT * FROM servicos WHERE id = ? AND veiculo_id = ?", (servico_id, id)).fetchone()
    if not servico:
        abort(404)
    tipo = request.form.get("tipo", "").strip().upper()
    problema = " ".join(request.form.get("problema", "").split())

    erros = []
    if tipo not in TIPOS_SERVICO:
        erros.append("Escolha o tipo de serviço.")
    if sum(1 for letra in problema if letra.isalpha()) < 3:
        erros.append("Descreva o problema encontrado no veículo.")
    elif len(problema) > MAX_PROBLEMA:
        erros.append(f"A descrição do problema pode ter no máximo {MAX_PROBLEMA} letras.")
    if tipo in TIPOS_SERVICO and tipo != servico["tipo"] and servico["garantia_valor"]:
        limite_meses = limites_de_garantia(db).get(tipo, MAX_LIMITE_MESES)
        if servico["garantia_valor"] > limite_em(servico["garantia_unidade"], limite_meses):
            erros.append(f"A garantia deste serviço ({texto_garantia(servico['garantia_valor'], servico['garantia_unidade'])}) "
                         f"passa do limite de {tipo}, que é {texto_limite(limite_meses)}. "
                         "Peça ao dono para corrigir a garantia antes de mudar o tipo.")
    if erros:
        return pagina_veiculo(id, erros)

    db.execute("UPDATE servicos SET tipo = ?, problema = ? WHERE id = ?", (tipo, problema, servico_id))
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


@app.route("/veiculos/<int:id>/pecas/buscar")
def buscar_peca_na_web(id):
    """Abre a pesquisa de uma peça na Web, já com marca, modelo e ano do veículo e pedindo o número original,
    para comprar na autopeça a peça certa. O sistema só monta o endereço: quem decide a compra é a pessoa.
    Só abre os sites da lista SITES_BUSCA (o texto digitado vai apenas dentro da pesquisa)."""
    db = get_db()
    veiculo = buscar_veiculo(db, id)
    peca = " ".join(request.args.get("peca", "").split())
    site = request.args.get("site", "").upper()
    erros = []
    if site not in SITES_BUSCA:
        erros.append("Escolha onde pesquisar a peça.")
    if sum(1 for letra in peca if letra.isalpha()) < 3:
        erros.append("Escreva qual peça procurar (exemplo: pastilha de freio dianteira).")
    elif len(peca) > MAX_PECA_BUSCA:
        erros.append(f"O nome da peça pode ter no máximo {MAX_PECA_BUSCA} letras.")
    if not (veiculo["marca"] or "").strip() or not (veiculo["modelo"] or "").strip():
        erros.append("Cadastre a marca e o modelo do veículo para pesquisar a peça certa para ele.")
    if site == "CHASSI" and not veiculo["chassi"]:
        erros.append("Cadastre o chassi do veículo para pesquisar a peça pelo chassi.")
    if erros:
        return pagina_veiculo(id, erros)
    carro = " ".join(p for p in (veiculo["marca"], veiculo["modelo"], veiculo["motor"], veiculo["ano"])
                     if p and p.strip())
    texto = f"{peca} {carro}"
    if site == "GOOGLE":
        texto += " número original OEM código"
    elif site == "CHASSI":
        texto += f" chassi {veiculo['chassi']}"
    if site == "MERCADOLIVRE":      # o Mercado Livre pede a pesquisa com hífens no lugar dos espaços
        codificado = quote("-".join(texto.lower().split()), safe="-")
    else:
        codificado = quote_plus(texto)
    return redirect(SITES_BUSCA[site][1].format(q=codificado))


@app.route("/veiculos/<int:id>/servicos/<int:servico_id>/referencia", methods=["POST"])
def registrar_referencia(id, servico_id):
    """Anota a peça de referência do serviço (número original, onde comprar). É só lembrete: não muda o orçamento.
    Dá para apagar deixando vazio."""
    db = get_db()
    buscar_veiculo(db, id)
    if not db.execute("SELECT 1 FROM servicos WHERE id = ? AND veiculo_id = ?", (servico_id, id)).fetchone():
        abort(404)
    texto = " ".join(request.form.get("referencia", "").split())
    if len(texto) > MAX_REFERENCIA:
        return pagina_veiculo(id, [f"A anotação da peça pode ter no máximo {MAX_REFERENCIA} letras."])
    db.execute("UPDATE servicos SET referencia_peca = ? WHERE id = ?", (texto or None, servico_id))
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
            "garantia_valor, garantia_unidade, garantia_ate, pecas_centavos) SELECT ?, tipo, problema, como_resolver, "
            "valor_centavos, garantia_valor, garantia_unidade, garantia_ate, pecas_centavos "
            "FROM entrega_itens WHERE entrega_id = ? ORDER BY id",
            (cursor.lastrowid, entrega["id"]))
        # As fotos da entrega não são apagadas: ficam guardadas, ligadas à entrega desfeita
        db.execute("UPDATE fotos SET momento = 'ENTREGA_DESFEITA', entrega_desfeita_id = ? "
                   "WHERE veiculo_id = ? AND momento = 'ENTREGA'", (cursor.lastrowid, id))
        db.execute("DELETE FROM entrega_pecas WHERE entrega_item_id IN "
                   "(SELECT id FROM entrega_itens WHERE entrega_id = ?)", (entrega["id"],))
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
    """História 8: o dono fecha a entrega do veículo. Só com o orçamento aprovado, o veículo na etapa
    "Pronto para retirada", o tempo de garantia informado em TODOS os serviços e as condições que cancelam a garantia. A data de entrega é hoje.
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
    atual = etapa_atual(db, id)
    if atual != "PRONTO":
        erros.append(f"A entrega só pode ser fechada com o veículo na etapa \"{ETAPAS['PRONTO']}\" (agora está em "
                     f"\"{ETAPAS[atual]}\"). Mude a etapa em \"Etapa do serviço\" quando o reparo terminar.")
    faltam = sum(1 for s in servicos if s["garantia_valor"] is None)
    if faltam:
        erros.append("Informe o tempo de garantia de todos os serviços antes de fechar a entrega "
                     f"(falta{'m' if faltam != 1 else ''} {faltam}).")
    if any(s["garantia_valor"] for s in servicos) and sum(1 for letra in condicoes if letra.isalpha()) < 20:
        erros.append("Escreva as condições que cancelam a garantia (aparecem no comprovante do cliente).")
    if len(condicoes) > MAX_CONDICOES:
        erros.append(f"As condições podem ter no máximo {MAX_CONDICOES} letras.")
    # Fotos do veículo na entrega: obrigatórias (são a prova do estado em que o carro saiu)
    erros_fotos, fotos_entrega, enviadas = preparar_fotos_enviadas("fotos_entrega")
    erros += erros_fotos
    if not enviadas:
        erros.append("Tire ou escolha pelo menos uma foto do veículo na entrega: ela é a prova do estado em que o carro saiu.")
    if erros:
        if enviadas:
            erros.append("Por segurança do navegador, as fotos precisam ser escolhidas de novo.")
        return pagina_veiculo(id, erros, {"condicoes": condicoes})

    total = sum(s["valor_centavos"] + s["pecas_centavos"] for s in servicos)
    criados = []
    try:
        cursor = db.execute("INSERT INTO entregas (veiculo_id, data_entrega, condicoes, total_centavos, entregue_por) "
                            "VALUES (?, ?, ?, ?, ?)",
                            (id, hoje.isoformat(), condicoes or None, total, g.usuario["nome"]))
        for s in servicos:
            ate = fim_da_garantia(hoje, s["garantia_valor"], s["garantia_unidade"])
            item = db.execute("INSERT INTO entrega_itens (entrega_id, servico_id, tipo, problema, como_resolver, "
                              "valor_centavos, garantia_valor, garantia_unidade, garantia_ate, pecas_centavos) "
                              "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                              (cursor.lastrowid, s["id"], s["tipo"], s["problema"], s["como_resolver"],
                               s["valor_centavos"], s["garantia_valor"], s["garantia_unidade"],
                               ate.isoformat() if ate else None, s["pecas_centavos"]))
            db.execute("INSERT INTO entrega_pecas (entrega_item_id, nome, quantidade, preco_centavos) "
                       "SELECT ?, nome, quantidade, preco_centavos FROM servico_pecas WHERE servico_id = ? ORDER BY id",
                       (item.lastrowid, s["id"]))
        guardar_fotos(db, id, fotos_entrega, criados, momento="ENTREGA")
        db.commit()
    except sqlite3.IntegrityError:      # dois cliques ao mesmo tempo: só um fecha a entrega
        db.rollback()
        apagar_arquivos(criados)
        return pagina_veiculo(id, ["Este veículo já foi entregue."]), 409
    except Exception:
        db.rollback()
        apagar_arquivos(criados)        # não deixa foto "órfã" no disco
        raise
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
    fotos_entrega = [f["id"] for f in db.execute(
        "SELECT id FROM fotos WHERE veiculo_id = ? AND momento = 'ENTREGA' ORDER BY id", (id,))]
    pecas_entrega = {}
    for p in db.execute("SELECT ep.* FROM entrega_pecas ep JOIN entrega_itens ei ON ei.id = ep.entrega_item_id "
                        "WHERE ei.entrega_id = ? ORDER BY ep.id", (entrega["id"],)):
        pecas_entrega.setdefault(p["entrega_item_id"], []).append(p)
    return render_template("comprovante.html", pecas_entrega=pecas_entrega, veiculo=veiculo, entrega=entrega, itens=itens, aprovacao=aprovacao,
                           fotos_entrega=fotos_entrega,
                           formatar_data=formatar_data, formatar_dinheiro=formatar_dinheiro,
                           texto_garantia=texto_garantia, nomes_formas=NOMES_FORMAS_APROVACAO)


@app.route("/veiculos/<int:id>/etapa", methods=["POST"])
def registrar_etapa(id):
    """Dono e funcionário mudam a etapa do serviço (aguardando início, em reparo, pronto para retirada).
    Só dá para iniciar o reparo depois que o cliente aprovou o orçamento. Cada mudança fica guardada
    (quem e quando) e a última é a que vale."""
    db = get_db()
    buscar_veiculo(db, id)
    servicos = db.execute("SELECT * FROM servicos WHERE veiculo_id = ? ORDER BY id", (id,)).fetchall()
    ultima_aprovacao = db.execute("SELECT * FROM aprovacoes WHERE veiculo_id = ? ORDER BY id DESC LIMIT 1",
                                  (id,)).fetchone()
    atual = etapa_atual(db, id)
    nova = request.form.get("etapa", "")

    erros = []
    if nova not in ETAPAS:
        erros.append("Escolha a etapa.")
    elif nova not in MUDANCAS_DE_ETAPA[atual]:
        erros.append(f"O veículo está em \"{ETAPAS[atual]}\": não dá para ir direto para \"{ETAPAS[nova]}\".")
    elif nova == "EM_REPARO" and atual == "AGUARDANDO_INICIO" \
            and situacao_aprovacao(servicos, ultima_aprovacao)[0] != "APROVADO":
        erros.append("O reparo só pode começar depois que o cliente aprovar o orçamento.")
    if erros:
        return pagina_veiculo(id, erros)

    db.execute("INSERT INTO etapas (veiculo_id, etapa, registrado_por) VALUES (?, ?, ?)",
               (id, nova, g.usuario["nome"]))
    db.commit()
    return redirect(url_for("ver_veiculo", id=id))


@app.route("/veiculos/<int:id>/dados", methods=["POST"])
def registrar_dados_veiculo(id):
    """Dono e funcionário completam ou corrigem marca, modelo, cor, ano, quilometragem e chassi do veículo depois do
    cadastro (a pesquisa de peça na Web precisa da marca e do modelo). Placa e responsável não mudam aqui.
    Depois da entrega o cadastro fica travado. Se algum campo estiver inválido, nada é salvo."""
    db = get_db()
    buscar_veiculo(db, id)
    dados = {c: " ".join(request.form.get(c, "").split()) for c in ("marca", "modelo", "cor", "ano", "quilometragem", "motor")}
    chassi, erro_chassi = interpretar_chassi(request.form.get("chassi", ""))
    erros = [erro_chassi] if erro_chassi else []
    for campo, rotulo in (("marca", "A marca"), ("modelo", "O modelo"), ("cor", "A cor"),
                          ("quilometragem", "A quilometragem"), ("motor", "O motor")):
        if len(dados[campo]) > MAX_DADO_VEICULO:
            erros.append(f"{rotulo} pode ter no máximo {MAX_DADO_VEICULO} letras.")
    if dados["ano"]:
        achou = re.search(r"\d{4}", dados["ano"])
        if len(dados["ano"]) > 9 or not achou or not 1900 <= int(achou.group()) <= 2100:
            erros.append("O ano deve ter 4 números, entre 1900 e 2100 (exemplo: 2012 ou 2012/2013).")
    if erros:
        return pagina_veiculo(id, erros)
    db.execute("UPDATE veiculos SET marca = ?, modelo = ?, cor = ?, ano = ?, quilometragem = ?, chassi = ?, motor = ? "
               "WHERE id = ?",
               (dados["marca"], dados["modelo"], dados["cor"], dados["ano"], dados["quilometragem"], chassi or None,
                dados["motor"] or None, id))
    db.commit()
    return redirect(url_for("ver_veiculo", id=id))


@app.route("/veiculos/<int:id>/telefone", methods=["POST"])
def registrar_telefone(id):
    """Dono e funcionário informam ou corrigem o telefone (WhatsApp) do cliente. Pode ficar vazio."""
    db = get_db()
    buscar_veiculo(db, id)
    telefone, erro = normalizar_telefone(request.form.get("telefone", ""))
    if erro:
        return pagina_veiculo(id, [erro])
    db.execute("UPDATE veiculos SET telefone = ? WHERE id = ?", (telefone, id))
    db.commit()
    return redirect(url_for("ver_veiculo", id=id))


@app.route("/veiculos/<int:id>/excluir", methods=["POST"])
def excluir_veiculo(id):
    """Só o dono exclui um veículo cadastrado por engano ou de teste. O motivo é obrigatório.
    Some o veículo e tudo que era dele (serviços, aprovações, prazos, fotos e os arquivos das fotos);
    fica só o registro de que existiu, quem excluiu, quando e por quê.
    Não exclui veículo com entrega fechada nem com entregas desfeitas: ali há comprovante e prova
    do que foi combinado, e isso não se apaga."""
    so_dono()
    db = get_db()
    veiculo = buscar_veiculo(db, id)
    motivo = " ".join(request.form.get("motivo", "").split())

    erros = []
    if db.execute("SELECT 1 FROM entregas WHERE veiculo_id = ?", (id,)).fetchone():
        erros.append("Este veículo tem a entrega fechada e não pode ser excluído. "
                     "Se foi engano, desfaça a entrega primeiro.")
    elif db.execute("SELECT 1 FROM entregas_desfeitas WHERE veiculo_id = ?", (id,)).fetchone():
        erros.append("Este veículo já teve uma entrega (depois desfeita) e não pode ser excluído, "
                     "porque o histórico da entrega precisa ser guardado.")
    if sum(1 for letra in motivo if letra.isalpha()) < 3:
        erros.append("Explique o motivo de excluir o veículo.")
    elif len(motivo) > MAX_MOTIVO_EXCLUIR:
        erros.append(f"O motivo pode ter no máximo {MAX_MOTIVO_EXCLUIR} letras.")
    if erros:
        return pagina_veiculo(id, erros)

    codigos = [f["arquivo"] for f in db.execute("SELECT arquivo FROM fotos WHERE veiculo_id = ?", (id,))]
    try:
        db.execute("INSERT INTO veiculos_excluidos (veiculo_id, placa, responsavel, motivo, excluido_por) "
                   "VALUES (?, ?, ?, ?, ?)",
                   (id, veiculo["placa"], veiculo["responsavel"], motivo, g.usuario["nome"]))
        devolver_pecas(db, "veiculo_id = ?", (id,), "Veículo excluído")
        for tabela in ("fotos", "fotos_historico", "servicos", "aprovacoes", "prazos", "etapas"):
            db.execute(f"DELETE FROM {tabela} WHERE veiculo_id = ?", (id,))
        db.execute("DELETE FROM veiculos WHERE id = ?", (id,))
        db.commit()
    except Exception:
        db.rollback()
        raise
    for codigo in codigos:           # os arquivos só somem depois de gravar no banco
        apagar_arquivos_da_foto(codigo)
    return redirect(url_for("index", excluido=veiculo["placa"]))


@app.route("/veiculos/<int:id>/servicos/<int:servico_id>/excluir", methods=["POST"])
def excluir_servico(id, servico_id):
    """Só o dono apaga um problema registrado por engano."""
    so_dono()
    db = get_db()
    codigos = [f["arquivo"] for f in db.execute(
        "SELECT arquivo FROM fotos WHERE servico_id = ? AND veiculo_id = ? AND momento = 'PROBLEMA'",
        (servico_id, id))]
    devolver_pecas(db, "servico_id = ? AND veiculo_id = ?", (servico_id, id), "Serviço excluído")
    db.execute("DELETE FROM fotos WHERE servico_id = ? AND veiculo_id = ? AND momento = 'PROBLEMA'", (servico_id, id))
    db.execute("DELETE FROM servicos WHERE id = ? AND veiculo_id = ?", (servico_id, id))
    db.commit()
    for codigo in codigos:           # os arquivos das fotos do problema só somem depois de gravar no banco
        apagar_arquivos_da_foto(codigo)
    return redirect(url_for("ver_veiculo", id=id))


# ---------- ESTOQUE DE PEÇAS E TINTAS (história 9) ----------

NOMES_MOVIMENTO = {"INICIAL": "Estoque inicial", "ENTRADA": "Entrada", "SAIDA": "Uso em serviço",
                   "DEVOLUCAO": "Devolvida ao estoque", "AJUSTE": "Ajuste"}


def interpretar_quantidade(texto, minimo=1):
    """Número inteiro (só dígitos) entre 'minimo' e MAX_QUANTIDADE; devolve None se não servir."""
    texto = texto.strip()
    if not (texto.isascii() and texto.isdigit()) or len(texto) > 7:
        return None
    numero = int(texto)
    return numero if minimo <= numero <= MAX_QUANTIDADE else None


def mover_estoque(db, item_id, variacao, tipo, motivo=None, veiculo_id=None, servico_id=None):
    """Soma 'variacao' (positiva ou negativa) à quantidade do item e anota a movimentação.
    Não deixa o estoque ficar negativo: devolve False e não muda nada nesse caso."""
    cursor = db.execute("UPDATE estoque_itens SET quantidade = quantidade + ? WHERE id = ? AND quantidade + ? >= 0",
                        (variacao, item_id, variacao))
    if cursor.rowcount == 0:
        return False
    saldo = db.execute("SELECT quantidade FROM estoque_itens WHERE id = ?", (item_id,)).fetchone()[0]
    db.execute("INSERT INTO estoque_movimentos (item_id, tipo, variacao, saldo_apos, motivo, veiculo_id, servico_id, "
               "registrado_por) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
               (item_id, tipo, variacao, saldo, motivo, veiculo_id, servico_id, g.usuario["nome"]))
    return True


def recalcular_pecas(db, servico_id):
    """Atualiza a soma (em centavos) das peças usadas em um serviço."""
    db.execute("UPDATE servicos SET pecas_centavos = COALESCE((SELECT SUM(quantidade * preco_centavos) "
               "FROM servico_pecas WHERE servico_id = servicos.id), 0) WHERE id = ?", (servico_id,))


def devolver_pecas(db, condicao, parametros, motivo):
    """Devolve ao estoque as peças usadas nos serviços que casam com a condição (e apaga o uso delas).
    Usado quando um serviço ou um veículo é excluído: a peça não foi gasta, volta para a prateleira."""
    for p in db.execute(f"SELECT * FROM servico_pecas WHERE {condicao}", parametros).fetchall():
        mover_estoque(db, p["item_id"], p["quantidade"], "DEVOLUCAO", motivo, p["veiculo_id"], p["servico_id"])
    db.execute(f"DELETE FROM servico_pecas WHERE {condicao}", parametros)


def normalizar(texto):
    """Maiúsculas, sem acento e só letras e números: para comparar marca, modelo e busca."""
    sem_acento = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return "".join(c for c in sem_acento.upper() if c.isalnum())


def interpretar_aplicacoes(texto):
    """Lê o campo "serve para": uma linha por marca, no formato MARCA / MODELO / ANO (o ano é opcional e pode
    ser um período, como 2010-2015). Vários modelos da mesma marca e do mesmo ano podem ir na mesma linha,
    separados por vírgula ou ponto e vírgula (GM / MONZA, KADETT / 1983-1998). Cada modelo vira um carro.
    Devolve (lista de (marca, modelo, ano_de, ano_ate), erros)."""
    linhas, erros = [], []
    for numero, bruto in enumerate(texto.replace("\r", "").split("\n"), 1):
        linha = " ".join(bruto.split())
        if not linha:
            continue
        partes = [p.strip() for p in linha.split("/")]
        exemplo = f"Linha {numero} do campo \"serve para\": use MARCA / MODELO / ANO (exemplo: FIAT / UNO / 2010-2015)."
        modelos = [m.strip() for m in re.split(r"[,;]", partes[1])] if len(partes) >= 2 else []
        modelos = [m for m in modelos if m]
        if not 2 <= len(partes) <= 3 or not partes[0] or not modelos:
            erros.append(exemplo)
            continue
        if len(partes[0]) > MAX_TEXTO_ITEM or any(len(m) > MAX_TEXTO_ITEM for m in modelos):
            erros.append(f"Linha {numero} do campo \"serve para\": marca e modelo podem ter no máximo {MAX_TEXTO_ITEM} letras.")
            continue
        ano_de = ano_ate = None
        if len(partes) == 3 and partes[2]:
            achou = re.fullmatch(r"(\d{4})(?:\s*-\s*(\d{4}))?", partes[2])
            if not achou:
                erros.append(exemplo)
                continue
            ano_de, ano_ate = int(achou.group(1)), int(achou.group(2) or achou.group(1))
            if ano_ate < ano_de or ano_de < 1900 or ano_ate > 2100:
                erros.append(f"Linha {numero} do campo \"serve para\": confira os anos (de 1900 a 2100, do menor para o maior).")
                continue
        for modelo in modelos:
            carro = (partes[0].upper(), modelo.upper(), ano_de, ano_ate)
            if carro not in linhas:          # o mesmo carro repetido conta uma vez só
                linhas.append(carro)
    if len(linhas) > MAX_APLICACOES:
        erros.append(f"Informe no máximo {MAX_APLICACOES} carros por item.")
    return linhas, erros


def texto_aplicacao(a):
    """Uma aplicação como aparece na tela e no campo de edição: FIAT / UNO / 2010-2015."""
    ano = ""
    if a["ano_de"]:
        ano = str(a["ano_de"]) if a["ano_de"] == a["ano_ate"] else f"{a['ano_de']}-{a['ano_ate']}"
    return f"{a['marca']} / {a['modelo']}" + (f" / {ano}" if ano else "")


def aplicacoes_dos_itens(db):
    """Aplicações de todos os itens, agrupadas pelo código do item."""
    resultado = {}
    for a in db.execute("SELECT * FROM estoque_aplicacoes ORDER BY id"):
        resultado.setdefault(a["item_id"], []).append(a)
    return resultado


def serve_no_veiculo(aplicacoes, veiculo):
    """Alguma das aplicações do item combina com a marca, o modelo e o ano do veículo?
    O nome do modelo conta quando um contém o outro (UNO serve para UNO MILLE)."""
    marca, modelo = normalizar(veiculo["marca"]), normalizar(veiculo["modelo"])
    achou_ano = re.search(r"\d{4}", veiculo["ano"] or "")
    ano = int(achou_ano.group()) if achou_ano else None
    for a in aplicacoes:
        a_marca, a_modelo = normalizar(a["marca"]), normalizar(a["modelo"])
        if not (marca and modelo and a_marca and a_modelo):
            continue
        if not (a_marca in marca or marca in a_marca) or not (a_modelo in modelo or modelo in a_modelo):
            continue
        if ano and a["ano_de"] and not a["ano_de"] <= ano <= a["ano_ate"]:
            continue
        return True
    return False


def agrupar_por_aplicacao(itens, aplicacoes, veiculo):
    """Separa os itens para a lista "usar do estoque": os que servem no veículo vêm primeiro."""
    servem, sem_aplicacao, outros = [], [], []
    for i in itens:
        do_item = aplicacoes.get(i["id"], [])
        if not do_item:
            sem_aplicacao.append(i)
        elif serve_no_veiculo(do_item, veiculo):
            servem.append(i)
        else:
            outros.append(i)
    grupos = [("Serve neste veículo", servem), ("Sem carro informado (tintas e itens universais)", sem_aplicacao),
              ("Serve em outros carros", outros)]
    return [(titulo, lista) for titulo, lista in grupos if lista]


def pagina_estoque(erros=None, dados=None, status=200, editando=None, valores=None):
    db = get_db()
    itens = db.execute("SELECT * FROM estoque_itens WHERE ativo = 1 ORDER BY tipo, nome").fetchall()
    aplicacoes = aplicacoes_dos_itens(db)
    busca = " ".join(request.args.get("q", "").split())[:80]
    total_itens = len(itens)
    if busca:             # procura o texto no nome, categoria, fabricante, código e nos carros do item
        alvo = normalizar(busca)
        itens = [i for i in itens if alvo in normalizar(" ".join(
            [i["nome"], i["categoria"] or "", i["fabricante"] or "", i["codigo"] or ""]
            + [texto_aplicacao(a) for a in aplicacoes.get(i["id"], [])]))]
    inativos = db.execute("SELECT * FROM estoque_itens WHERE ativo = 0 ORDER BY tipo, nome").fetchall()
    movimentos = db.execute(
        "SELECT m.*, i.nome, v.placa FROM estoque_movimentos m JOIN estoque_itens i ON i.id = m.item_id "
        "LEFT JOIN veiculos v ON v.id = m.veiculo_id ORDER BY m.id DESC LIMIT 40").fetchall()
    valor_custo = sum(i["quantidade"] * i["custo_centavos"] for i in itens)
    valor_venda = sum(i["quantidade"] * i["preco_centavos"] for i in itens)
    return render_template("estoque.html", editando=editando, valores=valores or {}, salvo=bool(request.args.get("salvo")),
                           itens=itens, inativos=inativos, movimentos=movimentos,
                           aplicacoes=aplicacoes, texto_aplicacao=texto_aplicacao, busca=busca,
                           total_itens=total_itens, categorias=CATEGORIAS_SUGERIDAS, max_texto=MAX_TEXTO_ITEM,
                           max_aplicacoes=MAX_APLICACOES,
                           valor_custo=valor_custo, valor_venda=valor_venda, tipos=TIPOS_ESTOQUE,
                           nomes_movimento=NOMES_MOVIMENTO, formatar_dinheiro=formatar_dinheiro,
                           max_nome=MAX_NOME_ITEM, max_quantidade=MAX_QUANTIDADE, max_motivo=MAX_MOTIVO_ESTOQUE,
                           erros=erros or [], dados=dados or {}), status


@app.route("/estoque")
def estoque():
    return pagina_estoque()


def ler_dados_do_item(db, item_id=None, com_quantidade=False):
    """Lê e confere o formulário de um item do estoque. Devolve (erros, dados)."""
    nome = " ".join(request.form.get("nome", "").split())
    tipo = request.form.get("tipo", "").strip().upper()
    texto_custo = request.form.get("custo", "").strip()
    custo = 0 if not texto_custo else interpretar_valor(texto_custo)
    preco = interpretar_valor(request.form.get("preco", ""))
    minimo = 0 if not request.form.get("minimo", "").strip() else interpretar_quantidade(request.form["minimo"], 0)
    quantidade = 0
    erros = []
    categoria, fabricante, codigo = (" ".join(request.form.get(c, "").split()) for c in ("categoria", "fabricante", "codigo"))
    for rotulo, valor in (("categoria", categoria), ("fabricante", fabricante), ("código", codigo)):
        if len(valor) > MAX_TEXTO_ITEM:
            erros.append(f"O campo {rotulo} pode ter no máximo {MAX_TEXTO_ITEM} letras.")
    aplicacoes, erros_aplicacao = interpretar_aplicacoes(request.form.get("aplicacoes", ""))
    erros += erros_aplicacao
    if sum(1 for letra in nome if letra.isalnum()) < 2:
        erros.append("Informe o nome do item (exemplo: Pastilha de freio dianteira).")
    elif len(nome) > MAX_NOME_ITEM:
        erros.append(f"O nome pode ter no máximo {MAX_NOME_ITEM} letras.")
    if tipo not in TIPOS_ESTOQUE:
        erros.append("Escolha se o item é peça ou tinta.")
    if com_quantidade and request.form.get("quantidade", "").strip():
        quantidade = interpretar_quantidade(request.form["quantidade"], 0)
        if quantidade is None:
            erros.append(f"A quantidade deve ser um número inteiro de 0 a {MAX_QUANTIDADE}.")
    if minimo is None:
        erros.append(f"O estoque mínimo deve ser um número inteiro de 0 a {MAX_QUANTIDADE}.")
    if custo is None:
        erros.append("O custo deve ser um valor válido (exemplo: 35,00) ou ficar vazio.")
    if preco is None:
        erros.append("Informe o preço de venda (exemplo: 60,00).")
    if not erros:
        repetido = db.execute("SELECT 1 FROM estoque_itens WHERE UPPER(nome) = ? AND tipo = ? AND id IS NOT ?",
                              (nome.upper(), tipo, item_id)).fetchone()
        if repetido:
            erros.append("Já existe um item com esse nome e esse tipo. Dê entrada nele em vez de cadastrar de novo.")
    return erros, {"nome": nome, "tipo": tipo, "quantidade": quantidade, "minimo": minimo, "custo": custo, "preco": preco,
                   "categoria": categoria or None, "fabricante": fabricante or None, "codigo": codigo or None,
                   "aplicacoes": aplicacoes,
                   "texto": {k: request.form.get(k, "") for k in ("nome", "tipo", "quantidade", "minimo", "custo", "preco",
                                                                  "categoria", "fabricante", "codigo", "aplicacoes")}}


def gravar_aplicacoes(db, item_id, aplicacoes):
    db.execute("DELETE FROM estoque_aplicacoes WHERE item_id = ?", (item_id,))
    db.executemany("INSERT INTO estoque_aplicacoes (item_id, marca, modelo, ano_de, ano_ate) VALUES (?, ?, ?, ?, ?)",
                   [(item_id,) + tuple(a) for a in aplicacoes])


@app.route("/estoque/novo", methods=["POST"])
def cadastrar_item():
    """Só o dono cadastra itens: é ele quem define custo e preço."""
    so_dono()
    db = get_db()
    erros, d = ler_dados_do_item(db, com_quantidade=True)
    if erros:
        return pagina_estoque(erros, d["texto"])
    cursor = db.execute("INSERT INTO estoque_itens (nome, tipo, minimo, custo_centavos, preco_centavos, criado_por, "
                        "categoria, fabricante, codigo) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (d["nome"], d["tipo"], d["minimo"], d["custo"], d["preco"], g.usuario["nome"],
                         d["categoria"], d["fabricante"], d["codigo"]))
    gravar_aplicacoes(db, cursor.lastrowid, d["aplicacoes"])
    if d["quantidade"]:
        mover_estoque(db, cursor.lastrowid, d["quantidade"], "INICIAL", "Cadastro do item")
    db.commit()
    return redirect(url_for("estoque", salvo=1))


def buscar_item(db, id):
    item = db.execute("SELECT * FROM estoque_itens WHERE id = ?", (id,)).fetchone()
    if not item:
        abort(404)
    return item


@app.route("/estoque/<int:id>/editar", methods=["POST"])
def editar_item(id):
    """Muda nome, categoria, fabricante, código, carros em que serve, estoque mínimo, custo e preço. O preço novo só vale para usos futuros: o que já foi
    colocado em um orçamento guarda o preço da hora. Só o dono edita (custo e preço são dele)."""
    so_dono()
    db = get_db()
    buscar_item(db, id)
    erros, d = ler_dados_do_item(db, item_id=id)
    if erros:
        # Nada é salvo; o formulário do item continua aberto, com o que a pessoa digitou
        return pagina_estoque([f"Nada foi salvo no item {buscar_item(db, id)['nome']}. Corrija e salve de novo:"] + erros,
                              editando=id, valores=d["texto"])
    db.execute("UPDATE estoque_itens SET nome = ?, tipo = ?, minimo = ?, custo_centavos = ?, preco_centavos = ?, "
               "categoria = ?, fabricante = ?, codigo = ? WHERE id = ?",
               (d["nome"], d["tipo"], d["minimo"], d["custo"], d["preco"], d["categoria"], d["fabricante"],
                d["codigo"], id))
    gravar_aplicacoes(db, id, d["aplicacoes"])
    db.commit()
    return redirect(url_for("estoque", salvo=1))


@app.route("/estoque/<int:id>/entrada", methods=["POST"])
def entrada_estoque(id):
    db = get_db()
    item = buscar_item(db, id)
    quantidade = interpretar_quantidade(request.form.get("quantidade", ""))
    motivo = " ".join(request.form.get("motivo", "").split())
    erros = []
    if quantidade is None:
        erros.append(f"A quantidade que entrou deve ser um número inteiro de 1 a {MAX_QUANTIDADE}.")
    elif item["quantidade"] + quantidade > MAX_QUANTIDADE:
        erros.append(f"O estoque de um item não pode passar de {MAX_QUANTIDADE}.")
    if len(motivo) > MAX_MOTIVO_ESTOQUE:
        erros.append(f"A observação pode ter no máximo {MAX_MOTIVO_ESTOQUE} letras.")
    if erros:
        return pagina_estoque(erros)
    mover_estoque(db, id, quantidade, "ENTRADA", motivo or None)
    db.commit()
    return redirect(url_for("estoque", salvo=1))


@app.route("/estoque/<int:id>/ajuste", methods=["POST"])
def ajuste_estoque(id):
    """Corrige a quantidade para o que foi contado na prateleira (perda, quebra, contagem). O motivo é obrigatório."""
    db = get_db()
    item = buscar_item(db, id)
    contada = interpretar_quantidade(request.form.get("quantidade", ""), 0)
    motivo = " ".join(request.form.get("motivo", "").split())
    erros = []
    if contada is None:
        erros.append(f"A quantidade contada deve ser um número inteiro de 0 a {MAX_QUANTIDADE}.")
    elif contada == item["quantidade"]:
        erros.append("A quantidade contada é igual à do sistema: não há o que ajustar.")
    if sum(1 for letra in motivo if letra.isalpha()) < 3:
        erros.append("Explique o motivo do ajuste (exemplo: contagem, peça quebrada).")
    elif len(motivo) > MAX_MOTIVO_ESTOQUE:
        erros.append(f"O motivo pode ter no máximo {MAX_MOTIVO_ESTOQUE} letras.")
    if erros:
        return pagina_estoque(erros)
    mover_estoque(db, id, contada - item["quantidade"], "AJUSTE", motivo)
    db.commit()
    return redirect(url_for("estoque", salvo=1))


@app.route("/estoque/<int:id>/alternar", methods=["POST"])
def alternar_item(id):
    """Só o dono tira um item de uso (ou volta com ele). O item e o histórico dele continuam guardados."""
    so_dono()
    db = get_db()
    item = buscar_item(db, id)
    db.execute("UPDATE estoque_itens SET ativo = ? WHERE id = ?", (0 if item["ativo"] else 1, id))
    db.commit()
    return redirect(url_for("estoque", salvo=1))


@app.route("/veiculos/<int:id>/servicos/<int:servico_id>/pecas", methods=["POST"])
def usar_peca(id, servico_id):
    """Usa uma peça ou tinta do estoque em um serviço: baixa no estoque e soma o preço ao orçamento."""
    db = get_db()
    buscar_veiculo(db, id)
    servico = db.execute("SELECT id FROM servicos WHERE id = ? AND veiculo_id = ?", (servico_id, id)).fetchone()
    if not servico:
        abort(404)
    texto_item = request.form.get("item_id", "")
    item = db.execute("SELECT * FROM estoque_itens WHERE id = ? AND ativo = 1",
                      (int(texto_item) if texto_item.isascii() and texto_item.isdigit() else 0,)).fetchone()
    quantidade = interpretar_quantidade(request.form.get("quantidade", ""))
    if not item:
        return pagina_veiculo(id, ["Escolha uma peça ou tinta do estoque."])
    if quantidade is None:
        return pagina_veiculo(id, ["Informe a quantidade usada (número inteiro, a partir de 1)."])
    if not mover_estoque(db, item["id"], -quantidade, "SAIDA", None, id, servico_id):
        db.rollback()
        return pagina_veiculo(id, [f"Não há estoque suficiente de {item['nome']}: restam {item['quantidade']}."])
    db.execute("INSERT INTO servico_pecas (servico_id, veiculo_id, item_id, nome, quantidade, preco_centavos, "
               "custo_centavos, registrado_por) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
               (servico_id, id, item["id"], item["nome"], quantidade, item["preco_centavos"],
                item["custo_centavos"], g.usuario["nome"]))
    recalcular_pecas(db, servico_id)
    db.commit()
    return redirect(url_for("ver_veiculo", id=id))


@app.route("/veiculos/<int:id>/servicos/<int:servico_id>/pecas/<int:peca_id>/devolver", methods=["POST"])
def devolver_peca(id, servico_id, peca_id):
    """Tira a peça do serviço (foi colocada por engano ou não foi usada): ela volta para o estoque."""
    db = get_db()
    buscar_veiculo(db, id)
    peca = db.execute("SELECT * FROM servico_pecas WHERE id = ? AND servico_id = ? AND veiculo_id = ?",
                      (peca_id, servico_id, id)).fetchone()
    if not peca:
        abort(404)
    mover_estoque(db, peca["item_id"], peca["quantidade"], "DEVOLUCAO", "Tirada do serviço", id, servico_id)
    db.execute("DELETE FROM servico_pecas WHERE id = ?", (peca_id,))
    recalcular_pecas(db, servico_id)
    db.commit()
    return redirect(url_for("ver_veiculo", id=id))


if __name__ == "__main__":
    app.run(debug=True)
