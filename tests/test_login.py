"""Testes do login, dos usuários e da proteção das telas.
Rodar na pasta do projeto:  python -m unittest discover tests -v"""
import os
import re
import unittest

from base import BaseTest, SENHA, oficina

DADOS_VEICULO = {"placa": "ABC1D23", "documento_deixado": "on"}


def vai_para(resposta, caminho):
    return resposta.status_code == 302 and resposta.headers["Location"].split("?")[0].endswith(caminho)


class PrimeiroAcessoTest(BaseTest):
    def test_sistema_sem_usuarios_manda_criar_o_dono(self):
        self.assertTrue(vai_para(self.c.get("/"), "/primeiro-acesso"))
        self.assertTrue(vai_para(self.c.get("/login"), "/primeiro-acesso"))
        self.assertEqual(self.c.get("/primeiro-acesso").status_code, 200)

    def test_cria_o_dono_com_senha_protegida_e_ja_entra(self):
        r = self.c.post("/primeiro-acesso", data={"nome": "dona maria", "email": "Dona@Oficina.com",
                                                   "senha": SENHA, "senha2": SENHA})
        self.assertTrue(vai_para(r, "/"))
        usuario = self.sql("SELECT * FROM usuarios")[0]
        self.assertEqual((usuario["nome"], usuario["email"], usuario["tipo"]),
                         ("DONA MARIA", "dona@oficina.com", "DONO"))
        self.assertNotIn(SENHA, usuario["senha_hash"])           # a senha nunca fica "aberta"
        self.assertTrue(usuario["senha_hash"].startswith("pbkdf2:"))
        self.assertEqual(self.c.get("/").status_code, 200)       # já está logado

    def test_so_funciona_uma_vez(self):
        self.criar_usuario("dono@teste.com", "DONO")
        self.assertTrue(vai_para(self.c.get("/primeiro-acesso"), "/login"))
        r = self.c.post("/primeiro-acesso", data={"nome": "INTRUSO", "email": "x@x.com",
                                                   "senha": SENHA, "senha2": SENHA})
        self.assertTrue(vai_para(r, "/login"))
        self.assertEqual(len(self.sql("SELECT * FROM usuarios")), 1)

    def test_recusa_senhas_diferentes_ou_curtas(self):
        for senha, senha2, trecho in [(SENHA, "outra-senha", "não são iguais"), ("curta", "curta", "8 caracteres")]:
            r = self.c.post("/primeiro-acesso", data={"nome": "MARIA", "email": "m@m.com",
                                                       "senha": senha, "senha2": senha2})
            self.assertIn(trecho.encode(), r.data)
        self.assertEqual(self.sql("SELECT * FROM usuarios"), [])

    def test_codigo_de_instalacao(self):
        os.environ["OFICINA_CODIGO_INICIAL"] = "codigo-secreto"
        self.addCleanup(os.environ.pop, "OFICINA_CODIGO_INICIAL", None)
        dados = {"nome": "MARIA", "email": "m@m.com", "senha": SENHA, "senha2": SENHA}
        self.assertIn(b"digo de instala", self.c.get("/primeiro-acesso").data)   # o campo aparece
        r = self.c.post("/primeiro-acesso", data={**dados, "codigo": "errado"})
        self.assertIn("Código de instalação errado".encode(), r.data)
        self.assertEqual(self.sql("SELECT * FROM usuarios"), [])
        r = self.c.post("/primeiro-acesso", data={**dados, "codigo": "codigo-secreto"})
        self.assertTrue(vai_para(r, "/"))
        self.assertEqual(len(self.sql("SELECT * FROM usuarios")), 1)


