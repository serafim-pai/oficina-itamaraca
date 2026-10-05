"""Testes da história 7: definir o prazo de entrega.
Rodar na pasta do projeto:  python -m unittest discover tests -v"""
import re
import unittest
from datetime import date, datetime, timedelta, timezone

from base import BaseTest, oficina

HOJE_REAL = oficina.hoje_brasil          # guardado antes de cada teste trocar por uma data fixa
HOJE = date(2026, 10, 15)                # uma quinta-feira
VEICULO = {"responsavel": "JOSE", "placa": "ABC1D23", "marca": "FIAT", "modelo": "UNO",
           "documento_deixado": "on"}


def em(dias):
    """Texto AAAA-MM-DD de 'hoje + dias'."""
    return (HOJE + timedelta(days=dias)).isoformat()


class PrazoBase(BaseTest):
    def setUp(self):
        super().setUp()
        oficina.hoje_brasil = lambda agora_utc=None: HOJE      # congela o "hoje" dos testes
        self.addCleanup(setattr, oficina, "hoje_brasil", HOJE_REAL)
        self.func = self.funcionario()
        self.dono_c = self.dono()
        self.func.post("/veiculos", data=VEICULO)
        self.vid = self.sql("SELECT id FROM veiculos")[0]["id"]
        self.func.post(f"/veiculos/{self.vid}/servicos", data={"tipo": "LATARIA", "problema": "Amassado na porta"})
        self.sid = self.sql("SELECT id FROM servicos")[0]["id"]
        self.valor("150,00")
        self.aprovar()

    # ---- atalhos ----
    def valor(self, texto):
        self.dono_c.post(f"/veiculos/{self.vid}/servicos/{self.sid}/valor", data={"valor": texto})

    def aprovar(self, decisao="APROVADO"):
        pagina = self.func.get(f"/veiculos/{self.vid}").data.decode()
        assinatura = re.search(r'name="assinatura" value="([^"]+)"', pagina).group(1)
        self.func.post(f"/veiculos/{self.vid}/aprovacao",
                       data={"decisao": decisao, "forma": "TELEFONE", "assinatura": assinatura})

    def definir(self, data, motivo="", cliente=None):
        return (cliente or self.dono_c).post(f"/veiculos/{self.vid}/prazo",
                                             data={"data_prevista": data, "motivo": motivo})

    def prazos(self):
        return self.sql("SELECT * FROM prazos ORDER BY id")

    def pagina(self, cliente=None):
        return (cliente or self.dono_c).get(f"/veiculos/{self.vid}").data.decode()


class DefinirPrazoTest(PrazoBase):
    def test_dono_define_o_primeiro_prazo(self):
        r = self.definir(em(10))
        self.assertEqual(r.status_code, 302)
        p = self.prazos()[0]
        self.assertEqual((p["data_prevista"], p["veiculo_id"], p["registrado_por"]), (em(10), self.vid, "DONA MARIA"))
        self.assertIsNone(p["motivo"])
        self.assertTrue(p["criado_em"])

    def test_aparece_na_pagina_do_veiculo(self):
        self.definir(em(10))
        pagina = self.pagina()
        self.assertIn("25/10/2026", pagina)                  # 15/10 + 10 dias
        self.assertIn("Faltam 10 dias", pagina)
        self.assertIn("selo-no-prazo", pagina)

    def test_motivo_e_opcional_no_primeiro_prazo_mas_fica_guardado_se_vier(self):
        self.definir(em(5), "Cliente pediu urgência")
        self.assertEqual(self.prazos()[0]["motivo"], "Cliente pediu urgência")

    def test_funcionario_nao_define(self):
        r = self.definir(em(10), cliente=self.func)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.prazos(), [])

    def test_funcionario_ve_o_prazo_mas_nao_o_formulario(self):
        self.definir(em(10))
        pagina = self.pagina(self.func)
        self.assertIn("25/10/2026", pagina)
        self.assertNotIn('name="data_prevista"', pagina)

    def test_so_o_dono_ve_o_formulario(self):
        self.assertIn('name="data_prevista"', self.pagina(self.dono_c))
        self.assertNotIn('name="data_prevista"', self.pagina(self.func))

    def test_veiculo_inexistente_da_404(self):
        r = self.dono_c.post("/veiculos/99999/prazo", data={"data_prevista": em(3)})
        self.assertEqual(r.status_code, 404)

    def test_sem_login_nao_define(self):
        r = oficina.app.test_client().post(f"/veiculos/{self.vid}/prazo", data={"data_prevista": em(3)})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith("/login"))
        self.assertEqual(self.prazos(), [])


