"""Testes dos limites de garantia por tipo de serviço e do desfazer a entrega.
Rodar na pasta do projeto:  python -m unittest discover tests -v"""
import re
import unittest
from datetime import date

from base import BaseTest, foto_de_entrega, oficina

HOJE_REAL = oficina.hoje_brasil
HOJE = date(2026, 10, 15)
VEICULO = {"responsavel": "JOSE DA SILVA", "placa": "ABC1D23", "marca": "FIAT", "modelo": "UNO",
           "cor": "VERMELHO", "ano": "2012", "quilometragem": "150000", "documento_deixado": "on"}
CONDICOES = "A garantia deixa de valer se o veículo for consertado por outra oficina ou sofrer acidente."


class Base(BaseTest):
    def setUp(self):
        super().setUp()
        oficina.hoje_brasil = lambda agora_utc=None: HOJE
        self.addCleanup(setattr, oficina, "hoje_brasil", HOJE_REAL)
        self.func = self.funcionario()
        self.dono_c = self.dono()
        self.func.post("/veiculos", data=VEICULO)
        self.vid = self.sql("SELECT id FROM veiculos")[0]["id"]

    def servico(self, tipo, valor="100,00", vid=None):
        vid = vid or self.vid
        self.func.post(f"/veiculos/{vid}/servicos", data={"tipo": tipo, "problema": f"Problema de {tipo.lower()} aqui"})
        sid = self.sql("SELECT MAX(id) AS id FROM servicos")[0]["id"]
        if valor:
            self.dono_c.post(f"/veiculos/{vid}/servicos/{sid}/valor", data={"valor": valor})
        return sid

    def garantia(self, sid, valor, unidade="MESES", vid=None, cliente=None):
        return (cliente or self.dono_c).post(f"/veiculos/{vid or self.vid}/servicos/{sid}/garantia",
                                             data={"valor": str(valor), "unidade": unidade})

    def guardado(self, sid):
        linha = self.sql("SELECT garantia_valor, garantia_unidade FROM servicos WHERE id = ?", (sid,))[0]
        return linha["garantia_valor"], linha["garantia_unidade"]

    def assinatura(self, vid=None, cliente=None):
        pagina = (cliente or self.dono_c).get(f"/veiculos/{vid or self.vid}").data.decode()
        achou = re.search(r'name="assinatura" value="([^"]+)"', pagina)
        return achou.group(1) if achou else None

    def aprovar(self, vid=None):
        vid = vid or self.vid
        self.func.post(f"/veiculos/{vid}/aprovacao",
                       data={"decisao": "APROVADO", "forma": "TELEFONE", "assinatura": self.assinatura(vid, self.func)})


