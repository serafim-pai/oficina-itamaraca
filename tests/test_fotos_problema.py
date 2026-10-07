"""Testes das fotos ligadas a cada problema (serviço).
Rodar na pasta do projeto:  python -m unittest discover tests -v"""
import os
import unittest

from base import BaseTest, oficina
from test_fotos import foto, imagem_em_bytes

VEICULO = {"responsavel": "JOSE", "placa": "ABC1D23", "documento_deixado": "on"}


class FotosProblemaBase(BaseTest):
    def setUp(self):
        super().setUp()
        self.func = self.funcionario()
        self.dono_c = self.dono()
        self.func.post("/veiculos", data=VEICULO)
        self.vid = self.sql("SELECT id FROM veiculos")[0]["id"]
        self.sid = self.novo_servico("LATARIA", "Amassado na porta")

    def novo_servico(self, tipo, problema):
        self.func.post(f"/veiculos/{self.vid}/servicos", data={"tipo": tipo, "problema": problema})
        return self.sql("SELECT MAX(id) AS id FROM servicos")[0]["id"]

    def anexar(self, quantas=1, cliente=None, sid=None, vid=None):
        return (cliente or self.func).post(
            f"/veiculos/{vid or self.vid}/servicos/{sid or self.sid}/fotos",
            data={"fotos": [foto(f"p{i}.jpg") for i in range(quantas)]}, content_type="multipart/form-data")

    def fotos_do(self, sid=None):
        return self.sql("SELECT * FROM fotos WHERE servico_id = ? ORDER BY id", (sid or self.sid,))


class AnexarFotosTest(FotosProblemaBase):
    def test_funcionario_anexa_fotos_ao_problema(self):
        r = self.anexar(2)
        self.assertEqual(r.status_code, 302)
        fotos = self.fotos_do()
        self.assertEqual(len(fotos), 2)
        self.assertTrue(all(f["momento"] == "PROBLEMA" and f["veiculo_id"] == self.vid for f in fotos))
        for f in fotos:
            self.assertTrue(os.path.exists(os.path.join(oficina.PASTA_FOTOS, f["arquivo"] + ".jpg")))

    def test_as_fotos_aparecem_no_problema_e_nao_na_galeria_de_entrada(self):
        self.anexar(1)
        fid = self.fotos_do()[0]["id"]
        pagina = self.func.get(f"/veiculos/{self.vid}").data.decode()
        self.assertIn(f"/fotos/{fid}/miniatura", pagina)
        self.assertEqual(self.func.get(f"/fotos/{fid}").status_code, 200)
        # a lista de veículos mostra só as fotos de entrada
        self.assertNotIn(f"/fotos/{fid}/miniatura", self.func.get("/").data.decode())

    def test_fica_no_historico_de_fotos(self):
        self.anexar(1)
        h = self.sql("SELECT * FROM fotos_historico")[0]
        self.assertEqual((h["acao"], h["foto_id"], h["veiculo_id"]), ("ADICIONADA", self.fotos_do()[0]["id"], self.vid))
        self.assertTrue(h["feita_por"])

    def test_sem_foto_escolhida_avisa(self):
        r = self.func.post(f"/veiculos/{self.vid}/servicos/{self.sid}/fotos", data={},
                           content_type="multipart/form-data")
        self.assertIn("Escolha pelo menos uma foto", r.data.decode())

    def test_limite_de_fotos_por_problema(self):
        self.anexar(oficina.MAX_FOTOS_PROBLEMA)
        r = self.anexar(1)
        self.assertEqual(r.status_code, 200)
        self.assertIn("no máximo", r.data.decode())
        self.assertEqual(len(self.fotos_do()), oficina.MAX_FOTOS_PROBLEMA)

    def test_foto_invalida_nao_guarda_nenhuma(self):
        r = self.func.post(f"/veiculos/{self.vid}/servicos/{self.sid}/fotos", content_type="multipart/form-data",
                           data={"fotos": [foto("ok.jpg"), foto("falsa.jpg", b"isto nao e imagem")]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self.fotos_do()), 0)
        self.assertEqual(os.listdir(oficina.PASTA_FOTOS), [])

    def test_problema_de_outro_veiculo_da_404(self):
        self.func.post("/veiculos", data={**VEICULO, "placa": "ZZZ9Z99"})
        outro = self.sql("SELECT id FROM veiculos WHERE placa = 'ZZZ9Z99'")[0]["id"]
        self.assertEqual(self.anexar(1, vid=outro).status_code, 404)
        self.assertEqual(self.anexar(1, sid=99999).status_code, 404)

    def test_nao_conta_nas_fotos_de_entrada_do_veiculo(self):
        self.anexar(oficina.MAX_FOTOS_PROBLEMA)
        r = self.func.post(f"/veiculos/{self.vid}/fotos", data={"fotos": [foto()]},
                           content_type="multipart/form-data")
        self.assertEqual(r.status_code, 302)


