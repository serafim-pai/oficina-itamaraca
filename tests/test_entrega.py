"""Testes da história 8: garantia por serviço, fechar a entrega e comprovante.
Rodar na pasta do projeto:  python -m unittest discover tests -v"""
import re
import unittest
from datetime import date, timedelta

from base import BaseTest, foto_de_entrega, oficina

HOJE_REAL = oficina.hoje_brasil
HOJE = date(2026, 10, 15)
VEICULO = {"responsavel": "JOSE DA SILVA", "placa": "ABC1D23", "marca": "FIAT", "modelo": "UNO",
           "cor": "VERMELHO", "ano": "2012", "quilometragem": "150000", "documento_deixado": "on"}
CONDICOES = "A garantia deixa de valer se o veículo for consertado por outra oficina ou sofrer acidente."


class EntregaBase(BaseTest):
    def setUp(self):
        super().setUp()
        oficina.hoje_brasil = lambda agora_utc=None: HOJE
        self.addCleanup(setattr, oficina, "hoje_brasil", HOJE_REAL)
        self.func = self.funcionario()
        self.dono_c = self.dono()
        self.func.post("/veiculos", data=VEICULO)
        self.vid = self.sql("SELECT id FROM veiculos")[0]["id"]
        self.sid1 = self.novo_servico("LATARIA", "Amassado na porta do motorista", "150,00")
        self.sid2 = self.novo_servico("PINTURA", "Pintura desbotada no capô", "250,50")
        self.aprovar()

    # ---- atalhos ----
    def novo_servico(self, tipo, problema, valor=None):
        self.func.post(f"/veiculos/{self.vid}/servicos", data={"tipo": tipo, "problema": problema})
        sid = self.sql("SELECT MAX(id) AS id FROM servicos")[0]["id"]
        if valor:
            self.dono_c.post(f"/veiculos/{self.vid}/servicos/{sid}/valor", data={"valor": valor})
        return sid

    def assinatura(self, cliente=None):
        pagina = (cliente or self.dono_c).get(f"/veiculos/{self.vid}").data.decode()
        achou = re.search(r'name="assinatura" value="([^"]+)"', pagina)
        return achou.group(1) if achou else None

    def aprovar(self, decisao="APROVADO"):
        self.func.post(f"/veiculos/{self.vid}/aprovacao",
                       data={"decisao": decisao, "forma": "TELEFONE", "assinatura": self.assinatura(self.func)})

    def garantia(self, sid, valor, unidade="DIAS", cliente=None):
        return (cliente or self.dono_c).post(f"/veiculos/{self.vid}/servicos/{sid}/garantia",
                                             data={"valor": str(valor), "unidade": unidade})

    def garantias_ok(self):
        """90 dias na lataria e 12 meses na pintura."""
        self.garantia(self.sid1, 90, "DIAS")
        self.garantia(self.sid2, 12, "MESES")

    def fechar(self, condicoes=CONDICOES, assinatura=..., cliente=None):
        cliente = cliente or self.dono_c
        self.marcar_pronto(self.vid)
        return cliente.post(f"/veiculos/{self.vid}/entrega", content_type="multipart/form-data", data={
            "condicoes": condicoes, "assinatura": self.assinatura(cliente) if assinatura is ... else assinatura,
            "fotos_entrega": foto_de_entrega()})

    def entregas(self):
        return self.sql("SELECT * FROM entregas ORDER BY id")

    def itens(self):
        return self.sql("SELECT * FROM entrega_itens ORDER BY id")

    def pagina(self, cliente=None):
        return (cliente or self.dono_c).get(f"/veiculos/{self.vid}").data.decode()

    def comprovante(self, cliente=None):
        return (cliente or self.dono_c).get(f"/veiculos/{self.vid}/comprovante")


