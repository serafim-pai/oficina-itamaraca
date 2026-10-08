"""Testes de quem fornece a peça: o cliente traz ou a oficina compra (preço soma no orçamento e pede nova
aprovação), peça em mãos e a trava do início do reparo.
Rodar na pasta do projeto:  python -m unittest discover tests -v"""
import unittest

from base import BaseTest, oficina
from test_aprovacao import AprovacaoBase


class PecaOrigemTest(AprovacaoBase):
    def peca(self, situacao, preco="", cliente=None, sid=None):
        return (cliente or self.dono_c).post(f"/veiculos/{self.vid}/servicos/{sid or self.sid1}/peca",
                                             data={"situacao": situacao, "preco": preco})

    def maos(self, marcar=True, cliente=None, sid=None):
        return (cliente or self.func).post(f"/veiculos/{self.vid}/servicos/{sid or self.sid1}/peca/maos",
                                           data={"em_maos": "1" if marcar else "0"})

    def etapa(self, nova, cliente=None):
        return (cliente or self.func).post(f"/veiculos/{self.vid}/etapa", data={"etapa": nova})

    def servico(self, sid=None):
        return self.sql("SELECT * FROM servicos WHERE id = ?", (sid or self.sid1,))[0]

    def test_oficina_compra_soma_no_orcamento_e_invalida_a_aprovacao(self):
        self.decidir("APROVADO")
        r = self.peca("OFICINA_COMPRA", "90,00")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.servico()["pecas_centavos"], 9000)
        pagina = self.func.get(f"/veiculos/{self.vid}").data.decode()
        self.assertIn("não vale mais", pagina)                    # a aprovação anterior caiu
        self.assertIn("R$ 490,50", pagina)                         # 150,00 + 250,50 + 90,00

    def test_cliente_traz_nao_soma_nada(self):
        self.peca("CLIENTE_TRAZ")
        self.assertEqual(self.servico()["pecas_centavos"], 0)
        self.assertEqual(self.servico()["peca_situacao"], "CLIENTE_TRAZ")

    def test_trocar_para_cliente_traz_tira_o_preco_do_orcamento(self):
        self.peca("OFICINA_COMPRA", "90,00")
        self.peca("CLIENTE_TRAZ")
        self.assertEqual(self.servico()["pecas_centavos"], 0)

    def test_oficina_compra_exige_preco_valido(self):
        self.peca("OFICINA_COMPRA", "")
        self.assertIsNone(self.servico()["peca_situacao"])
        self.assertEqual(self.peca("OFICINA_COMPRA", "abc").status_code, 200)
        self.assertIsNone(self.servico()["peca_situacao"])

    def test_situacao_invalida_nao_grava(self):
        self.peca("INVENTADA")
        self.assertIsNone(self.servico()["peca_situacao"])

    def test_funcionario_nao_define_quem_fornece_a_peca_mas_marca_em_maos(self):
        self.assertEqual(self.peca("CLIENTE_TRAZ", cliente=self.func).status_code, 403)
        self.peca("CLIENTE_TRAZ")
        self.assertEqual(self.maos(True).status_code, 302)
        self.assertEqual(self.servico()["peca_em_maos"], 1)
        self.maos(False)
        self.assertEqual(self.servico()["peca_em_maos"], 0)

    def test_mudar_quem_fornece_zera_a_peca_em_maos(self):
        self.peca("CLIENTE_TRAZ")
        self.maos(True)
        self.peca("OFICINA_COMPRA", "50,00")
        self.assertEqual(self.servico()["peca_em_maos"], 0)

    def test_nao_marca_em_maos_sem_definir_quem_fornece(self):
        self.maos(True)
        self.assertEqual(self.servico()["peca_em_maos"], 0)

    def test_reparo_nao_comeca_sem_a_peca_em_maos(self):
        self.peca("CLIENTE_TRAZ")
        self.decidir("APROVADO")
        r = self.etapa("EM_REPARO")
        self.assertEqual(r.status_code, 200)
        self.assertIn("com a peça em mãos", r.data.decode())
        self.maos(True)
        self.assertEqual(self.etapa("EM_REPARO").status_code, 302)

    def test_servico_sem_peca_nao_trava_o_reparo(self):
        self.decidir("APROVADO")
        self.assertEqual(self.etapa("EM_REPARO").status_code, 302)

    def test_servico_de_outro_veiculo_da_404(self):
        self.assertEqual(self.dono_c.post(f"/veiculos/{self.vid}/servicos/99999/peca",
                                          data={"situacao": "CLIENTE_TRAZ"}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
