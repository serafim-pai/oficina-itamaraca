"""Chassi do veículo: cadastro, correção depois e pesquisa de peça pelo chassi.
Rodar na pasta do projeto:  python -m unittest discover tests -v"""
import unittest
from urllib.parse import parse_qs, urlparse

from base import BaseTest

VEICULO = {"responsavel": "JOSE", "placa": "ABC1D23", "marca": "GM", "modelo": "MONZA", "ano": "1993",
           "documento_deixado": "on"}
CHASSI = "9BGKS08R0NB123456"


class ChassiTest(BaseTest):
    def setUp(self):
        super().setUp()
        self.func = self.funcionario()
        self.dono_c = self.dono()

    def cadastrar(self, **extra):
        return self.func.post("/veiculos", data=dict(VEICULO, **extra))

    def chassi_no_banco(self):
        return self.sql("SELECT chassi FROM veiculos")[0]["chassi"]

    def vid(self):
        return self.sql("SELECT id FROM veiculos")[0]["id"]

    def com_servico(self):
        self.func.post(f"/veiculos/{self.vid()}/servicos", data={"tipo": "FREIOS", "problema": "Pastilhas gastas"})

    def corrigir(self, chassi, cliente=None):
        return (cliente or self.func).post(f"/veiculos/{self.vid()}/dados", data={
            "marca": "GM", "modelo": "MONZA", "cor": "", "ano": "1993", "quilometragem": "", "chassi": chassi})

    def buscar(self, site):
        return self.func.get(f"/veiculos/{self.vid()}/pecas/buscar", query_string={"peca": "pastilha de freio", "site": site})

    def test_cadastro_aceita_chassi_em_maiusculas_sem_espacos(self):
        self.assertEqual(self.cadastrar(chassi=" 9bgks08r0nb 123456 ").status_code, 302)
        self.assertEqual(self.chassi_no_banco(), CHASSI)

    def test_chassi_e_opcional(self):
        self.assertEqual(self.cadastrar().status_code, 302)
        self.assertIsNone(self.chassi_no_banco())

    def test_chassi_invalido_nao_cadastra(self):
        for ruim in ("123", "9BGKS08R0NB1234567890", "9BGKS08R-NB123456", "9BGKS08R0NB12345O"):
            r = self.cadastrar(chassi=ruim)
            self.assertEqual(r.status_code, 200, ruim)
            self.assertRegex(r.data.decode(), "chassi|Chassi")
        self.assertEqual(self.total_veiculos(), 0)

    def test_chassi_antigo_com_menos_de_17_aceita(self):
        self.assertEqual(self.cadastrar(chassi="AB12345").status_code, 302)
        self.assertEqual(self.chassi_no_banco(), "AB12345")

    def test_corrigir_depois_do_cadastro_e_aparece_na_tela(self):
        self.cadastrar()
        self.com_servico()
        self.assertEqual(self.corrigir(CHASSI).status_code, 302)
        self.assertEqual(self.chassi_no_banco(), CHASSI)
        pagina = self.func.get(f"/veiculos/{self.vid()}").data.decode()
        self.assertIn(f"<strong>Chassi:</strong> {CHASSI}", pagina)
        self.assertIn("Chassi para dizer no balcão", pagina)
        self.assertIn("Pelo chassi (Google)", pagina)

    def test_chassi_invalido_na_correcao_nao_salva_nada(self):
        self.cadastrar()
        r = self.corrigir("12")
        self.assertIn("O chassi deve ter".encode(), r.data)
        self.assertIsNone(self.chassi_no_banco())

    def test_apagar_o_chassi(self):
        self.cadastrar(chassi=CHASSI)
        self.corrigir("")
        self.assertIsNone(self.chassi_no_banco())

    def test_pesquisa_pelo_chassi_leva_o_chassi_na_busca(self):
        self.cadastrar(chassi=CHASSI)
        r = self.buscar("CHASSI")
        self.assertEqual(r.status_code, 302)
        texto = parse_qs(urlparse(r.headers["Location"]).query)["q"][0]
        for parte in ("pastilha de freio", "GM", "MONZA", "1993", "chassi", CHASSI):
            self.assertIn(parte, texto)

    def test_sem_chassi_a_pesquisa_pelo_chassi_nao_abre_e_o_botao_nao_aparece(self):
        self.cadastrar()
        self.com_servico()
        r = self.buscar("CHASSI")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Cadastre o chassi".encode(), r.data)
        pagina = self.func.get(f"/veiculos/{self.vid()}").data.decode()
        self.assertNotIn("Pelo chassi (Google)", pagina)
        self.assertIn("Informe o chassi do veículo", pagina)

    def test_google_normal_nao_leva_o_chassi(self):
        self.cadastrar(chassi=CHASSI)
        texto = parse_qs(urlparse(self.buscar("GOOGLE").headers["Location"]).query)["q"][0]
        self.assertNotIn(CHASSI, texto)

    def test_html_no_chassi_nao_passa(self):
        r = self.cadastrar(chassi="<script>alert(1)</script>")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.total_veiculos(), 0)

    def test_banco_antigo_ganha_a_coluna_chassi(self):
        import os, sqlite3, tempfile
        from base import oficina
        arquivo = os.path.join(tempfile.mkdtemp(), "antigo.db")
        banco = sqlite3.connect(arquivo)
        banco.execute("CREATE TABLE veiculos (id INTEGER PRIMARY KEY, placa TEXT, telefone TEXT)")
        banco.commit()
        banco.close()
        anterior = oficina.DATABASE
        oficina.DATABASE = arquivo
        try:
            oficina.init_db()
        finally:
            oficina.DATABASE = anterior
        banco = sqlite3.connect(arquivo)
        colunas = [c[1] for c in banco.execute("PRAGMA table_info(veiculos)")]
        banco.close()
        self.assertIn("chassi", colunas)


if __name__ == "__main__":
    unittest.main()
