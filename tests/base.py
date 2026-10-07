"""Preparação comum dos testes: banco temporário e atalhos para criar usuários e entrar.
Os dados reais nunca são tocados."""
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from io import BytesIO

_pasta = tempfile.mkdtemp()
os.environ["OFICINA_DB"] = os.path.join(_pasta, "teste.db")   # tem que vir ANTES de importar o sistema
os.environ["OFICINA_FOTOS"] = os.path.join(_pasta, "fotos")
os.environ["OFICINA_SECRET"] = "segredo-so-dos-testes"
os.environ.pop("OFICINA_CODIGO_INICIAL", None)

from werkzeug.security import generate_password_hash   # noqa: E402
import app as oficina                                   # noqa: E402

def foto_de_entrega(nome="entrega.jpg", tamanho=(200, 100), cor=(30, 120, 200)):
    """Uma foto de verdade (para o campo 'fotos do veículo na entrega' dos testes)."""
    from PIL import Image
    memoria = BytesIO()
    Image.new("RGB", tamanho, cor).save(memoria, "JPEG")
    memoria.seek(0)
    return memoria, nome


SENHA = "senha1234"
HASH = generate_password_hash(SENHA, method="pbkdf2:sha256")   # calculado uma vez só (é lento de propósito)


class BaseTest(unittest.TestCase):
    csrf = False   # os testes de CSRF ligam isto

    def setUp(self):
        oficina.app.config["TESTING"] = True
        oficina.app.config["WTF_CSRF_ENABLED"] = self.csrf
        for tabela in ("veiculos", "usuarios", "tentativas_login", "fotos", "servicos", "aprovacoes", "prazos",
                       "entregas", "entrega_itens", "limites_garantia", "entregas_desfeitas",
                       "entrega_itens_desfeitos", "fotos_historico", "veiculos_excluidos", "etapas"):
            self.sql(f"DELETE FROM {tabela}")
        for arquivo in os.listdir(oficina.PASTA_FOTOS):
            os.remove(os.path.join(oficina.PASTA_FOTOS, arquivo))
        self.c = oficina.app.test_client()

    # ---- atalhos ----
    def sql(self, comando, parametros=()):
        with closing(sqlite3.connect(oficina.DATABASE)) as banco:
            banco.row_factory = sqlite3.Row
            linhas = banco.execute(comando, parametros).fetchall()
            banco.commit()
            return linhas

    def criar_usuario(self, email, tipo="FUNCIONARIO", ativo=1, nome="PESSOA TESTE"):
        with closing(sqlite3.connect(oficina.DATABASE)) as banco:
            novo_id = banco.execute(
                "INSERT INTO usuarios (nome, email, senha_hash, tipo, ativo) VALUES (?, ?, ?, ?, ?)",
                (nome, email, HASH, tipo, ativo)).lastrowid
            banco.commit()
            return novo_id

    def entrar_como(self, usuario_id):
        """Devolve um navegador de teste já logado (sem passar pela tela de login)."""
        cliente = oficina.app.test_client()
        with cliente.session_transaction() as sessao:
            sessao["usuario_id"] = usuario_id
        return cliente

    def dono(self):
        self.dono_id = self.criar_usuario("dono@teste.com", "DONO", nome="DONA MARIA")
        return self.entrar_como(self.dono_id)

    def funcionario(self):
        return self.entrar_como(self.criar_usuario("func@teste.com", "FUNCIONARIO"))

    def total_veiculos(self):
        return self.sql("SELECT COUNT(*) AS n FROM veiculos")[0]["n"]
