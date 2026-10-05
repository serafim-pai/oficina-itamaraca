"""Testes da história 5: montar o orçamento (valor de cada serviço registrado).
Rodar na pasta do projeto:  python -m unittest discover tests -v"""
import unittest

from base import BaseTest

VEICULO = {"responsavel": "JOSE", "placa": "ABC1D23", "marca": "FIAT", "modelo": "UNO",
           "documento_deixado": "on"}
SERVICO = {"tipo": "LATARIA", "problema": "Amassado na porta do motorista"}


class OrcamentoTest(BaseTest):
    def setUp(self):
        super().setUp()
        self.func = self.funcionario()
        self.dono_c = self.dono()
        self.func.post("/veiculos", data=VEICULO)
        self.vid = self.sql("SELECT id FROM veiculos")[0]["id"]
        self.func.post(f"/veiculos/{self.vid}/servicos", data=SERVICO)
        self.sid = self.sql("SELECT id FROM servicos")[0]["id"]

    def valor_url(self, servico_id=None):
        return f"/veiculos/{self.vid}/servicos/{servico_id or self.sid}/valor"

    def valor_no_banco(self):
        return self.sql("SELECT valor_centavos FROM servicos WHERE id = ?", (self.sid,))[0]["valor_centavos"]

    def test_dono_define_o_valor(self):
        r = self.dono_c.post(self.valor_url(), data={"valor": "150,00"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.valor_no_banco(), 15000)

    def test_valor_aparece_na_pagina_do_veiculo(self):
        self.dono_c.post(self.valor_url(), data={"valor": "150,00"})
        pagina = self.dono_c.get(f"/veiculos/{self.vid}").data
        self.assertIn("R$ 150,00".encode(), pagina)

    def test_funcionario_nao_pode_definir_valor(self):
        r = self.func.post(self.valor_url(), data={"valor": "150,00"})
        self.assertEqual(r.status_code, 403)
        self.assertIsNone(self.valor_no_banco())

    def test_aceita_ponto_como_separador_decimal(self):
        self.dono_c.post(self.valor_url(), data={"valor": "150.00"})
        self.assertEqual(self.valor_no_banco(), 15000)

    def test_aceita_numero_sem_centavos(self):
        self.dono_c.post(self.valor_url(), data={"valor": "150"})
        self.assertEqual(self.valor_no_banco(), 15000)

    def test_aceita_milhar_com_ponto_e_centavos_com_virgula(self):
        self.dono_c.post(self.valor_url(), data={"valor": "1.250,50"})
        self.assertEqual(self.valor_no_banco(), 125050)

    def test_nao_aceita_valor_vazio(self):
        r = self.dono_c.post(self.valor_url(), data={"valor": ""})
        self.assertIn("Informe um valor válido".encode(), r.data)
        self.assertIsNone(self.valor_no_banco())

    def test_nao_aceita_valor_com_letras(self):
        self.dono_c.post(self.valor_url(), data={"valor": "cem reais"})
        self.assertIsNone(self.valor_no_banco())

    def test_nao_aceita_valor_zero(self):
        self.dono_c.post(self.valor_url(), data={"valor": "0,00"})
        self.assertIsNone(self.valor_no_banco())

    def test_nao_aceita_valor_negativo(self):
        self.dono_c.post(self.valor_url(), data={"valor": "-50,00"})
        self.assertIsNone(self.valor_no_banco())

    def test_pode_corrigir_o_valor_depois(self):
        self.dono_c.post(self.valor_url(), data={"valor": "150,00"})
        self.dono_c.post(self.valor_url(), data={"valor": "200,00"})
        self.assertEqual(self.valor_no_banco(), 20000)

    def test_valor_de_servico_de_outro_veiculo_da_404(self):
        self.func.post("/veiculos", data={**VEICULO, "placa": "XYZ9K88"})
        outro_servico_url = self.valor_url(servico_id=99999)
        r = self.dono_c.post(outro_servico_url, data={"valor": "150,00"})
        self.assertEqual(r.status_code, 404)

    def test_orcamento_incompleto_enquanto_falta_valor(self):
        self.func.post(f"/veiculos/{self.vid}/servicos",
                       data={"tipo": "PINTURA", "problema": "Risco no capô"})
        self.dono_c.post(self.valor_url(), data={"valor": "150,00"})
        pagina = self.dono_c.get(f"/veiculos/{self.vid}").data
        self.assertIn("Orçamento incompleto".encode(), pagina)
        self.assertIn("1 serviço".encode(), pagina)

    def test_orcamento_completo_mostra_o_total(self):
        self.func.post(f"/veiculos/{self.vid}/servicos",
                       data={"tipo": "PINTURA", "problema": "Risco no capô"})
        outro_sid = self.sql("SELECT id FROM servicos ORDER BY id")[1]["id"]
        self.dono_c.post(self.valor_url(), data={"valor": "150,00"})
        self.dono_c.post(self.valor_url(outro_sid), data={"valor": "50,00"})
        pagina = self.dono_c.get(f"/veiculos/{self.vid}").data
        self.assertIn("Valor total do orçamento: R$ 200,00".encode(), pagina)


if __name__ == "__main__":
    unittest.main()