class LimitesPorTipoTest(Base):
    def test_valores_de_partida(self):
        self.assertEqual(oficina.LIMITES_PADRAO_MESES,
                         {"LATARIA": 12, "PINTURA": 24, "MECÂNICA": 6, "ELÉTRICA": 6, "SUSPENSÃO": 12,
                          "FREIOS": 6, "POLIMENTO E ESTÉTICA": 3, "OUTRO": 12})

    def test_todo_tipo_de_servico_tem_um_limite(self):
        self.assertEqual(set(oficina.LIMITES_PADRAO_MESES), set(oficina.TIPOS_SERVICO))

    def test_cada_tipo_aceita_ate_o_seu_limite_em_meses_e_recusa_um_a_mais(self):
        for tipo, limite in oficina.LIMITES_PADRAO_MESES.items():
            sid = self.servico(tipo)
            self.assertEqual(self.garantia(sid, limite, "MESES").status_code, 302, tipo)
            r = self.garantia(sid, limite + 1, "MESES")
            self.assertEqual(r.status_code, 200, tipo)
            self.assertIn(f"limite de garantia para {tipo}".encode(), r.data)
            self.assertEqual(self.guardado(sid), (limite, "MESES"), tipo)

    def test_mecanica_6_meses(self):
        sid = self.servico("MECÂNICA")
        self.assertEqual(self.garantia(sid, 6, "MESES").status_code, 302)
        r = self.garantia(sid, 7, "MESES")
        self.assertIn("limite de garantia para MECÂNICA é 6 meses (183 dias)".encode(), r.data)

    def test_em_dias_o_limite_e_o_mesmo_tempo(self):
        casos = {"LATARIA": 365, "PINTURA": 730, "MECÂNICA": 183, "POLIMENTO E ESTÉTICA": 92}
        for tipo, dias in casos.items():
            sid = self.servico(tipo)
            self.assertEqual(self.garantia(sid, dias, "DIAS").status_code, 302, (tipo, dias))
            self.assertEqual(self.garantia(sid, dias + 1, "DIAS").status_code, 200, (tipo, dias + 1))

    def test_zero_sempre_vale(self):
        sid = self.servico("POLIMENTO E ESTÉTICA")
        self.assertEqual(self.garantia(sid, 0, "DIAS").status_code, 302)

    def test_mensagem_traz_o_limite_em_meses_e_dias(self):
        sid = self.servico("PINTURA")
        self.assertIn("é 24 meses (730 dias)".encode(), self.garantia(sid, 25, "MESES").data)

    def test_o_limite_aparece_ao_lado_do_campo(self):
        self.servico("PINTURA")
        self.servico("POLIMENTO E ESTÉTICA")
        pagina = self.dono_c.get(f"/veiculos/{self.vid}").data.decode()
        self.assertIn("máx. 24 meses", pagina)
        self.assertIn("máx. 3 meses", pagina)

    def test_servico_de_tipo_desconhecido_no_banco_cai_no_teto_geral(self):
        sid = self.servico("OUTRO")
        self.sql("UPDATE servicos SET tipo = 'TIPO ANTIGO' WHERE id = ?", (sid,))
        r = self.garantia(sid, oficina.MAX_LIMITE_MESES, "MESES")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.garantia(sid, oficina.MAX_LIMITE_MESES + 1, "MESES").status_code, 200)

    def test_calculos_auxiliares(self):
        self.assertEqual(oficina.limite_em("MESES", 24), 24)
        self.assertEqual(oficina.limite_em("DIAS", 12), 365)
        self.assertEqual(oficina.limite_em("DIAS", 6), 183)
        self.assertEqual(oficina.limite_em("DIAS", 3), 92)
        self.assertEqual(oficina.texto_limite(1), "1 mês (31 dias)")
        self.assertEqual(oficina.texto_limite(24), "24 meses (730 dias)")


class TelaDeLimitesTest(Base):
    def salvar(self, **mudancas):
        padrao = dict(oficina.LIMITES_PADRAO_MESES)
        dados = {}
        for i, tipo in enumerate(oficina.TIPOS_SERVICO):
            dados[f"meses_{i}"] = str(mudancas.get(tipo, padrao[tipo]))
        return self.dono_c.post("/limites-garantia", data=dados)

    def guardados(self):
        return {l["tipo"]: l["meses"] for l in self.sql("SELECT tipo, meses FROM limites_garantia")}

    def test_dono_ve_todos_os_tipos_com_o_limite_atual(self):
        r = self.dono_c.get("/limites-garantia")
        self.assertEqual(r.status_code, 200)
        pagina = r.data.decode()
        for tipo in oficina.TIPOS_SERVICO:
            self.assertIn(tipo, pagina)
        self.assertIn('value="24"', pagina)       # pintura
        self.assertIn('value="6"', pagina)        # mecânica, elétrica e freios
        self.assertIn("24 meses (730 dias)", pagina)

    def test_funcionario_nao_acessa(self):
        self.assertEqual(self.func.get("/limites-garantia").status_code, 403)
        self.assertEqual(self.func.post("/limites-garantia", data={"meses_0": "5"}).status_code, 403)
        self.assertEqual(self.guardados(), {})

    def test_sem_login_vai_para_o_login(self):
        r = oficina.app.test_client().get("/limites-garantia")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith("/login"))

    def test_menu_so_mostra_o_link_para_o_dono(self):
        self.assertIn(b"/limites-garantia", self.dono_c.get("/").data)
        self.assertNotIn(b"/limites-garantia", self.func.get("/").data)

    def test_salvar_muda_o_limite_na_hora(self):
        sid = self.servico("PINTURA")
        self.assertEqual(self.garantia(sid, 30, "MESES").status_code, 200)         # passa de 24: recusa
        r = self.salvar(PINTURA=36)
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith("/limites-garantia?salvo=1"))
        self.assertEqual(self.guardados()["PINTURA"], 36)
        self.assertEqual(self.garantia(sid, 30, "MESES").status_code, 302)         # agora passa
        self.assertEqual(self.garantia(sid, 37, "MESES").status_code, 200)
        pagina = self.dono_c.get("/limites-garantia?salvo=1").data.decode()
        self.assertIn("Limites salvos", pagina)
        self.assertIn('value="36"', pagina)

    def test_baixar_o_limite_nao_mexe_em_garantias_ja_informadas(self):
        sid = self.servico("PINTURA")
        self.garantia(sid, 20, "MESES")
        self.salvar(PINTURA=6)
        self.assertEqual(self.guardado(sid), (20, "MESES"))
        self.assertEqual(self.garantia(sid, 7, "MESES").status_code, 200)

    def test_limites_de_cada_tipo_sao_independentes(self):
        self.salvar(FREIOS=18)
        outro = self.servico("ELÉTRICA")
        freios = self.servico("FREIOS")
        self.assertEqual(self.garantia(freios, 18, "MESES").status_code, 302)
        self.assertEqual(self.garantia(outro, 7, "MESES").status_code, 200)

    def test_aceita_1_e_120(self):
        self.assertEqual(self.salvar(FREIOS=1, PINTURA=120).status_code, 302)
        self.assertEqual(self.guardados()["FREIOS"], 1)
        self.assertEqual(self.guardados()["PINTURA"], 120)

    def test_recusa_valores_invalidos_e_nao_salva_nada(self):
        for ruim in ["", " ", "0", "121", "abc", "-1", "1.5", "1,5", "1000", "12 meses"]:
            r = self.salvar(FREIOS=ruim, PINTURA=30)
            self.assertEqual(r.status_code, 200, repr(ruim))
            self.assertIn("FREIOS: informe um número inteiro de meses".encode(), r.data, repr(ruim))
            self.assertEqual(self.guardados(), {}, repr(ruim))      # tudo ou nada: o PINTURA=30 válido também não foi salvo

    def test_erro_mantem_o_que_foi_digitado(self):
        r = self.salvar(FREIOS="abc", PINTURA=30)
        self.assertIn(b'value="abc"', r.data)
        self.assertIn(b'value="30"', r.data)

    def test_tipo_removido_no_banco_e_ignorado(self):
        self.sql("INSERT INTO limites_garantia (tipo, meses) VALUES ('TIPO QUE NAO EXISTE MAIS', 99)")
        with oficina.app.app_context():
            self.assertNotIn("TIPO QUE NAO EXISTE MAIS", oficina.limites_de_garantia(oficina.get_db()))

    def test_sem_token_nao_salva(self):
        oficina.app.config["WTF_CSRF_ENABLED"] = True
        self.addCleanup(oficina.app.config.__setitem__, "WTF_CSRF_ENABLED", False)
        r = self.salvar(FREIOS=30)
        self.assertTrue(r.headers["Location"].endswith("/login?expirou=1"))
        self.assertEqual(self.guardados(), {})


