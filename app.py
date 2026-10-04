import os
import sqlite3

from flask import Flask, g, redirect, render_template, request, url_for

# O banco fica ao lado deste arquivo, de onde quer que o sistema seja ligado
# (na hospedagem online a pasta de trabalho é outra). OFICINA_DB troca o caminho nos testes.
DATABASE = os.environ.get("OFICINA_DB") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "oficina.db"
)

app = Flask(__name__)


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
    db.commit()
    db.close()


# Cria a tabela ao carregar o sistema (também na hospedagem, que não roda o bloco abaixo)
init_db()


@app.route("/")
def index():
    db = get_db()
    veiculos = db.execute("SELECT * FROM veiculos ORDER BY id DESC").fetchall()
    return render_template("index.html", veiculos=veiculos, erros=[], dados={})


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

    if erros:
        db = get_db()
        veiculos = db.execute("SELECT * FROM veiculos ORDER BY id DESC").fetchall()
        return render_template(
            "index.html", veiculos=veiculos, erros=erros, dados=dados
        )

    db = get_db()
    db.execute(
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
    db.commit()
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True)
