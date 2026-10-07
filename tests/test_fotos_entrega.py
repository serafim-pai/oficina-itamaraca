"""Testes das fotos do veículo na entrega.
Rodar na pasta do projeto:  python -m unittest discover tests -v"""
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import date

from base import BaseTest, foto_de_entrega, oficina
from test_fotos import abrir_salva, foto, imagem_em_bytes

HOJE_REAL = oficina.hoje_brasil
HOJE = date(2026, 10, 15)
VEICULO = {"responsavel": "JOSE DA SILVA", "placa": "ABC1D23", "marca": "FIAT", "modelo": "UNO",
           "cor": "VERMELHO", "ano": "2012", "quilometragem": "150000", "documento_deixado": "on"}
CONDICOES = "A garantia deixa de valer se o veículo for consertado por outra oficina ou sofrer acidente."


class Base(BaseTest):
    def setUp(self):
        super().setUp()
        oficina.hoje_brasil = lambda agora_utc=None: HOJE
        self.addCleanup(setattr, oficina, "hoje_brasil", HOJE_REAL)
        self.func = self.funcionario()
        self.dono_c = self.dono()
        self.vid = self.novo_veiculo("ABC1D23", entrada=2)
        self.sid = self.servico(self.vid)

    # ---- atalhos ----
    def novo_veiculo(self, placa, entrada=0):
        envio = [foto(f"e{i}.jpg", imagem_em_bytes(tamanho=(200 + i, 100))) for i in range(entrada)]
        self.func.post("/veiculos", data={**VEICULO, "placa": placa, "fotos": envio}, content_type="multipart/form-data")
        return self.sql("SELECT id FROM veiculos WHERE placa = ?", (placa,))[0]["id"]

    def servico(self, vid):
        """Um serviço com valor, aprovado e com garantia: o veículo fica pronto para fechar a entrega."""
        self.func.post(f"/veiculos/{vid}/servicos", data={"tipo": "LATARIA", "problema": "Amassado na porta do motorista"})
        sid = self.sql("SELECT MAX(id) AS id FROM servicos")[0]["id"]
        self.dono_c.post(f"/veiculos/{vid}/servicos/{sid}/valor", data={"valor": "150,00"})
        self.func.post(f"/veiculos/{vid}/aprovacao",
                       data={"decisao": "APROVADO", "forma": "TELEFONE", "assinatura": self.assinatura(vid)})
        self.dono_c.post(f"/veiculos/{vid}/servicos/{sid}/garantia", data={"valor": "90", "unidade": "DIAS"})
        return sid

    def assinatura(self, vid=None):
        pagina = self.dono_c.get(f"/veiculos/{vid or self.vid}").data.decode()
        achou = re.search(r'name="assinatura" value="([^"]+)"', pagina)
        return achou.group(1) if achou else None

    def fechar(self, fotos=..., condicoes=CONDICOES, cliente=None, vid=None):
        vid = vid or self.vid
        self.marcar_pronto(vid)
        if fotos is ...:
            fotos = [foto_de_entrega()]
        return (cliente or self.dono_c).post(
            f"/veiculos/{vid}/entrega", content_type="multipart/form-data",
            data={"condicoes": condicoes, "assinatura": self.assinatura(vid), "fotos_entrega": fotos})

    def desfazer(self, vid=None):
        return self.dono_c.post(f"/veiculos/{vid or self.vid}/entrega/desfazer", data={"motivo": "Cliente pediu uma correção"})

    def fotos(self, momento=None, vid=None):
        consulta = "SELECT * FROM fotos WHERE veiculo_id = ?" + (" AND momento = ?" if momento else "") + " ORDER BY id"
        return self.sql(consulta, (vid or self.vid,) + ((momento,) if momento else ()))

    def entregas(self):
        return self.sql("SELECT * FROM entregas")

    def arquivos_no_disco(self):
        return sorted(os.listdir(oficina.PASTA_FOTOS))

    def pagina(self, cliente=None, vid=None):
        return (cliente or self.dono_c).get(f"/veiculos/{vid or self.vid}").data.decode()