class GarantiaPorServicoTest(EntregaBase):
    def guardado(self, sid):
        linha = self.sql("SELECT garantia_valor, garantia_unidade FROM servicos WHERE id = ?", (sid,))[0]
        return linha["garantia_valor"], linha["garantia_unidade"]

    def test_dono_define_garantia_de_cada_servico_em_dias_ou_meses(self):
        self.assertEqual(self.garantia(self.sid1, 90, "DIAS").status_code, 302)
        self.assertEqual(self.garantia(self.sid2, 12, "MESES").status_code, 302)
        self.assertEqual(self.guardado(self.sid1), (90, "DIAS"))
        self.assertEqual(self.guardado(self.sid2), (12, "MESES"))

    def test_zero_quer_dizer_sem_garantia_e_conta_como_informado(self):
        self.garantia(self.sid1, 0, "DIAS")
        self.assertEqual(self.guardado(self.sid1), (0, "DIAS"))
        self.assertIn("Sem garantia", self.pagina(self.func))      # o dono vê o campo com "0"; o funcionário vê o texto

    def test_da_para_corrigir_antes_da_entrega(self):
        self.garantia(self.sid1, 30, "DIAS")
        self.garantia(self.sid1, 6, "MESES")
        self.assertEqual(self.guardado(self.sid1), (6, "MESES"))

    def test_aparece_na_tela_com_singular_e_plural(self):
        self.garantia(self.sid1, 1, "MESES")
        self.garantia(self.sid2, 45, "DIAS")
        pagina = self.func.get(f"/veiculos/{self.vid}").data.decode()
        self.assertIn("1 mês", pagina)
        self.assertIn("45 dias", pagina)

    def test_funcionario_nao_define(self):
        self.assertEqual(self.garantia(self.sid1, 90, "DIAS", cliente=self.func).status_code, 403)
        self.assertEqual(self.guardado(self.sid1), (None, None))

    def test_so_o_dono_ve_os_campos_de_garantia(self):
        self.assertIn('aria-label="Tempo de garantia"', self.pagina(self.dono_c))
        self.assertNotIn('aria-label="Tempo de garantia"', self.pagina(self.func))

    def test_recusa_valores_invalidos(self):
        for valor, unidade in [("", "DIAS"), ("abc", "DIAS"), ("-1", "DIAS"), ("1.5", "DIAS"), ("1,5", "MESES"),
                               ("12345", "DIAS"), (" ", "DIAS"), ("10", ""), ("10", "ANOS"), ("10", "dias; DROP")]:
            r = self.garantia(self.sid1, valor, unidade)
            self.assertEqual(r.status_code, 200, (valor, unidade))
            self.assertIn(b'class="erros"', r.data, (valor, unidade))
        self.assertEqual(self.guardado(self.sid1), (None, None))

    def test_o_limite_depende_do_tipo_de_servico(self):
        # lataria: 12 meses (365 dias); pintura: 24 meses (730 dias) — detalhes em test_limites_desfazer.py
        self.assertEqual(self.garantia(self.sid1, 12, "MESES").status_code, 302)
        self.assertIn("limite de garantia para LATARIA".encode(), self.garantia(self.sid1, 13, "MESES").data)
        self.assertEqual(self.garantia(self.sid2, 24, "MESES").status_code, 302)
        self.assertIn("limite de garantia para PINTURA".encode(), self.garantia(self.sid2, 25, "MESES").data)

    def test_aceita_unidade_em_minusculas(self):
        self.garantia(self.sid1, 5, "meses")
        self.assertEqual(self.guardado(self.sid1), (5, "MESES"))

    def test_servico_inexistente_ou_de_outro_veiculo_da_404(self):
        self.assertEqual(self.garantia(99999, 10).status_code, 404)
        self.func.post("/veiculos", data={**VEICULO, "placa": "ZZZ9Z99"})
        outro = self.sql("SELECT id FROM veiculos WHERE placa = 'ZZZ9Z99'")[0]["id"]
        r = self.dono_c.post(f"/veiculos/{outro}/servicos/{self.sid1}/garantia", data={"valor": "5", "unidade": "DIAS"})
        self.assertEqual(r.status_code, 404)

    def test_sem_login_nao_define(self):
        r = oficina.app.test_client().post(f"/veiculos/{self.vid}/servicos/{self.sid1}/garantia",
                                           data={"valor": "5", "unidade": "DIAS"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith("/login"))


class CalculoDaGarantiaTest(unittest.TestCase):
    def test_dias(self):
        self.assertEqual(oficina.fim_da_garantia(date(2026, 10, 15), 90, "DIAS"), date(2027, 1, 13))
        self.assertEqual(oficina.fim_da_garantia(date(2026, 10, 15), 1, "DIAS"), date(2026, 10, 16))

    def test_meses(self):
        self.assertEqual(oficina.fim_da_garantia(date(2026, 10, 15), 12, "MESES"), date(2027, 10, 15))
        self.assertEqual(oficina.fim_da_garantia(date(2026, 11, 15), 3, "MESES"), date(2027, 2, 15))
        self.assertEqual(oficina.fim_da_garantia(date(2026, 10, 15), 120, "MESES"), date(2036, 10, 15))

    def test_meses_quando_o_dia_nao_existe_no_mes_de_destino(self):
        self.assertEqual(oficina.fim_da_garantia(date(2026, 1, 31), 1, "MESES"), date(2026, 2, 28))
        self.assertEqual(oficina.fim_da_garantia(date(2024, 1, 31), 1, "MESES"), date(2024, 2, 29))   # ano bissexto
        self.assertEqual(oficina.fim_da_garantia(date(2024, 2, 29), 12, "MESES"), date(2025, 2, 28))
        self.assertEqual(oficina.fim_da_garantia(date(2026, 8, 31), 1, "MESES"), date(2026, 9, 30))

    def test_virada_de_ano(self):
        self.assertEqual(oficina.fim_da_garantia(date(2026, 12, 20), 1, "MESES"), date(2027, 1, 20))
        self.assertEqual(oficina.fim_da_garantia(date(2026, 12, 31), 2, "MESES"), date(2027, 2, 28))

    def test_sem_garantia_nao_tem_data(self):
        self.assertIsNone(oficina.fim_da_garantia(date(2026, 10, 15), 0, "DIAS"))
        self.assertIsNone(oficina.fim_da_garantia(date(2026, 10, 15), None, None))

    def test_textos(self):
        casos = [((None, None), "-"), ((0, "DIAS"), "Sem garantia"), ((1, "DIAS"), "1 dia"), ((90, "DIAS"), "90 dias"),
                 ((1, "MESES"), "1 mês"), ((12, "MESES"), "12 meses")]
        for args, texto in casos:
            self.assertEqual(oficina.texto_garantia(*args), texto, args)

    def test_situacao_da_garantia(self):
        self.assertEqual(oficina.situacao_garantia(None, HOJE), ("SEM_GARANTIA", "Sem garantia"))
        self.assertEqual(oficina.situacao_garantia("2026-10-15", HOJE), ("VIGENTE", "Vigente até 15/10/2026"))   # no último dia ainda vale
        self.assertEqual(oficina.situacao_garantia("2026-10-14", HOJE), ("VENCIDA", "Venceu em 14/10/2026"))
        self.assertEqual(oficina.situacao_garantia("2027-01-13", HOJE), ("VIGENTE", "Vigente até 13/01/2027"))


class FecharEntregaTest(EntregaBase):
    def test_fecha_a_entrega_e_guarda_o_que_foi_combinado(self):
        self.garantias_ok()
        r = self.fechar()
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith(f"/veiculos/{self.vid}/comprovante"))
        e = self.entregas()[0]
        self.assertEqual((e["veiculo_id"], e["data_entrega"], e["condicoes"], e["total_centavos"], e["entregue_por"]),
                         (self.vid, "2026-10-15", CONDICOES, 40050, "DONA MARIA"))
        i1, i2 = self.itens()
        self.assertEqual((i1["tipo"], i1["valor_centavos"], i1["garantia_valor"], i1["garantia_unidade"], i1["garantia_ate"]),
                         ("LATARIA", 15000, 90, "DIAS", "2027-01-13"))
        self.assertEqual((i2["tipo"], i2["valor_centavos"], i2["garantia_valor"], i2["garantia_unidade"], i2["garantia_ate"]),
                         ("PINTURA", 25050, 12, "MESES", "2027-10-15"))

    def test_a_data_de_entrega_e_hoje_no_horario_de_brasilia(self):
        self.garantias_ok()
        self.fechar()
        self.assertEqual(self.entregas()[0]["data_entrega"], HOJE.isoformat())

    def test_nao_fecha_sem_informar_a_garantia_de_todos_os_servicos(self):
        self.garantia(self.sid1, 90, "DIAS")                        # falta o outro
        r = self.fechar()
        self.assertIn("Informe o tempo de garantia de todos os serviços".encode(), r.data)
        self.assertIn(b"falta 1", r.data)
        self.assertEqual(self.entregas(), [])

    def test_nao_fecha_sem_nenhuma_garantia_informada(self):
        r = self.fechar()
        self.assertIn(b"faltam 2", r.data)
        self.assertEqual(self.entregas(), [])

    def test_zero_conta_como_informado(self):
        self.garantia(self.sid1, 0, "DIAS")
        self.garantia(self.sid2, 6, "MESES")
        self.assertEqual(self.fechar().status_code, 302)
        self.assertIsNone(self.itens()[0]["garantia_ate"])
        self.assertEqual(self.itens()[1]["garantia_ate"], "2027-04-15")

    def test_botao_fica_desabilitado_enquanto_falta_garantia(self):
        pagina = self.pagina()
        self.assertIn("Falta informar o tempo de garantia de <strong>2</strong>", pagina)
        self.assertRegex(pagina, r"<button type=\"submit\" disabled>Fechar a entrega de hoje")
        self.garantias_ok()
        self.marcar_pronto(self.vid)          # com a garantia informada e o veículo pronto, o botão liga
        self.assertNotRegex(self.pagina(), r"<button type=\"submit\" disabled>Fechar a entrega")

    def test_exige_as_condicoes_que_cancelam_a_garantia(self):
        self.garantias_ok()
        for texto in ["", "   ", "curto", "1234567890123456789"]:
            r = self.fechar(condicoes=texto)
            self.assertIn("condições que cancelam a garantia".encode(), r.data, repr(texto))
        self.assertEqual(self.entregas(), [])

    def test_sem_nenhuma_garantia_as_condicoes_sao_opcionais(self):
        self.garantia(self.sid1, 0)
        self.garantia(self.sid2, 0)
        self.assertEqual(self.fechar(condicoes="").status_code, 302)
        self.assertIsNone(self.entregas()[0]["condicoes"])

    def test_condicoes_sao_limpas_mas_mantem_as_linhas(self):
        self.garantias_ok()
        self.fechar(condicoes="  Primeira   condição  longa o bastante \r\n\r\n\r\n   Segunda   condição   ")
        self.assertEqual(self.entregas()[0]["condicoes"], "Primeira condição longa o bastante\nSegunda condição")

    def test_condicoes_longas_demais_sao_recusadas(self):
        self.garantias_ok()
        r = self.fechar(condicoes="a" * (oficina.MAX_CONDICOES + 1))
        self.assertIn("no máximo".encode(), r.data)
        self.assertEqual(self.entregas(), [])

    def test_erro_mantem_o_texto_que_o_dono_escreveu(self):
        r = self.fechar(condicoes="Minhas condições, mas ainda falta garantia nos serviços")
        self.assertIn("Minhas condições, mas ainda falta garantia nos serviços".encode(), r.data)

    def test_o_formulario_ja_vem_com_o_texto_sugerido(self):
        self.assertIn("A garantia deixa de valer se:", self.pagina())

    def test_so_o_dono_fecha(self):
        self.garantias_ok()
        r = self.fechar(cliente=self.func, assinatura="x")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.entregas(), [])

    def test_so_o_dono_ve_o_formulario(self):
        self.garantias_ok()
        self.assertIn('name="condicoes"', self.pagina(self.dono_c))
        pagina = self.pagina(self.func)
        self.assertNotIn('name="condicoes"', pagina)
        self.assertIn("fechada pelo dono da oficina", pagina)

    def test_veiculo_inexistente_da_404_e_sem_login_redireciona(self):
        self.assertEqual(self.dono_c.post("/veiculos/99999/entrega", data={"condicoes": CONDICOES}).status_code, 404)
        r = oficina.app.test_client().post(f"/veiculos/{self.vid}/entrega", data={"condicoes": CONDICOES})
        self.assertTrue(r.headers["Location"].endswith("/login"))
        self.assertEqual(self.entregas(), [])

    def test_segunda_tentativa_de_fechar_e_barrada(self):
        self.garantias_ok()
        self.fechar()
        r = self.fechar()
        self.assertEqual(r.status_code, 409)
        self.assertIn("já foi entregue".encode(), r.data)
        self.assertEqual(len(self.entregas()), 1)
        self.assertEqual(len(self.itens()), 2)

    def test_o_banco_tambem_impede_duas_entregas_do_mesmo_veiculo(self):
        import sqlite3
        self.garantias_ok()
        self.fechar()
        with self.assertRaises(sqlite3.IntegrityError):
            self.sql("INSERT INTO entregas (veiculo_id, data_entrega, total_centavos) VALUES (?, '2026-10-16', 1)", (self.vid,))


