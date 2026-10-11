"""Testes do relatório do mês (só o dono vê).
Rodar na pasta do projeto:  python -m unittest discover tests -v"""
import unittest

from test_fotos_entrega import Base


class RelatorioTest(Base):
    def relatorio(self, mes=None, cliente=None):
        caminho = "/relatorio" + (f"?mes={mes}" if mes else "")
        return (cliente or self.dono_c).get(caminho)

    def texto(self, mes=None):
        return self.relatorio(mes).data.decode()

    def test_funcionario_nao_entra(self):
        self.assertEqual(self.relatorio(cliente=self.func).status_code, 403)

    def test_menu_so_mostra_o_relatorio_ao_dono(self):
        self.assertIn("/relatorio", self.pagina(cliente=self.dono_c))
        self.assertNotIn("/relatorio", self.pagina(cliente=self.func))

    def test_mes_sem_entrega(self):
        pagina = self.texto()
        self.assertIn("Relatório de outubro de 2026", pagina)
        self.assertIn("Nenhum carro foi entregue neste mês", pagina)

    def test_faturamento_e_servicos_por_tipo(self):
        self.fechar()
        pagina = self.texto()
        self.assertIn("Total faturado", pagina)
        self.assertIn("R$ 150,00", pagina)
        self.assertIn("<td>LATARIA</td><td class=\"num\">1</td>", pagina)
        self.assertNotIn("Nenhum carro foi entregue", pagina)

    def test_media_por_carro_com_dois_carros(self):
        self.fechar()
        outro = self.novo_veiculo("XYZ9K88", entrada=1)
        self.servico(outro)
        self.fechar(vid=outro)
        pagina = self.texto()
        self.assertIn(">2</td>", pagina)
        self.assertIn("R$ 300,00", pagina)
        self.assertIn("Valor médio por carro</th><td class=\"num\">R$ 150,00", pagina)

    def test_outro_mes_nao_conta_a_entrega(self):
        self.fechar()
        self.assertIn("Nenhum carro foi entregue neste mês", self.texto("2026-09"))
        self.assertIn("setembro de 2026", self.texto("2026-09"))

    def test_mes_invalido_vira_o_mes_atual(self):
        self.assertIn("outubro de 2026", self.texto("abc"))
        self.assertIn("outubro de 2026", self.texto("2026-13"))

    def test_navegacao_entre_meses_passa_de_ano(self):
        self.assertIn("mes=2025-12", self.texto("2026-01"))
        self.assertIn("mes=2027-01", self.texto("2026-12"))

    def test_pecas_do_estoque_com_custo_venda_e_lucro(self):
        self.fechar()
        self.sql("INSERT INTO servico_pecas (servico_id, veiculo_id, item_id, nome, quantidade, preco_centavos, "
                 "custo_centavos) VALUES (?, ?, 1, 'TINTA BRANCA', 2, 5000, 3000)", (self.sid, self.vid))
        pagina = self.texto()
        self.assertIn("TINTA BRANCA", pagina)
        self.assertIn("R$ 100,00", pagina)   # venda
        self.assertIn("R$ 60,00", pagina)    # custo
        self.assertIn("R$ 40,00", pagina)    # lucro

    def test_sem_peca_do_estoque(self):
        self.fechar()
        self.assertIn("Nenhuma peça do estoque foi usada", self.texto())

    def test_garantia_vigente_sem_vencimento_proximo(self):
        self.fechar()
        pagina = self.texto()
        self.assertIn("<strong>1</strong> garantia vigente", pagina)
        self.assertIn("Nenhuma vence nos próximos 30 dias", pagina)

    def test_garantia_que_vence_em_breve_aparece_com_a_placa(self):
        self.fechar()
        self.sql("UPDATE entrega_itens SET garantia_ate = '2026-10-20'")
        pagina = self.texto()
        self.assertIn("Vencem nos próximos 30 dias", pagina)
        self.assertIn("ABC1D23", pagina)
        self.assertIn("20/10/2026", pagina)

    def test_garantia_vencida_nao_conta(self):
        self.fechar()
        self.sql("UPDATE entrega_itens SET garantia_ate = '2026-10-01'")
        self.assertIn("<strong>0</strong> garantias vigentes", self.texto())


if __name__ == "__main__":
    unittest.main()
