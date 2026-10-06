"""Testes de adicionar, trocar e excluir fotos de um veículo já cadastrado.
Rodar na pasta do projeto:  python -m unittest discover tests -v"""
import os
import re
import unittest

from base import BaseTest, oficina
from test_fotos import abrir_salva, foto, imagem_em_bytes

VEICULO = {"responsavel": "JOSE DA SILVA", "placa": "ABC1D23", "marca": "FIAT", "modelo": "UNO",
           "documento_deixado": "on"}


class GerenciarFotosBase(BaseTest):
    def setUp(self):
        super().setUp()
        self.func = self.funcionario()
        self.dono_c = self.dono()
        self.vid = self.novo_veiculo("ABC1D23", fotos=2)
        self.f1, self.f2 = self.ids_fotos()

    # ---- atalhos ----
    def novo_veiculo(self, placa, fotos=0):
        envio = [foto(f"{i}.jpg", imagem_em_bytes(tamanho=(200 + i, 100))) for i in range(fotos)]
        self.func.post("/veiculos", data={**VEICULO, "placa": placa, "fotos": envio}, content_type="multipart/form-data")
        return self.sql("SELECT id FROM veiculos WHERE placa = ?", (placa,))[0]["id"]

    def ids_fotos(self, vid=None):
        return [f["id"] for f in self.sql("SELECT id FROM fotos WHERE veiculo_id = ? ORDER BY id", (vid or self.vid,))]

    def arquivo_da_foto(self, foto_id):
        return self.sql("SELECT arquivo FROM fotos WHERE id = ?", (foto_id,))[0]["arquivo"]

    def arquivos_no_disco(self):
        return sorted(os.listdir(oficina.PASTA_FOTOS))

    def adicionar(self, fotos, cliente=None, vid=None):
        return (cliente or self.func).post(f"/veiculos/{vid or self.vid}/fotos", data={"fotos": fotos},
                                           content_type="multipart/form-data")

    def trocar(self, foto_id, arquivo, cliente=None, vid=None):
        return (cliente or self.dono_c).post(f"/veiculos/{vid or self.vid}/fotos/{foto_id}/trocar",
                                             data={"foto": arquivo}, content_type="multipart/form-data")

    def excluir(self, foto_id, cliente=None, vid=None):
        return (cliente or self.dono_c).post(f"/veiculos/{vid or self.vid}/fotos/{foto_id}/excluir")

    def servir(self, caminho, **extra):
        """(status, conteúdo) de uma foto servida pelo sistema, sem deixar o arquivo aberto."""
        resposta = self.dono_c.get(caminho, **extra)
        try:
            return resposta.status_code, resposta.data
        finally:
            resposta.close()

    def historico(self):
        return [(h["foto_id"], h["acao"], h["feita_por"]) for h in self.sql("SELECT * FROM fotos_historico ORDER BY id")]

    def marcar_como_entregue(self, vid=None):
        self.sql("INSERT INTO entregas (veiculo_id, data_entrega, total_centavos) VALUES (?, '2026-10-15', 1)", (vid or self.vid,))

    def pagina(self, cliente=None, vid=None):
        return (cliente or self.dono_c).get(f"/veiculos/{vid or self.vid}").data.decode()

    def quebrar_o_historico(self):
        """Faz a última etapa (anotar no histórico) falhar, para testar o que acontece quando algo dá errado no meio."""
        self.sql("ALTER TABLE fotos_historico RENAME TO fotos_historico_x")
        self.addCleanup(self.sql, "ALTER TABLE fotos_historico_x RENAME TO fotos_historico")
        oficina.app.testing = False
        self.addCleanup(setattr, oficina.app, "testing", True)


