"""Testes das etapas do serviço (aguardando início, em reparo, pronto para retirada).
Rodar na pasta do projeto:  python -m unittest discover tests -v"""
import html
import re
import unittest
from urllib.parse import unquote

from base import BaseTest, oficina

VEICULO = {"responsavel": "JOSE", "placa": "ABC1D23", "marca": "FIAT", "modelo": "UNO",
           "telefone": "81987654321", "documento_deixado": "on"}


class EtapasBase(BaseTest):
    def setUp(self):
        super().setUp()
        self.func = self.funcionario()
        self.dono_c = self.dono()
        self.func.post("/veiculos", data=VEICULO)
        self.vid = self.sql("SELECT id FROM veiculos")[0]["id"]
        self.func.post(f"/veiculos/{self.vid}/servicos", data={"tipo": "LATARIA", "problema": "Amassado na porta"})
        self.sid = self.sql("SELECT id FROM servicos")[0]["id"]
        self.dono_c.post(f"/veiculos/{self.vid}/servicos/{self.sid}/valor", data={"valor": "150,00"})

    def aprovar(self):
        pagina = self.func.get(f"/veiculos/{self.vid}").data.decode()
        assinatura = re.search(r'name="assinatura" value="([^"]+)"', pagina).group(1)
        self.func.post(f"/veiculos/{self.vid}/aprovacao", data={
            "decisao": "APROVADO", "forma": "PESSOALMENTE", "observacao": "", "assinatura": assinatura})

    def mudar(self, etapa, cliente=None):
        return (cliente or self.func).post(f"/veiculos/{self.vid}/etapa", data={"etapa": etapa})

    def etapas(self):
        return [e["etapa"] for e in self.sql("SELECT etapa FROM etapas ORDER BY id")]

    def pagina(self, cliente=None):
        return (cliente or self.func).get(f"/veiculos/{self.vid}").data.decode()

    def link_pronto(self):
        links = [html.unescape(t.split('"')[0]) for t in self.pagina().split('href="') if t.startswith("https://wa.me/")]
        achou = [l for l in links if "pronto" in unquote(l)]         # o outro link do WhatsApp é o do orçamento
        return achou[0] if achou else None


class MudarEtapaTest(EtapasBase):
    def test_comeca_aguardando_inicio(self):
        self.assertIn("Aguardando início", self.pagina())
        self.assertEqual(self.etapas(), [])

    def test_nao_inicia_o_reparo_sem_aprovacao_do_cliente(self):
        r = self.mudar("EM_REPARO")
        self.assertEqual(r.status_code, 200)
        self.assertIn("só pode começar depois que o cliente aprovar", r.data.decode())
        self.assertEqual(self.etapas(), [])

    def test_fluxo_completo_com_aprovacao(self):
        self.aprovar()
        for etapa in ("EM_REPARO", "PRONTO"):
            self.assertEqual(self.mudar(etapa).status_code, 302)
        self.assertEqual(self.etapas(), ["EM_REPARO", "PRONTO"])
        e = self.sql("SELECT * FROM etapas ORDER BY id")[0]
        self.assertTrue(e["registrado_por"] and e["criado_em"])
        self.assertIn("Pronto para retirada", self.pagina())

    def test_dono_tambem_muda_a_etapa(self):
        self.aprovar()
        self.assertEqual(self.mudar("EM_REPARO", self.dono_c).status_code, 302)

    def test_nao_pula_etapa(self):
        self.aprovar()
        r = self.mudar("PRONTO")                       # direto de "aguardando início" para "pronto"
        self.assertIn("não dá para ir direto", r.data.decode())
        self.assertEqual(self.etapas(), [])

    def test_etapa_invalida_ou_repetida_e_recusada(self):
        self.aprovar()
        self.assertIn("Escolha a etapa", self.mudar("QUALQUER").data.decode())
        self.mudar("EM_REPARO")
        self.assertIn("não dá para ir direto", self.mudar("EM_REPARO").data.decode())
        self.assertEqual(self.etapas(), ["EM_REPARO"])

    def test_pode_voltar_uma_etapa_para_corrigir_engano(self):
        self.aprovar()
        self.mudar("EM_REPARO")
        self.mudar("PRONTO")
        self.assertEqual(self.mudar("EM_REPARO").status_code, 302)
        self.assertEqual(self.mudar("AGUARDANDO_INICIO").status_code, 302)
        self.assertEqual(self.etapas(), ["EM_REPARO", "PRONTO", "EM_REPARO", "AGUARDANDO_INICIO"])
        self.assertIn("Aguardando início", self.pagina())

    def test_depois_de_iniciado_o_orcamento_mudar_nao_trava_a_etapa(self):
        self.aprovar()
        self.mudar("EM_REPARO")
        self.dono_c.post(f"/veiculos/{self.vid}/servicos/{self.sid}/valor", data={"valor": "200,00"})   # aprovação deixa de valer
        self.assertEqual(self.mudar("PRONTO").status_code, 302)

    def test_depois_da_entrega_nao_muda(self):
        self.aprovar()
        self.mudar("EM_REPARO")
        self.sql("INSERT INTO entregas (veiculo_id, data_entrega, total_centavos) VALUES (?, '2026-10-06', 15000)",
                 (self.vid,))
        self.assertEqual(self.mudar("PRONTO").status_code, 409)
        self.assertEqual(self.etapas(), ["EM_REPARO"])

    def test_historico_das_etapas_aparece_na_tela(self):
        self.aprovar()
        self.mudar("EM_REPARO")
        self.assertIn("Histórico das etapas (1)", self.pagina())