class ObrigatoriedadeDaFotoTest(Base):
    def test_nao_fecha_a_entrega_sem_foto(self):
        antes = self.arquivos_no_disco()
        for envio in ([], None):
            r = self.fechar(fotos=envio)
            self.assertIn("pelo menos uma foto do veículo na entrega".encode(), r.data)
        self.assertEqual(self.entregas(), [])
        self.assertEqual(self.fotos("ENTREGA"), [])
        self.assertEqual(self.arquivos_no_disco(), antes)

    def test_fecha_com_uma_foto(self):
        r = self.fechar()
        self.assertEqual(r.status_code, 302)
        self.assertEqual(len(self.entregas()), 1)
        entrega = self.fotos("ENTREGA")
        self.assertEqual(len(entrega), 1)
        self.assertEqual(len(self.fotos("ENTRADA")), 2)                       # as de entrada continuam como estavam
        self.assertEqual(len(self.arquivos_no_disco()), 6)                    # 3 fotos × (grande + miniatura)

    def test_fecha_com_varias_fotos(self):
        self.fechar(fotos=[foto_de_entrega(f"{i}.jpg") for i in range(3)])
        self.assertEqual(len(self.fotos("ENTREGA")), 3)

    def test_limite_de_fotos_na_entrega(self):
        r = self.fechar(fotos=[foto_de_entrega(f"{i}.jpg") for i in range(oficina.MAX_FOTOS + 1)])
        self.assertIn("no máximo".encode(), r.data)
        self.assertEqual(self.entregas(), [])
        self.assertEqual(self.fechar(fotos=[foto_de_entrega(f"{i}.jpg") for i in range(oficina.MAX_FOTOS)]).status_code, 302)
        self.assertEqual(len(self.fotos("ENTREGA")), oficina.MAX_FOTOS)

    def test_uma_foto_ruim_barra_a_entrega_toda(self):
        antes = self.arquivos_no_disco()
        r = self.fechar(fotos=[foto_de_entrega("boa.jpg"), foto("ruim.jpg", b"isto nao e imagem"), foto_de_entrega("boa2.jpg")])
        self.assertIn("ruim.jpg".encode(), r.data)
        self.assertEqual(self.entregas(), [])
        self.assertEqual(self.sql("SELECT * FROM entrega_itens"), [])
        self.assertEqual(self.fotos("ENTREGA"), [])
        self.assertEqual(self.arquivos_no_disco(), antes)

    def test_html_e_svg_disfarcados_de_foto_sao_recusados(self):
        for nome, conteudo in [("a.jpg", b"<script>alert(1)</script>"),
                               ("b.svg", b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')]:
            r = self.fechar(fotos=[foto(nome, conteudo)])
            self.assertIn("não é uma foto válida".encode(), r.data, nome)
        self.assertEqual(self.entregas(), [])

    def test_foto_grande_demais_e_recusada(self):
        r = self.fechar(fotos=[foto("enorme.jpg", b"0" * (oficina.MAX_BYTES_FOTO + 1))])
        self.assertIn("grande demais".encode(), r.data)
        self.assertEqual(self.entregas(), [])

    def test_outro_erro_na_entrega_nao_guarda_as_fotos_e_avisa(self):
        self.sql("UPDATE servicos SET garantia_valor = NULL")                     # falta informar a garantia
        antes = self.arquivos_no_disco()
        r = self.fechar()
        self.assertIn("Informe o tempo de garantia".encode(), r.data)
        self.assertIn("escolhidas de novo".encode(), r.data)
        self.assertEqual(self.entregas(), [])
        self.assertEqual(self.fotos("ENTREGA"), [])
        self.assertEqual(self.arquivos_no_disco(), antes)

    def test_a_foto_da_entrega_passa_pelo_mesmo_tratamento_das_outras(self):
        self.fechar(fotos=[foto("grande.png", imagem_em_bytes("PNG", (4000, 3000)))])
        codigo = self.fotos("ENTREGA")[0]["arquivo"]
        imagem = abrir_salva(codigo + ".jpg")
        self.assertEqual(imagem.format, "JPEG")
        self.assertEqual(max(imagem.size), oficina.LADO_FOTO)
        self.assertEqual(len(imagem.getexif()), 0)

    def test_nome_do_arquivo_nunca_vira_caminho(self):
        self.fechar(fotos=[foto("../../../etc/passwd.jpg", imagem_em_bytes())])
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{32}(_m)?\.jpg", n) for n in self.arquivos_no_disco()))

    def test_falha_no_meio_nao_deixa_foto_orfa_nem_entrega_pela_metade(self):
        assinatura = self.assinatura()                                            # antes de estragar a tabela
        gravadas = []
        original = oficina.gravar_arquivos_da_foto

        def gravar_e_anotar(grande, miniatura, criados):
            codigo = original(grande, miniatura, criados)
            gravadas.append(codigo)                                               # prova de que o arquivo chegou a ser criado
            return codigo

        oficina.gravar_arquivos_da_foto = gravar_e_anotar
        self.addCleanup(setattr, oficina, "gravar_arquivos_da_foto", original)
        self.sql("ALTER TABLE fotos RENAME TO fotos_x")                           # o registro da foto no banco vai falhar
        oficina.app.testing = False
        self.addCleanup(setattr, oficina.app, "testing", True)
        try:
            self.marcar_pronto(self.vid)
            r = self.dono_c.post(f"/veiculos/{self.vid}/entrega", content_type="multipart/form-data",
                                 data={"condicoes": CONDICOES, "assinatura": assinatura,
                                       "fotos_entrega": [foto_de_entrega()]})
            self.assertEqual(r.status_code, 500)
        finally:
            self.sql("ALTER TABLE fotos_x RENAME TO fotos")
        self.assertEqual(len(gravadas), 1)                                        # o arquivo foi criado...
        self.assertFalse(any(g in n for g in gravadas for n in self.arquivos_no_disco()))   # ...e depois removido
        self.assertEqual(self.entregas(), [])                                     # a entrega foi desfeita junto
        self.assertEqual(self.sql("SELECT * FROM entrega_itens"), [])
        self.assertEqual(len(self.arquivos_no_disco()), 4)                        # só as 2 fotos de entrada: nenhum arquivo órfão

    def test_so_o_dono_fecha_a_entrega(self):
        r = self.fechar(cliente=self.func)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.fotos("ENTREGA"), [])

    def test_sem_login_nao_fecha(self):
        r = oficina.app.test_client().post(f"/veiculos/{self.vid}/entrega", content_type="multipart/form-data",
                                           data={"fotos_entrega": [foto_de_entrega()]})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith("/login"))
        self.assertEqual(self.fotos("ENTREGA"), [])

    def test_segunda_tentativa_de_fechar_nao_acrescenta_fotos(self):
        self.fechar()
        r = self.fechar(fotos=[foto_de_entrega("outra.jpg")])
        self.assertEqual(r.status_code, 409)
        self.assertEqual(len(self.fotos("ENTREGA")), 1)
        self.assertEqual(len(self.arquivos_no_disco()), 6)

    def test_o_formulario_pede_as_fotos_e_tem_previa(self):
        pagina = self.pagina()
        self.assertIn('name="fotos_entrega"', pagina)
        self.assertIn('enctype="multipart/form-data"', pagina)
        self.assertIn("Fotos do veículo na entrega *", pagina)
        self.assertIn("previa-fotos-entrega", pagina)

    def test_sem_token_nao_fecha(self):
        oficina.app.config["WTF_CSRF_ENABLED"] = True
        self.addCleanup(oficina.app.config.__setitem__, "WTF_CSRF_ENABLED", False)
        r = self.fechar()
        self.assertTrue(r.headers["Location"].endswith("/login?expirou=1"))
        self.assertEqual(self.entregas(), [])
        self.assertEqual(self.fotos("ENTREGA"), [])