class AdicionarFotosTest(GerenciarFotosBase):
    def test_funcionario_adiciona_fotos(self):
        r = self.adicionar([foto("a.jpg"), foto("b.png", imagem_em_bytes("PNG"))])
        self.assertEqual(r.status_code, 302)
        self.assertEqual(len(self.ids_fotos()), 4)
        self.assertEqual(len(self.arquivos_no_disco()), 8)             # cada foto: grande + miniatura

    def test_dono_tambem_adiciona(self):
        self.assertEqual(self.adicionar([foto()], cliente=self.dono_c).status_code, 302)
        self.assertEqual(len(self.ids_fotos()), 3)

    def test_as_novas_aparecem_na_pagina_do_veiculo(self):
        self.adicionar([foto()])
        pagina = self.pagina()
        for foto_id in self.ids_fotos():
            self.assertIn(f"/fotos/{foto_id}/miniatura", pagina)

    def test_fica_registrado_quem_adicionou(self):
        self.adicionar([foto(), foto("b.jpg")])
        self.assertEqual([(a, p) for (_, a, p) in self.historico()], [("ADICIONADA", "PESSOA TESTE")] * 2)

    def test_a_foto_adicionada_passa_pelo_mesmo_tratamento_das_do_cadastro(self):
        self.adicionar([foto("grande.png", imagem_em_bytes("PNG", (4000, 3000)))])
        nova = self.ids_fotos()[-1]
        imagem = abrir_salva(self.arquivo_da_foto(nova) + ".jpg")
        self.assertEqual(imagem.format, "JPEG")
        self.assertEqual(max(imagem.size), oficina.LADO_FOTO)

    def test_nome_do_arquivo_nunca_vira_caminho(self):
        self.adicionar([foto("../../../etc/passwd.jpg")])
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{32}(_m)?\.jpg", n) for n in self.arquivos_no_disco()))

    def test_exige_escolher_pelo_menos_uma_foto(self):
        r = self.adicionar([])
        self.assertIn("Escolha pelo menos uma foto".encode(), r.data)
        self.assertEqual(len(self.ids_fotos()), 2)

    def test_uma_foto_ruim_barra_todas(self):
        antes = self.arquivos_no_disco()
        r = self.adicionar([foto("boa.jpg"), foto("ruim.jpg", b"isto nao e imagem"), foto("boa2.jpg")])
        self.assertIn("ruim.jpg".encode(), r.data)
        self.assertEqual(len(self.ids_fotos()), 2)
        self.assertEqual(self.arquivos_no_disco(), antes)
        self.assertEqual(self.historico(), [])

    def test_recusa_foto_grande_demais(self):
        r = self.adicionar([foto("enorme.jpg", b"0" * (oficina.MAX_BYTES_FOTO + 1))])
        self.assertIn("grande demais".encode(), r.data)
        self.assertEqual(len(self.ids_fotos()), 2)

    def test_limite_por_envio(self):
        r = self.adicionar([foto(f"{i}.jpg") for i in range(oficina.MAX_FOTOS + 1)])
        self.assertIn("no máximo".encode(), r.data)
        self.assertEqual(len(self.ids_fotos()), 2)

    def test_limite_total_por_veiculo(self):
        self.adicionar([foto(f"{i}.jpg") for i in range(10)])           # 2 + 10 = 12
        self.adicionar([foto(f"{i}.jpg") for i in range(8)])            # 12 + 8 = 20 (no limite)
        self.assertEqual(len(self.ids_fotos()), oficina.MAX_FOTOS_VEICULO)
        r = self.adicionar([foto("a-mais.jpg")])
        self.assertIn("máximo 20 fotos".encode(), r.data)
        self.assertEqual(len(self.ids_fotos()), oficina.MAX_FOTOS_VEICULO)

    def test_o_limite_e_de_cada_veiculo(self):
        outro = self.novo_veiculo("ZZZ9Z99", fotos=0)
        self.adicionar([foto(f"{i}.jpg") for i in range(10)])
        self.adicionar([foto(f"{i}.jpg") for i in range(8)])
        self.assertEqual(self.adicionar([foto()], vid=outro).status_code, 302)

    def test_veiculo_inexistente_da_404(self):
        self.assertEqual(self.adicionar([foto()], vid=99999).status_code, 404)

    def test_sem_login_nao_adiciona(self):
        r = oficina.app.test_client().post(f"/veiculos/{self.vid}/fotos", data={"fotos": [foto()]},
                                           content_type="multipart/form-data")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith("/login"))
        self.assertEqual(len(self.ids_fotos()), 2)

    def test_falha_no_meio_nao_deixa_foto_orfa(self):
        self.quebrar_o_historico()
        antes = self.arquivos_no_disco()
        r = self.adicionar([foto(), foto("b.jpg")])
        self.assertEqual(r.status_code, 500)
        self.assertEqual(len(self.ids_fotos()), 2)
        self.assertEqual(self.arquivos_no_disco(), antes)