class PrecisaDeAprovacaoParaEntregarTest(EntregaBase):
    def setUp(self):
        super().setUp()
        self.garantias_ok()

    def test_sem_aprovacao_nao_fecha(self):
        self.sql("DELETE FROM aprovacoes")
        r = self.fechar(assinatura="qualquer")
        self.assertIn("depois que o cliente aprovar".encode(), r.data)
        self.assertEqual(self.entregas(), [])

    def test_cliente_recusou_nao_fecha(self):
        self.sql("DELETE FROM aprovacoes")
        self.aprovar("RECUSADO")
        self.assertIn("depois que o cliente aprovar".encode(), self.fechar().data)
        self.assertEqual(self.entregas(), [])

    def test_orcamento_mudou_depois_da_aprovacao_nao_fecha(self):
        self.dono_c.post(f"/veiculos/{self.vid}/servicos/{self.sid1}/valor", data={"valor": "999,00"})
        self.assertIn("depois que o cliente aprovar".encode(), self.fechar().data)
        self.assertEqual(self.entregas(), [])

    def test_formulario_nao_aparece_sem_aprovacao_valendo(self):
        self.dono_c.post(f"/veiculos/{self.vid}/servicos/{self.sid1}/valor", data={"valor": "999,00"})
        pagina = self.pagina()
        self.assertNotIn('name="condicoes"', pagina)
        self.assertIn("só pode ser fechada depois que o cliente aprovar", pagina)

    def test_orcamento_que_mudou_enquanto_fechava_e_recusado(self):
        r = self.fechar(assinatura="assinatura-velha")
        self.assertIn("orçamento mudou enquanto você fechava".encode(), r.data)
        self.assertEqual(self.entregas(), [])

    def test_aprovacao_aparece_no_comprovante(self):
        self.fechar()
        self.assertIn("aprovado pelo cliente".encode(), self.comprovante().data)


