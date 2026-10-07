"""Testes da história 9: pesquisar a peça certa na Web e anotar a peça de referência do serviço.
Rodar na pasta do projeto:  python -m unittest discover tests -v"""
import unittest
from urllib.parse import parse_qs, urlparse

from base import BaseTest, oficina

VEICULO = {"responsavel": "JOSE", "placa": "ABC1D23", "marca": "FIAT", "modelo": "UNO MILLE", "ano": "2012",
           "documento_deixado": "on"}
SERVICO = {"tipo": "FREIOS", "problema": "Pastilhas gastas fazendo barulho"}


class PecasWebTest(BaseTest):
    def setUp(self):
        super().setUp()
        self.func = self.funcionario()
        self.dono_c = self.dono()
        self.func.post("/veiculos", data=VEICULO)
        self.vid = self.sql("SELECT id FROM veiculos")[0]["id"]
        self.func.post(f"/veiculos/{self.vid}/servicos", data=SERVICO)
        self.sid = self.sql("SELECT id FROM servicos")[0]["id"]

    def buscar(self, peca="pastilha de freio dianteira", site="GOOGLE", cliente=None):
        return (cliente or self.func).get(f"/veiculos/{self.vid}/pecas/buscar", query_string={"peca": peca, "site": site})

    def test_google_pesquisa_a_peca_para_o_carro_pedindo_o_numero_original(self):
        r = self.buscar()
        self.assertEqual(r.status_code, 302)
        url = urlparse(r.headers["Location"])
        self.assertEqual((url.scheme, url.netloc, url.path), ("https", "www.google.com", "/search"))
        texto = parse_qs(url.query)["q"][0]
        for parte in ("pastilha de freio dianteira", "FIAT", "UNO MILLE", "2012", "número original", "OEM"):
            self.assertIn(parte, texto)

    def test_mercado_livre_e_imagens(self):
        ml = self.buscar(site="MERCADOLIVRE").headers["Location"]
        self.assertTrue(ml.startswith("https://lista.mercadolivre.com.br/pastilha-de-freio-dianteira-fiat-uno-mille-2012"), ml)
        img = self.buscar(site="IMAGENS").headers["Location"]
        self.assertTrue(img.startswith("https://www.google.com/search?tbm=isch&q="), img)

    def test_texto_digitado_fica_so_dentro_da_pesquisa(self):
        for malicioso in ("https://site-ruim.com/x", "//site-ruim.com", "a&site=x#y", "pastilha\r\nLocation: http://ruim"):
            for site in ("GOOGLE", "MERCADOLIVRE", "IMAGENS"):
                r = self.buscar(peca=malicioso, site=site)
                alvo = urlparse(r.headers["Location"]).netloc
                self.assertIn(alvo, ("www.google.com", "lista.mercadolivre.com.br"), malicioso)
                self.assertNotIn("\n", r.headers["Location"])

    def test_site_fora_da_lista_nao_abre(self):
        r = self.buscar(site="http://site-ruim.com")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Escolha onde pesquisar".encode(), r.data)

    def test_peca_vazia_ou_gigante_nao_abre(self):
        self.assertIn("Escreva qual peça".encode(), self.buscar(peca=" ").data)
        self.assertIn("no máximo".encode(), self.buscar(peca="a" * 101).data)

    def test_sem_marca_ou_modelo_nao_pesquisa(self):
        self.sql("UPDATE veiculos SET modelo = ''")
        r = self.buscar()
        self.assertEqual(r.status_code, 200)
        self.assertIn("Cadastre a marca e o modelo".encode(), r.data)

    def test_sem_ano_pesquisa_so_com_marca_e_modelo(self):
        self.sql("UPDATE veiculos SET ano = NULL")
        texto = parse_qs(urlparse(self.buscar().headers["Location"]).query)["q"][0]
        self.assertIn("FIAT UNO MILLE número", texto)

    def test_sem_login_nao_pesquisa(self):
        r = oficina.app.test_client().get(f"/veiculos/{self.vid}/pecas/buscar",
                                          query_string={"peca": "filtro", "site": "GOOGLE"})
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login", r.headers["Location"])

    def test_veiculo_inexistente_da_404(self):
        r = self.func.get("/veiculos/9999/pecas/buscar", query_string={"peca": "filtro", "site": "GOOGLE"})
        self.assertEqual(r.status_code, 404)

    def test_pagina_do_veiculo_mostra_a_caixa_de_pesquisa(self):
        pagina = self.func.get(f"/veiculos/{self.vid}").data.decode()
        self.assertIn("Pesquisar peça na Web", pagina)
        self.assertIn("Número original (Google)", pagina)
        self.assertIn("Mercado Livre", pagina)

    def test_anotar_peca_de_referencia_nao_mexe_no_orcamento(self):
        self.dono_c.post(f"/veiculos/{self.vid}/servicos/{self.sid}/valor", data={"valor": "200,00"})
        r = self.func.post(f"/veiculos/{self.vid}/servicos/{self.sid}/referencia",
                           data={"referencia": "Fras-le PD/123 - Auto Peças Silva"})
        self.assertEqual(r.status_code, 302)
        linha = self.sql("SELECT referencia_peca, valor_centavos FROM servicos")[0]
        self.assertEqual(linha["referencia_peca"], "Fras-le PD/123 - Auto Peças Silva")
        self.assertEqual(linha["valor_centavos"], 20000)
        pagina = self.func.get(f"/veiculos/{self.vid}").data.decode()
        self.assertIn("Fras-le PD/123", pagina)
        self.assertIn("R$ 200,00", pagina)

    def test_vazio_apaga_e_texto_longo_nao_salva(self):
        self.func.post(f"/veiculos/{self.vid}/servicos/{self.sid}/referencia", data={"referencia": "peça X"})
        r = self.func.post(f"/veiculos/{self.vid}/servicos/{self.sid}/referencia", data={"referencia": "x" * 301})
        self.assertIn("no máximo".encode(), r.data)
        self.assertEqual(self.sql("SELECT referencia_peca FROM servicos")[0]["referencia_peca"], "peça X")
        self.func.post(f"/veiculos/{self.vid}/servicos/{self.sid}/referencia", data={"referencia": " "})
        self.assertIsNone(self.sql("SELECT referencia_peca FROM servicos")[0]["referencia_peca"])

    def test_anotacao_com_html_nao_executa(self):
        self.func.post(f"/veiculos/{self.vid}/servicos/{self.sid}/referencia",
                       data={"referencia": "<script>alert(1)</script>"})
        self.assertNotIn(b"<script>alert(1)</script>", self.func.get(f"/veiculos/{self.vid}").data)

    def test_servico_de_outro_veiculo_da_404(self):
        r = self.func.post(f"/veiculos/{self.vid}/servicos/9999/referencia", data={"referencia": "x"})
        self.assertEqual(r.status_code, 404)

    def test_depois_da_entrega_a_anotacao_trava(self):
        self.sql("INSERT INTO entregas (veiculo_id, data_entrega, total_centavos) VALUES (?, '2026-10-01', 100)", (self.vid,))
        r = self.func.post(f"/veiculos/{self.vid}/servicos/{self.sid}/referencia", data={"referencia": "nova"})
        self.assertEqual(r.status_code, 409)
        self.assertIsNone(self.sql("SELECT referencia_peca FROM servicos")[0]["referencia_peca"])
        self.assertNotIn("Pesquisar peça na Web", self.func.get(f"/veiculos/{self.vid}").data.decode())

    def test_busca_e_estoque_convivem_na_mesma_pagina(self):
        pagina = self.func.get(f"/veiculos/{self.vid}").data.decode()
        self.assertIn("Pesquisar peça na Web", pagina)
        self.assertIn("Peça de referência", pagina)
        self.assertIn("Peças e tintas", pagina)
        self.assertEqual(self.func.get("/estoque").status_code, 200)


if __name__ == "__main__":
    unittest.main()