class TrocarFotoTest(GerenciarFotosBase):
    def test_dono_troca_e_a_nova_ocupa_o_mesmo_lugar(self):
        antiga = self.arquivo_da_foto(self.f1)
        r = self.trocar(self.f1, foto("nova.jpg", imagem_em_bytes(tamanho=(555, 333))))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.ids_fotos(), [self.f1, self.f2])               # mesma posição, mesmo número
        nova = self.arquivo_da_foto(self.f1)
        self.assertNotEqual(nova, antiga)
        self.assertEqual(abrir_salva(nova + ".jpg").size, (555, 333))

    def test_a_antiga_some_do_disco_e_nao_sobra_nada(self):
        antiga = self.arquivo_da_foto(self.f1)
        self.trocar(self.f1, foto())
        nomes = self.arquivos_no_disco()
        self.assertNotIn(antiga + ".jpg", nomes)
        self.assertNotIn(antiga + "_m.jpg", nomes)
        self.assertEqual(len(nomes), 4)                                       # 2 fotos × (grande + miniatura)

    def test_as_outras_fotos_nao_sao_afetadas(self):
        outra = self.arquivo_da_foto(self.f2)
        self.trocar(self.f1, foto())
        self.assertEqual(self.arquivo_da_foto(self.f2), outra)
        self.assertIn(outra + ".jpg", self.arquivos_no_disco())

    def test_o_endereco_serve_a_foto_nova(self):
        antes = self.servir(f"/fotos/{self.f1}")[1]
        self.trocar(self.f1, foto("nova.jpg", imagem_em_bytes(tamanho=(555, 333), cor=(10, 200, 10))))
        depois = self.servir(f"/fotos/{self.f1}")[1]
        self.assertNotEqual(antes, depois)

    def test_navegador_sempre_confere_se_a_foto_mudou(self):
        r = self.dono_c.get(f"/fotos/{self.f1}")
        self.assertEqual(r.headers["Cache-Control"], "private, no-cache")
        etiqueta = r.headers["ETag"]
        r.close()
        igual = self.dono_c.get(f"/fotos/{self.f1}", headers={"If-None-Match": etiqueta})
        self.assertEqual(igual.status_code, 304)                              # não mudou: não baixa de novo
        igual.close()
        self.trocar(self.f1, foto("nova.jpg", imagem_em_bytes(tamanho=(555, 333), cor=(10, 200, 10))))
        mudou = self.dono_c.get(f"/fotos/{self.f1}", headers={"If-None-Match": etiqueta})
        self.assertEqual(mudou.status_code, 200)                              # mudou: baixa a nova
        mudou.close()

    def test_fica_registrado_quem_trocou(self):
        self.trocar(self.f1, foto())
        self.assertEqual(self.historico(), [(self.f1, "TROCADA", "DONA MARIA")])

    def test_funcionario_nao_troca(self):
        antiga = self.arquivo_da_foto(self.f1)
        r = self.trocar(self.f1, foto(), cliente=self.func)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.arquivo_da_foto(self.f1), antiga)
        self.assertEqual(self.historico(), [])

    def test_arquivo_invalido_mantem_a_foto_antiga(self):
        antiga = self.arquivo_da_foto(self.f1)
        antes = self.arquivos_no_disco()
        r = self.trocar(self.f1, foto("falsa.jpg", b"isto nao e imagem"))
        self.assertIn("não é uma foto válida".encode(), r.data)
        self.assertEqual(self.arquivo_da_foto(self.f1), antiga)
        self.assertEqual(self.arquivos_no_disco(), antes)

    def test_sem_escolher_arquivo_e_com_mais_de_um(self):
        antiga = self.arquivo_da_foto(self.f1)
        self.assertIn("Escolha a foto que vai ficar".encode(), self.trocar(self.f1, []).data)
        self.assertIn("uma foto só".encode(), self.trocar(self.f1, [foto("a.jpg"), foto("b.jpg")]).data)
        self.assertEqual(self.arquivo_da_foto(self.f1), antiga)

    def test_foto_de_outro_veiculo_ou_inexistente_da_404(self):
        outro = self.novo_veiculo("ZZZ9Z99", fotos=1)
        foto_do_outro = self.ids_fotos(outro)[0]
        self.assertEqual(self.trocar(foto_do_outro, foto()).status_code, 404)       # na URL do veículo errado
        self.assertEqual(self.trocar(99999, foto()).status_code, 404)
        self.assertEqual(self.trocar(self.f1, foto(), vid=99999).status_code, 404)

    def test_falha_no_meio_mantem_a_antiga_e_nao_deixa_foto_nova_orfa(self):
        self.quebrar_o_historico()
        antiga = self.arquivo_da_foto(self.f1)
        antes = self.arquivos_no_disco()
        r = self.trocar(self.f1, foto())
        self.assertEqual(r.status_code, 500)
        self.assertEqual(self.arquivo_da_foto(self.f1), antiga)
        self.assertEqual(self.arquivos_no_disco(), antes)


