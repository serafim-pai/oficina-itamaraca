"""Testes de excluir veículo (só o dono, com motivo).
Rodar na pasta do projeto:  python -m unittest discover tests -v"""
import os
import unittest

from base import BaseTest, oficina
from test_fotos import foto

DADOS = {"responsavel": "JOSE", "placa": "ABC1D23", "documento_deixado": "on"}


class ExcluirVeiculoTest(BaseTest):
    def setUp(self):
        super().setUp()
        self.func = self.funcionario()
        self.dono_c = self.dono()
        self.func.post("/veiculos", data={**DADOS, "fotos": [foto()]}, content_type="multipart/form-data")
        self.vid = self.sql("SELECT id FROM veiculos")[0]["id"]
        self.func.post(f"/veiculos/{self.vid}/servicos", data={"tipo": "LATARIA", "problema": "Amassado na porta"})

    def excluir(self, cliente=None, motivo="Cadastrado por engano"):
        return (cliente or self.dono_c).post(f"/veiculos/{self.vid}/excluir", data={"motivo": motivo})

    def test_dono_exclui_e_some_tudo_do_veiculo_inclusive_os_arquivos_das_fotos(self):
        self.assertTrue(os.listdir(oficina.PASTA_FOTOS))
        r = self.excluir()
        self.assertEqual(r.status_code, 302)
        for tabela in ("veiculos", "servicos", "fotos"):
            self.assertEqual(self.sql(f"SELECT COUNT(*) AS n FROM {tabela}")[0]["n"], 0, tabela)
        self.assertEqual(os.listdir(oficina.PASTA_FOTOS), [])

    def test_fica_o_registro_de_quem_excluiu_quando_e_por_que(self):
        self.excluir(motivo="  Cadastrado   por engano ")
        reg = self.sql("SELECT * FROM veiculos_excluidos")[0]
        self.assertEqual((reg["placa"], reg["responsavel"], reg["motivo"]),
                         ("ABC1D23", "JOSE", "Cadastrado por engano"))
        self.assertTrue(reg["excluido_por"] and reg["excluido_em"])

    def test_depois_de_excluir_a_lista_avisa_e_nao_mostra_o_veiculo(self):
        r = self.excluir()
        pagina = self.dono_c.get(r.headers["Location"]).data.decode()
        self.assertIn("excluído", pagina)
        self.assertEqual(self.dono_c.get(f"/veiculos/{self.vid}").status_code, 404)

    def test_funcionario_nao_exclui(self):
        self.assertEqual(self.excluir(self.func).status_code, 403)
        self.assertEqual(len(self.sql("SELECT id FROM veiculos")), 1)

    def test_botao_so_aparece_para_o_dono(self):
        self.assertIn("Excluir este veículo", self.dono_c.get(f"/veiculos/{self.vid}").data.decode())
        self.assertNotIn("Excluir este veículo", self.func.get(f"/veiculos/{self.vid}").data.decode())

    def test_exige_motivo(self):
        for motivo in ("", "  ", "12"):
            r = self.excluir(motivo=motivo)
            self.assertEqual(r.status_code, 200)
            self.assertIn("Explique o motivo", r.data.decode())
        self.assertEqual(len(self.sql("SELECT id FROM veiculos")), 1)

    def test_motivo_grande_demais_e_recusado(self):
        r = self.excluir(motivo="a" * (oficina.MAX_MOTIVO_EXCLUIR + 1))
        self.assertIn("no máximo", r.data.decode())
        self.assertEqual(len(self.sql("SELECT id FROM veiculos")), 1)

    def test_nao_exclui_veiculo_com_entrega_fechada(self):
        self.sql("INSERT INTO entregas (veiculo_id, data_entrega, total_centavos) VALUES (?, '2026-10-06', 0)",
                 (self.vid,))
        r = self.excluir()
        self.assertIn("entrega fechada", r.data.decode())
        self.assertEqual(len(self.sql("SELECT id FROM veiculos")), 1)
        self.assertNotIn("Excluir este veículo", self.dono_c.get(f"/veiculos/{self.vid}").data.decode())

    def test_nao_exclui_veiculo_com_entrega_desfeita(self):
        self.sql("INSERT INTO entregas_desfeitas (veiculo_id, data_entrega, total_centavos, motivo) "
                 "VALUES (?, '2026-10-06', 0, 'teste')", (self.vid,))
        self.assertIn("entrega", self.excluir().data.decode())
        self.assertEqual(len(self.sql("SELECT id FROM veiculos")), 1)

    def test_excluir_um_nao_mexe_nos_outros(self):
        self.func.post("/veiculos", data={**DADOS, "placa": "ZZZ9Z99"}, content_type="multipart/form-data")
        self.excluir()
        self.assertEqual([v["placa"] for v in self.sql("SELECT placa FROM veiculos")], ["ZZZ9Z99"])

    def test_veiculo_inexistente_da_404(self):
        self.assertEqual(self.dono_c.post("/veiculos/9999/excluir", data={"motivo": "teste teste"}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
