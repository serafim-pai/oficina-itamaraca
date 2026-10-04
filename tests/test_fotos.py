"""Testes das fotos do veículo.
Rodar na pasta do projeto:  python -m unittest discover tests -v"""
import io
import os
import re
import unittest

from PIL import Image

from base import BaseTest, oficina

DADOS = {"placa": "ABC1D23", "documento_deixado": "on"}


def imagem_em_bytes(formato="JPEG", tamanho=(200, 100), cor=(200, 30, 30), **extras):
    memoria = io.BytesIO()
    Image.new("RGB", tamanho, cor).save(memoria, formato, **extras)
    return memoria.getvalue()


def abrir_salva(nome_do_arquivo):
    """Abre uma foto guardada pelo sistema sem deixar o arquivo aberto."""
    with open(os.path.join(oficina.PASTA_FOTOS, nome_do_arquivo), "rb") as f:
        imagem = Image.open(io.BytesIO(f.read()))
        imagem.load()
        return imagem


def foto(nome="carro.jpg", conteudo=None):
    return (io.BytesIO(conteudo if conteudo is not None else imagem_em_bytes()), nome)


class FotosTest(BaseTest):
    def setUp(self):
        super().setUp()
        self.c = self.funcionario()

    def cadastrar(self, fotos, **dados):
        return self.c.post("/veiculos", data={**DADOS, **dados, "fotos": fotos},
                           content_type="multipart/form-data")

    def arquivos_no_disco(self):
        return sorted(os.listdir(oficina.PASTA_FOTOS))

    # ---------- caminho feliz ----------

    def test_cadastra_veiculo_com_duas_fotos(self):
        r = self.cadastrar([foto("a.jpg"), foto("b.png", imagem_em_bytes("PNG"))])
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.total_veiculos(), 1)
        linhas = self.sql("SELECT * FROM fotos")
        self.assertEqual(len(linhas), 2)
        self.assertEqual(len(self.arquivos_no_disco()), 4)          # cada foto: grande + miniatura
        self.assertTrue(all(f["veiculo_id"] == self.sql("SELECT id FROM veiculos")[0]["id"] for f in linhas))

    def test_fotos_sao_opcionais(self):
        self.assertEqual(self.cadastrar([]).status_code, 302)
        self.assertEqual(self.c.post("/veiculos", data=DADOS).status_code, 302)   # envio simples, sem arquivo
        self.assertEqual(self.total_veiculos(), 2)
        self.assertEqual(self.sql("SELECT * FROM fotos"), [])

    def test_a_foto_e_reduzida_e_guardada_como_jpeg(self):
        self.cadastrar([foto("grande.png", imagem_em_bytes("PNG", (4000, 3000)))])
        codigo = self.sql("SELECT arquivo FROM fotos")[0]["arquivo"]
        grande = abrir_salva(codigo + ".jpg")
        mini = abrir_salva(codigo + "_m.jpg")
        self.assertEqual(grande.format, "JPEG")
        self.assertEqual(max(grande.size), oficina.LADO_FOTO)
        self.assertEqual(max(mini.size), oficina.LADO_MINIATURA)

    def test_foto_pequena_nao_e_ampliada(self):
        self.cadastrar([foto()])
        codigo = self.sql("SELECT arquivo FROM fotos")[0]["arquivo"]
        self.assertEqual(abrir_salva(codigo + ".jpg").size, (200, 100))

    def test_png_transparente_vira_jpeg_com_fundo_branco(self):
        memoria = io.BytesIO()
        Image.new("RGBA", (50, 50), (0, 0, 0, 0)).save(memoria, "PNG")
        self.cadastrar([foto("t.png", memoria.getvalue())])
        codigo = self.sql("SELECT arquivo FROM fotos")[0]["arquivo"]
        pixel = abrir_salva(codigo + ".jpg").getpixel((25, 25))
        self.assertTrue(all(canal > 240 for canal in pixel), pixel)

    # ---------- privacidade ----------

    def test_localizacao_gps_e_removida(self):
        original = Image.new("RGB", (100, 100), "blue")
        exif = Image.Exif()
        exif[0x010F] = "MarcaDoCelular"                  # fabricante
        exif.get_ifd(0x8825)[1] = "S"                    # bloco de GPS
        memoria = io.BytesIO()
        original.save(memoria, "JPEG", exif=exif)
        self.assertTrue(len(Image.open(io.BytesIO(memoria.getvalue())).getexif()) > 0)   # a foto de teste tem EXIF
        self.cadastrar([foto("gps.jpg", memoria.getvalue())])
        codigo = self.sql("SELECT arquivo FROM fotos")[0]["arquivo"]
        for sufixo in (".jpg", "_m.jpg"):
            salva = abrir_salva(codigo + sufixo)
            self.assertEqual(len(salva.getexif()), 0, sufixo)

    def test_foto_de_celular_deitada_e_endireitada(self):
        original = Image.new("RGB", (100, 50), "green")
        exif = Image.Exif()
        exif[0x0112] = 6                                  # "girar 90°", como os celulares gravam
        memoria = io.BytesIO()
        original.save(memoria, "JPEG", exif=exif)
        self.cadastrar([foto("celular.jpg", memoria.getvalue())])
        codigo = self.sql("SELECT arquivo FROM fotos")[0]["arquivo"]
        self.assertEqual(abrir_salva(codigo + ".jpg").size, (50, 100))

    def test_nome_do_arquivo_nunca_vira_caminho(self):
        self.cadastrar([foto("../../../etc/passwd.jpg")])
        codigo = self.sql("SELECT arquivo FROM fotos")[0]["arquivo"]
        self.assertRegex(codigo, r"^[0-9a-f]{32}$")
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{32}(_m)?\.jpg", n) for n in self.arquivos_no_disco()))

    # ---------- arquivos que não devem passar ----------

    def test_recusa_arquivo_que_nao_e_imagem_mesmo_com_nome_de_foto(self):
        r = self.cadastrar([foto("virus.jpg", b"isto nao e uma imagem" * 100)])
        self.assertEqual(r.status_code, 200)
        self.assertIn("não é uma foto válida".encode(), r.data)
        self.assertEqual(self.total_veiculos(), 0)
        self.assertEqual(self.arquivos_no_disco(), [])

    def test_recusa_html_e_svg_disfarcados(self):
        for nome, conteudo in [("a.jpg", b"<script>alert(1)</script>"),
                               ("b.svg", b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')]:
            r = self.cadastrar([foto(nome, conteudo)])
            self.assertIn("não é uma foto válida".encode(), r.data, nome)
        self.assertEqual(self.total_veiculos(), 0)

    def test_recusa_foto_cortada_no_meio(self):
        r = self.cadastrar([foto("cortada.jpg", imagem_em_bytes(tamanho=(800, 800))[:500])])
        self.assertIn("não é uma foto válida".encode(), r.data)
        self.assertEqual(self.total_veiculos(), 0)

    def test_recusa_foto_grande_demais(self):
        r = self.cadastrar([foto("enorme.jpg", b"0" * (oficina.MAX_BYTES_FOTO + 1))])
        self.assertIn("grande demais".encode(), r.data)
        self.assertEqual(self.total_veiculos(), 0)

    def test_recusa_resolucao_absurda(self):
        original = oficina.MAX_PIXELS_FOTO
        oficina.MAX_PIXELS_FOTO = 1000
        self.addCleanup(setattr, oficina, "MAX_PIXELS_FOTO", original)
        r = self.cadastrar([foto("alta.jpg", imagem_em_bytes(tamanho=(100, 100)))])
        self.assertIn("resolução alta demais".encode(), r.data)
        self.assertEqual(self.total_veiculos(), 0)

    def test_recusa_mais_de_dez_fotos(self):
        r = self.cadastrar([foto(f"{i}.jpg") for i in range(oficina.MAX_FOTOS + 1)])
        self.assertIn("no máximo".encode(), r.data)
        self.assertEqual(self.total_veiculos(), 0)
        self.assertEqual(self.arquivos_no_disco(), [])

    def test_aceita_exatamente_dez_fotos(self):
        self.assertEqual(self.cadastrar([foto(f"{i}.jpg") for i in range(oficina.MAX_FOTOS)]).status_code, 302)
        self.assertEqual(len(self.sql("SELECT * FROM fotos")), oficina.MAX_FOTOS)

    def test_uma_foto_ruim_barra_o_cadastro_inteiro(self):
        r = self.cadastrar([foto("boa.jpg"), foto("ruim.jpg", b"lixo"), foto("boa2.jpg")])
        self.assertIn("ruim.jpg".encode(), r.data)
        self.assertEqual(self.total_veiculos(), 0)
        self.assertEqual(self.sql("SELECT * FROM fotos"), [])
        self.assertEqual(self.arquivos_no_disco(), [])

    def test_erro_no_cadastro_nao_guarda_fotos_e_pede_para_escolher_de_novo(self):
        r = self.cadastrar([foto()], placa="")
        self.assertIn("A placa é obrigatória".encode(), r.data)
        self.assertIn("escolhidas de novo".encode(), r.data)
        self.assertEqual(self.arquivos_no_disco(), [])
        self.assertEqual(self.total_veiculos(), 0)

    def test_nome_de_arquivo_com_html_aparece_como_texto(self):
        r = self.cadastrar([foto("<img src=x onerror=alert(1)>.jpg", b"lixo")])
        self.assertNotIn(b"<img src=x onerror", r.data)

    def test_falha_ao_gravar_nao_deixa_foto_orfa(self):
        original = oficina.guardar_fotos

        def guardar_e_falhar(db, veiculo_id, fotos, criados):
            original(db, veiculo_id, fotos[:1], criados)    # grava a 1ª foto...
            raise RuntimeError("falha de teste")             # ...e cai antes de terminar

        oficina.guardar_fotos = guardar_e_falhar
        self.addCleanup(setattr, oficina, "guardar_fotos", original)
        oficina.app.config["PROPAGATE_EXCEPTIONS"] = False
        self.addCleanup(oficina.app.config.__setitem__, "PROPAGATE_EXCEPTIONS", None)
        oficina.app.testing = False
        self.addCleanup(setattr, oficina.app, "testing", True)
        r = self.cadastrar([foto(), foto("b.jpg")])
        self.assertEqual(r.status_code, 500)
        self.assertEqual(self.total_veiculos(), 0)
        self.assertEqual(self.sql("SELECT * FROM fotos"), [])
        self.assertEqual(self.arquivos_no_disco(), [])

    def test_envio_gigante_recebe_mensagem_simples(self):
        original = oficina.app.config["MAX_CONTENT_LENGTH"]
        oficina.app.config["MAX_CONTENT_LENGTH"] = 100_000
        self.addCleanup(oficina.app.config.__setitem__, "MAX_CONTENT_LENGTH", original)
        r = self.cadastrar([foto("a.jpg", b"0" * 300_000)])
        self.assertEqual(r.status_code, 413)
        self.assertIn("passaram do tamanho".encode(), r.data)
        self.assertEqual(self.total_veiculos(), 0)

    # ---------- ver as fotos ----------

    def cadastrar_e_pegar_id(self):
        self.cadastrar([foto()])
        return self.sql("SELECT id FROM fotos")[0]["id"]

    def test_lista_mostra_as_miniaturas_do_veiculo(self):
        foto_id = self.cadastrar_e_pegar_id()
        pagina = self.c.get("/").data
        self.assertIn(f"/fotos/{foto_id}/miniatura".encode(), pagina)
        self.assertIn(f'href="/fotos/{foto_id}"'.encode(), pagina)

    def test_logado_ve_a_foto_com_cabecalhos_de_seguranca(self):
        foto_id = self.cadastrar_e_pegar_id()
        for caminho in (f"/fotos/{foto_id}", f"/fotos/{foto_id}/miniatura"):
            r = self.c.get(caminho)
            self.assertEqual(r.status_code, 200, caminho)
            self.assertEqual(r.mimetype, "image/jpeg")
            self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")
            self.assertIn("private", r.headers["Cache-Control"])
            self.assertEqual(Image.open(io.BytesIO(r.data)).format, "JPEG")
            r.close()

    def test_sem_login_nao_ve_foto_nenhuma(self):
        foto_id = self.cadastrar_e_pegar_id()
        visitante = oficina.app.test_client()
        for caminho in (f"/fotos/{foto_id}", f"/fotos/{foto_id}/miniatura"):
            r = visitante.get(caminho)
            self.assertEqual(r.status_code, 302, caminho)
            self.assertTrue(r.headers["Location"].endswith("/login"))

    def test_foto_inexistente_da_404(self):
        self.assertEqual(self.c.get("/fotos/99999").status_code, 404)
        self.assertEqual(self.c.get("/fotos/99999/miniatura").status_code, 404)

    def test_nao_da_para_acessar_a_pasta_de_fotos_pela_internet(self):
        self.cadastrar_e_pegar_id()
        nome = self.arquivos_no_disco()[0]
        for caminho in (f"/static/{nome}", f"/static/../fotos/{nome}", f"/fotos/{nome}"):
            self.assertEqual(self.c.get(caminho).status_code, 404, caminho)


class FotosComCsrfTest(BaseTest):
    csrf = True

    def test_envio_com_arquivo_e_token_funciona_e_sem_token_nao_grava(self):
        c = self.funcionario()
        sem_token = c.post("/veiculos", data={**DADOS, "fotos": [foto()]}, content_type="multipart/form-data")
        self.assertEqual(sem_token.status_code, 302)
        self.assertEqual(self.total_veiculos(), 0)
        self.assertEqual(os.listdir(oficina.PASTA_FOTOS), [])
        token = re.search(rb'name="csrf_token" value="([^"]+)"', c.get("/").data).group(1).decode()
        com_token = c.post("/veiculos", data={**DADOS, "csrf_token": token, "fotos": [foto()]},
                           content_type="multipart/form-data")
        self.assertEqual(com_token.status_code, 302)
        self.assertEqual(self.total_veiculos(), 1)
        self.assertEqual(len(self.sql("SELECT * FROM fotos")), 1)


if __name__ == "__main__":
    unittest.main()
