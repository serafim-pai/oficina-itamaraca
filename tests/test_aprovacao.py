"""Testes da história 6: registrar a aprovação do cliente.
Rodar na pasta do projeto:  python -m unittest discover tests -v"""
import re
import unittest

from base import BaseTest, oficina

VEICULO = {"responsavel": "JOSE", "placa": "ABC1D23", "marca": "FIAT", "modelo": "UNO",
           "documento_deixado": "on"}


class AprovacaoBase(BaseTest):
    def setUp(self):
        super().setUp()
        self.func = self.funcionario()
        self.dono_c = self.dono()
        self.func.post("/veiculos", data=VEICULO)
        self.vid = self.sql("SELECT id FROM veiculos")[0]["id"]
        self.sid1 = self.novo_servico("LATARIA", "Amassado na porta do motorista", "150,00")
        self.sid2 = self.novo_servico("PINTURA", "Pintura desbotada no capô", "250,50")

    # ---- atalhos ----
    def novo_servico(self, tipo, problema, valor=None):
        self.func.post(f"/veiculos/{self.vid}/servicos", data={"tipo": tipo, "problema": problema})
        sid = self.sql("SELECT MAX(id) AS id FROM servicos")[0]["id"]
        if valor:
            self.dono_c.post(f"/veiculos/{self.vid}/servicos/{sid}/valor", data={"valor": valor})
        return sid

    def assinatura(self, cliente=None):
        pagina = (cliente or self.func).get(f"/veiculos/{self.vid}").data.decode()
        achou = re.search(r'name="assinatura" value="([^"]+)"', pagina)
        return achou.group(1) if achou else None

    def decidir(self, decisao="APROVADO", forma="PESSOALMENTE", observacao="", cliente=None, assinatura=...):
        cliente = cliente or self.func
        dados = {"decisao": decisao, "forma": forma, "observacao": observacao,
                 "assinatura": self.assinatura(cliente) if assinatura is ... else assinatura}
        return cliente.post(f"/veiculos/{self.vid}/aprovacao", data=dados)

    def registros(self):
        return self.sql("SELECT * FROM aprovacoes ORDER BY id")

    def situacao(self):
        return oficina.situacao_aprovacao(
            self.sql("SELECT * FROM servicos WHERE veiculo_id = ? ORDER BY id", (self.vid,)),
            (self.registros() or [None])[-1])[0]


class RegistrarAprovacaoTest(AprovacaoBase):
    def test_registra_aprovacao_com_tudo_que_precisa_ficar_guardado(self):
        r = self.decidir("APROVADO", "WHATSAPP", "Cliente mandou mensagem às 14h")
        self.assertEqual(r.status_code, 302)
        a = self.registros()[0]
        self.assertEqual((a["decisao"], a["forma"], a["observacao"]), ("APROVADO", "WHATSAPP", "Cliente mandou mensagem às 14h"))
        self.assertEqual(a["total_centavos"], 40050)                 # 150,00 + 250,50
        self.assertEqual(a["registrado_por"], "PESSOA TESTE")        # quem registrou
        self.assertTrue(a["criado_em"])                              # quando
        self.assertEqual(a["veiculo_id"], self.vid)

    def test_registra_recusa(self):
        self.decidir("RECUSADO", "TELEFONE")
        self.assertEqual(self.registros()[0]["decisao"], "RECUSADO")
        self.assertEqual(self.situacao(), "RECUSADO")

    def test_observacao_e_opcional(self):
        self.decidir(observacao="")
        self.assertIsNone(self.registros()[0]["observacao"])

    def test_dono_e_funcionario_podem_registrar(self):
        self.assertEqual(self.decidir(cliente=self.func).status_code, 302)
        self.assertEqual(self.decidir("RECUSADO", cliente=self.dono_c).status_code, 302)
        self.assertEqual(len(self.registros()), 2)

    def test_aparece_na_pagina_do_veiculo(self):
        self.decidir("APROVADO", "TELEFONE", "Ligou de manhã")
        pagina = self.func.get(f"/veiculos/{self.vid}").data.decode()
        self.assertIn("Aprovado pelo cliente", pagina)
        self.assertIn("R$ 400,50", pagina)
        self.assertIn("Ligou de manhã", pagina)
        self.assertIn("PESSOA TESTE", pagina)


