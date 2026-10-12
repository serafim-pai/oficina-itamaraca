"""Testes do saldo a receber no comprovante de entrega.
Rodar na pasta do projeto:  python -m unittest discover tests -v"""
import unittest

from test_fotos_entrega import Base


class SaldoNoComprovanteTest(Base):
    def comprovante(self, cliente=None):
        return (cliente or self.dono_c).get(f"/veiculos/{self.vid}/comprovante").data.decode()

    def pagar(self, valor):
        self.dono_c.post(f"/veiculos/{self.vid}/pagamentos", data={"valor": valor, "forma": "PIX"})

    def test_entregue_sem_pagar_mostra_o_saldo_inteiro(self):
        self.fechar()                         # os testes liberam o saldo automaticamente
        pagina = self.comprovante()
        self.assertIn("Saldo a receber", pagina)
        self.assertIn("R$ 150,00", pagina)
        self.assertNotIn("Já recebido", pagina)

    def test_pagamento_parcial_mostra_recebido_e_saldo(self):
        self.pagar("50,00")
        self.fechar()
        pagina = self.comprovante()
        self.assertIn("Já recebido", pagina)
        self.assertIn("R$ 50,00", pagina)
        self.assertIn("Saldo a receber</td><td class=\"num\">R$ 100,00", pagina)

    def test_pago_por_completo_nao_mostra_nada_de_saldo(self):
        self.pagar("150,00")
        self.fechar()
        pagina = self.comprovante()
        self.assertNotIn("Saldo a receber", pagina)
        self.assertNotIn("Já recebido", pagina)

    def test_quitar_depois_faz_o_saldo_sumir_do_comprovante(self):
        self.fechar()
        self.assertIn("Saldo a receber", self.comprovante())
        self.pagar("150,00")
        self.assertNotIn("Saldo a receber", self.comprovante())

    def test_funcionario_que_imprime_ve_o_mesmo_comprovante(self):
        self.fechar()
        self.assertIn("Saldo a receber", self.comprovante(cliente=self.func))


if __name__ == "__main__":
    unittest.main()