class DesfazerEntregaTest(Base):
    def setUp(self):
        super().setUp()
        self.s1 = self.servico("LATARIA", "150,00")
        self.s2 = self.servico("PINTURA", "250,50")
        self.aprovar()
        self.garantia(self.s1, 90, "DIAS")
        self.garantia(self.s2, 12, "MESES")

    # ---- atalhos ----
    def fechar(self, vid=None):
        vid = vid or self.vid
        self.marcar_pronto(vid)
        return self.dono_c.post(f"/veiculos/{vid}/entrega", content_type="multipart/form-data",
                                data={"condicoes": CONDICOES, "assinatura": self.assinatura(vid), "fotos_entrega": foto_de_entrega()})

    def desfazer(self, motivo="Cliente pediu para trocar o serviço de pintura", cliente=None, vid=None):
        return (cliente or self.dono_c).post(f"/veiculos/{vid or self.vid}/entrega/desfazer", data={"motivo": motivo})

    def entregas(self):
        return self.sql("SELECT * FROM entregas")

    def desfeitas(self):
        return self.sql("SELECT * FROM entregas_desfeitas ORDER BY id")

    def pagina(self, cliente=None, vid=None):
        return (cliente or self.dono_c).get(f"/veiculos/{vid or self.vid}").data.decode()

    def entregar_e_desfazer(self):
        self.fechar()
        return self.desfazer()

    # ---- testes ----
    def test_dono_desfaz_com_motivo(self):
        self.fechar()
        r = self.desfazer()
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.entregas(), [])
        self.assertEqual(self.sql("SELECT * FROM entrega_itens"), [])

    def test_a_copia_da_entrega_desfeita_fica_guardada(self):
        self.fechar()
        original = self.entregas()[0]
        self.desfazer("Cliente pediu para trocar o serviço de pintura")
        d = self.desfeitas()[0]
        self.assertEqual((d["veiculo_id"], d["data_entrega"], d["condicoes"], d["total_centavos"], d["entregue_por"]),
                         (self.vid, "2026-10-15", CONDICOES, 40050, "DONA MARIA"))
        self.assertEqual(d["entregue_em"], original["criado_em"])
        self.assertEqual((d["motivo"], d["desfeita_por"]), ("Cliente pediu para trocar o serviço de pintura", "DONA MARIA"))
        self.assertTrue(d["desfeita_em"])
        itens = self.sql("SELECT * FROM entrega_itens_desfeitos ORDER BY id")
        self.assertEqual([(i["tipo"], i["valor_centavos"], i["garantia_valor"], i["garantia_unidade"], i["garantia_ate"])
                          for i in itens],
                         [("LATARIA", 15000, 90, "DIAS", "2027-01-13"), ("PINTURA", 25050, 12, "MESES", "2027-10-15")])
        self.assertTrue(all(i["entrega_desfeita_id"] == d["id"] for i in itens))

    def test_o_cadastro_destrava(self):
        self.entregar_e_desfazer()
        pagina = self.pagina()
        for campo in ['name="problema"', 'name="decisao"', 'aria-label="Tempo de garantia"', 'aria-label="Valor do serviço"']:
            self.assertIn(campo, pagina, campo)
        r = self.func.post(f"/veiculos/{self.vid}/servicos", data={"tipo": "FREIOS", "problema": "Pastilha gasta nova"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.dono_c.post(f"/veiculos/{self.vid}/servicos/{self.s1}/valor", data={"valor": "180,00"}).status_code, 302)
        self.assertEqual(self.garantia(self.s1, 60, "DIAS").status_code, 302)

    def test_o_comprovante_antigo_deixa_de_existir_e_a_pagina_volta_ao_normal(self):
        self.fechar()
        self.assertEqual(self.dono_c.get(f"/veiculos/{self.vid}/comprovante").status_code, 200)
        self.desfazer()
        self.assertEqual(self.dono_c.get(f"/veiculos/{self.vid}/comprovante").status_code, 404)
        pagina = self.pagina()
        self.assertNotIn("Entregue em", pagina)
        self.assertIn("Fechar a entrega de hoje", pagina)

    def test_lista_deixa_de_mostrar_entregue(self):
        self.fechar()
        self.assertIn("Entregue em 15/10/2026", self.func.get("/").data.decode())
        self.desfazer()
        lista = self.func.get("/").data.decode()
        self.assertNotIn("Entregue em", lista)
        self.assertIn("Sem prazo definido", lista)

    def test_historico_de_entregas_desfeitas_na_tela(self):
        self.entregar_e_desfazer()
        pagina = self.pagina(self.func)
        self.assertIn("Entregas desfeitas (1)", pagina)
        self.assertIn("Cliente pediu para trocar o serviço de pintura", pagina)
        self.assertIn("DONA MARIA", pagina)
        self.assertIn("15/10/2026", pagina)

    def test_fechar_de_novo_gera_outro_comprovante_e_o_historico_continua(self):
        self.entregar_e_desfazer()
        self.dono_c.post(f"/veiculos/{self.vid}/servicos/{self.s2}/valor", data={"valor": "300,00"})
        self.aprovar()                                              # o valor mudou: o cliente aprova de novo
        self.assertEqual(self.fechar().status_code, 302)
        self.assertEqual(len(self.entregas()), 1)
        self.assertEqual(self.entregas()[0]["total_centavos"], 45000)
        self.assertIn("R$ 450,00", self.dono_c.get(f"/veiculos/{self.vid}/comprovante").data.decode())
        self.assertEqual(len(self.desfeitas()), 1)
        self.assertEqual(self.desfeitas()[0]["total_centavos"], 40050)      # a antiga continua guardada com o valor antigo

    def test_pode_desfazer_mais_de_uma_vez(self):
        self.entregar_e_desfazer()
        self.fechar()
        self.desfazer("Segunda correção necessária na entrega")
        self.assertEqual(len(self.desfeitas()), 2)
        self.assertIn("Entregas desfeitas (2)", self.pagina())

    def test_motivo_e_obrigatorio(self):
        self.fechar()
        for motivo in ["", "   ", "ab", "123", "!!!"]:
            r = self.desfazer(motivo)
            self.assertIn("Explique o motivo de desfazer".encode(), r.data, repr(motivo))
        self.assertEqual(len(self.entregas()), 1)
        self.assertEqual(self.desfeitas(), [])

    def test_motivo_longo_demais(self):
        self.fechar()
        r = self.desfazer("a" * (oficina.MAX_MOTIVO_DESFAZER + 1))
        self.assertIn("no máximo".encode(), r.data)
        self.assertEqual(len(self.entregas()), 1)

    def test_nao_desfaz_o_que_nao_foi_entregue(self):
        r = self.desfazer()
        self.assertIn("não há entrega para desfazer".encode(), r.data)
        self.assertEqual(self.desfeitas(), [])

    def test_nao_desfaz_duas_vezes_seguidas(self):
        self.entregar_e_desfazer()
        r = self.desfazer("Tentando desfazer outra vez")
        self.assertIn("não há entrega para desfazer".encode(), r.data)
        self.assertEqual(len(self.desfeitas()), 1)

    def test_funcionario_nao_desfaz(self):
        self.fechar()
        self.assertEqual(self.desfazer(cliente=self.func).status_code, 403)
        self.assertEqual(len(self.entregas()), 1)
        self.assertEqual(self.desfeitas(), [])

    def test_so_o_dono_ve_o_botao(self):
        self.fechar()
        self.assertIn("Desfazer a entrega", self.pagina(self.dono_c))
        self.assertNotIn("Desfazer a entrega", self.pagina(self.func))

    def test_veiculo_inexistente_da_404_e_sem_login_redireciona(self):
        self.assertEqual(self.desfazer(vid=99999).status_code, 404)
        r = oficina.app.test_client().post(f"/veiculos/{self.vid}/entrega/desfazer", data={"motivo": "Tentativa sem entrar"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith("/login"))

    def test_motivo_com_html_aparece_como_texto(self):
        self.fechar()
        self.desfazer("<script>alert(1)</script> erro de digitação")
        pagina = self.pagina()
        self.assertNotIn("<script>alert(1)</script>", pagina)
        self.assertIn("&lt;script&gt;", pagina)

    def test_enquanto_entregue_o_cadastro_continua_travado(self):
        self.fechar()
        r = self.dono_c.post(f"/veiculos/{self.vid}/servicos/{self.s1}/valor", data={"valor": "1,00"})
        self.assertEqual(r.status_code, 409)

    def test_a_copia_guardada_nao_muda_quando_o_cadastro_e_corrigido_depois(self):
        self.entregar_e_desfazer()
        self.sql("UPDATE servicos SET problema = 'TEXTO NOVO', valor_centavos = 1")
        itens = self.sql("SELECT problema, valor_centavos FROM entrega_itens_desfeitos ORDER BY id")
        self.assertEqual([i["valor_centavos"] for i in itens], [15000, 25050])
        self.assertNotIn("TEXTO NOVO", [i["problema"] for i in itens])

    def test_outro_veiculo_entregue_nao_e_afetado(self):
        self.func.post("/veiculos", data={**VEICULO, "placa": "ZZZ9Z99"})
        outro = self.sql("SELECT id FROM veiculos WHERE placa = 'ZZZ9Z99'")[0]["id"]
        o1 = self.servico("FREIOS", "80,00", vid=outro)
        self.aprovar(outro)
        self.garantia(o1, 3, "MESES", vid=outro)
        self.fechar(outro)
        self.fechar()
        self.desfazer()
        self.assertEqual([e["veiculo_id"] for e in self.entregas()], [outro])
        self.assertEqual([d["veiculo_id"] for d in self.desfeitas()], [self.vid])
        self.assertNotIn("Entregas desfeitas", self.pagina(vid=outro))

    def test_sem_token_nao_desfaz(self):
        self.fechar()
        oficina.app.config["WTF_CSRF_ENABLED"] = True
        self.addCleanup(oficina.app.config.__setitem__, "WTF_CSRF_ENABLED", False)
        r = self.desfazer()
        self.assertTrue(r.headers["Location"].endswith("/login?expirou=1"))
        self.assertEqual(len(self.entregas()), 1)
        self.assertEqual(self.desfeitas(), [])

    def test_falha_no_meio_nao_perde_a_entrega(self):
        self.fechar()
        self.sql("ALTER TABLE entrega_itens_desfeitos RENAME TO entrega_itens_desfeitos_x")   # força um erro no meio
        try:
            oficina.app.config["PROPAGATE_EXCEPTIONS"] = False
            oficina.app.testing = False
            r = self.desfazer()
            self.assertEqual(r.status_code, 500)
        finally:
            oficina.app.testing = True
            self.sql("ALTER TABLE entrega_itens_desfeitos_x RENAME TO entrega_itens_desfeitos")
        self.assertEqual(len(self.entregas()), 1)                # a entrega continua inteira
        self.assertEqual(len(self.sql("SELECT * FROM entrega_itens")), 2)
        self.assertEqual(self.desfeitas(), [])                    # e nada ficou pela metade no histórico


if __name__ == "__main__":
    unittest.main()