class ExcluirFotoProblemaTest(FotosProblemaBase):
    def test_dono_exclui_a_foto_e_o_arquivo(self):
        self.anexar(1)
        f = self.fotos_do()[0]
        r = self.dono_c.post(f"/veiculos/{self.vid}/servicos/{self.sid}/fotos/{f['id']}/excluir")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.fotos_do(), [])
        self.assertEqual(os.listdir(oficina.PASTA_FOTOS), [])
        self.assertEqual(self.sql("SELECT acao FROM fotos_historico ORDER BY id")[-1]["acao"], "EXCLUIDA")

    def test_funcionario_nao_exclui(self):
        self.anexar(1)
        f = self.fotos_do()[0]
        r = self.func.post(f"/veiculos/{self.vid}/servicos/{self.sid}/fotos/{f['id']}/excluir")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(len(self.fotos_do()), 1)

    def test_nao_exclui_foto_de_outro_problema(self):
        outro = self.novo_servico("PINTURA", "Pintura desbotada")
        self.anexar(1, sid=outro)
        f = self.fotos_do(outro)[0]
        r = self.dono_c.post(f"/veiculos/{self.vid}/servicos/{self.sid}/fotos/{f['id']}/excluir")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(len(self.fotos_do(outro)), 1)


class FotosProblemaNoResto(FotosProblemaBase):
    def test_excluir_o_problema_apaga_as_fotos_dele(self):
        outro = self.novo_servico("PINTURA", "Pintura desbotada")
        self.anexar(2)
        self.anexar(1, sid=outro)
        self.dono_c.post(f"/veiculos/{self.vid}/servicos/{self.sid}/excluir")
        self.assertEqual(self.fotos_do(), [])
        self.assertEqual(len(self.fotos_do(outro)), 1)
        self.assertEqual(len(os.listdir(oficina.PASTA_FOTOS)), 2)       # grande + miniatura da que ficou

    def test_excluir_o_veiculo_apaga_as_fotos_dos_problemas(self):
        self.anexar(2)
        self.dono_c.post(f"/veiculos/{self.vid}/excluir", data={"motivo": "Cadastro de teste"})
        self.assertEqual(self.sql("SELECT COUNT(*) AS n FROM fotos")[0]["n"], 0)
        self.assertEqual(os.listdir(oficina.PASTA_FOTOS), [])

    def test_depois_da_entrega_nao_anexa_nem_exclui_mas_as_fotos_continuam_visiveis(self):
        self.anexar(1)
        f = self.fotos_do()[0]
        self.sql("INSERT INTO entregas (veiculo_id, data_entrega, total_centavos) VALUES (?, '2026-10-06', 0)",
                 (self.vid,))
        self.assertEqual(self.anexar(1).status_code, 409)       # veículo entregue: cadastro travado
        self.assertEqual(self.dono_c.post(
            f"/veiculos/{self.vid}/servicos/{self.sid}/fotos/{f['id']}/excluir").status_code, 409)
        self.assertEqual(len(self.fotos_do()), 1)
        self.assertIn(f"/fotos/{f['id']}/miniatura", self.dono_c.get(f"/veiculos/{self.vid}").data.decode())


if __name__ == "__main__":
    unittest.main()