class ExcluirFotoTest(GerenciarFotosBase):
    def test_dono_exclui_a_foto_e_os_arquivos(self):
        codigo = self.arquivo_da_foto(self.f1)
        r = self.excluir(self.f1)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.ids_fotos(), [self.f2])
        nomes = self.arquivos_no_disco()
        self.assertNotIn(codigo + ".jpg", nomes)
        self.assertNotIn(codigo + "_m.jpg", nomes)
        self.assertEqual(len(nomes), 2)

    def test_o_endereco_da_foto_excluida_da_404(self):
        self.excluir(self.f1)
        self.assertEqual(self.servir(f"/fotos/{self.f1}")[0], 404)
        self.assertEqual(self.servir(f"/fotos/{self.f1}/miniatura")[0], 404)
        self.assertEqual(self.servir(f"/fotos/{self.f2}")[0], 200)

    def test_as_outras_fotos_continuam(self):
        outra = self.arquivo_da_foto(self.f2)
        self.excluir(self.f1)
        self.assertEqual(self.arquivo_da_foto(self.f2), outra)
        self.assertIn(outra + ".jpg", self.arquivos_no_disco())

    def test_pode_excluir_todas(self):
        self.excluir(self.f1)
        self.excluir(self.f2)
        self.assertEqual(self.ids_fotos(), [])
        self.assertEqual(self.arquivos_no_disco(), [])
        self.assertIn("Adicionar fotos", self.pagina())

    def test_fica_registrado_quem_excluiu(self):
        self.excluir(self.f1)
        self.assertEqual(self.historico(), [(self.f1, "EXCLUIDA", "DONA MARIA")])

    def test_funcionario_nao_exclui(self):
        r = self.excluir(self.f1, cliente=self.func)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.ids_fotos(), [self.f1, self.f2])
        self.assertEqual(len(self.arquivos_no_disco()), 4)
        self.assertEqual(self.historico(), [])

    def test_foto_de_outro_veiculo_inexistente_ou_ja_excluida_da_404(self):
        outro = self.novo_veiculo("ZZZ9Z99", fotos=1)
        foto_do_outro = self.ids_fotos(outro)[0]
        self.assertEqual(self.excluir(foto_do_outro).status_code, 404)             # na URL do veículo errado
        self.assertEqual(self.ids_fotos(outro), [foto_do_outro])
        self.assertEqual(self.excluir(99999).status_code, 404)
        self.excluir(self.f1)
        self.assertEqual(self.excluir(self.f1).status_code, 404)                   # segunda vez

    def test_nao_exclui_por_link_simples(self):
        self.assertEqual(self.dono_c.get(f"/veiculos/{self.vid}/fotos/{self.f1}/excluir").status_code, 405)
        self.assertEqual(len(self.ids_fotos()), 2)

    def test_sem_login_nao_exclui(self):
        r = oficina.app.test_client().post(f"/veiculos/{self.vid}/fotos/{self.f1}/excluir")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(len(self.ids_fotos()), 2)

    def test_falha_no_meio_nao_perde_a_foto(self):
        self.quebrar_o_historico()
        antes = self.arquivos_no_disco()
        r = self.excluir(self.f1)
        self.assertEqual(r.status_code, 500)
        self.assertEqual(self.ids_fotos(), [self.f1, self.f2])
        self.assertEqual(self.arquivos_no_disco(), antes)


