"""Completar ou corrigir marca, modelo, cor, ano e km do veículo depois do cadastro.
Rodar na pasta do projeto:  python -m unittest discover tests -v"""
import unittest

from base import BaseTest

VEICULO = {"responsavel": "JOSE", "placa": "ABC1D23", "documento_deixado": "on"}
NOVOS = {"marca": "Fiat", "modelo": "Uno Mille", "cor": "Vermelho", "ano": "2012", "quilometragem": "150000"}


class DadosDoVeiculoTest(BaseTest):
    def setUp(self):
        super().setUp()
        self.func = self.funcionario()
        self.dono_c = self.dono()
        self.func.post("/veiculos", data=VEICULO)           # cadastrado sem marca, modelo e ano
        self.vid = self.sql("SELECT id FROM veiculos")[0]["id"]

    def salvar(self, cliente=None, **extra):
        dados = dict(NOVOS)
        dados.update(extra)
        return (cliente or self.func).post(f"/veiculos/{self.vid}/dados", data=dados)

    def veiculo(self):
        return self.sql("SELECT * FROM veiculos")[0]

    def test_funcionario_e_dono_completam_os_dados(self):
        self.assertEqual(self.salvar().status_code, 302)
        v = self.veiculo()
        self.assertEqual((v["marca"], v["modelo"], v["cor"], v["ano"], v["quilometragem"]),
                         ("FIAT", "UNO MILLE", "VERMELHO", "2012", "150000"))
        self.assertEqual(self.salvar(cliente=self.dono_c, cor="Preto").status_code, 302)
        self.assertEqual(self.veiculo()["cor"], "PRETO")

    def test_placa_e_responsavel_nao_mudam(self):
        self.func.post(f"/veiculos/{self.vid}/dados", data=dict(NOVOS, placa="ZZZ9Z99", responsavel="OUTRO"))
        v = self.veiculo()
        self.assertEqual((v["placa"], v["responsavel"]), ("ABC1D23", "JOSE"))

    def test_depois_de_completar_a_pesquisa_de_peca_abre(self):
        url = f"/veiculos/{self.vid}/pecas/buscar"
        self.assertEqual(self.func.get(url, query_string={"peca": "filtro de oleo", "site": "GOOGLE"}).status_code, 200)
        self.salvar()
        r = self.func.get(url, query_string={"peca": "filtro de oleo", "site": "GOOGLE"})
        self.assertEqual(r.status_code, 302)
        self.assertIn("UNO+MILLE", r.headers["Location"])

    def test_formulario_abre_sozinho_quando_falta_marca_ou_modelo(self):
        pagina = self.func.get(f"/veiculos/{self.vid}").data.decode()
        self.assertRegex(pagina, r"<details class=\"telefone-cliente\" open>\s*<summary>✏️ Corrigir")
        self.assertIn("Informe a marca e o modelo", pagina)
        self.salvar()
        pagina = self.func.get(f"/veiculos/{self.vid}").data.decode()
        self.assertNotIn("Informe a marca e o modelo", pagina)
        self.assertIn('value="UNO MILLE"', pagina)

    def test_ano_invalido_nao_salva_nada(self):
        for ruim in ("abc", "12", "1800", "2300", "20122012123"):
            r = self.salvar(ano=ruim)
            self.assertIn("O ano deve ter 4 números".encode(), r.data, ruim)
        self.assertIsNone(self.veiculo()["marca"] or None)

    def test_texto_muito_longo_nao_salva(self):
        r = self.salvar(modelo="X" * 41)
        self.assertIn("no máximo".encode(), r.data)
        self.assertEqual(self.veiculo()["modelo"], "")

    def test_campos_vazios_apagam_e_espacos_sao_limpos(self):
        self.salvar(marca="  Fiat   ", modelo="Uno   Mille")
        self.assertEqual((self.veiculo()["marca"], self.veiculo()["modelo"]), ("FIAT", "UNO MILLE"))
        self.salvar(marca="", modelo="", ano="")
        self.assertEqual((self.veiculo()["marca"], self.veiculo()["modelo"], self.veiculo()["ano"]), ("", "", ""))

    def test_html_digitado_nao_executa(self):
        self.salvar(cor="<script>alert(1)</script>")
        self.assertNotIn(b"<script>alert(1)</script>", self.func.get(f"/veiculos/{self.vid}").data)

    def test_veiculo_inexistente_da_404(self):
        self.assertEqual(self.func.post("/veiculos/9999/dados", data=NOVOS).status_code, 404)

    def test_depois_da_entrega_trava(self):
        self.sql("INSERT INTO entregas (veiculo_id, data_entrega, total_centavos) VALUES (?, '2026-10-01', 100)", (self.vid,))
        r = self.salvar()
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.veiculo()["marca"], "")
        self.assertNotIn("Corrigir marca".encode(), self.func.get(f"/veiculos/{self.vid}").data)


if __name__ == "__main__":
    unittest.main()
