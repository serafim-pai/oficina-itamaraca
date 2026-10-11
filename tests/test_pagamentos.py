"""Testes dos pagamentos recebidos e da lista "A receber" (só o dono).
Rodar na pasta do projeto:  python -m unittest discover tests -v"""
import unittest

from test_fotos_entrega import Base, HOJE


class PagamentosTest(Base):
    def pagar(self, valor="50,00", forma="PIX", cliente=None, vid=None, **extra):
        dados = {"valor": valor, "forma": forma, **extra}
        return (cliente or self.dono_c).post(f"/veiculos/{vid or self.vid}/pagamentos", data=dados)

    def apagar(self, pagamento_id, motivo="Lancei o valor errado", cliente=None):
        return (cliente or self.dono_c).post(f"/veiculos/{self.vid}/pagamentos/{pagamento_id}/apagar",
                                             data={"motivo": motivo})

    def lancamentos(self, vid=None):
        return self.sql("SELECT * FROM pagamentos WHERE veiculo_id = ? ORDER BY id", (vid or self.vid,))

    def ficha(self, cliente=None, vid=None):
        return self.pagina(cliente=cliente, vid=vid)

    # ---- permissão ----
    def test_funcionario_nao_registra_nao_apaga_e_nao_ve(self):
        self.assertEqual(self.pagar(cliente=self.func).status_code, 403)
        self.pagar()
        self.assertEqual(self.apagar(self.lancamentos()[0]["id"], cliente=self.func).status_code, 403)
        self.assertEqual(self.func.get("/a-receber").status_code, 403)
        ficha = self.ficha(cliente=self.func)
        self.assertNotIn("Registrar pagamento recebido", ficha)
        self.assertNotIn("Já recebido", ficha)
        self.assertNotIn("/a-receber", ficha)
        self.assertEqual(len(self.lancamentos()), 1)

    def test_dono_ve_o_bloco_e_o_menu(self):
        ficha = self.ficha()
        self.assertIn("Registrar pagamento recebido", ficha)
        self.assertIn("/a-receber", ficha)
        self.assertIn("Sem pagamento", ficha)

    # ---- registrar ----
    def test_pagamento_em_partes_ate_quitar(self):
        self.assertEqual(self.pagar("50,00").status_code, 302)
        ficha = self.ficha()
        self.assertIn("Pago em parte", ficha)
        self.assertIn("R$ 100,00", ficha)           # falta
        self.pagar("100,00", "DINHEIRO")
        ficha = self.ficha()
        self.assertIn("selo-pago\">Pago<", ficha)
        self.assertNotIn("Registrar pagamento recebido", ficha)
        self.assertEqual(sum(p["valor_centavos"] for p in self.lancamentos()), 15000)

    def test_guarda_forma_data_observacao_e_quem_lancou(self):
        self.pagar("40,00", "CREDITO", data="2026-10-10", observacao="  sinal  ")
        p = self.lancamentos()[0]
        self.assertEqual((p["forma"], p["data_pagamento"], p["observacao"], p["registrado_por"], p["valor_centavos"]),
                         ("CREDITO", "2026-10-10", "sinal", "DONA MARIA", 4000))

    def test_sem_data_usa_hoje(self):
        self.pagar("10,00")
        self.assertEqual(self.lancamentos()[0]["data_pagamento"], HOJE.isoformat())

    def test_valor_passando_do_que_falta_e_recusado(self):
        resposta = self.pagar("150,01")
        self.assertIn("passa do que falta receber (R$ 150,00)", resposta.data.decode())
        self.assertEqual(self.lancamentos(), [])

    def test_valor_invalido_forma_invalida_e_data_invalida(self):
        for dados in ({"valor": "abc"}, {"valor": "0"}, {"valor": "-5"}, {"valor": "10", "forma": "CHEQUE"},
                      {"valor": "10", "data": "2026-10-16"}, {"valor": "10", "data": "ontem"},
                      {"valor": "10", "data": "1999-01-01"}, {"valor": "10", "observacao": "x" * 101}):
            padrao = {"valor": "10", "forma": "PIX"}
            padrao.update(dados)
            self.dono_c.post(f"/veiculos/{self.vid}/pagamentos", data=padrao)
        self.assertEqual(self.lancamentos(), [])

    def test_ficha_sem_valor_nao_aceita_pagamento(self):
        outro = self.novo_veiculo("XYZ9K88")
        self.func.post(f"/veiculos/{outro}/servicos", data={"tipo": "LATARIA", "problema": "Risco na porta"})
        resposta = self.pagar(vid=outro)
        self.assertIn("ainda não tem valor de serviço", resposta.data.decode())
        self.assertIn("Informe o valor dos serviços", self.ficha(vid=outro))
        self.assertEqual(self.lancamentos(outro), [])

    def test_entrega_fechada_usa_o_total_da_entrega(self):
        self.fechar()
        self.pagar("150,00")
        self.assertIn("selo-pago\">Pago<", self.ficha())

    # ---- apagar ----
    def test_apagar_exige_motivo_e_guarda_a_linha(self):
        self.pagar("50,00")
        pid = self.lancamentos()[0]["id"]
        self.assertIn("Explique o motivo", self.apagar(pid, motivo=" 1 ").data.decode())
        self.assertIsNone(self.lancamentos()[0]["apagado_em"])
        self.assertEqual(self.apagar(pid).status_code, 302)
        p = self.lancamentos()[0]
        self.assertIsNotNone(p["apagado_em"])
        self.assertEqual((p["apagado_por"], p["motivo_apagado"]), ("DONA MARIA", "Lancei o valor errado"))
        ficha = self.ficha()
        self.assertIn("Sem pagamento", ficha)
        self.assertIn("Lancei o valor errado", ficha)

    def test_pagamento_apagado_nao_conta_e_nao_apaga_duas_vezes(self):
        self.pagar("150,00")
        pid = self.lancamentos()[0]["id"]
        self.apagar(pid)
        self.assertEqual(self.apagar(pid).status_code, 404)
        self.assertIn("Registrar pagamento recebido", self.ficha())
        self.assertEqual(self.pagar("150,00").status_code, 302)

    def test_apagar_pagamento_de_outra_ficha_da_404(self):
        outro = self.novo_veiculo("XYZ9K88")
        self.pagar("10,00")
        pid = self.lancamentos()[0]["id"]
        resposta = self.dono_c.post(f"/veiculos/{outro}/pagamentos/{pid}/apagar", data={"motivo": "Teste de erro"})
        self.assertEqual(resposta.status_code, 404)

    # ---- excluir ficha ----
    def test_ficha_com_pagamento_nao_pode_ser_excluida(self):
        self.pagar("10,00")
        resposta = self.dono_c.post(f"/veiculos/{self.vid}/excluir", data={"motivo": "Cadastro de teste"})
        self.assertIn("tem pagamentos registrados", resposta.data.decode())
        self.assertEqual(len(self.sql("SELECT * FROM veiculos WHERE id = ?", (self.vid,))), 1)

    def test_apagando_o_pagamento_a_ficha_pode_ser_excluida_e_leva_as_linhas(self):
        self.pagar("10,00")
        self.apagar(self.lancamentos()[0]["id"])
        self.dono_c.post(f"/veiculos/{self.vid}/excluir", data={"motivo": "Cadastro de teste"})
        self.assertEqual(self.sql("SELECT * FROM veiculos WHERE id = ?", (self.vid,)), [])
        self.assertEqual(self.sql("SELECT * FROM pagamentos"), [])