class TelaDasFotosTest(GerenciarFotosBase):
    def test_dono_ve_trocar_excluir_e_adicionar(self):
        pagina = self.pagina(self.dono_c)
        for foto_id in (self.f1, self.f2):
            self.assertIn(f"/veiculos/{self.vid}/fotos/{foto_id}/trocar", pagina)
            self.assertIn(f"/veiculos/{self.vid}/fotos/{foto_id}/excluir", pagina)
        self.assertIn(f"/veiculos/{self.vid}/fotos", pagina)
        self.assertIn("Adicionar fotos", pagina)

    def test_funcionario_so_ve_adicionar(self):
        pagina = self.pagina(self.func)
        self.assertIn("Adicionar fotos", pagina)
        self.assertNotIn("/trocar", pagina)
        self.assertNotIn("/excluir", pagina)

    def test_excluir_e_trocar_pedem_confirmacao(self):
        pagina = self.pagina(self.dono_c)
        self.assertIn("confirm('Excluir esta foto?", pagina)
        self.assertIn("confirm('Trocar esta foto", pagina)

    def test_veiculo_sem_fotos_ja_abre_o_adicionar(self):
        sem_fotos = self.novo_veiculo("ZZZ9Z99", fotos=0)
        self.assertRegex(self.pagina(vid=sem_fotos), r'<details class="adicionar-fotos" open>')
        self.assertNotRegex(self.pagina(), r'<details class="adicionar-fotos" open>')

    def test_veiculo_entregue_nao_oferece_mexer_nas_fotos(self):
        self.marcar_como_entregue()
        for cliente in (self.dono_c, self.func):
            pagina = self.pagina(cliente)
            self.assertNotIn("/trocar", pagina)
            self.assertNotIn("/excluir\"", pagina.replace("/servicos", ""))
            self.assertNotIn("Adicionar fotos", pagina)
            self.assertIn(f"/fotos/{self.f1}/miniatura", pagina)                 # mas as fotos continuam visíveis

    def test_veiculo_entregue_barra_adicionar_trocar_e_excluir(self):
        self.marcar_como_entregue()
        antes = self.arquivos_no_disco()
        for r in (self.adicionar([foto()]), self.trocar(self.f1, foto()), self.excluir(self.f1)):
            self.assertEqual(r.status_code, 409)
            self.assertIn("já foi entregue".encode(), r.data)
        self.assertEqual(self.ids_fotos(), [self.f1, self.f2])
        self.assertEqual(self.arquivos_no_disco(), antes)
        self.assertEqual(self.historico(), [])

    def test_historico_so_para_o_dono_com_hora_de_brasilia(self):
        self.excluir(self.f1)
        self.sql("UPDATE fotos_historico SET feita_em = '2026-10-06 00:30:30'")
        pagina = self.pagina(self.dono_c)
        self.assertIn("Histórico das fotos (1)", pagina)
        self.assertIn("Foto excluída", pagina)
        self.assertIn("05/10/2026 21:30", pagina)
        self.assertNotIn("Histórico das fotos", self.pagina(self.func))

    def test_historico_de_outro_veiculo_nao_aparece(self):
        outro = self.novo_veiculo("ZZZ9Z99", fotos=1)
        self.excluir(self.ids_fotos(outro)[0], vid=outro)
        self.assertNotIn("Histórico das fotos", self.pagina())

    def test_a_lista_de_veiculos_acompanha_as_mudancas(self):
        self.excluir(self.f1)
        lista = self.func.get("/").data.decode()
        self.assertNotIn(f"/fotos/{self.f1}/miniatura", lista)
        self.assertIn(f"/fotos/{self.f2}/miniatura", lista)


class FotosGerenciarComCsrfTest(GerenciarFotosBase):
    def test_sem_token_nada_acontece(self):
        oficina.app.config["WTF_CSRF_ENABLED"] = True
        self.addCleanup(oficina.app.config.__setitem__, "WTF_CSRF_ENABLED", False)
        antes = self.arquivos_no_disco()
        respostas = [self.adicionar([foto()]), self.trocar(self.f1, foto()), self.excluir(self.f1)]
        for r in respostas:
            self.assertEqual(r.status_code, 302)
            self.assertTrue(r.headers["Location"].endswith("/login?expirou=1"))
        self.assertEqual(self.ids_fotos(), [self.f1, self.f2])
        self.assertEqual(self.arquivos_no_disco(), antes)


if __name__ == "__main__":
    unittest.main()
