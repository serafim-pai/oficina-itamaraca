"""Testes da comissão por profissional (só o dono).
Rodar na pasta do projeto:  python -m unittest discover tests -v"""
import unittest

from base import oficina
from test_fotos_entrega import Base


class PercentualTest(unittest.TestCase):
    def test_interpretar_percentual(self):
        for texto, esperado in (("30", 3000), ("12,5", 1250), ("7.25%", 725), (" 100 ", 10000), ("0,01", 1),
                                ("30 %", 3000), ("5,", None), ("0", None), ("101", None), ("abc", None), ("", None),
                                ("-5", None), ("1.234", None), ("10,555", None), ("1,2,3", None)):
            self.assertEqual(oficina.interpretar_percentual(texto), esperado, texto)

    def test_texto_percentual(self):
        self.assertEqual(oficina.texto_percentual(3000), "30%")
        self.assertEqual(oficina.texto_percentual(1250), "12,5%")
        self.assertEqual(oficina.texto_percentual(725), "7,25%")
        self.assertEqual(oficina.texto_percentual(10000), "100%")
        self.assertEqual(oficina.texto_percentual(None), "-")

    def test_comissao_arredonda_ao_centavo(self):
        self.assertEqual(oficina.comissao_centavos(15000, 3000), 4500)
        self.assertEqual(oficina.comissao_centavos(333, 3333), 111)
        self.assertEqual(oficina.comissao_centavos(10001, 3000), 3000)    # 3000,3 centavos
        self.assertEqual(oficina.comissao_centavos(10002, 2500), 2501)    # 2500,5 sobe


class ComissaoBase(Base):
    def novo_profissional(self, nome="CARLOS", percentual="30", cliente=None):
        (cliente or self.dono_c).post("/profissionais", data={"nome": nome, "percentual": percentual})
        return self.sql("SELECT id FROM profissionais WHERE nome = ?", (nome,))[0]["id"]

    def escolher(self, profissional_id, cliente=None, vid=None, sid=None):
        return (cliente or self.dono_c).post(
            f"/veiculos/{vid or self.vid}/servicos/{sid or self.sid}/profissional",
            data={"profissional_id": "" if profissional_id is None else str(profissional_id)})

    def pagina_comissoes(self, mes=None, cliente=None):
        return (cliente or self.dono_c).get("/comissoes" + (f"?mes={mes}" if mes else "")).data.decode()


