"""Testes do cadastro de veículo (agora só para quem entrou).
Rodar na pasta do projeto:  python -m unittest discover tests -v"""
import unittest

from base import BaseTest

DADOS = {"responsavel": "JOSE", "placa": "ABC1D23", "marca": "FIAT", "modelo": "UNO",
         "cor": "PRETO", "ano": "2012", "quilometragem": "150000", "documento_deixado": "on"}


class VeiculoTest(BaseTest):
    def setUp(self):
        super().setUp()
        self.c = self.funcionario()

    def test_pagina_inicial_abre(self):
        self.assertEqual(self.c.get("/").status_code, 200)

    def test_cadastra_veiculo_completo(self):
        r = self.c.post("/veiculos", data=DADOS)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.total_veiculos(), 1)
        self.assertIn(b"ABC1D23", self.c.get("/").data)

    def test_nao_salva_sem_placa(self):
        r = self.c.post("/veiculos", data={**DADOS, "placa": "  "})
        self.assertEqual(r.status_code, 200)
        self.assertIn("A placa é obrigatória.".encode(), r.data)
        self.assertEqual(self.total_veiculos(), 0)

    def test_nao_salva_sem_documento_deixado(self):
        dados = {k: v for k, v in DADOS.items() if k != "documento_deixado"}
        r = self.c.post("/veiculos", data=dados)
        self.assertIn("documento do carro".encode(), r.data)
        self.assertEqual(self.total_veiculos(), 0)

    def test_mantem_o_que_foi_digitado_quando_da_erro(self):
        r = self.c.post("/veiculos", data={**DADOS, "placa": ""})
        self.assertIn(b'value="FIAT"', r.data)

    def test_html_digitado_nao_vira_codigo(self):
        self.c.post("/veiculos", data={**DADOS, "responsavel": "<script>alert(1)</script>"})
        self.assertNotIn(b"<script>alert(1)</script>", self.c.get("/").data)


if __name__ == "__main__":
    unittest.main()


class AvisoDeCadastroTest(BaseTest):
    def test_depois_de_cadastrar_mostra_aviso_com_a_placa_e_link_do_veiculo(self):
        func = self.funcionario()
        r = func.post("/veiculos", data={"placa": "ABC1D23", "documento_deixado": "on"})
        self.assertEqual(r.status_code, 302)
        vid = self.sql("SELECT id FROM veiculos")[0]["id"]
        # cadastro "corrido": vai direto para a ficha do veículo, no ponto de registrar o problema
        self.assertIn(f"/veiculos/{vid}?cadastrado=1#registrar-problema", r.headers["Location"])
        pagina = func.get(r.headers["Location"]).data.decode()
        self.assertIn("cadastrado com sucesso", pagina)
        self.assertIn("ABC1D23", pagina)
        self.assertIn('id="registrar-problema"', pagina)
        self.assertNotIn("cadastrado com sucesso", func.get(f"/veiculos/{vid}").data.decode())

    def test_sem_cadastro_novo_nao_mostra_aviso_e_id_invalido_e_ignorado(self):
        func = self.funcionario()
        self.assertNotIn("cadastrado com sucesso", func.get("/").data.decode())
        self.assertNotIn("cadastrado com sucesso", func.get("/?cadastrado=999").data.decode())


class PaginaCorridaTest(BaseTest):
    def test_paginas_de_trabalho_carregam_o_script_que_mantem_o_lugar_da_tela(self):
        func = self.funcionario()
        func.post("/veiculos", data={"placa": "ABC1D23", "documento_deixado": "on"})
        vid = self.sql("SELECT id FROM veiculos")[0]["id"]
        for caminho in (f"/veiculos/{vid}", "/estoque"):
            self.assertIn("continuo.js", func.get(caminho).data.decode())
        self.assertEqual(func.get("/static/continuo.js").status_code, 200)


class FormularioDeProblemaTest(BaseTest):
    def test_formulario_fica_aberto_sem_problema_e_recolhido_depois_do_primeiro(self):
        func = self.funcionario()
        func.post("/veiculos", data={"placa": "ABC1D23", "documento_deixado": "on"})
        vid = self.sql("SELECT id FROM veiculos")[0]["id"]
        pagina = func.get(f"/veiculos/{vid}").data.decode()
        self.assertIn("<h2 id=\"registrar-problema\">", pagina)
        self.assertNotIn("Registrar outro problema", pagina)
        func.post(f"/veiculos/{vid}/servicos", data={"tipo": "FREIOS", "problema": "pastilha gasta"})
        pagina = func.get(f"/veiculos/{vid}").data.decode()
        self.assertIn("Registrar outro problema", pagina)
        self.assertIn('action="/veiculos/%d/servicos"' % vid, pagina)


class RascunhoTest(BaseTest):
    def test_formularios_de_cadastro_e_de_problema_usam_o_rascunho_automatico(self):
        func = self.funcionario()
        pagina = func.get("/").data.decode()
        self.assertIn('data-rascunho="cadastro-veiculo"', pagina)
        self.assertIn("rascunho.js", pagina)
        func.post("/veiculos", data={"placa": "ABC1D23", "documento_deixado": "on"})
        vid = self.sql("SELECT id FROM veiculos")[0]["id"]
        pagina = func.get(f"/veiculos/{vid}").data.decode()
        self.assertIn('data-rascunho="problema"', pagina)
        self.assertIn("rascunho.js", pagina)
        self.assertEqual(func.get("/static/rascunho.js").status_code, 200)