class LoginTest(BaseTest):
    def setUp(self):
        super().setUp()
        self.criar_usuario("func@teste.com", "FUNCIONARIO")

    def entrar(self, email="func@teste.com", senha=SENHA):
        return self.c.post("/login", data={"email": email, "senha": senha})

    def test_login_certo(self):
        self.assertTrue(vai_para(self.entrar("  FUNC@teste.com "), "/"))   # maiúsculas e espaços não atrapalham
        self.assertEqual(self.c.get("/").status_code, 200)

    def test_cookie_de_sessao_e_proprio_e_protegido(self):
        cookies = self.entrar().headers.get_all("Set-Cookie")
        self.assertEqual(len(cookies), 1)
        self.assertTrue(cookies[0].startswith("oficina_sessao="), cookies[0])   # não usa o "session" do varejo
        self.assertIn("HttpOnly", cookies[0])
        self.assertIn("SameSite=Lax", cookies[0])

    def test_senha_errada_e_email_inexistente_dao_a_mesma_mensagem(self):
        a = self.entrar(senha="errada123")
        b = self.entrar(email="ninguem@teste.com")
        self.assertIn(b"E-mail ou senha errados", a.data)
        self.assertIn(b"E-mail ou senha errados", b.data)
        self.assertTrue(vai_para(self.c.get("/"), "/login"))

    def test_cinco_erros_bloqueiam_ate_com_a_senha_certa(self):
        for _ in range(5):
            self.entrar(senha="errada123")
        r = self.entrar()
        self.assertIn(b"Muitas tentativas", r.data)
        self.assertTrue(vai_para(self.c.get("/"), "/login"))

    def test_bloqueio_passa_depois_de_10_minutos(self):
        for _ in range(5):
            self.entrar(senha="errada123")
        self.sql("UPDATE tentativas_login SET quando = datetime('now', '-11 minutes')")
        self.assertTrue(vai_para(self.entrar(), "/"))

    def test_bloqueio_de_um_email_nao_pega_os_outros(self):
        self.criar_usuario("outro@teste.com")
        for _ in range(5):
            self.entrar(senha="errada123")
        self.assertTrue(vai_para(self.entrar("outro@teste.com"), "/"))

    def test_acerto_zera_as_tentativas(self):
        for _ in range(4):
            self.entrar(senha="errada123")
        self.entrar()
        self.assertEqual(self.sql("SELECT * FROM tentativas_login"), [])

    def test_usuario_bloqueado_nao_entra(self):
        self.criar_usuario("bloq@teste.com", ativo=0)
        self.assertIn(b"est\xc3\xa1 bloqueado", self.entrar("bloq@teste.com").data)

    def test_quem_foi_bloqueado_perde_a_sessao_na_hora(self):
        self.entrar()
        self.assertEqual(self.c.get("/").status_code, 200)
        self.sql("UPDATE usuarios SET ativo = 0")
        self.assertTrue(vai_para(self.c.get("/"), "/login"))

    def test_sair_so_por_formulario(self):
        self.entrar()
        self.assertEqual(self.c.get("/sair").status_code, 405)
        self.assertTrue(vai_para(self.c.post("/sair"), "/login"))
        self.assertTrue(vai_para(self.c.get("/"), "/login"))


class ProtecaoDasTelasTest(BaseTest):
    def setUp(self):
        super().setUp()
        self.dono_id = self.criar_usuario("dono@teste.com", "DONO")

    def test_sem_login_nada_abre_e_nada_grava(self):
        self.assertTrue(vai_para(self.c.get("/"), "/login"))
        self.assertTrue(vai_para(self.c.get("/usuarios"), "/login"))
        self.assertTrue(vai_para(self.c.post("/veiculos", data=DADOS_VEICULO), "/login"))
        self.assertEqual(self.total_veiculos(), 0)

    def test_funcionario_nao_mexe_em_usuarios(self):
        c = self.funcionario()
        self.assertEqual(c.get("/usuarios").status_code, 403)
        self.assertEqual(c.post("/usuarios", data={"nome": "X", "email": "x@x.com", "senha": SENHA}).status_code, 403)
        self.assertEqual(c.post("/usuarios/1/alternar").status_code, 403)
        self.assertNotIn("Usuários".encode(), c.get("/").data)

    def test_dono_ve_o_menu_de_usuarios(self):
        self.assertIn("Usuários".encode(), self.entrar_como(self.dono_id).get("/").data)

    def test_cookie_proprio_nao_briga_com_o_varejo(self):
        c = self.entrar_como(self.dono_id)
        cabecalho = c.get("/").headers.get_all("Set-Cookie")
        cookie = " ".join(cabecalho) if cabecalho else ""
        # (a sessão já existe, então só confere a configuração)
        self.assertEqual(oficina.app.config["SESSION_COOKIE_NAME"], "oficina_sessao")
        self.assertEqual(oficina.app.config["SESSION_COOKIE_SAMESITE"], "Lax")
        self.assertTrue(oficina.app.config["SESSION_COOKIE_HTTPONLY"])
        self.assertNotIn("session=", cookie)