class EntradaEEntregaSeparadasTest(Base):
    def test_a_foto_de_entrega_tem_o_momento_certo(self):
        self.fechar()
        self.assertEqual([f["momento"] for f in self.fotos()], ["ENTRADA", "ENTRADA", "ENTREGA"])

    def test_a_tela_mostra_as_duas_galerias_separadas(self):
        self.fechar()
        pagina = self.pagina(self.func)
        entrada = [f["id"] for f in self.fotos("ENTRADA")]
        entrega = [f["id"] for f in self.fotos("ENTREGA")]
        self.assertIn("Fotos da entrada do veículo (como o carro chegou)", pagina)
        self.assertIn("Fotos do veículo na entrega", pagina)
        divisao = pagina.index("Fotos do veículo na entrega</h3>")
        for foto_id in entrada:
            self.assertLess(pagina.index(f"/fotos/{foto_id}/miniatura"), divisao)
        for foto_id in entrega:
            self.assertGreater(pagina.index(f"/fotos/{foto_id}/miniatura"), divisao)

    def test_funcionario_tambem_ve_as_fotos_da_entrega(self):
        self.fechar()
        entrega = self.fotos("ENTREGA")[0]["id"]
        self.assertIn(f"/fotos/{entrega}/miniatura", self.pagina(self.func))

    def test_antes_da_entrega_nao_ha_galeria_de_entrega(self):
        self.assertNotIn("Fotos do veículo na entrega</h3>", self.pagina())

    def test_a_lista_de_veiculos_mostra_so_as_fotos_de_entrada(self):
        self.fechar()
        lista = self.func.get("/").data.decode()
        for f in self.fotos("ENTRADA"):
            self.assertIn(f"/fotos/{f['id']}/miniatura", lista)
        self.assertNotIn(f"/fotos/{self.fotos('ENTREGA')[0]['id']}/miniatura", lista)

    def test_fotos_da_entrega_nao_tem_botao_de_trocar_ou_excluir(self):
        self.fechar()
        pagina = self.pagina(self.dono_c)
        entrega = self.fotos("ENTREGA")[0]["id"]
        self.assertNotIn(f"/fotos/{entrega}/trocar", pagina)
        self.assertNotIn(f"/fotos/{entrega}/excluir", pagina)

    def test_nao_da_para_trocar_nem_excluir_foto_de_entrega_nem_depois_de_desfazer(self):
        self.fechar()
        self.desfazer()                                   # destrava o cadastro: agora só o tipo da foto protege
        for f in self.fotos():
            if f["momento"] == "ENTRADA":
                continue
            r1 = self.dono_c.post(f"/veiculos/{self.vid}/fotos/{f['id']}/excluir")
            r2 = self.dono_c.post(f"/veiculos/{self.vid}/fotos/{f['id']}/trocar", data={"foto": foto_de_entrega()},
                                  content_type="multipart/form-data")
            self.assertEqual((r1.status_code, r2.status_code), (404, 404))
        self.assertEqual(len(self.fotos("ENTREGA_DESFEITA")), 1)

    def test_o_limite_de_20_fotos_conta_so_as_de_entrada(self):
        self.fechar(fotos=[foto_de_entrega(f"{i}.jpg") for i in range(3)])
        self.desfazer()                                   # 2 de entrada + 3 de entrega desfeita
        r = self.func.post(f"/veiculos/{self.vid}/fotos", data={"fotos": [foto(f"{i}.jpg") for i in range(10)]},
                           content_type="multipart/form-data")
        self.assertEqual(r.status_code, 302)
        r = self.func.post(f"/veiculos/{self.vid}/fotos", data={"fotos": [foto(f"{i}.jpg") for i in range(8)]},
                           content_type="multipart/form-data")
        self.assertEqual(r.status_code, 302)              # 2 + 10 + 8 = 20 de entrada; as 3 desfeitas não contam
        self.assertEqual(len(self.fotos("ENTRADA")), oficina.MAX_FOTOS_VEICULO)

    def test_as_fotos_de_entrega_so_aparecem_para_quem_entrou(self):
        self.fechar()
        entrega = self.fotos("ENTREGA")[0]["id"]
        anonimo = oficina.app.test_client()
        for caminho in (f"/fotos/{entrega}", f"/fotos/{entrega}/miniatura"):
            r = anonimo.get(caminho)
            self.assertEqual(r.status_code, 302, caminho)
            r.close()
            r = self.func.get(caminho)
            self.assertEqual(r.status_code, 200, caminho)
            r.close()