class EtapaNaListaTest(EtapasBase):
    def test_lista_mostra_a_etapa_de_cada_veiculo(self):
        self.func.post("/veiculos", data={**VEICULO, "placa": "ZZZ9Z99"})
        self.aprovar()
        self.mudar("EM_REPARO")
        pagina = self.func.get("/").data.decode()
        self.assertIn("<th>Etapa</th>", pagina)
        self.assertIn("Em reparo", pagina)
        self.assertIn("Aguardando início", pagina)         # o outro veículo

    def test_veiculo_entregue_aparece_como_entregue(self):
        self.sql("INSERT INTO entregas (veiculo_id, data_entrega, total_centavos) VALUES (?, '2026-10-06', 0)",
                 (self.vid,))
        self.assertIn("selo-etapa-entregue", self.func.get("/").data.decode())

    def test_excluir_o_veiculo_apaga_as_etapas(self):
        self.aprovar()
        self.mudar("EM_REPARO")
        self.dono_c.post(f"/veiculos/{self.vid}/excluir", data={"motivo": "Cadastro de teste"})
        self.assertEqual(self.sql("SELECT COUNT(*) AS n FROM etapas")[0]["n"], 0)


class AvisoProntoWhatsappTest(EtapasBase):
    def test_so_aparece_quando_esta_pronto(self):
        self.aprovar()
        self.assertIsNone(self.link_pronto())
        self.mudar("EM_REPARO")
        self.assertIsNone(self.link_pronto())
        self.mudar("PRONTO")
        self.assertIsNotNone(self.link_pronto())

    def test_link_tem_o_numero_e_o_aviso(self):
        self.aprovar()
        self.mudar("EM_REPARO")
        self.mudar("PRONTO")
        link = self.link_pronto()
        self.assertTrue(link.startswith("https://wa.me/5581987654321?text="))
        texto = unquote(link.split("?text=")[1])
        for trecho in ("JOSE", "FIAT UNO", "ABC1D23", "pronto para retirada"):
            self.assertIn(trecho, texto)

    def test_sem_telefone_o_whatsapp_pede_o_contato(self):
        self.func.post(f"/veiculos/{self.vid}/telefone", data={"telefone": ""})
        self.aprovar()
        self.mudar("EM_REPARO")
        self.mudar("PRONTO")
        self.assertTrue(self.link_pronto().startswith("https://wa.me/?text="))


if __name__ == "__main__":
    unittest.main()
