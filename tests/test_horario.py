"""Testes do horário de Brasília nas telas (o banco guarda tudo em UTC, 3 horas à frente).
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
HORA_CRUA = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")      # como o banco guarda: não pode aparecer nas telas


class FiltroHoraBrasilTest(unittest.TestCase):
    def confere(self, utc, esperado):
        self.assertEqual(oficina.hora_brasil(utc), esperado, utc)

    def test_converte_utc_para_brasilia(self):
        self.confere("2026-10-06 00:30:30", "05/10/2026 21:30")       # passou da meia-noite em UTC, ainda é "ontem" aqui
        self.confere("2026-10-05 15:00:00", "05/10/2026 12:00")
        self.confere("2026-10-05 23:59:59", "05/10/2026 20:59")

    def test_virada_do_dia(self):
        self.confere("2026-10-06 02:59:59", "05/10/2026 23:59")
        self.confere("2026-10-06 03:00:00", "06/10/2026 00:00")

    def test_virada_do_ano_e_do_mes(self):
        self.confere("2027-01-01 02:15:00", "31/12/2026 23:15")
        self.confere("2026-11-01 01:00:00", "31/10/2026 22:00")

    def test_29_de_fevereiro_de_ano_bissexto(self):
        self.confere("2024-03-01 01:00:00", "29/02/2024 22:00")

    def test_vazio_vira_traco(self):
        self.confere(None, "-")
        self.confere("", "-")

    def test_texto_que_nao_e_data_e_mostrado_como_veio(self):
        self.confere("ontem à noite", "ontem à noite")
        self.confere("2026-10-06", "2026-10-06")
        self.confere("2026-13-45 99:99:99", "2026-13-45 99:99:99")

    def test_o_filtro_esta_registrado_nos_modelos(self):
        self.assertIs(oficina.app.jinja_env.filters["hora_brasil"], oficina.hora_brasil)


class HorarioNasTelasTest(BaseTest):
    def setUp(self):
        super().setUp()
        oficina.hoje_brasil = lambda agora_utc=None: HOJE
        self.addCleanup(setattr, oficina, "hoje_brasil", HOJE_REAL)
        self.func = self.funcionario()
        self.dono_c = self.dono()
        self.func.post("/veiculos", data=VEICULO)
        self.vid = self.sql("SELECT id FROM veiculos")[0]["id"]
        self.func.post(f"/veiculos/{self.vid}/servicos", data={"tipo": "LATARIA", "problema": "Amassado na porta do motorista"})
        self.sid = self.sql("SELECT id FROM servicos")[0]["id"]
        self.dono_c.post(f"/veiculos/{self.vid}/servicos/{self.sid}/valor", data={"valor": "150,00"})
        # duas aprovações e dois prazos, para aparecerem também as tabelas de histórico
        self.aprovar("RECUSADO")
        self.aprovar("APROVADO")
        self.dono_c.post(f"/veiculos/{self.vid}/prazo", data={"data_prevista": (HOJE + timedelta(days=10)).isoformat()})
        self.dono_c.post(f"/veiculos/{self.vid}/prazo", data={"data_prevista": (HOJE + timedelta(days=20)).isoformat(),
                                                              "motivo": "Peça importada atrasou"})
        self.dono_c.post(f"/veiculos/{self.vid}/servicos/{self.sid}/garantia", data={"valor": "6", "unidade": "MESES"})
        self.fechar()
        self.dono_c.post(f"/veiculos/{self.vid}/entrega/desfazer", data={"motivo": "Cliente pediu uma correção no serviço"})
        self.fechar()                                       # a entrega vale de novo; a desfeita fica no histórico
        # horários conhecidos, em UTC, em cada tabela
        self.sql("UPDATE servicos SET criado_em = '2026-10-06 00:30:30'")
        self.sql("UPDATE aprovacoes SET criado_em = '2026-10-06 03:00:00'")
        self.sql("UPDATE prazos SET criado_em = '2026-12-31 15:45:10'")
        self.sql("UPDATE entregas SET criado_em = '2027-01-01 02:15:00'")
        self.sql("UPDATE entregas_desfeitas SET desfeita_em = '2026-07-04 12:00:00'")

    def assinatura(self):
        pagina = self.dono_c.get(f"/veiculos/{self.vid}").data.decode()
        achou = re.search(r'name="assinatura" value="([^"]+)"', pagina)
        return achou.group(1) if achou else None

    def aprovar(self, decisao):
        self.func.post(f"/veiculos/{self.vid}/aprovacao",
                       data={"decisao": decisao, "forma": "TELEFONE", "assinatura": self.assinatura()})

    def fechar(self):
        self.marcar_pronto(self.vid)
        return self.dono_c.post(f"/veiculos/{self.vid}/entrega", content_type="multipart/form-data",
                                data={"condicoes": CONDICOES, "assinatura": self.assinatura(), "fotos_entrega": foto_de_entrega()})

    def pagina(self):
        return self.dono_c.get(f"/veiculos/{self.vid}").data.decode()

    def test_servico_mostra_a_hora_de_brasilia(self):
        self.assertIn("05/10/2026 21:30", self.pagina())

    def test_aprovacao_mostra_a_hora_de_brasilia_no_resumo_e_no_historico(self):
        pagina = self.pagina()
        self.assertEqual(pagina.count("06/10/2026 00:00"), 3)       # resumo da última decisão + 2 linhas do histórico

    def test_prazo_mostra_a_hora_de_brasilia_no_resumo_e_no_historico(self):
        pagina = self.pagina()
        self.assertEqual(pagina.count("31/12/2026 12:45"), 3)       # resumo + 2 linhas do histórico

    def test_entrega_mostra_a_hora_de_brasilia(self):
        self.assertIn("Entrega fechada por DONA MARIA em 31/12/2026 23:15", " ".join(self.pagina().split()))

    def test_entrega_desfeita_mostra_a_hora_de_brasilia(self):
        self.assertIn("04/07/2026 09:00", self.pagina())

    def test_comprovante_mostra_a_hora_de_brasilia_e_diz_que_e_de_brasilia(self):
        pagina = " ".join(self.dono_c.get(f"/veiculos/{self.vid}/comprovante").data.decode().split())
        self.assertIn("em 06/10/2026 00:00", pagina)                # aprovação do cliente
        self.assertIn("em 31/12/2026 23:15 (horário de Brasília)", pagina)
        self.assertNotIn("horário do servidor", pagina)

    def test_nenhum_horario_cru_do_banco_aparece_nas_telas(self):
        telas = [f"/veiculos/{self.vid}", f"/veiculos/{self.vid}/comprovante", "/", "/usuarios", "/limites-garantia"]
        for tela in telas:
            conteudo = self.dono_c.get(tela).data.decode()
            self.assertIsNone(HORA_CRUA.search(conteudo), tela)

    def test_funcionario_tambem_ve_hora_de_brasilia(self):
        pagina = self.func.get(f"/veiculos/{self.vid}").data.decode()
        self.assertIn("05/10/2026 21:30", pagina)
        self.assertIsNone(HORA_CRUA.search(pagina))

    def test_o_dado_guardado_no_banco_continua_em_utc(self):
        self.assertEqual(self.sql("SELECT criado_em FROM servicos")[0]["criado_em"], "2026-10-06 00:30:30")

    def test_registro_novo_usa_o_relogio_utc_do_banco_e_aparece_convertido(self):
        # um serviço novo (hora real do banco, UTC) aparece na tela 3 horas antes do que o banco guardou
        self.dono_c.post(f"/veiculos/{self.vid}/entrega/desfazer", data={"motivo": "Registrar mais um serviço depois"})
        self.func.post(f"/veiculos/{self.vid}/servicos", data={"tipo": "FREIOS", "problema": "Pastilha gasta nova"})
        guardado = self.sql("SELECT criado_em FROM servicos WHERE tipo = 'FREIOS'")[0]["criado_em"]
        mostrado = oficina.hora_brasil(guardado)
        self.assertIn(mostrado, self.pagina())
        from datetime import datetime
        diferenca = datetime.strptime(guardado, "%Y-%m-%d %H:%M:%S") - datetime.strptime(mostrado, "%d/%m/%Y %H:%M")
        self.assertEqual(diferenca.total_seconds() // 60 // 60, 3)  # 3 horas de diferença (arredondando os segundos)


if __name__ == "__main__":
    unittest.main()