class ComprovanteComFotosTest(Base):
    def test_o_comprovante_mostra_as_fotos_da_entrega_e_so_elas(self):
        self.fechar(fotos=[foto_de_entrega("a.jpg"), foto_de_entrega("b.jpg")])
        pagina = self.dono_c.get(f"/veiculos/{self.vid}/comprovante").data.decode()
        self.assertIn("Fotos do veículo na entrega", pagina)
        for f in self.fotos("ENTREGA"):
            self.assertIn(f"/fotos/{f['id']}/miniatura", pagina)
        for f in self.fotos("ENTRADA"):
            self.assertNotIn(f"/fotos/{f['id']}/miniatura", pagina)
        self.assertEqual(pagina.count('class="fotos-comprovante"'), 1)

    def test_a_ordem_do_comprovante_continua_a_mesma(self):
        self.fechar()
        pagina = self.dono_c.get(f"/veiculos/{self.vid}/comprovante").data.decode()
        self.assertLess(pagina.index("Condições que cancelam a garantia"), pagina.index("Fotos do veículo na entrega"))
        self.assertLess(pagina.index("Fotos do veículo na entrega"), pagina.index('class="assinaturas"'))

    def test_o_estilo_das_fotos_do_comprovante_existe(self):
        resposta = self.dono_c.get("/static/estilo.css")
        css = resposta.data.decode()
        resposta.close()
        self.assertIn(".comprovante .fotos-comprovante", css)


