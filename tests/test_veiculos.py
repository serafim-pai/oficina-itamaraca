"""Testes do cadastro de veículo. Rodar na pasta do projeto:  python -m unittest discover tests -v
Usam um banco temporário, então os dados reais nunca são tocados."""
import os
import sqlite3
import tempfile
import unittest

_pasta = tempfile.mkdtemp()
os.environ["OFICINA_DB"] = os.path.join(_pasta, "teste.db")   # tem que vir ANTES de importar o sistema

import app as oficina   # noqa: E402

DADOS = {"responsavel": "JOSE", "placa": "ABC1D23", "marca": "FIAT", "modelo": "UNO",
         "cor": "PRETO", "ano": "2012", "quilometragem": "150000", "documento_deixado": "on"}


class VeiculoTest(unittest.TestCase):
    def setUp(self):
        with sqlite3.connect(oficina.DATABASE) as banco:
            banco.execute("DELETE FROM veiculos")
        self.c = oficina.app.test_client()

    def total(self):
        with sqlite3.connect(oficina.DATABASE) as banco:
            return banco.execute("SELECT COUNT(*) FROM veiculos").fetchone()[0]

    def test_tabela_e_criada_ao_carregar_o_sistema(self):
        self.assertEqual(self.c.get("/").status_code, 200)

    def test_cadastra_veiculo_completo(self):
        r = self.c.post("/veiculos", data=DADOS)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.total(), 1)
        self.assertIn(b"ABC1D23", self.c.get("/").data)

    def test_nao_salva_sem_placa(self):
        r = self.c.post("/veiculos", data={**DADOS, "placa": "  "})
        self.assertEqual(r.status_code, 200)
        self.assertIn("A placa é obrigatória.".encode(), r.data)
        self.assertEqual(self.total(), 0)

    def test_nao_salva_sem_documento_deixado(self):
        dados = {k: v for k, v in DADOS.items() if k != "documento_deixado"}
        r = self.c.post("/veiculos", data=dados)
        self.assertIn("documento do carro".encode(), r.data)
        self.assertEqual(self.total(), 0)

    def test_mantem_o_que_foi_digitado_quando_da_erro(self):
        r = self.c.post("/veiculos", data={**DADOS, "placa": ""})
        self.assertIn(b'value="FIAT"', r.data)

    def test_html_digitado_nao_vira_codigo(self):
        self.c.post("/veiculos", data={**DADOS, "responsavel": "<script>alert(1)</script>"})
        self.assertNotIn(b"<script>alert(1)</script>", self.c.get("/").data)


if __name__ == "__main__":
    unittest.main()
