"""Testes das passagens anteriores do mesmo carro (histórico do veículo).
Rodar na pasta do projeto:  python -m unittest discover tests -v"""
import unittest

from test_fotos_entrega import Base


class PassagensAnterioresTest(Base):
    def test_carro_novo_nao_mostra_o_bloco(self):
        self.assertNotIn('class="passagens"', self.pagina())

    def test_mostra_a_passagem_anterior_com_servico_total_e_garantia_vigente(self):
        self.fechar()
        outro = self.novo_veiculo("ABC-1D23")
        pagina = self.pagina(vid=outro)
        self.assertIn("Passagens anteriores deste carro (1)", pagina)
        self.assertIn("LATARIA: Amassado na porta", pagina)
        self.assertIn("Entregue em 15/10/2026", pagina)
        self.assertIn("R$ 150,00", pagina)
        self.assertIn(f"/veiculos/{self.vid}/comprovante", pagina)
        self.assertIn("tem garantia vigente", pagina)
        self.assertIn("Garantia vigente: LATARIA", pagina)

    def test_ficha_antiga_tambem_mostra_a_nova_em_andamento(self):
        outro = self.novo_veiculo("ABC 1D23")
        self.assertIn("Em andamento", self.pagina(vid=self.vid))
        self.assertIn(f"/veiculos/{outro}", self.pagina(vid=self.vid))

    def test_placa_diferente_nao_entra(self):
        outro = self.novo_veiculo("XYZ9K88")
        self.assertNotIn('class="passagens"', self.pagina(vid=outro))
        self.assertNotIn('class="passagens"', self.pagina(vid=self.vid))

    def test_sem_garantia_vigente_nao_mostra_o_selo(self):
        outro = self.novo_veiculo("ABC1D23")
        pagina = self.pagina(vid=outro)
        self.assertIn("Passagens anteriores deste carro (1)", pagina)
        self.assertNotIn("tem garantia vigente", pagina)

    def test_funcionario_tambem_ve(self):
        outro = self.novo_veiculo("ABC1D23")
        self.assertIn("Passagens anteriores", self.pagina(cliente=self.func, vid=outro))


if __name__ == "__main__":
    unittest.main()