class ProfissionaisTest(ComissaoBase):
    def test_funcionario_nao_acessa_nada_de_comissao(self):
        pid = self.novo_profissional()
        self.assertEqual(self.func.get("/profissionais").status_code, 403)
        self.assertEqual(self.func.get("/comissoes").status_code, 403)
        self.assertEqual(self.func.post("/profissionais", data={"nome": "X", "percentual": "10"}).status_code, 403)
        self.assertEqual(self.func.post(f"/profissionais/{pid}/editar", data={"nome": "X", "percentual": "10"}).status_code, 403)
        self.assertEqual(self.func.post(f"/profissionais/{pid}/ativo").status_code, 403)
        self.assertEqual(self.escolher(pid, cliente=self.func).status_code, 403)
        ficha = self.pagina(cliente=self.func)
        self.assertNotIn("Executado por", ficha)
        self.assertNotIn("/comissoes", ficha)
        self.assertNotIn("/profissionais", ficha)

    def test_dono_ve_menu_e_cadastra_com_o_nome_em_maiusculas(self):
        pagina_inicial = self.pagina()
        self.assertIn("👷 Profissionais", pagina_inicial)
        self.assertNotIn("👷 Comissões", pagina_inicial)
        resposta = self.dono_c.post("/profissionais", data={"nome": "  Carlos   Silva ", "percentual": "12,5"})
        self.assertEqual(resposta.status_code, 302)
        p = self.sql("SELECT * FROM profissionais")[0]
        self.assertEqual((p["nome"], p["percentual_bp"], p["ativo"]), ("CARLOS SILVA", 1250, 1))
        pagina = self.dono_c.get("/profissionais").data.decode()
        self.assertIn("CARLOS SILVA", pagina)
        self.assertIn('value="12,5"', pagina)
        self.assertIn("Ver as comissões do mês", pagina)

    def test_editar_tambem_deixa_o_nome_em_maiusculas(self):
        pid = self.novo_profissional("CARLOS", "30")
        self.dono_c.post(f"/profissionais/{pid}/editar", data={"nome": "carlos alberto", "percentual": "30"})
        self.assertEqual(self.sql("SELECT nome FROM profissionais")[0]["nome"], "CARLOS ALBERTO")

    def test_nome_em_minusculas_que_ja_existia_vira_maiusculas_ao_iniciar(self):
        self.sql("INSERT INTO profissionais (nome, percentual_bp) VALUES ('mecânico modelo', 3000)")
        with oficina.app.app_context():
            oficina.init_db()
        self.assertEqual(self.sql("SELECT nome FROM profissionais")[0]["nome"], "MECÂNICO MODELO")

    def test_cadastro_invalido(self):
        self.novo_profissional("CARLOS")
        casos = (({"nome": "", "percentual": "30"}, "Escreva o nome"),
                 ({"nome": "x" * 61, "percentual": "30"}, "no máximo 60"),
                 ({"nome": "carlos", "percentual": "30"}, "Já existe"),
                 ({"nome": "JOAO", "percentual": "0"}, "percentual de comissão"),
                 ({"nome": "JOAO", "percentual": "abc"}, "percentual de comissão"),
                 ({"nome": "JOAO", "percentual": "150"}, "percentual de comissão"))
        for dados, trecho in casos:
            self.assertIn(trecho, self.dono_c.post("/profissionais", data=dados).data.decode())
        self.assertEqual(len(self.sql("SELECT * FROM profissionais")), 1)

    def test_editar_nome_e_percentual(self):
        pid = self.novo_profissional("CARLOS", "30")
        self.novo_profissional("JOAO", "20")
        self.dono_c.post(f"/profissionais/{pid}/editar", data={"nome": "CARLOS SILVA", "percentual": "35"})
        p = self.sql("SELECT * FROM profissionais WHERE id = ?", (pid,))[0]
        self.assertEqual((p["nome"], p["percentual_bp"]), ("CARLOS SILVA", 3500))
        self.assertIn("Já existe", self.dono_c.post(f"/profissionais/{pid}/editar",
                                                    data={"nome": "joao", "percentual": "35"}).data.decode())
        self.assertIn("percentual", self.dono_c.post(f"/profissionais/{pid}/editar",
                                                     data={"nome": "CARLOS SILVA", "percentual": "0"}).data.decode())
        self.assertEqual(self.sql("SELECT percentual_bp FROM profissionais WHERE id = ?", (pid,))[0][0], 3500)
        self.assertEqual(self.dono_c.post("/profissionais/99999/editar", data={"nome": "X", "percentual": "1"}).status_code, 404)

    def test_ativar_e_desativar(self):
        pid = self.novo_profissional()
        self.dono_c.post(f"/profissionais/{pid}/ativo")
        self.assertEqual(self.sql("SELECT ativo FROM profissionais")[0]["ativo"], 0)
        self.assertNotIn("CARLOS</option>", self.pagina())
        self.dono_c.post(f"/profissionais/{pid}/ativo")
        self.assertIn("CARLOS</option>", self.pagina())
        self.assertEqual(self.dono_c.post("/profissionais/99999/ativo").status_code, 404)


