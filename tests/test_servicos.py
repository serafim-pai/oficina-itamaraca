"""Testes da história 3: registrar os problemas e os tipos de serviço de um veículo.
Rodar na pasta do projeto:  python -m unittest discover tests -v"""
import unittest

from base import BaseTest

VEICULO = {"responsavel": "JOSE", "placa": "ABC1D23", "marca": "FIAT", "modelo": "UNO",
           "documento_deixado": "on"}
SERVICO = {"tipo": "LATARIA", "problema": "Amassado na porta do motorista"}


class ServicoTest(BaseTest):
    def setUp(self):
        super().setUp()
        self.c = self.funcionario()
        self.c.post("/veiculos", data=VEICULO)
        self.vid = self.sql("SELECT id FROM veiculos")[0]["id"]

    def total(self):
        return self.sql("SELECT COUNT(*) AS n FROM servicos")[0]["n"]

    def test_pagina_do_veiculo_abre(self):
        r = self.c.get(f"/veiculos/{self.vid}")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"ABC1D23", r.data)

    def test_veiculo_inexistente_da_404(self):
        self.assertEqual(self.c.get("/veiculos/9999").status_code, 404)
        self.assertEqual(self.c.post("/veiculos/9999/servicos", data=SERVICO).status_code, 404)

    def test_registra_problema_com_tipo(self):
        r = self.c.post(f"/veiculos/{self.vid}/servicos", data=SERVICO)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.total(), 1)
        pagina = self.c.get(f"/veiculos/{self.vid}").data
        self.assertIn(b"LATARIA", pagina)
        self.assertIn(b"Amassado na porta", pagina)

    def test_guarda_quem_registrou(self):
        self.c.post(f"/veiculos/{self.vid}/servicos", data=SERVICO)
        self.assertEqual(self.sql("SELECT registrado_por FROM servicos")[0]["registrado_por"], "PESSOA TESTE")

    def test_aceita_varios_problemas_no_mesmo_veiculo(self):
        self.c.post(f"/veiculos/{self.vid}/servicos", data=SERVICO)
        self.c.post(f"/veiculos/{self.vid}/servicos", data={"tipo": "PINTURA", "problema": "Risco no capô"})
        self.assertEqual(self.total(), 2)

    def test_nao_salva_sem_tipo(self):
        r = self.c.post(f"/veiculos/{self.vid}/servicos", data={**SERVICO, "tipo": ""})
        self.assertIn("Escolha o tipo de serviço.".encode(), r.data)
        self.assertEqual(self.total(), 0)

    def test_nao_aceita_tipo_inventado(self):
        self.c.post(f"/veiculos/{self.vid}/servicos", data={**SERVICO, "tipo": "HACKER"})
        self.assertEqual(self.total(), 0)

    def test_nao_salva_sem_descricao(self):
        r = self.c.post(f"/veiculos/{self.vid}/servicos", data={**SERVICO, "problema": "   "})
        self.assertIn("Descreva o problema".encode(), r.data)
        self.assertEqual(self.total(), 0)

    def test_nao_aceita_descricao_enorme(self):
        self.c.post(f"/veiculos/{self.vid}/servicos", data={**SERVICO, "problema": "a" * 501})
        self.assertEqual(self.total(), 0)

    def test_mantem_o_que_foi_digitado_quando_da_erro(self):
        r = self.c.post(f"/veiculos/{self.vid}/servicos", data={**SERVICO, "tipo": ""})
        self.assertIn(b"Amassado na porta", r.data)

    def test_html_digitado_nao_vira_codigo(self):
        self.c.post(f"/veiculos/{self.vid}/servicos",
                    data={**SERVICO, "problema": "<script>alert(1)</script> teste"})
        self.assertNotIn(b"<script>alert(1)</script>", self.c.get(f"/veiculos/{self.vid}").data)

    def test_sem_login_nao_registra(self):
        anonimo = self.entrar_como(0)
        r = anonimo.post(f"/veiculos/{self.vid}/servicos", data=SERVICO)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.total(), 0)

    def test_funcionario_nao_exclui(self):
        self.c.post(f"/veiculos/{self.vid}/servicos", data=SERVICO)
        sid = self.sql("SELECT id FROM servicos")[0]["id"]
        r = self.c.post(f"/veiculos/{self.vid}/servicos/{sid}/excluir")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.total(), 1)

    def test_dono_exclui(self):
        self.c.post(f"/veiculos/{self.vid}/servicos", data=SERVICO)
        sid = self.sql("SELECT id FROM servicos")[0]["id"]
        dono = self.dono()
        self.assertEqual(dono.post(f"/veiculos/{self.vid}/servicos/{sid}/excluir").status_code, 302)
        self.assertEqual(self.total(), 0)


if __name__ == "__main__":
    unittest.main()