class PrecisaDeAprovacaoTest(PrazoBase):
    def test_sem_aprovacao_nao_define(self):
        self.sql("DELETE FROM aprovacoes")
        r = self.definir(em(10))
        self.assertIn("depois que o cliente aprovar".encode(), r.data)
        self.assertEqual(self.prazos(), [])

    def test_cliente_recusou_nao_define(self):
        self.sql("DELETE FROM aprovacoes")
        self.aprovar("RECUSADO")
        self.assertIn("depois que o cliente aprovar".encode(), self.definir(em(10)).data)
        self.assertEqual(self.prazos(), [])

    def test_aprovacao_que_perdeu_a_validade_nao_serve(self):
        self.valor("999,00")                                  # o orçamento mudou depois da aprovação
        self.assertIn("depois que o cliente aprovar".encode(), self.definir(em(10)).data)
        self.assertEqual(self.prazos(), [])

    def test_formulario_some_quando_nao_ha_aprovacao_valendo(self):
        self.valor("999,00")
        pagina = self.pagina()
        self.assertNotIn('name="data_prevista"', pagina)
        self.assertIn("só pode ser definido depois que o cliente aprovar", pagina)

    def test_prazo_ja_definido_avisa_se_a_aprovacao_deixou_de_valer(self):
        self.definir(em(10))
        self.valor("999,00")
        pagina = self.pagina()
        self.assertIn("25/10/2026", pagina)                   # o prazo continua guardado
        self.assertIn("não está mais valendo", pagina)
        self.assertIn("Confirme esse prazo com o cliente", pagina)
        self.assertEqual(len(self.prazos()), 1)


class DataDoPrazoTest(PrazoBase):
    def recusa(self, texto, trecho):
        r = self.definir(texto)
        self.assertIn(trecho.encode(), r.data, texto)
        self.assertEqual(self.prazos(), [], texto)

    def test_recusa_data_vazia_ou_estranha(self):
        for texto in ["", "   ", "amanhã", "15/10/2026", "2026-13-01", "2026-02-31", "20261025", "2026-10-1", "2026-10-25 10:00"]:
            self.recusa(texto, "Escolha a data de entrega")

    def test_recusa_data_que_ja_passou(self):
        self.recusa(em(-1), "já passou")
        self.recusa(em(-30), "já passou")

    def test_aceita_hoje(self):
        self.assertEqual(self.definir(em(0)).status_code, 302)
        self.assertIn("Entrega hoje", self.pagina())

    def test_aceita_amanha(self):
        self.definir(em(1))
        self.assertIn("Entrega amanhã", self.pagina())

    def test_limite_de_um_ano(self):
        self.recusa(em(oficina.MAX_DIAS_PRAZO + 1), "no máximo daqui a 365 dias")
        self.assertEqual(self.definir(em(oficina.MAX_DIAS_PRAZO)).status_code, 302)

    def test_o_formulario_ja_limita_as_datas_no_navegador(self):
        pagina = self.pagina()
        self.assertIn(f'min="{HOJE.isoformat()}"', pagina)
        self.assertIn(f'max="{em(oficina.MAX_DIAS_PRAZO)}"', pagina)


class MudarPrazoTest(PrazoBase):
    def setUp(self):
        super().setUp()
        self.definir(em(10))

    def test_mudar_exige_motivo(self):
        for motivo in ["", "   ", "ab", "123"]:
            r = self.definir(em(20), motivo)
            self.assertIn("explique o motivo".encode(), r.data, repr(motivo))
        self.assertEqual(len(self.prazos()), 1)

    def test_mudar_com_motivo_funciona_e_o_novo_prazo_vale(self):
        r = self.definir(em(20), "Peça importada atrasou")
        self.assertEqual(r.status_code, 302)
        ultimo = self.prazos()[-1]
        self.assertEqual((ultimo["data_prevista"], ultimo["motivo"]), (em(20), "Peça importada atrasou"))
        pagina = self.pagina()
        self.assertIn("Faltam 20 dias", pagina)
        self.assertIn("Motivo: Peça importada atrasou", pagina)

    def test_historico_guarda_todos_os_prazos(self):
        self.definir(em(20), "Peça importada atrasou")
        self.definir(em(7), "Conseguimos adiantar o serviço")
        self.assertEqual([p["data_prevista"] for p in self.prazos()], [em(10), em(20), em(7)])
        pagina = self.pagina()
        self.assertIn("Histórico de prazos (3)", pagina)
        self.assertIn("Faltam 7 dias", pagina)

    def test_antecipar_tambem_exige_motivo(self):
        self.assertIn("explique o motivo".encode(), self.definir(em(3)).data)

    def test_mesma_data_do_prazo_atual_e_recusada(self):
        r = self.definir(em(10), "Só confirmando")
        self.assertIn("já é a data do prazo atual".encode(), r.data)
        self.assertEqual(len(self.prazos()), 1)

    def test_recusa_motivo_longo_demais(self):
        r = self.definir(em(20), "x" * (oficina.MAX_MOTIVO_PRAZO + 1))
        self.assertIn("no máximo".encode(), r.data)
        self.assertEqual(len(self.prazos()), 1)

    def test_motivo_com_html_aparece_como_texto(self):
        self.definir(em(20), "<script>alert(1)</script> atrasou")
        self.assertNotIn(b"<script>alert(1)</script>", self.dono_c.get(f"/veiculos/{self.vid}").data)

    def test_formulario_de_mudanca_pede_o_motivo(self):
        self.assertIn('name="motivo"', self.pagina())
        self.assertIn("Mudar o prazo", self.pagina())