class EscolherProfissionalTest(ComissaoBase):
    def do_servico(self):
        return self.sql("SELECT profissional_id FROM servicos WHERE id = ?", (self.sid,))[0]["profissional_id"]

    def test_dono_escolhe_e_tira(self):
        pid = self.novo_profissional()
        self.assertEqual(self.escolher(pid).status_code, 302)
        self.assertEqual(self.do_servico(), pid)
        self.assertIn(f'<option value="{pid}" selected>CARLOS</option>', self.pagina())
        self.escolher(None)
        self.assertIsNone(self.do_servico())

    def test_profissional_invalido_ou_inativo_e_recusado(self):
        pid = self.novo_profissional()
        self.assertIn("Escolha um profissional da lista", self.escolher(99999).data.decode())
        self.assertIn("Escolha um profissional da lista", self.dono_c.post(
            f"/veiculos/{self.vid}/servicos/{self.sid}/profissional", data={"profissional_id": "abc"}).data.decode())
        self.dono_c.post(f"/profissionais/{pid}/ativo")
        self.assertIn("Escolha um profissional da lista", self.escolher(pid).data.decode())
        self.assertIsNone(self.do_servico())

    def test_quem_ja_estava_no_servico_continua_mesmo_ficando_inativo(self):
        pid = self.novo_profissional()
        self.escolher(pid)
        self.dono_c.post(f"/profissionais/{pid}/ativo")
        self.assertIn("CARLOS (inativo)", self.pagina())
        self.assertEqual(self.escolher(pid).status_code, 302)

    def test_servico_de_outra_ficha_da_404(self):
        pid = self.novo_profissional()
        outro = self.novo_veiculo("XYZ9K88")
        self.assertEqual(self.escolher(pid, vid=outro).status_code, 404)

    def test_depois_da_entrega_fica_travado(self):
        pid = self.novo_profissional()
        self.escolher(pid)
        self.fechar()
        outro = self.novo_profissional("JOAO", "10")
        resposta = self.escolher(outro)
        self.assertNotEqual(resposta.status_code, 302)
        self.assertEqual(self.do_servico(), pid)
        pagina = self.pagina()
        self.assertIn("CARLOS", pagina)
        self.assertNotIn('name="profissional_id"', pagina)


