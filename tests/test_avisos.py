"""Testes dos avisos aos clientes pelo WhatsApp (revisão de 3 em 3 meses e garantia vencendo).
Rodar na pasta do projeto:  python -m unittest discover tests -v"""
import unittest
from datetime import date

from base import oficina
from test_fotos_entrega import Base

# A entrega dos testes é fechada em 15/10/2026. Com garantia até 15/10/2027, as marcas de revisão caem em
# 15/01, 15/04, 15/07 e 15/10 de 2027.
GARANTIA_LONGA = "2027-10-15"


class AvisosTest(Base):
    def preparar(self, garantia_ate=GARANTIA_LONGA):
        self.fechar()
        self.sql("UPDATE entrega_itens SET garantia_ate = ?", (garantia_ate,))

    def em(self, dia):
        oficina.hoje_brasil = lambda agora_utc=None: dia

    def lista(self, cliente=None):
        return (cliente or self.dono_c).get("/avisos").data.decode()

    def avisei(self, tipo="REVISAO", cliente=None, vid=None):
        return (cliente or self.func).post(f"/veiculos/{vid or self.vid}/avisos", data={"tipo": tipo})

    def registros(self):
        return self.sql("SELECT * FROM avisos ORDER BY id")

    # ---- quando entra na lista ----
    def test_lista_vazia(self):
        self.assertIn("Nenhum cliente para avisar", self.lista())

    def test_no_dia_da_entrega_ainda_nao_ha_aviso(self):
        self.preparar()
        self.assertIn("Nenhum cliente para avisar", self.lista())

    def test_tres_meses_depois_entra_a_revisao(self):
        self.preparar()
        self.em(date(2027, 1, 15))
        pagina = self.lista()
        self.assertIn("Revisão de 3 meses", pagina)
        self.assertIn("ABC1D23", pagina)
        self.assertIn("hoje", pagina)

    def test_entra_sete_dias_antes_da_data_e_nao_antes(self):
        self.preparar()
        self.em(date(2027, 1, 7))
        self.assertIn("Nenhum cliente para avisar", self.lista())
        self.em(date(2027, 1, 8))
        pagina = self.lista()
        self.assertIn("Revisão de 3 meses", pagina)
        self.assertIn("em 7 dias", pagina)

    def test_atrasado_mostra_so_a_marca_mais_recente(self):
        self.preparar()
        self.em(date(2027, 8, 1))
        pagina = self.lista()
        self.assertIn("Revisão de 9 meses", pagina)
        self.assertNotIn("Revisão de 3 meses", pagina)
        self.assertNotIn("Revisão de 6 meses", pagina)
        self.assertIn("atrasado 17 dias", pagina)

    def test_nao_avisa_revisao_depois_do_fim_da_garantia(self):
        self.preparar()
        self.em(date(2028, 6, 1))
        self.assertNotIn("Revisão de", self.lista())

    def test_aviso_muito_atrasado_sai_da_lista(self):
        self.preparar()
        self.em(date(2027, 10, 15))
        self.assertIn("Revisão de 12 meses", self.lista())
        self.em(date(2028, 1, 13))      # 90 dias depois da marca de 12 meses
        self.assertIn("Revisão de 12 meses", self.lista())
        self.em(date(2028, 1, 14))
        self.assertNotIn("Revisão de", self.lista())

    def test_garantia_curta_nao_gera_revisao_mas_gera_aviso_de_garantia_vencendo(self):
        self.fechar()   # garantia de 90 dias: vence em 13/01/2027
        self.em(date(2026, 12, 20))
        pagina = self.lista()
        self.assertNotIn("Revisão de", pagina)
        self.assertIn("Garantia vencendo", pagina)
        self.assertIn("em 24 dias", pagina)

    def test_servico_sem_garantia_nao_gera_aviso(self):
        self.fechar()
        self.sql("UPDATE entrega_itens SET garantia_ate = NULL")
        self.em(date(2027, 1, 15))
        self.assertIn("Nenhum cliente para avisar", self.lista())

    # ---- Avisei ----
    def test_avisei_tira_da_lista_e_a_proxima_marca_volta_depois(self):
        self.preparar()
        self.em(date(2027, 1, 15))
        self.assertEqual(self.avisei().status_code, 302)
        registro = self.registros()[0]
        self.assertEqual((registro["tipo"], registro["marca_meses"]), ("REVISAO", 3))
        self.assertTrue(registro["feito_por"])
        self.assertIn("Nenhum cliente para avisar", self.lista())
        self.em(date(2027, 4, 15))
        self.assertIn("Revisão de 6 meses", self.lista())

    def test_avisei_sem_aviso_pendente_nao_registra(self):
        self.preparar()
        self.avisei()
        self.assertEqual(self.registros(), [])

    def test_avisei_atrasado_cobre_as_marcas_anteriores(self):
        self.preparar()
        self.em(date(2027, 8, 1))
        self.avisei()
        self.assertEqual(self.registros()[0]["marca_meses"], 9)
        self.em(date(2027, 8, 20))
        self.assertIn("Nenhum cliente para avisar", self.lista())

    def test_avisei_de_garantia_so_cobre_o_aviso_de_garantia(self):
        self.preparar(garantia_ate="2027-01-15")
        self.em(date(2027, 1, 10))
        pagina = self.lista()
        self.assertIn("Garantia vencendo", pagina)
        self.assertIn("Revisão de 3 meses", pagina)
        self.avisei("GARANTIA")
        pagina = self.lista()
        self.assertNotIn("Garantia vencendo", pagina)
        self.assertIn("Revisão de 3 meses", pagina)

    def test_tipo_invalido_nao_registra(self):
        self.preparar()
        self.em(date(2027, 1, 15))
        self.avisei("QUALQUER")
        self.assertEqual(self.registros(), [])

    def test_ficha_inexistente_da_404(self):
        self.assertEqual(self.avisei(vid=99999).status_code, 404)

    # ---- quem não entra ----
    def test_nao_avisar_mais_tira_o_cliente_de_vez(self):
        self.preparar()
        self.em(date(2027, 1, 15))
        self.avisei("NAO_AVISAR")
        self.assertIn("Nenhum cliente para avisar", self.lista())
        self.em(date(2027, 4, 15))
        self.assertIn("Nenhum cliente para avisar", self.lista())

    def test_carro_que_voltou_nao_aparece(self):
        self.preparar()
        self.novo_veiculo("ABC-1D23")
        self.em(date(2027, 1, 15))
        self.assertIn("Nenhum cliente para avisar", self.lista())

    def test_ficha_arquivada_nao_aparece(self):
        self.preparar()
        self.dono_c.post(f"/veiculos/{self.vid}/arquivar", data={"motivo": "Cliente mudou de cidade"})
        self.em(date(2027, 1, 15))
        self.assertIn("Nenhum cliente para avisar", self.lista())

    def test_ficha_sem_entrega_nao_aparece(self):
        self.em(date(2027, 1, 15))
        self.assertIn("Nenhum cliente para avisar", self.lista())

    # ---- WhatsApp e permissão ----
    def test_sem_telefone_nao_mostra_o_link(self):
        self.preparar()
        self.em(date(2027, 1, 15))
        pagina = self.lista()
        self.assertIn("sem telefone", pagina)
        self.assertNotIn("wa.me/", pagina)

    def test_com_telefone_monta_o_link_com_a_mensagem(self):
        self.preparar()
        self.sql("UPDATE veiculos SET telefone = '81987654321'")
        self.em(date(2027, 1, 15))
        pagina = self.lista()
        self.assertIn("https://wa.me/5581987654321?text=", pagina)
        self.assertIn("%C3%B3leo", pagina)   # a mensagem fala de óleo
        self.assertIn("15/10/2027", pagina)   # e da data de fim da garantia

    def test_funcionario_ve_a_lista_e_o_menu_e_nao_ve_dinheiro(self):
        self.preparar()
        self.em(date(2027, 1, 15))
        pagina = self.lista(cliente=self.func)
        self.assertIn("Revisão de 3 meses", pagina)
        self.assertIn("/avisos", self.pagina(cliente=self.func))
        self.assertNotIn("R$", pagina)

    def test_texto_do_aviso_de_garantia_fala_da_data_de_vencimento(self):
        self.preparar(garantia_ate="2027-01-15")
        self.sql("UPDATE veiculos SET telefone = '81987654321'")
        self.em(date(2027, 1, 10))
        self.assertIn("vence%20em%2015/01/2027", self.lista())


class SomarMesesTest(unittest.TestCase):
    def test_soma_simples_e_virada_de_ano(self):
        self.assertEqual(oficina.somar_meses(date(2026, 10, 15), 3), date(2027, 1, 15))
        self.assertEqual(oficina.somar_meses(date(2026, 10, 15), 12), date(2027, 10, 15))

    def test_dia_31_em_mes_curto_vira_o_ultimo_dia(self):
        self.assertEqual(oficina.somar_meses(date(2026, 11, 30), 3), date(2027, 2, 28))
        self.assertEqual(oficina.somar_meses(date(2026, 10, 31), 4), date(2027, 2, 28))
        self.assertEqual(oficina.somar_meses(date(2027, 11, 30), 3), date(2028, 2, 29))


if __name__ == "__main__":
    unittest.main()