class TravaAposEntregaTest(EntregaBase):
    def setUp(self):
        super().setUp()
        self.garantias_ok()
        self.fechar()
        self.antes = (self.sql("SELECT * FROM servicos"), len(self.sql("SELECT * FROM aprovacoes")),
                      len(self.sql("SELECT * FROM prazos")))

    def depois(self):
        return (self.sql("SELECT * FROM servicos"), len(self.sql("SELECT * FROM aprovacoes")),
                len(self.sql("SELECT * FROM prazos")))

    def assertTravado(self, resposta):
        self.assertEqual(resposta.status_code, 409)
        self.assertIn("já foi entregue".encode(), resposta.data)
        self.assertEqual([tuple(l) for l in self.depois()[0]], [tuple(l) for l in self.antes[0]])
        self.assertEqual(self.depois()[1:], self.antes[1:])

    def test_nao_aceita_novo_servico(self):
        self.assertTravado(self.func.post(f"/veiculos/{self.vid}/servicos",
                                          data={"tipo": "FREIOS", "problema": "Pastilha gasta nova"}))

    def test_nao_aceita_mudar_como_resolver(self):
        self.assertTravado(self.func.post(f"/veiculos/{self.vid}/servicos/{self.sid1}/resolucao",
                                          data={"como_resolver": "Outra forma de resolver"}))

    def test_nao_aceita_mudar_valor(self):
        self.assertTravado(self.dono_c.post(f"/veiculos/{self.vid}/servicos/{self.sid1}/valor", data={"valor": "1,00"}))

    def test_nao_aceita_excluir_servico(self):
        self.assertTravado(self.dono_c.post(f"/veiculos/{self.vid}/servicos/{self.sid1}/excluir"))

    def test_nao_aceita_mudar_garantia(self):
        self.assertTravado(self.garantia(self.sid1, 1, "DIAS"))

    def test_nao_aceita_nova_aprovacao(self):
        self.assertTravado(self.func.post(f"/veiculos/{self.vid}/aprovacao",
                                          data={"decisao": "RECUSADO", "forma": "TELEFONE", "assinatura": "x"}))

    def test_nao_aceita_novo_prazo(self):
        self.assertTravado(self.dono_c.post(f"/veiculos/{self.vid}/prazo",
                                            data={"data_prevista": (HOJE + timedelta(days=5)).isoformat()}))

    def test_a_pagina_nao_oferece_mais_formularios_de_alteracao(self):
        for cliente in (self.dono_c, self.func):
            pagina = self.pagina(cliente)
            for campo in ['name="problema"', 'name="decisao"', 'name="data_prevista"', 'name="como_resolver"',
                          'aria-label="Valor do serviço"', 'aria-label="Tempo de garantia"', 'name="condicoes"',
                          "Excluir este problema"]:
                self.assertNotIn(campo, pagina, campo)

    def test_a_pagina_mostra_a_entrega_e_as_garantias(self):
        pagina = self.pagina(self.func)
        self.assertIn("Entregue em 15/10/2026", pagina)
        self.assertIn("Vigente até 13/01/2027", pagina)
        self.assertIn("Vigente até 15/10/2027", pagina)
        self.assertIn(f"/veiculos/{self.vid}/comprovante", pagina)

    def test_garantia_vencida_aparece_como_vencida(self):
        oficina.hoje_brasil = lambda agora_utc=None: date(2027, 2, 1)      # passaram os 90 dias da lataria
        pagina = self.pagina()
        self.assertIn("Venceu em 13/01/2027", pagina)
        self.assertIn("Vigente até 15/10/2027", pagina)
        self.assertIn("selo-vencida", pagina)

    def test_outro_veiculo_continua_editavel(self):
        self.func.post("/veiculos", data={**VEICULO, "placa": "ZZZ9Z99"})
        outro = self.sql("SELECT id FROM veiculos WHERE placa = 'ZZZ9Z99'")[0]["id"]
        r = self.func.post(f"/veiculos/{outro}/servicos", data={"tipo": "FREIOS", "problema": "Pastilha gasta nova"})
        self.assertEqual(r.status_code, 302)

    def test_ler_continua_permitido(self):
        self.assertEqual(self.func.get(f"/veiculos/{self.vid}").status_code, 200)
        self.assertEqual(self.func.get("/").status_code, 200)

    def test_lista_mostra_entregue_no_lugar_do_prazo(self):
        pagina = self.func.get("/").data.decode()
        self.assertIn("Entregue em 15/10/2026", pagina)
        self.assertIn("selo-entregue", pagina)