class SituacaoDoPrazoTest(unittest.TestCase):
    def test_situacoes(self):
        casos = [(None, "SEM_PRAZO", "Sem prazo definido"),
                 (em(-1), "ATRASADO", "Atrasado há 1 dia"),
                 (em(-5), "ATRASADO", "Atrasado há 5 dias"),
                 (em(0), "HOJE", "Entrega hoje"),
                 (em(1), "PROXIMO", "Entrega amanhã"),
                 (em(2), "PROXIMO", "Faltam 2 dias"),
                 (em(3), "PROXIMO", "Faltam 3 dias"),
                 (em(4), "NO_PRAZO", "Faltam 4 dias"),
                 (em(60), "NO_PRAZO", "Faltam 60 dias")]
        for data, chave, texto in casos:
            self.assertEqual(oficina.situacao_prazo(data, HOJE), (chave, texto), data)

    def test_formatar_data(self):
        self.assertEqual(oficina.formatar_data("2026-10-05"), "05/10/2026")


class FusoHorarioTest(unittest.TestCase):
    """O servidor usa UTC (3 horas à frente de Brasília): o 'hoje' precisa ser o de Brasília."""

    def utc(self, ano, mes, dia, hora, minuto=0):
        return datetime(ano, mes, dia, hora, minuto, tzinfo=timezone.utc)

    def test_de_madrugada_em_utc_ainda_e_o_dia_anterior_no_brasil(self):
        self.assertEqual(HOJE_REAL(self.utc(2026, 10, 6, 1, 30)), date(2026, 10, 5))     # 22:30 em Brasília
        self.assertEqual(HOJE_REAL(self.utc(2026, 10, 6, 2, 59)), date(2026, 10, 5))     # 23:59 em Brasília

    def test_a_virada_do_dia_e_as_3h_utc(self):
        self.assertEqual(HOJE_REAL(self.utc(2026, 10, 6, 3, 0)), date(2026, 10, 6))      # 00:00 em Brasília

    def test_durante_o_dia_nao_muda(self):
        self.assertEqual(HOJE_REAL(self.utc(2026, 10, 5, 15, 0)), date(2026, 10, 5))

    def test_sem_argumento_usa_o_relogio_de_verdade(self):
        esperado = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=-3))).date()
        self.assertIn(HOJE_REAL(), {esperado, esperado + timedelta(days=1), esperado - timedelta(days=1)})


class PrazoNaListaTest(PrazoBase):
    def test_lista_mostra_o_selo_de_entrega_de_cada_veiculo(self):
        self.func.post("/veiculos", data={**VEICULO, "placa": "ZZZ9Z99"})          # outro veículo, sem prazo
        self.definir(em(10))
        pagina = self.func.get("/").data.decode()
        self.assertIn("Faltam 10 dias", pagina)
        self.assertIn("Sem prazo definido", pagina)
        self.assertIn("selo-no-prazo", pagina)
        self.assertIn("selo-sem-prazo", pagina)

    def test_atrasado_aparece_em_vermelho_na_lista(self):
        self.definir(em(2))
        oficina.hoje_brasil = lambda agora_utc=None: HOJE + timedelta(days=5)      # passam 5 dias
        pagina = self.func.get("/").data.decode()
        self.assertIn("Atrasado há 3 dias", pagina)
        self.assertIn("selo-atrasado", pagina)

    def test_prazo_de_um_veiculo_nao_vaza_para_outro(self):
        self.func.post("/veiculos", data={**VEICULO, "placa": "ZZZ9Z99"})
        outro = self.sql("SELECT id FROM veiculos WHERE placa = 'ZZZ9Z99'")[0]["id"]
        self.definir(em(10))
        pagina = self.func.get(f"/veiculos/{outro}").data.decode()
        self.assertNotIn("25/10/2026", pagina)
        self.assertIn("Sem prazo definido", pagina)


class PrazoComCsrfTest(PrazoBase):
    def test_sem_token_nao_define(self):
        oficina.app.config["WTF_CSRF_ENABLED"] = True      # liga só depois de montar os dados do teste
        self.addCleanup(oficina.app.config.__setitem__, "WTF_CSRF_ENABLED", False)
        r = self.definir(em(10))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith("/login?expirou=1"))
        self.assertEqual(self.prazos(), [])


if __name__ == "__main__":
    unittest.main()
