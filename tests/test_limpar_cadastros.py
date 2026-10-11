"""Testes da ferramenta que limpa todos os cadastros de veículos (limpar_cadastros.py).
Rodar na pasta do projeto:  python -m unittest discover tests -v"""
import contextlib
import io
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing

from base import oficina
from test_fotos_entrega import Base

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import limpar_cadastros as ferramenta  # noqa: E402


class LimparCadastrosTest(Base):
    def setUp(self):
        super().setUp()
        self.fechar()                                                     # ficha entregue, com fotos e garantia
        self.dono_c.post(f"/veiculos/{self.vid}/pagamentos", data={"valor": "50,00", "forma": "PIX"})
        self.sql("INSERT INTO avisos (veiculo_id, tipo, feito_por) VALUES (?, 'NAO_AVISAR', 'TESTE')", (self.vid,))
        self.sql("INSERT INTO estoque_itens (nome, tipo, quantidade, preco_centavos) VALUES ('TINTA BRANCA', 'TINTA', 5, 5000)")
        item = self.sql("SELECT id FROM estoque_itens")[0]["id"]
        self.sql("INSERT INTO estoque_movimentos (item_id, tipo, variacao, saldo_apos, veiculo_id, servico_id) "
                 "VALUES (?, 'SAIDA', -1, 4, ?, ?)", (item, self.vid, self.sid))
        self.dono_c.post("/profissionais", data={"nome": "CARLOS", "percentual": "30"})
        # Trabalha numa CÓPIA do banco e das fotos, para o teste não mexer nos arquivos de teste dos outros testes
        self.pasta = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.pasta, True)
        self.banco = os.path.join(self.pasta, "copia.db")
        with closing(sqlite3.connect(oficina.DATABASE)) as de, closing(sqlite3.connect(self.banco)) as para:
            de.backup(para)
        self.fotos = os.path.join(self.pasta, "fotos")
        shutil.copytree(oficina.PASTA_FOTOS, self.fotos)
        for nome, valor in (("BANCO", self.banco), ("PASTA_FOTOS", self.fotos)):
            antigo = getattr(ferramenta, nome)
            setattr(ferramenta, nome, valor)
            self.addCleanup(setattr, ferramenta, nome, antigo)

    def rodar(self, argumentos, resposta=""):
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            codigo = ferramenta.principal(argumentos, entrada=lambda _: resposta)
        return codigo, saida.getvalue()

    def contar(self, tabela, banco=None):
        with closing(sqlite3.connect(banco or self.banco)) as b:
            return b.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0]

    def test_sem_executar_so_mostra_e_nao_muda_nada(self):
        codigo, texto = self.rodar([])
        self.assertEqual(codigo, 0)
        self.assertIn("Nada foi alterado", texto)
        self.assertIn("veiculos: 1", texto)
        self.assertEqual(self.contar("veiculos"), 1)
        self.assertTrue(os.listdir(self.fotos))

    def test_frase_errada_nao_apaga(self):
        codigo, texto = self.rodar(["--executar"], resposta="apagar")
        self.assertEqual(codigo, 1)
        self.assertIn("Nada foi alterado", texto)
        self.assertEqual(self.contar("veiculos"), 1)
        self.assertTrue(os.listdir(self.fotos))
        self.assertEqual([n for n in os.listdir(self.pasta) if "antes-da-limpeza" in n], [])

    def test_executar_apaga_os_cadastros_e_mantem_o_resto(self):
        codigo, texto = self.rodar(["--executar"], resposta="APAGAR TUDO")
        self.assertEqual(codigo, 0)
        for tabela in ferramenta.APAGAR:
            self.assertEqual(self.contar(tabela), 0, tabela)
        self.assertEqual(self.contar("usuarios"), 2)
        self.assertEqual(self.contar("estoque_itens"), 1)
        self.assertEqual(self.contar("profissionais"), 1)
        with closing(sqlite3.connect(self.banco)) as b:
            b.row_factory = sqlite3.Row
            movimento = b.execute("SELECT * FROM estoque_movimentos").fetchone()
            self.assertIsNone(movimento["veiculo_id"])
            self.assertIsNone(movimento["servico_id"])
            self.assertEqual(b.execute("SELECT quantidade FROM estoque_itens").fetchone()[0], 5)
        self.assertIn("Pronto", texto)

    def test_guarda_copia_do_banco_e_move_as_fotos(self):
        fotos_antes = sorted(os.listdir(self.fotos))
        self.assertTrue(fotos_antes)
        self.rodar(["--executar"], resposta="APAGAR TUDO")
        copias = [n for n in os.listdir(self.pasta) if n.endswith(".db") and "antes-da-limpeza" in n]
        self.assertEqual(len(copias), 1)
        self.assertEqual(self.contar("veiculos", os.path.join(self.pasta, copias[0])), 1)        # a cópia tem tudo
        pastas = [n for n in os.listdir(self.pasta) if n.startswith("fotos-antes-da-limpeza")]
        self.assertEqual(len(pastas), 1)
        self.assertEqual(sorted(os.listdir(os.path.join(self.pasta, pastas[0]))), fotos_antes)
        self.assertEqual(os.listdir(self.fotos), [])                                              # pasta nova, vazia

    def test_numeracao_das_fichas_recomeca_do_um(self):
        self.rodar(["--executar"], resposta="APAGAR TUDO")
        with closing(sqlite3.connect(self.banco)) as b:
            b.execute("INSERT INTO veiculos (placa, documento_deixado) VALUES ('NOV1A23', 1)")
            self.assertEqual(b.execute("SELECT id FROM veiculos").fetchone()[0], 1)

    def test_limpar_duas_vezes_e_seguro(self):
        self.rodar(["--executar"], resposta="APAGAR TUDO")
        codigo, _ = self.rodar(["--executar"], resposta="APAGAR TUDO")
        self.assertEqual(codigo, 0)
        self.assertEqual(self.contar("usuarios"), 2)

    def test_banco_inexistente(self):
        ferramenta.BANCO = os.path.join(self.pasta, "nao-existe.db")
        codigo, texto = self.rodar([])
        self.assertEqual(codigo, 1)
        self.assertIn("Não achei o banco", texto)

    def test_mover_fotos_sem_pasta_cria_uma_vazia(self):
        nova = os.path.join(self.pasta, "outra-fotos")
        self.assertIsNone(ferramenta.mover_fotos(nova, "x"))
        self.assertTrue(os.path.isdir(nova))


if __name__ == "__main__":
    unittest.main()
