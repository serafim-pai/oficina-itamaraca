"""Testes de arquivar e desarquivar fichas (só o dono).
Rodar na pasta do projeto:  python -m unittest discover tests -v"""
import unittest

from test_fotos_entrega import Base

MOTIVO = "Cliente desistiu do conserto"


class ArquivarTest(Base):
    def arquivar(self, cliente=None, motivo=MOTIVO, vid=None):
        return (cliente or self.dono_c).post(f"/veiculos/{vid or self.vid}/arquivar", data={"motivo": motivo})

    def desarquivar(self, cliente=None, vid=None):
        return (cliente or self.dono_c).post(f"/veiculos/{vid or self.vid}/desarquivar")

    def lista(self, query="", cliente=None):
        return (cliente or self.dono_c).get("/" + query).data.decode()

    def link(self, vid=None):
        return f'href="/veiculos/{vid or self.vid}"'

    def estado(self, vid=None):
        return self.sql("SELECT arquivado FROM veiculos WHERE id = ?", (vid or self.vid,))[0]["arquivado"]

    def test_funcionario_nao_arquiva_nem_ve_o_botao(self):
        self.assertEqual(self.arquivar(cliente=self.func).status_code, 403)
        self.assertEqual(self.estado(), 0)
        self.assertNotIn("Arquivar esta ficha", self.pagina(cliente=self.func))
        self.assertIn("Arquivar esta ficha", self.pagina(cliente=self.dono_c))

    def test_sem_motivo_nao_arquiva(self):
        resposta = self.arquivar(motivo="  1 ")
        self.assertIn("Explique o motivo de arquivar a ficha", resposta.data.decode())
        self.assertEqual(self.estado(), 0)

    def test_motivo_grande_demais_nao_arquiva(self):
        self.arquivar(motivo="a" * 301)
        self.assertEqual(self.estado(), 0)

    def test_arquivar_tira_da_lista_e_vai_para_arquivadas(self):
        resposta = self.arquivar()
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(self.estado(), 1)
        principal = self.lista()
        self.assertNotIn(self.link(), principal)
        self.assertIn("Ver arquivadas (1)", principal)
        self.assertIn("arquivada. Para vê-la", self.lista("?arquivado=ABC1D23"))
        arquivadas = self.lista("?arquivadas=1")
        self.assertIn(self.link(), arquivadas)
        self.assertIn("Fichas arquivadas", arquivadas)
        registro = self.sql("SELECT * FROM arquivamentos")
        self.assertEqual([(r["veiculo_id"], r["acao"], r["motivo"], r["feito_por"]) for r in registro],
                         [(self.vid, "ARQUIVADA", MOTIVO, "DONA MARIA")])

    def test_sem_arquivadas_nao_mostra_o_link(self):
        self.assertNotIn("Ver arquivadas", self.lista())

    def test_lista_de_arquivadas_vazia(self):
        self.assertIn("Nenhuma ficha arquivada.", self.lista("?arquivadas=1"))

    def test_ficha_arquivada_mostra_aviso_com_motivo_e_so_o_dono_desarquiva(self):
        self.arquivar()
        for cliente in (self.dono_c, self.func):
            pagina = self.pagina(cliente=cliente)
            self.assertIn("Ficha arquivada", pagina)
            self.assertIn(MOTIVO, pagina)
            self.assertIn("DONA MARIA", pagina)
        self.assertIn("Desarquivar", self.pagina(cliente=self.dono_c))
        self.assertNotIn("Desarquivar", self.pagina(cliente=self.func))
        self.assertNotIn("Arquivar esta ficha", self.pagina(cliente=self.dono_c))

    def test_desarquivar_volta_para_a_lista_e_fica_registrado(self):
        self.arquivar()
        self.assertEqual(self.desarquivar(cliente=self.func).status_code, 403)
        self.assertEqual(self.estado(), 1)
        self.assertEqual(self.desarquivar().status_code, 302)
        self.assertEqual(self.estado(), 0)
        self.assertIn(self.link(), self.lista())
        self.assertNotIn("Ver arquivadas", self.lista())
        self.assertEqual([r["acao"] for r in self.sql("SELECT acao FROM arquivamentos ORDER BY id")],
                         ["ARQUIVADA", "DESARQUIVADA"])
        self.assertNotIn("Ficha arquivada", self.pagina())

    def test_arquivar_duas_vezes_avisa(self):
        self.arquivar()
        resposta = self.arquivar()
        self.assertIn("já está arquivada", resposta.data.decode())
        self.assertEqual(len(self.sql("SELECT * FROM arquivamentos")), 1)

    def test_desarquivar_ficha_que_nao_esta_arquivada_nao_registra_nada(self):
        self.desarquivar()
        self.assertEqual(self.sql("SELECT * FROM arquivamentos"), [])

    def test_busca_avisa_que_ha_arquivadas_que_combinam(self):
        self.arquivar()
        principal = self.lista("?q=ABC1D23")
        self.assertNotIn(self.link(), principal)
        self.assertIn("1 ficha arquivada também combina", principal)
        achada = self.lista("?arquivadas=1&q=abc-1d23")
        self.assertIn(self.link(), achada)
        self.assertNotIn("também combina", achada)

    def test_ficha_com_entrega_fechada_tambem_arquiva_e_o_relatorio_continua_contando(self):
        self.fechar()
        self.assertEqual(self.arquivar().status_code, 302)
        self.assertEqual(self.estado(), 1)
        relatorio = self.dono_c.get("/relatorio").data.decode()
        self.assertIn("R$ 150,00", relatorio)
        self.assertIn("<strong>1</strong> garantia vigente", relatorio)
        self.assertEqual(self.dono_c.get(f"/veiculos/{self.vid}/comprovante").status_code, 200)

    def test_historico_do_carro_marca_a_passagem_arquivada(self):
        self.arquivar()
        outro = self.novo_veiculo("ABC-1D23")
        self.assertIn("Arquivada", self.pagina(vid=outro))

    def test_excluir_ficha_arquivada_apaga_o_registro_de_arquivamento(self):
        self.arquivar()
        self.dono_c.post(f"/veiculos/{self.vid}/excluir", data={"motivo": "Cadastro de teste"})
        self.assertEqual(self.sql("SELECT * FROM veiculos WHERE id = ?", (self.vid,)), [])
        self.assertEqual(self.sql("SELECT * FROM arquivamentos"), [])

    def test_ficha_arquivada_continua_aceitando_trabalho(self):
        self.arquivar()
        resposta = self.func.post(f"/veiculos/{self.vid}/servicos", data={"tipo": "FREIOS", "problema": "Disco gasto"})
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(len(self.sql("SELECT * FROM servicos WHERE veiculo_id = ?", (self.vid,))), 2)


if __name__ == "__main__":
    unittest.main()
