"""Testes da regra: a entrega só fecha com o pagamento completo ou com a liberação do dono (com motivo).
Rodar na pasta do projeto:  python -m unittest discover tests -v"""
import unittest

from base import foto_de_entrega
from test_fotos_entrega import Base, CONDICOES


class EntregaComSaldoTest(Base):
    def fechar_sem_liberar(self, motivo=None, liberar=False, vid=None):
        """Fecha a entrega como o formulário faz, SEM a liberação automática dos outros testes."""
        vid = vid or self.vid
        self.marcar_pronto(vid)
        dados = {"condicoes": CONDICOES, "assinatura": self.assinatura(vid), "fotos_entrega": foto_de_entrega()}
        if liberar:
            dados["liberar_saldo"] = "on"
        if motivo is not None:
            dados["motivo_saldo"] = motivo
        return self.dono_c.post(f"/veiculos/{vid}/entrega", content_type="multipart/form-data", data=dados)

    def pagar(self, valor):
        self.dono_c.post(f"/veiculos/{self.vid}/pagamentos", data={"valor": valor, "forma": "PIX"})

    def entrega(self):
        return self.sql("SELECT * FROM entregas")

    def test_sem_pagamento_e_sem_liberar_nao_fecha(self):
        resposta = self.fechar_sem_liberar()
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("Falta receber R$ 150,00", resposta.data.decode())
        self.assertEqual(self.entrega(), [])

    def test_liberar_sem_motivo_nao_fecha(self):
        for motivo in (None, "", " 12 "):
            resposta = self.fechar_sem_liberar(liberar=True, motivo=motivo)
            self.assertIn("Explique o motivo de entregar com saldo a receber", resposta.data.decode())
        self.assertEqual(self.entrega(), [])

    def test_motivo_grande_demais_nao_fecha(self):
        resposta = self.fechar_sem_liberar(liberar=True, motivo="a" * 201)
        self.assertIn("no máximo 200", resposta.data.decode())
        self.assertEqual(self.entrega(), [])

    def test_motivo_sem_marcar_a_liberacao_nao_basta(self):
        resposta = self.fechar_sem_liberar(liberar=False, motivo="Cliente conhecido")
        self.assertIn("Falta receber", resposta.data.decode())
        self.assertEqual(self.entrega(), [])

    def test_dono_libera_com_motivo_e_fica_registrado(self):
        resposta = self.fechar_sem_liberar(liberar=True, motivo="  Cliente conhecido, paga na sexta ")
        self.assertEqual(resposta.status_code, 302)
        e = self.entrega()[0]
        self.assertEqual((e["saldo_liberado_centavos"], e["saldo_liberado_motivo"], e["saldo_liberado_por"]),
                         (15000, "Cliente conhecido, paga na sexta", "DONA MARIA"))
        ficha = self.pagina()
        self.assertIn("Entregue com", ficha)
        self.assertIn("saldo a receber de R$ 150,00", ficha)
        self.assertIn("Cliente conhecido, paga na sexta", ficha)
        self.assertIn("ABC1D23", self.dono_c.get("/a-receber").data.decode())

    def test_pagamento_completo_fecha_sem_liberar(self):
        self.pagar("150,00")
        self.assertEqual(self.fechar_sem_liberar().status_code, 302)
        e = self.entrega()[0]
        self.assertIsNone(e["saldo_liberado_centavos"])
        self.assertIsNone(e["saldo_liberado_por"])
        self.assertNotIn("Entregue com saldo", self.pagina())

    def test_pagamento_parcial_registra_so_o_que_falta(self):
        self.pagar("50,00")
        resposta = self.fechar_sem_liberar()
        self.assertIn("Falta receber R$ 100,00", resposta.data.decode())
        self.fechar_sem_liberar(liberar=True, motivo="Paga o resto na retirada")
        self.assertEqual(self.entrega()[0]["saldo_liberado_centavos"], 10000)

    def test_marcar_liberar_sem_saldo_nao_registra_nada(self):
        self.pagar("150,00")
        self.fechar_sem_liberar(liberar=True, motivo="Sem necessidade")
        e = self.entrega()[0]
        self.assertIsNone(e["saldo_liberado_centavos"])
        self.assertIsNone(e["saldo_liberado_motivo"])

    def test_pagina_mostra_o_aviso_e_os_campos_so_quando_ha_saldo(self):
        self.marcar_pronto(self.vid)
        pagina = self.pagina()
        self.assertIn("Falta receber R$ 150,00", pagina)
        self.assertIn('name="liberar_saldo"', pagina)
        self.assertIn('name="motivo_saldo"', pagina)
        self.pagar("150,00")
        pagina = self.pagina()
        self.assertNotIn('name="liberar_saldo"', pagina)

    def test_erro_mantem_o_que_foi_digitado(self):
        resposta = self.fechar_sem_liberar(liberar=True, motivo="  ")
        pagina = resposta.data.decode()          # motivo vazio: a página volta com a caixa ainda marcada
        self.assertIn('name="liberar_saldo" checked', pagina)

    def test_funcionario_continua_sem_poder_fechar(self):
        self.marcar_pronto(self.vid)
        resposta = self.func.post(f"/veiculos/{self.vid}/entrega", content_type="multipart/form-data",
                                  data={"condicoes": CONDICOES, "assinatura": self.assinatura(), "liberar_saldo": "on",
                                        "motivo_saldo": "Tentando", "fotos_entrega": foto_de_entrega()})
        self.assertEqual(resposta.status_code, 403)
        self.assertEqual(self.entrega(), [])

    def test_desfazer_e_fechar_de_novo_recalcula_o_saldo(self):
        self.fechar_sem_liberar(liberar=True, motivo="Paga depois")
        self.desfazer()
        self.pagar("150,00")
        self.assertEqual(self.fechar_sem_liberar().status_code, 302)
        self.assertIsNone(self.entrega()[0]["saldo_liberado_centavos"])


if __name__ == "__main__":
    unittest.main()
