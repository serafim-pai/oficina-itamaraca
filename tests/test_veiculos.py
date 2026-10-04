"""Testes do cadastro de veículo (agora só para quem entrou).
Rodar na pasta do projeto:  python -m unittest discover tests -v"""
import unittest

from base import BaseTest

DADOS = {"responsavel": "JOSE", "placa": "ABC1D23", "marca": "FIAT", "modelo": "UNO",
         "cor": "PRETO", "ano": "2012", "quilometragem": "150000", "documento_deixado": "on"}


class VeiculoTest(BaseTest):
    def setUp(self):
        super().setUp()
        self.c = self.funcionario()

    def test_pagina_inicial_abre(self):
        self.assertEqual(self.c.get("/").status_code, 200)

    def test_cadastra_veiculo_completo(self):
        r = self.c.post("/veiculos", data=DADOS)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.total_veiculos(), 1)
        self.assertIn(b"ABC1D23", self.c.get("/").data)

    def test_nao_salva_sem_placa(self):
        r = self.c.post("/veiculos", data={**DADOS, "placa": "  "})
        self.assertEqual(r.status_code, 200)
        self.assertIn("A placa é obrigatória.".encode(), r.data)
        self.assertEqual(self.total_veiculos(), 0)

    def test_nao_salva_sem_documento_deixado(self):
        dados = {k: v for k, v in DADOS.items() if k != "documento_deixado"}
        r = self.c.post("/veiculos", data=dados)
        self.assertIn("documento do carro".encode(), r.data)
        self.assertEqual(self.total_veiculos(), 0)

    def test_mantem_o_que_foi_digitado_quando_da_erro(self):
        r = self.c.post("/veiculos", data={**DADOS, "placa": ""})
        self.assertIn(b'value="FIAT"', r.data)

    def test_html_digitado_nao_vira_codigo(self):
        self.c.post("/veiculos", data={**DADOS, "responsavel": "<script>alert(1)</script>"})
        self.assertNotIn(b"<script>alert(1)</script>", self.c.get("/").data)


if __name__ == "__main__":
    unittest.main()