class AReceberTest(Base):
    def pagar(self, valor, vid=None, **extra):
        self.dono_c.post(f"/veiculos/{vid or self.vid}/pagamentos", data={"valor": valor, "forma": "PIX", **extra})

    def lista(self):
        return self.dono_c.get("/a-receber").data.decode()

    def test_sem_entrega_nada_a_receber(self):
        self.assertIn("Nenhum carro entregue com saldo", self.lista())

    def test_carro_entregue_sem_pagamento_aparece_com_o_saldo(self):
        self.fechar()
        pagina = self.lista()
        self.assertIn("ABC1D23", pagina)
        self.assertIn("R$ 150,00", pagina)
        self.assertIn("<strong>1</strong> carro com saldo", pagina)
        self.assertIn("sem telefone", pagina)
        self.assertIn("hoje", pagina)

    def test_pagamento_parcial_mostra_so_o_que_falta(self):
        self.fechar()
        self.pagar("100,00")
        pagina = self.lista()
        self.assertIn("<strong>R$ 50,00</strong>", pagina)

    def test_quitado_sai_da_lista(self):
        self.fechar()
        self.pagar("150,00")
        self.assertIn("Nenhum carro entregue com saldo", self.lista())

    def test_carro_nao_entregue_nao_entra(self):
        self.pagar("50,00")
        self.assertIn("Nenhum carro entregue com saldo", self.lista())

    def test_link_do_whatsapp_com_telefone(self):
        self.fechar()
        self.sql("UPDATE veiculos SET telefone = '81987654321'")
        pagina = self.lista()
        self.assertIn("https://wa.me/5581987654321?text=", pagina)
        self.assertIn("150%2C00", pagina)

    def test_ficha_arquivada_com_saldo_continua_na_lista(self):
        self.fechar()
        self.dono_c.post(f"/veiculos/{self.vid}/arquivar", data={"motivo": "Cliente sumiu"})
        pagina = self.lista()
        self.assertIn("ABC1D23", pagina)
        self.assertIn("Arquivada", pagina)