class ComprovanteTest(EntregaBase):
    def entregar(self):
        self.garantias_ok()
        self.fechar()

    def test_sem_entrega_da_404(self):
        self.assertEqual(self.comprovante().status_code, 404)

    def test_veiculo_inexistente_da_404(self):
        self.assertEqual(self.dono_c.get("/veiculos/99999/comprovante").status_code, 404)

    def test_sem_login_redireciona(self):
        self.entregar()
        r = oficina.app.test_client().get(f"/veiculos/{self.vid}/comprovante")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith("/login"))

    def test_funcionario_tambem_ve_e_imprime(self):
        self.entregar()
        self.assertEqual(self.comprovante(self.func).status_code, 200)

    def test_tem_tudo_que_o_cliente_precisa(self):
        self.entregar()
        pagina = self.comprovante().data.decode()
        for texto in ["OFICINA ITAMARACÁ", "Comprovante de entrega e garantia", "ABC1D23", "FIAT", "UNO", "VERMELHO",
                      "JOSE DA SILVA", "15/10/2026", "LATARIA", "Amassado na porta do motorista", "R$ 150,00",
                      "90 dias", "13/01/2027", "PINTURA", "R$ 250,50", "12 meses", "15/10/2027", "R$ 400,50",
                      "Condições que cancelam a garantia", CONDICOES, "DONA MARIA", "Cliente", "Oficina Itamaracá",
                      "aprovado pelo cliente", "window.print()"]:
            self.assertIn(texto, pagina, texto)

    def test_a_data_de_fim_da_garantia_aparece_por_servico(self):
        self.garantia(self.sid1, 90, "DIAS")
        self.garantia(self.sid2, 0, "DIAS")
        self.fechar()
        pagina = self.comprovante().data.decode()
        self.assertIn("13/01/2027", pagina)
        self.assertIn("Sem garantia", pagina)

    def test_sem_garantia_nenhuma_avisa_no_comprovante(self):
        self.garantia(self.sid1, 0)
        self.garantia(self.sid2, 0)
        self.fechar(condicoes="")
        pagina = self.comprovante().data.decode()
        self.assertIn("Nenhum dos serviços acima tem garantia", pagina)
        self.assertNotIn("Condições que cancelam a garantia", pagina)

    def test_comprovante_e_uma_copia_fiel_e_nao_muda_depois(self):
        self.entregar()
        antes = self.comprovante().data
        self.sql("UPDATE servicos SET problema = 'TEXTO ALTERADO NO BANCO', valor_centavos = 1, garantia_valor = 1")
        self.sql("DELETE FROM servicos WHERE id = ?", (self.sid2,))
        self.assertEqual(self.comprovante().data, antes)

    def test_condicoes_com_html_aparecem_como_texto(self):
        self.garantias_ok()
        self.fechar(condicoes="<script>alert(1)</script> vale para quem lê este comprovante")
        pagina = self.comprovante().data
        self.assertNotIn(b"<script>alert(1)</script>", pagina)
        self.assertIn(b"&lt;script&gt;", pagina)

    def test_problema_com_html_aparece_como_texto(self):
        self.sql("UPDATE servicos SET problema = '<img src=x onerror=alert(1)> amassado' WHERE id = ?", (self.sid1,))
        self.entregar()
        self.assertNotIn(b"<img src=x onerror", self.comprovante().data)

    def test_o_comprovante_tem_regras_de_impressao(self):
        self.entregar()
        resposta = self.dono_c.get("/static/estilo.css")
        css = resposta.data.decode()
        resposta.close()
        self.assertIn("@media print", css)
        self.assertIn(".nao-imprimir { display: none", css)
        self.assertIn("nao-imprimir", self.comprovante().data.decode())


