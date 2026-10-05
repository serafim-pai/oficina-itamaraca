import os
import re
import secrets
import sqlite3
from datetime import timedelta
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

def pagina_inicial(erros=None, dados=None):
    """Desenha a tela de cadastro com a lista de veículos e as fotos de cada um."""
    db = get_db()
    veiculos = db.execute("SELECT * FROM veiculos ORDER BY id DESC").fetchall()
    fotos = {}
    for foto in db.execute("SELECT id, veiculo_id FROM fotos ORDER BY id"):
        fotos.setdefault(foto["veiculo_id"], []).append(foto["id"])
    return render_template("index.html", veiculos=veiculos, fotos=fotos, erros=erros or [],
                           dados=dados or {}, max_fotos=MAX_FOTOS,
                           max_mb=MAX_BYTES_FOTO // (1024 * 1024))


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
    return render_template("veiculo.html", veiculo=veiculo, servicos=servicos, fotos=fotos,
                           tipos=TIPOS_SERVICO, max_problema=MAX_PROBLEMA,
                           erros=erros or [], dados=dados or {},
                           total_centavos=total_centavos, faltam_valor=faltam,
                           orcamento_completo=orcamento_completo, formatar_dinheiro=formatar_dinheiro)


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