class DesfazerEntregaComFotosTest(Base):
    def test_as_fotos_da_entrega_desfeita_ficam_guardadas_e_ligadas_a_ela(self):
        self.fechar(fotos=[foto_de_entrega("a.jpg"), foto_de_entrega("b.jpg")])
        self.desfazer()
        desfeitas = self.fotos("ENTREGA_DESFEITA")
        self.assertEqual(len(desfeitas), 2)
        self.assertEqual(self.fotos("ENTREGA"), [])
        entrega_desfeita = self.sql("SELECT id FROM entregas_desfeitas")[0]["id"]
        self.assertTrue(all(f["entrega_desfeita_id"] == entrega_desfeita for f in desfeitas))
        self.assertEqual(len(self.arquivos_no_disco()), 8)                       # nada foi apagado do disco

    def test_aparecem_no_historico_de_entregas_desfeitas(self):
        self.fechar(fotos=[foto_de_entrega("a.jpg"), foto_de_entrega("b.jpg")])
        self.desfazer()
        pagina = self.pagina()
        for f in self.fotos("ENTREGA_DESFEITA"):
            self.assertIn(f"/fotos/{f['id']}/miniatura", pagina)
        self.assertIn("Fotos da entrega</th>", pagina)

    def test_nao_aparecem_nas_galerias_normais(self):
        self.fechar()
        self.desfazer()
        pagina = self.pagina()
        self.assertNotIn("Fotos do veículo na entrega</h3>", pagina)
        lista = self.func.get("/").data.decode()
        self.assertNotIn(f"/fotos/{self.fotos('ENTREGA_DESFEITA')[0]['id']}/miniatura", lista)

    def test_as_fotos_desfeitas_continuam_acessiveis_para_quem_entrou(self):
        self.fechar()
        self.desfazer()
        antiga = self.fotos("ENTREGA_DESFEITA")[0]["id"]
        for caminho in (f"/fotos/{antiga}", f"/fotos/{antiga}/miniatura"):
            r = self.dono_c.get(caminho)
            self.assertEqual(r.status_code, 200)
            r.close()

    def test_fechar_de_novo_exige_novas_fotos(self):
        self.fechar()
        self.desfazer()
        r = self.fechar(fotos=[])
        self.assertIn("pelo menos uma foto do veículo na entrega".encode(), r.data)
        self.assertEqual(self.entregas(), [])
        self.assertEqual(self.fechar().status_code, 302)
        self.assertEqual(len(self.fotos("ENTREGA")), 1)
        self.assertEqual(len(self.fotos("ENTREGA_DESFEITA")), 1)

    def test_cada_entrega_desfeita_mostra_so_as_suas_fotos(self):
        self.fechar(fotos=[foto_de_entrega("a.jpg")])
        self.desfazer()
        primeira = self.sql("SELECT id FROM entregas_desfeitas ORDER BY id")[0]["id"]
        self.fechar(fotos=[foto_de_entrega("b.jpg"), foto_de_entrega("c.jpg")])
        self.desfazer()
        segunda = self.sql("SELECT id FROM entregas_desfeitas ORDER BY id")[1]["id"]
        por_entrega = {}
        for f in self.fotos("ENTREGA_DESFEITA"):
            por_entrega.setdefault(f["entrega_desfeita_id"], []).append(f["id"])
        self.assertEqual({k: len(v) for k, v in por_entrega.items()}, {primeira: 1, segunda: 2})

    def test_o_comprovante_antigo_some_junto_com_a_entrega(self):
        self.fechar()
        self.desfazer()
        self.assertEqual(self.dono_c.get(f"/veiculos/{self.vid}/comprovante").status_code, 404)

    def test_outro_veiculo_nao_e_afetado(self):
        outro = self.novo_veiculo("ZZZ9Z99", entrada=1)
        self.servico(outro)
        self.fechar(vid=outro)
        self.fechar()
        self.desfazer()
        self.assertEqual(len(self.fotos("ENTREGA", vid=outro)), 1)
        self.assertEqual(self.fotos("ENTREGA_DESFEITA", vid=outro), [])