class RegrasDaAprovacaoTest(AprovacaoBase):
    def test_nao_registra_com_orcamento_incompleto(self):
        self.novo_servico("FREIOS", "Pastilha gasta")                  # sem valor
        r = self.decidir(assinatura="qualquer")
        self.assertIn("orçamento completo".encode(), r.data)
        self.assertEqual(self.registros(), [])

    def test_nao_registra_sem_servicos(self):
        self.sql("DELETE FROM servicos")
        r = self.decidir(assinatura="qualquer")
        self.assertIn("orçamento completo".encode(), r.data)
        self.assertEqual(self.registros(), [])

    def test_formulario_so_aparece_com_orcamento_completo(self):
        self.assertIn(b'name="decisao"', self.func.get(f"/veiculos/{self.vid}").data)
        self.novo_servico("FREIOS", "Pastilha gasta")
        pagina = self.func.get(f"/veiculos/{self.vid}").data
        self.assertNotIn(b'name="decisao"', pagina)
        self.assertIn("todos os serviços precisam ter valor".encode(), pagina)

    def test_recusa_decisao_ou_forma_invalida_ou_ausente(self):
        for mudanca, trecho in [({"decisao": ""}, "aprovou ou recusou"), ({"decisao": "TALVEZ"}, "aprovou ou recusou"),
                                ({"forma": ""}, "como o cliente respondeu"), ({"forma": "POMBO"}, "como o cliente respondeu")]:
            r = self.decidir(**{"decisao": "APROVADO", "forma": "TELEFONE", **mudanca})
            self.assertIn(trecho.encode(), r.data, mudanca)
        self.assertEqual(self.registros(), [])

    def test_recusa_observacao_longa_demais(self):
        r = self.decidir(observacao="x" * (oficina.MAX_OBS_APROVACAO + 1))
        self.assertIn("no máximo".encode(), r.data)
        self.assertEqual(self.registros(), [])

    def test_aceita_observacao_no_limite(self):
        self.assertEqual(self.decidir(observacao="x" * oficina.MAX_OBS_APROVACAO).status_code, 302)

    def test_veiculo_inexistente_da_404(self):
        r = self.func.post("/veiculos/99999/aprovacao", data={"decisao": "APROVADO", "forma": "TELEFONE"})
        self.assertEqual(r.status_code, 404)

    def test_sem_login_nao_registra(self):
        r = oficina.app.test_client().post(f"/veiculos/{self.vid}/aprovacao",
                                           data={"decisao": "APROVADO", "forma": "TELEFONE"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith("/login"))
        self.assertEqual(self.registros(), [])

    def test_observacao_com_html_aparece_como_texto(self):
        self.decidir(observacao="<script>alert(1)</script>")
        self.assertNotIn(b"<script>alert(1)</script>", self.func.get(f"/veiculos/{self.vid}").data)


class OrcamentoMudouTest(AprovacaoBase):
    """A decisão do cliente só vale para o orçamento que ele viu."""

    def test_mudar_um_valor_invalida_a_aprovacao(self):
        self.decidir("APROVADO")
        self.assertEqual(self.situacao(), "APROVADO")
        self.dono_c.post(f"/veiculos/{self.vid}/servicos/{self.sid1}/valor", data={"valor": "999,00"})
        self.assertEqual(self.situacao(), "DESATUALIZADA")
        pagina = self.func.get(f"/veiculos/{self.vid}").data.decode()
        self.assertIn("não vale mais", pagina)
        self.assertIn("Registre uma nova decisão", pagina)

    def test_incluir_servico_invalida_e_deixa_orcamento_incompleto(self):
        self.decidir("APROVADO")
        self.novo_servico("FREIOS", "Pastilha gasta")
        self.assertEqual(self.situacao(), "INCOMPLETO")
        self.assertIn("não vale mais".encode(), self.func.get(f"/veiculos/{self.vid}").data)

    def test_incluir_servico_com_valor_invalida(self):
        self.decidir("APROVADO")
        self.novo_servico("FREIOS", "Pastilha gasta", "80,00")
        self.assertEqual(self.situacao(), "DESATUALIZADA")

    def test_excluir_servico_invalida(self):
        self.decidir("APROVADO")
        self.dono_c.post(f"/veiculos/{self.vid}/servicos/{self.sid2}/excluir")
        self.assertEqual(self.situacao(), "DESATUALIZADA")

    def test_mudar_so_a_descricao_nao_invalida(self):
        self.decidir("APROVADO")
        self.func.post(f"/veiculos/{self.vid}/servicos/{self.sid1}/resolucao", data={"como_resolver": "Desamassar e pintar"})
        self.assertEqual(self.situacao(), "APROVADO")

    def test_voltar_ao_orcamento_original_volta_a_valer(self):
        # a assinatura só depende dos serviços e valores: o cliente aprovou exatamente este orçamento
        self.decidir("APROVADO")
        self.dono_c.post(f"/veiculos/{self.vid}/servicos/{self.sid1}/valor", data={"valor": "999,00"})
        self.assertEqual(self.situacao(), "DESATUALIZADA")
        self.dono_c.post(f"/veiculos/{self.vid}/servicos/{self.sid1}/valor", data={"valor": "150,00"})
        self.assertEqual(self.situacao(), "APROVADO")

    def test_nova_decisao_depois_de_mudar_vale_e_guarda_o_historico(self):
        self.decidir("APROVADO")
        self.dono_c.post(f"/veiculos/{self.vid}/servicos/{self.sid1}/valor", data={"valor": "300,00"})
        self.decidir("RECUSADO", "TELEFONE", "Achou caro")
        registros = self.registros()
        self.assertEqual([r["decisao"] for r in registros], ["APROVADO", "RECUSADO"])
        self.assertEqual([r["total_centavos"] for r in registros], [40050, 55050])
        self.assertEqual(self.situacao(), "RECUSADO")
        pagina = self.func.get(f"/veiculos/{self.vid}").data.decode()
        self.assertIn("Histórico de decisões (2)", pagina)

    def test_orcamento_mudou_enquanto_registrava_e_recusado(self):
        assinatura_que_a_pessoa_viu = self.assinatura()
        self.dono_c.post(f"/veiculos/{self.vid}/servicos/{self.sid1}/valor", data={"valor": "999,00"})
        r = self.decidir(assinatura=assinatura_que_a_pessoa_viu)
        self.assertIn("orçamento mudou enquanto você registrava".encode(), r.data)
        self.assertEqual(self.registros(), [])

    def test_assinatura_ausente_e_recusada(self):
        r = self.decidir(assinatura="")
        self.assertIn("orçamento mudou".encode(), r.data)
        self.assertEqual(self.registros(), [])


class SituacaoTest(AprovacaoBase):
    def test_situacoes_na_ordem_do_fluxo(self):
        self.sql("DELETE FROM servicos")
        self.assertEqual(self.situacao(), "SEM_ORCAMENTO")
        self.novo_servico("FREIOS", "Pastilha gasta")
        self.assertEqual(self.situacao(), "INCOMPLETO")
        self.dono_c.post(f"/veiculos/{self.vid}/servicos/{self.sql('SELECT id FROM servicos')[0]['id']}/valor", data={"valor": "80,00"})
        self.assertEqual(self.situacao(), "AGUARDANDO")
        self.decidir("APROVADO")
        self.assertEqual(self.situacao(), "APROVADO")

    def test_lista_de_veiculos_mostra_o_selo_de_cada_um(self):
        self.func.post("/veiculos", data={**VEICULO, "placa": "ZZZ9Z99"})        # outro veículo, sem serviços
        self.decidir("APROVADO")
        pagina = self.func.get("/").data.decode()
        self.assertIn("Aprovado pelo cliente", pagina)
        self.assertIn("Sem orçamento", pagina)
        self.assertIn("selo-aprovado", pagina)
        self.assertIn("selo-sem-orcamento", pagina)

    def test_lista_mostra_aguardando_e_desatualizada(self):
        self.assertIn("Aguardando o cliente".encode(), self.func.get("/").data)
        self.decidir("APROVADO")
        self.dono_c.post(f"/veiculos/{self.vid}/servicos/{self.sid1}/valor", data={"valor": "999,00"})
        self.assertIn("precisa de nova decisão".encode(), self.func.get("/").data)

    def test_dados_de_um_veiculo_nao_vazam_para_outro(self):
        self.func.post("/veiculos", data={**VEICULO, "placa": "ZZZ9Z99"})
        outro = self.sql("SELECT id FROM veiculos WHERE placa = 'ZZZ9Z99'")[0]["id"]
        self.decidir("APROVADO")
        pagina = self.func.get(f"/veiculos/{outro}").data.decode()
        self.assertNotIn("Aprovado pelo cliente", pagina)
        self.assertNotIn("Última decisão", pagina)


class AprovacaoComCsrfTest(AprovacaoBase):
    def test_sem_token_nao_registra(self):
        oficina.app.config["WTF_CSRF_ENABLED"] = True      # liga só depois de montar os dados do teste
        self.addCleanup(oficina.app.config.__setitem__, "WTF_CSRF_ENABLED", False)
        r = self.func.post(f"/veiculos/{self.vid}/aprovacao",
                           data={"decisao": "APROVADO", "forma": "TELEFONE", "assinatura": "x"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.registros(), [])


if __name__ == "__main__":
    unittest.main()


class FormularioRecolhidoTest(AprovacaoBase):
    def test_depois_de_decidir_o_formulario_fica_recolhido(self):
        antes = self.func.get(f"/veiculos/{self.vid}").data.decode()
        self.assertNotIn("Mudar a decisão do cliente", antes)
        self.decidir("APROVADO")
        depois = self.func.get(f"/veiculos/{self.vid}").data.decode()
        self.assertIn("Mudar a decisão do cliente", depois)
        self.assertIn('name="assinatura"', depois)      # o formulário continua lá, só recolhido