class EntregaComCsrfTest(EntregaBase):
    def test_sem_token_nao_fecha_e_nao_define_garantia(self):
        self.garantias_ok()
        oficina.app.config["WTF_CSRF_ENABLED"] = True      # liga só depois de montar os dados do teste
        self.addCleanup(oficina.app.config.__setitem__, "WTF_CSRF_ENABLED", False)
        r = self.fechar()
        self.assertTrue(r.headers["Location"].endswith("/login?expirou=1"))
        self.assertEqual(self.entregas(), [])
        r = self.garantia(self.sid1, 1, "DIAS")
        self.assertTrue(r.headers["Location"].endswith("/login?expirou=1"))


class MigracaoTest(unittest.TestCase):
    def test_banco_antigo_ganha_as_colunas_e_tabelas_novas_sem_perder_dados(self):
        import os, sqlite3, subprocess, sys, tempfile
        caminho = os.path.join(tempfile.mkdtemp(), "antigo.db")
        banco = sqlite3.connect(caminho)
        banco.execute("CREATE TABLE veiculos (id INTEGER PRIMARY KEY AUTOINCREMENT, responsavel TEXT, placa TEXT NOT NULL, "
                      "marca TEXT, modelo TEXT, cor TEXT, ano TEXT, quilometragem TEXT, documento_deixado INTEGER NOT NULL)")
        banco.execute("CREATE TABLE servicos (id INTEGER PRIMARY KEY AUTOINCREMENT, veiculo_id INTEGER NOT NULL, "
                      "tipo TEXT NOT NULL, problema TEXT NOT NULL, registrado_por TEXT, "
                      "criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")          # como era antes das histórias 4 a 8
        banco.execute("INSERT INTO veiculos (placa, documento_deixado) VALUES ('OLD1A11', 1)")
        banco.execute("INSERT INTO servicos (veiculo_id, tipo, problema) VALUES (1, 'LATARIA', 'Amassado antigo')")
        banco.commit()
        banco.close()
        pasta_projeto = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ambiente = dict(os.environ, OFICINA_DB=caminho, OFICINA_SECRET="x", OFICINA_FOTOS=os.path.join(os.path.dirname(caminho), "f"))
        r = subprocess.run([sys.executable, "-c", "import app"], cwd=pasta_projeto, env=ambiente, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        banco = sqlite3.connect(caminho)
        colunas = [c[1] for c in banco.execute("PRAGMA table_info(servicos)")]
        for coluna in ("como_resolver", "valor_centavos", "garantia_valor", "garantia_unidade"):
            self.assertIn(coluna, colunas)
        tabelas = {t[0] for t in banco.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for tabela in ("aprovacoes", "prazos", "entregas", "entrega_itens", "limites_garantia",
                       "entregas_desfeitas", "entrega_itens_desfeitos"):
            self.assertIn(tabela, tabelas)
        self.assertEqual(banco.execute("SELECT placa FROM veiculos").fetchone()[0], "OLD1A11")
        self.assertEqual(banco.execute("SELECT problema FROM servicos").fetchone()[0], "Amassado antigo")
        banco.close()


if __name__ == "__main__":
    unittest.main()