class MigracaoDasFotosTest(unittest.TestCase):
    def test_banco_antigo_ganha_as_colunas_e_as_fotos_antigas_viram_de_entrada(self):
        caminho = os.path.join(tempfile.mkdtemp(), "antigo.db")
        banco = sqlite3.connect(caminho)
        banco.execute("CREATE TABLE fotos (id INTEGER PRIMARY KEY AUTOINCREMENT, veiculo_id INTEGER NOT NULL, "
                      "arquivo TEXT NOT NULL, criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")   # como era antes
        banco.execute("INSERT INTO fotos (veiculo_id, arquivo) VALUES (1, 'abc'), (1, 'def')")
        banco.commit()
        banco.close()
        pasta_projeto = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ambiente = dict(os.environ, OFICINA_DB=caminho, OFICINA_SECRET="x", OFICINA_FOTOS=os.path.join(os.path.dirname(caminho), "f"))
        r = subprocess.run([sys.executable, "-c", "import app"], cwd=pasta_projeto, env=ambiente, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        banco = sqlite3.connect(caminho)
        colunas = [c[1] for c in banco.execute("PRAGMA table_info(fotos)")]
        self.assertIn("momento", colunas)
        self.assertIn("entrega_desfeita_id", colunas)
        self.assertEqual(banco.execute("SELECT arquivo, momento FROM fotos ORDER BY id").fetchall(),
                         [("abc", "ENTRADA"), ("def", "ENTRADA")])
        banco.close()


if __name__ == "__main__":
    unittest.main()
