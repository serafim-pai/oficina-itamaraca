"""Busca por placa ou nome na lista de veículos.
Rodar na pasta do projeto:  python -m unittest discover tests -v"""
import unittest

from base import BaseTest

CARROS = [
    {"responsavel": "JOÃO DA SILVA", "placa": "ABC1D23", "marca": "GM", "modelo": "MONZA", "cor": "VERMELHO", "ano": "1993"},
    {"responsavel": "MARIA SOUZA", "placa": "XYZ9K88", "marca": "FIAT", "modelo": "UNO", "cor": "PRETO", "ano": "2012",
     "telefone": "(81) 98765-4321"},
    {"responsavel": "JOSE ABREU", "placa": "QWE2R45", "marca": "FORD", "modelo": "PAMPA", "cor": "BRANCO", "ano": "1995"},
]


class BuscaDeVeiculosTest(BaseTest):
    def setUp(self):
        super().setUp()
        self.func = self.funcionario()
        for c in CARROS:
            self.func.post("/veiculos", data=dict(c, documento_deixado="on"))

    def achar(self, texto):
        """Placas que aparecem na lista para essa busca (ignora o texto do aviso de contagem)."""
        pagina = self.func.get("/", query_string={"q": texto}).data.decode()
        return [p for p in ("ABC1D23", "XYZ9K88", "QWE2R45") if f'>{p}</a>' in pagina]

    def test_sem_busca_mostra_todos(self):
        self.assertEqual(self.achar(""), ["ABC1D23", "XYZ9K88", "QWE2R45"])

    def test_busca_pela_placa_inteira_ou_em_parte_sem_ligar_para_maiuscula_ou_hifen(self):
        self.assertEqual(self.achar("abc1d23"), ["ABC1D23"])
        self.assertEqual(self.achar("ABC-1D23"), ["ABC1D23"])
        self.assertEqual(self.achar("1d2"), ["ABC1D23"])
        self.assertEqual(self.achar("  xyz 9k88 "), ["XYZ9K88"])

    def test_busca_pelo_nome_do_responsavel_sem_ligar_para_acento(self):
        self.assertEqual(self.achar("joao"), ["ABC1D23"])
        self.assertEqual(self.achar("JOÃO DA SILVA"), ["ABC1D23"])
        self.assertEqual(self.achar("souza"), ["XYZ9K88"])
        self.assertEqual(self.achar("jose abreu"), ["QWE2R45"])

    def test_pedaco_do_nome_que_serve_para_mais_de_um_mostra_todos(self):
        self.assertEqual(self.achar("jo"), ["ABC1D23", "QWE2R45"])      # JOÃO e JOSE

    def test_busca_por_marca_modelo_cor_e_telefone(self):
        self.assertEqual(self.achar("monza"), ["ABC1D23"])
        self.assertEqual(self.achar("gm monza vermelho"), ["ABC1D23"])
        self.assertEqual(self.achar("preto"), ["XYZ9K88"])
        self.assertEqual(self.achar("98765"), ["XYZ9K88"])
        self.assertEqual(self.achar("1995"), ["QWE2R45"])

    def test_todas_as_palavras_precisam_combinar(self):
        self.assertEqual(self.achar("fiat monza"), [])

    def test_sem_resultado_avisa_e_oferece_limpar(self):
        pagina = self.func.get("/", query_string={"q": "ferrari"}).data.decode()
        self.assertIn("Nenhum veículo encontrado", pagina)
        self.assertIn("Limpar busca", pagina)
        self.assertNotIn("Nenhum veículo cadastrado ainda", pagina)

    def test_mostra_quantos_foram_achados(self):
        pagina = self.func.get("/", query_string={"q": "jo"}).data.decode()
        self.assertIn("2 de 3 veículos", pagina)

    def test_lista_vazia_nao_mostra_a_busca(self):
        self.sql("DELETE FROM veiculos")
        pagina = self.func.get("/").data.decode()
        self.assertIn("Nenhum veículo cadastrado ainda", pagina)
        self.assertNotIn("Buscar veículo", pagina)

    def test_texto_html_na_busca_nao_executa(self):
        pagina = self.func.get("/", query_string={"q": "<script>alert(1)</script>"}).data.decode()
        self.assertNotIn("<script>alert(1)</script>", pagina)

    def test_busca_muito_longa_e_cortada_sem_dar_erro(self):
        self.assertEqual(self.func.get("/", query_string={"q": "a" * 500}).status_code, 200)

    def test_sem_login_nao_busca(self):
        from base import oficina
        r = oficina.app.test_client().get("/", query_string={"q": "abc"})
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login", r.headers["Location"])

    def test_cadastro_com_erro_continua_mostrando_todos(self):
        r = self.func.post("/veiculos", data={"responsavel": "X", "placa": ""})
        self.assertEqual(r.status_code, 200)
        self.assertIn(b">ABC1D23</a>", r.data)


if __name__ == "__main__":
    unittest.main()
