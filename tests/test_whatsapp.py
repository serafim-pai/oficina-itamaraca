"""Testes do orçamento pelo WhatsApp e do telefone do cliente.
Rodar na pasta do projeto:  python -m unittest discover tests -v"""
import html
import unittest
from urllib.parse import unquote

from base import BaseTest, oficina

VEICULO = {"responsavel": "JOSE", "placa": "ABC1D23", "marca": "FIAT", "modelo": "UNO",
           "documento_deixado": "on"}


class TelefoneTest(unittest.TestCase):
    def test_normaliza_varios_formatos(self):
        for texto in ("(81) 98765-4321", "81987654321", "+55 81 98765-4321", "55 (81) 98765 4321"):
            self.assertEqual(oficina.normalizar_telefone(texto), ("81987654321", None), texto)
        self.assertEqual(oficina.normalizar_telefone("(81) 3456-7890"), ("8134567890", None))

    def test_vazio_e_permitido(self):
        self.assertEqual(oficina.normalizar_telefone("  "), ("", None))

    def test_recusa_numero_invalido(self):
        for texto in ("12345", "0198765432", "819876543210000", "(81) 98765"):
            telefone, erro = oficina.normalizar_telefone(texto)
            self.assertIsNone(telefone, texto)
            self.assertIn("Telefone inválido", erro)


class WhatsappBase(BaseTest):
    def setUp(self):
        super().setUp()
        self.func = self.funcionario()
        self.dono_c = self.dono()
        self.func.post("/veiculos", data={**VEICULO, "telefone": "(81) 98765-4321"})
        self.vid = self.sql("SELECT id FROM veiculos")[0]["id"]

    def servico(self, tipo="LATARIA", problema="Amassado na porta", valor="150,00"):
        self.func.post(f"/veiculos/{self.vid}/servicos", data={"tipo": tipo, "problema": problema})
        sid = self.sql("SELECT MAX(id) AS id FROM servicos")[0]["id"]
        if valor:
            self.dono_c.post(f"/veiculos/{self.vid}/servicos/{sid}/valor", data={"valor": valor})
        return sid

    def link(self, cliente=None):
        pagina = (cliente or self.dono_c).get(f"/veiculos/{self.vid}").data.decode()
        achou = [t for t in pagina.split('href="') if t.startswith("https://wa.me/")]
        return html.unescape(achou[0].split('"')[0]) if achou else None


class CadastroComTelefoneTest(WhatsappBase):
    def test_telefone_fica_guardado_so_com_digitos(self):
        self.assertEqual(self.sql("SELECT telefone FROM veiculos")[0]["telefone"], "81987654321")

    def test_telefone_e_opcional(self):
        self.func.post("/veiculos", data={**VEICULO, "placa": "ZZZ9Z99"})
        self.assertEqual(len(self.sql("SELECT id FROM veiculos")), 2)

    def test_telefone_invalido_nao_cadastra_nada(self):
        r = self.func.post("/veiculos", data={**VEICULO, "placa": "ZZZ9Z99", "telefone": "123"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("Telefone inválido", r.data.decode())
        self.assertEqual(len(self.sql("SELECT id FROM veiculos")), 1)

    def test_dono_e_funcionario_corrigem_o_telefone_depois(self):
        for cliente, numero, esperado in ((self.func, "(81) 91111-2222", "81911112222"),
                                          (self.dono_c, "", "")):
            r = cliente.post(f"/veiculos/{self.vid}/telefone", data={"telefone": numero})
            self.assertEqual(r.status_code, 302)
            self.assertEqual(self.sql("SELECT telefone FROM veiculos")[0]["telefone"], esperado)

    def test_telefone_invalido_na_correcao_nao_muda_nada(self):
        r = self.func.post(f"/veiculos/{self.vid}/telefone", data={"telefone": "123"})
        self.assertIn("Telefone inválido", r.data.decode())
        self.assertEqual(self.sql("SELECT telefone FROM veiculos")[0]["telefone"], "81987654321")


class LinkWhatsappTest(WhatsappBase):
    def test_sem_orcamento_completo_nao_tem_botao(self):
        self.assertIsNone(self.link())                        # nenhum serviço
        self.servico("PINTURA", "Pintura desbotada", valor=None)
        self.assertIsNone(self.link())                        # serviço sem valor

    def test_link_tem_o_numero_os_servicos_e_o_total(self):
        self.servico("LATARIA", "Amassado na porta", "150,00")
        self.servico("PINTURA", "Pintura desbotada no capô", "250,50")
        link = self.link()
        self.assertTrue(link.startswith("https://wa.me/5581987654321?text="))
        texto = unquote(link.split("?text=")[1])
        for trecho in ("JOSE", "FIAT UNO", "ABC1D23", "Lataria: Amassado na porta - R$ 150,00",
                       "Pintura: Pintura desbotada no capô - R$ 250,50", "Total: R$ 400,50", "APROVADO"):
            self.assertIn(trecho, texto)

    def test_funcionario_tambem_ve_o_botao(self):
        self.servico()
        self.assertTrue(self.link(self.func).startswith("https://wa.me/5581"))

    def test_sem_telefone_o_whatsapp_pede_o_contato(self):
        self.func.post(f"/veiculos/{self.vid}/telefone", data={"telefone": ""})
        self.servico()
        self.assertTrue(self.link().startswith("https://wa.me/?text="))

    def test_texto_nao_quebra_com_caracteres_especiais(self):
        self.servico("LATARIA", "Porta & capô: 100% amassado #1 \"grave\"", "10,00")
        texto = unquote(self.link().split("?text=")[1])
        self.assertIn('Porta & capô: 100% amassado #1 "grave"', texto)

    def test_muitos_servicos_cabem_no_limite_do_link(self):
        for i in range(60):
            self.servico("MECÂNICA", f"Problema {i} " + "x" * 90, "10,00")
        link = self.link()
        self.assertLessEqual(len(link.split("?text=")[1]), oficina.MAX_LINK_WHATSAPP)
        texto = unquote(link.split("?text=")[1])
        self.assertIn("e mais", texto)
        self.assertIn("Total: R$ 600,00", texto)             # o total é sempre o de todos os serviços

    def test_depois_da_entrega_nao_tem_botao(self):
        self.servico()
        self.sql("INSERT INTO entregas (veiculo_id, data_entrega, total_centavos) VALUES (?, '2026-10-06', 15000)",
                 (self.vid,))
        self.assertIsNone(self.link())


if __name__ == "__main__":
    unittest.main()