class UsuariosTest(BaseTest):
    def setUp(self):
        super().setUp()
        self.c = self.dono()
        self.novo = {"nome": "joao mecanico", "email": "Joao@Oficina.com", "senha": SENHA, "tipo": "FUNCIONARIO"}

    def test_dono_cria_funcionario_que_consegue_entrar(self):
        self.assertTrue(vai_para(self.c.post("/usuarios", data=self.novo), "/usuarios"))
        criado = self.sql("SELECT * FROM usuarios WHERE email = 'joao@oficina.com'")[0]
        self.assertEqual((criado["nome"], criado["tipo"], criado["ativo"]), ("JOAO MECANICO", "FUNCIONARIO", 1))
        self.assertNotIn(SENHA, criado["senha_hash"])
        outro = oficina.app.test_client()
        self.assertTrue(vai_para(outro.post("/login", data={"email": "joao@oficina.com", "senha": SENHA}), "/"))

    def test_recusa_dados_ruins(self):
        casos = [({"senha": "curta"}, "8 caracteres"), ({"email": "sem-arroba"}, "e-mail válido"),
                 ({"nome": "1"}, "nome do usuário"), ({"tipo": "CHEFE"}, "Escolha o tipo"),
                 ({"email": "dono@teste.com"}, "Já existe")]
        for mudanca, trecho in casos:
            r = self.c.post("/usuarios", data={**self.novo, **mudanca})
            self.assertIn(trecho.encode(), r.data, mudanca)
        self.assertEqual(len(self.sql("SELECT * FROM usuarios")), 1)

    def test_bloquear_e_desbloquear(self):
        outro = self.criar_usuario("func@teste.com")
        self.c.post(f"/usuarios/{outro}/alternar")
        self.assertEqual(self.sql("SELECT ativo FROM usuarios WHERE id = ?", (outro,))[0]["ativo"], 0)
        self.c.post(f"/usuarios/{outro}/alternar")
        self.assertEqual(self.sql("SELECT ativo FROM usuarios WHERE id = ?", (outro,))[0]["ativo"], 1)

    def test_dono_nao_bloqueia_a_si_mesmo(self):
        self.assertEqual(self.c.post(f"/usuarios/{self.dono_id}/alternar").status_code, 400)
        self.assertEqual(self.sql("SELECT ativo FROM usuarios WHERE id = ?", (self.dono_id,))[0]["ativo"], 1)

    def test_nome_com_html_aparece_como_texto(self):
        self.criar_usuario("xss@teste.com", nome="<script>alert(1)</script>")
        self.assertNotIn(b"<script>alert(1)</script>", self.c.get("/usuarios").data)


class CsrfTest(BaseTest):
    csrf = True

    def token(self, cliente, caminho="/login"):
        return re.search(rb'name="csrf_token" value="([^"]+)"', cliente.get(caminho).data).group(1).decode()

    def test_login_sem_token_e_recusado(self):
        self.criar_usuario("func@teste.com")
        r = self.c.post("/login", data={"email": "func@teste.com", "senha": SENHA})
        self.assertTrue(vai_para(r, "/login"))
        self.assertTrue(vai_para(self.c.get("/"), "/login"))     # não entrou

    def test_login_com_token_funciona(self):
        self.criar_usuario("func@teste.com")
        r = self.c.post("/login", data={"email": "func@teste.com", "senha": SENHA, "csrf_token": self.token(self.c)})
        self.assertTrue(vai_para(r, "/"))
        self.assertEqual(self.c.get("/").status_code, 200)

    def test_cadastro_de_veiculo_sem_token_nao_grava(self):
        c = self.funcionario()
        r = c.post("/veiculos", data=DADOS_VEICULO)
        self.assertTrue(vai_para(r, "/login"))
        self.assertEqual(self.total_veiculos(), 0)

    def test_cadastro_de_veiculo_com_token_grava(self):
        c = self.funcionario()
        r = c.post("/veiculos", data={**DADOS_VEICULO, "csrf_token": self.token(c, "/")})
        self.assertTrue(vai_para(r, "/veiculos/1"))
        self.assertEqual(self.total_veiculos(), 1)

    def test_sair_sem_token_nao_desloga(self):
        c = self.funcionario()
        c.post("/sair")
        self.assertEqual(c.get("/").status_code, 200)


if __name__ == "__main__":
    unittest.main()