class ComissoesDoMesTest(ComissaoBase):
    def test_comissao_sobre_a_mao_de_obra_com_o_percentual_da_entrega(self):
        pid = self.novo_profissional("CARLOS", "30")
        self.escolher(pid)
        self.fechar()
        item = self.sql("SELECT * FROM entrega_itens")[0]
        self.assertEqual((item["profissional_id"], item["profissional_nome"], item["comissao_bp"]), (pid, "CARLOS", 3000))
        pagina = self.pagina_comissoes()
        self.assertIn("Comissões de outubro de 2026", pagina)
        self.assertIn("<strong>R$ 45,00</strong>", pagina)
        self.assertIn("R$ 150,00", pagina)
        self.assertIn("30%", pagina)
        self.assertIn("ABC1D23", pagina)

    def test_mudar_o_percentual_nao_altera_o_que_ja_foi_entregue(self):
        pid = self.novo_profissional("CARLOS", "30")
        self.escolher(pid)
        self.fechar()
        self.dono_c.post(f"/profissionais/{pid}/editar", data={"nome": "CARLOS", "percentual": "50"})
        pagina = self.pagina_comissoes()
        self.assertIn("<strong>R$ 45,00</strong>", pagina)
        self.assertNotIn("R$ 75,00", pagina)

    def test_nome_guardado_na_entrega_mesmo_se_o_profissional_mudar_de_nome(self):
        pid = self.novo_profissional("CARLOS", "30")
        self.escolher(pid)
        self.fechar()
        self.dono_c.post(f"/profissionais/{pid}/editar", data={"nome": "CARLOS ALBERTO", "percentual": "30"})
        pagina = self.pagina_comissoes()
        self.assertIn("<td>CARLOS</td>", pagina)

    def test_peca_nao_entra_na_base_da_comissao(self):
        pid = self.novo_profissional("CARLOS", "30")
        self.escolher(pid)
        self.fechar()
        self.sql("UPDATE entrega_itens SET pecas_centavos = 5000")
        pagina = self.pagina_comissoes()
        self.assertIn("<strong>R$ 45,00</strong>", pagina)      # 30% de 150,00; as peças (50,00) ficam fora

    def test_servico_entregue_sem_profissional_aparece_em_separado_e_nao_gera_comissao(self):
        self.fechar()
        pagina = self.pagina_comissoes()
        self.assertIn("Serviços entregues sem profissional", pagina)
        self.assertIn("ABC1D23", pagina)
        self.assertIn("Nenhum serviço com profissional foi entregue neste mês", pagina)

    def test_outro_mes_nao_conta(self):
        pid = self.novo_profissional()
        self.escolher(pid)
        self.fechar()
        pagina = self.pagina_comissoes("2026-09")
        self.assertIn("setembro de 2026", pagina)
        self.assertIn("Nenhum serviço com profissional foi entregue neste mês", pagina)

    def test_mes_invalido_vira_o_atual_e_navegacao_passa_de_ano(self):
        self.assertIn("outubro de 2026", self.pagina_comissoes("abc"))
        self.assertIn("mes=2025-12", self.pagina_comissoes("2026-01"))
        self.assertIn("mes=2027-01", self.pagina_comissoes("2026-12"))

    def test_previsto_usa_o_percentual_de_hoje_e_sai_quando_entrega(self):
        pid = self.novo_profissional("CARLOS", "30")
        self.escolher(pid)
        pagina = self.pagina_comissoes()
        self.assertIn("Comissão prevista", pagina)
        self.assertIn("Total previsto</td><td class=\"num\">R$ 45,00", pagina)
        self.dono_c.post(f"/profissionais/{pid}/editar", data={"nome": "CARLOS", "percentual": "40"})
        self.assertIn("Total previsto</td><td class=\"num\">R$ 60,00", self.pagina_comissoes())
        self.fechar()
        self.assertIn("Nenhum serviço em andamento com profissional", self.pagina_comissoes())

    def test_servico_sem_valor_ou_sem_profissional_nao_entra_no_previsto(self):
        self.assertIn("Nenhum serviço em andamento com profissional", self.pagina_comissoes())
        pid = self.novo_profissional()
        self.func.post(f"/veiculos/{self.vid}/servicos", data={"tipo": "FREIOS", "problema": "Disco gasto"})
        novo = self.sql("SELECT MAX(id) AS id FROM servicos")[0]["id"]
        self.escolher(pid, sid=novo)       # sem valor ainda
        self.assertIn("Nenhum serviço em andamento com profissional", self.pagina_comissoes())

    def test_dois_profissionais_em_ordem_de_comissao(self):
        a = self.novo_profissional("CARLOS", "10")
        b = self.novo_profissional("JOAO", "30")
        self.func.post(f"/veiculos/{self.vid}/servicos", data={"tipo": "FREIOS", "problema": "Disco gasto"})
        s2 = self.sql("SELECT MAX(id) AS id FROM servicos")[0]["id"]
        self.sql("UPDATE servicos SET valor_centavos = 20000 WHERE id = ?", (s2,))
        self.dono_c.post(f"/veiculos/{self.vid}/aprovacao",
                         data={"decisao": "APROVADO", "forma": "TELEFONE", "assinatura": self.assinatura(self.vid)})
        self.dono_c.post(f"/veiculos/{self.vid}/servicos/{s2}/garantia", data={"valor": "30", "unidade": "DIAS"})
        self.escolher(a)
        self.escolher(b, sid=s2)
        self.fechar()
        pagina = self.pagina_comissoes()
        self.assertLess(pagina.index("JOAO"), pagina.index("CARLOS"))     # R$ 60,00 antes de R$ 15,00
        self.assertIn("<strong>R$ 60,00</strong>", pagina)
        self.assertIn("<strong>R$ 15,00</strong>", pagina)
        self.assertIn("R$ 75,00", pagina)

    def test_entrega_antiga_sem_profissional_registrado_vai_para_sem_profissional(self):
        self.fechar()
        self.sql("UPDATE entrega_itens SET profissional_id = NULL, profissional_nome = NULL, comissao_bp = NULL")
        self.assertIn("Serviços entregues sem profissional", self.pagina_comissoes())


if __name__ == "__main__":
    unittest.main()
