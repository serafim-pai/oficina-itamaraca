"""Motor (cilindrada e potência) do veículo: cadastro, correção, aviso e pesquisa de peça.
Rodar na pasta do projeto:  python -m unittest discover tests -v"""
import unittest
from urllib.parse import parse_qs, urlparse

from base import BaseTest

VEICULO = {"responsavel": "JOSE", "placa": "ABC1D23", "marca": "GM", "modelo": "MONZA", "ano": "1993",
           "documento_deixado": "on"}


class MotorTest(BaseTest):
    def setUp(self):
        super().setUp()
        self.func = self.funcionario()
        self.dono_c = self.dono()

    def cadastrar(self, **extra):
        return self.func.post("/veiculos", data=dict(VEICULO, **extra))

    def vid(self):
        return self.sql("SELECT id FROM veiculos")[0]["id"]

    def motor_no_banco(self):
        return self.sql("SELECT motor FROM veiculos")[0]["motor"]

    def corrigir(self, motor, **extra):
        dados = {"marca": "GM", "modelo": "MONZA", "cor": "", "ano": "1993", "quilometragem": "", "chassi": "",
                 "motor": motor}
        dados.update(extra)
        return self.func.post(f"/veiculos/{self.vid()}/dados", data=dados)

    def com_servico(self):
        self.func.post(f"/veiculos/{self.vid()}/servicos", data={"tipo": "FREIOS", "problema": "Pastilhas gastas"})

    def pagina(self):
        return self.func.get(f"/veiculos/{self.vid()}").data.decode()

    def buscar(self, site="GOOGLE"):
        return self.func.get(f"/veiculos/{self.vid()}/pecas/buscar", query_string={"peca": "pastilha de freio", "site": site})

    def test_cadastro_guarda_o_motor_sem_espacos_repetidos(self):
        self.assertEqual(self.cadastrar(motor="  1.8   8v 99cv ").status_code, 302)
        self.assertEqual(self.motor_no_banco(), "1.8 8v 99cv")

    def test_motor_e_opcional_no_cadastro(self):
        self.assertEqual(self.cadastrar().status_code, 302)
        self.assertIsNone(self.motor_no_banco())

    def test_motor_muito_longo_nao_cadastra(self):
        r = self.cadastrar(motor="x" * 41)
        self.assertEqual(r.status_code, 200)
        self.assertIn("O motor pode ter no máximo".encode(), r.data)
        self.assertEqual(self.total_veiculos(), 0)

    def test_sem_motor_a_pagina_avisa_e_o_formulario_abre_sozinho(self):
        self.cadastrar()
        pagina = self.pagina()
        self.assertIn("Informe o <strong>motor</strong> do veículo", pagina)
        self.assertRegex(pagina, r"<details class=\"telefone-cliente\" open>\s*<summary>✏️ Corrigir")

    def test_com_motor_o_aviso_some_e_o_motor_aparece(self):
        self.cadastrar(motor="2.0 8v 110cv")
        pagina = self.pagina()
        self.assertNotIn("Informe o <strong>motor</strong> do veículo", pagina)
        self.assertIn("<strong>Motor:</strong> 2.0 8v 110cv", pagina)
        self.assertNotRegex(pagina, r"<details class=\"telefone-cliente\" open>\s*<summary>✏️ Corrigir")

    def test_corrigir_depois_do_cadastro(self):
        self.cadastrar()
        self.assertEqual(self.corrigir("1.8 8v 99cv").status_code, 302)
        self.assertEqual(self.motor_no_banco(), "1.8 8v 99cv")
        self.corrigir("")
        self.assertIsNone(self.motor_no_banco())

    def test_motor_longo_na_correcao_nao_salva_nada(self):
        self.cadastrar(motor="1.0")
        r = self.corrigir("x" * 41, cor="AZUL")
        self.assertIn("O motor pode ter no máximo".encode(), r.data)
        v = self.sql("SELECT motor, cor FROM veiculos")[0]
        self.assertEqual((v["motor"], v["cor"]), ("1.0", ""))

    def test_a_pesquisa_na_web_leva_o_motor(self):
        self.cadastrar(motor="2.0 8v")
        self.com_servico()
        texto = parse_qs(urlparse(self.buscar().headers["Location"]).query)["q"][0]
        self.assertIn("GM MONZA 2.0 8v 1993", texto)
        ml = self.buscar("MERCADOLIVRE").headers["Location"]
        self.assertIn("gm-monza-2.0-8v-1993", ml)

    def test_sem_motor_a_pesquisa_ainda_funciona_e_avisa_na_caixa(self):
        self.cadastrar()
        self.com_servico()
        self.assertEqual(self.buscar().status_code, 302)
        self.assertIn("Sem o motor informado a peça pode vir errada", self.pagina())

    def test_com_motor_a_caixa_de_pesquisa_mostra_o_motor_e_nao_avisa(self):
        self.cadastrar(motor="2.0 8v")
        self.com_servico()
        pagina = self.pagina()
        self.assertIn("Pesquisa para GM MONZA 2.0 8v 1993", pagina)
        self.assertNotIn("Sem o motor informado", pagina)

    def test_a_busca_da_lista_acha_pelo_motor(self):
        self.cadastrar(motor="1.8 8v")
        self.cadastrar(placa="XYZ9K88", motor="2.0 8v")
        pagina = self.func.get("/", query_string={"q": "2.0"}).data.decode()
        self.assertIn(">XYZ9K88</a>", pagina)
        self.assertNotIn(">ABC1D23</a>", pagina)

    def test_depois_da_entrega_nao_mostra_o_aviso(self):
        self.cadastrar()
        self.sql("INSERT INTO entregas (veiculo_id, data_entrega, total_centavos) VALUES (?, '2026-10-01', 100)", (self.vid(),))
        self.assertNotIn("Informe o <strong>motor</strong> do veículo", self.pagina())

    def test_html_no_motor_nao_executa(self):
        self.cadastrar(motor="<script>alert(1)</script>")
        self.assertNotIn(b"<script>alert(1)</script>", self.func.get(f"/veiculos/{self.vid()}").data)

    def test_banco_antigo_ganha_a_coluna_motor(self):
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
        self.assertIn("motor", colunas)


if __name__ == "__main__":
    unittest.main()