class RelatorioDeRecebimentosTest(Base):
    def relatorio(self):
        return self.dono_c.get("/relatorio").data.decode()

    def test_recebido_no_mes_por_forma_e_a_receber(self):
        self.fechar()
        self.dono_c.post(f"/veiculos/{self.vid}/pagamentos", data={"valor": "100,00", "forma": "PIX"})
        self.dono_c.post(f"/veiculos/{self.vid}/pagamentos", data={"valor": "20,00", "forma": "DINHEIRO"})
        pagina = self.relatorio()
        self.assertIn("Recebido neste mês", pagina)
        self.assertIn("<strong>R$ 120,00</strong>", pagina)
        self.assertIn("&nbsp;&nbsp;Pix</th><td class=\"num\">R$ 100,00", pagina)
        self.assertIn("&nbsp;&nbsp;Dinheiro</th><td class=\"num\">R$ 20,00", pagina)
        self.assertIn("A receber hoje (carros entregues)</th><td class=\"num\">R$ 30,00", pagina)
        self.assertIn("1 carro entregue ainda tem saldo", pagina)

    def test_pagamento_apagado_nao_entra_no_relatorio(self):
        self.fechar()
        self.dono_c.post(f"/veiculos/{self.vid}/pagamentos", data={"valor": "100,00", "forma": "PIX"})
        pid = self.sql("SELECT id FROM pagamentos")[0]["id"]
        self.dono_c.post(f"/veiculos/{self.vid}/pagamentos/{pid}/apagar", data={"motivo": "Lancamento errado"})
        self.assertIn("Recebido neste mês</th><td class=\"num\"><strong>R$ 0,00", self.relatorio())

    def test_pagamento_de_outro_mes_nao_conta_no_mes(self):
        self.fechar()
        self.dono_c.post(f"/veiculos/{self.vid}/pagamentos",
                         data={"valor": "100,00", "forma": "PIX", "data": "2026-09-20"})
        self.assertIn("Recebido neste mês</th><td class=\"num\"><strong>R$ 0,00", self.relatorio())


if __name__ == "__main__":
    unittest.main()
