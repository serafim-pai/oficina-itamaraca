"""Testes da lista "Avisos feitos" na ficha e do botão Desfazer (só o dono).
Rodar na pasta do projeto:  python -m unittest discover tests -v"""
import unittest
from datetime import date

from base import oficina
from test_fotos_entrega import Base


class AvisosFeitosTest(Base):
    def setUp(self):
        super().setUp()
        self.sql("UPDATE veiculos SET data_nascimento = '1985-10-15' WHERE id = ?", (self.vid,))

    def avisei(self, tipo="ANIVERSARIO", cliente=None, vid=None):
        return (cliente or self.func).post(f"/veiculos/{vid or self.vid}/avisos", data={"tipo": tipo})

    def desfazer(self, aviso_id, cliente=None, vid=None):
        return (cliente or self.dono_c).post(f"/veiculos/{vid or self.vid}/avisos/{aviso_id}/desfazer")

    def lista(self):
        return self.dono_c.get("/avisos").data.decode()

    def registros(self):
        return self.sql("SELECT * FROM avisos ORDER BY id")

    def test_sem_avisos_nao_mostra_o_bloco(self):
        self.assertNotIn("Avisos feitos", self.pagina())

    def test_ficha_mostra_o_aviso_feito_com_quem_e_quando(self):
        self.avisei()
        pagina = self.pagina()
        self.assertIn("Avisos feitos", pagina)
        self.assertIn("Aniversário de 2026", pagina)
        self.assertIn("(por ", pagina)

    def test_nomes_de_cada_tipo(self):
        for tipo, marca, texto in (("REVISAO", 6, "Revisão de 6 meses"), ("GARANTIA", 0, "Garantia vencendo"),
                                   ("NAO_AVISAR", 0, "Não avisar mais"), ("ANIVERSARIO", 2026, "Aniversário de 2026")):
            self.sql("INSERT INTO avisos (veiculo_id, tipo, marca_meses, feito_por) VALUES (?, ?, ?, 'T')",
                     (self.vid, tipo, marca))
            self.assertIn(texto, self.pagina())

    def test_so_o_dono_desfaz_funcionario_ve_a_lista_sem_o_botao(self):
        self.avisei()
        aviso = self.registros()[0]["id"]
        self.assertEqual(self.desfazer(aviso, cliente=self.func).status_code, 403)
        self.assertIsNone(self.registros()[0]["desfeito_em"])
        pagina = self.pagina(cliente=self.func)
        self.assertIn("Aniversário de 2026", pagina)
        self.assertNotIn("Desfazer", pagina.split("Avisos feitos")[1].split("<h2")[0])
        self.assertIn("Desfazer", self.pagina(cliente=self.dono_c).split("Avisos feitos")[1])

    def test_desfazer_devolve_o_cliente_para_a_lista_e_guarda_a_linha(self):
        self.avisei()
        self.assertNotIn("Aniversário</span>", self.lista())
        aviso = self.registros()[0]["id"]
        resposta = self.desfazer(aviso)
        self.assertEqual(resposta.status_code, 302)
        self.assertTrue(resposta.headers["Location"].endswith("#avisos-feitos"))
        registro = self.registros()[0]
        self.assertIsNotNone(registro["desfeito_em"])
        self.assertEqual(registro["desfeito_por"], "DONA MARIA")
        self.assertIn("Aniversário</span>", self.lista())
        pagina = self.pagina()
        self.assertIn("Desfeito por DONA MARIA", pagina)

    def test_nao_avisar_mais_desfeito_volta_a_avisar(self):
        self.avisei("NAO_AVISAR")
        self.assertNotIn("Aniversário</span>", self.lista())
        self.desfazer(self.registros()[0]["id"])
        self.assertIn("Aniversário</span>", self.lista())

    def test_pode_avisar_de_novo_depois_de_desfazer(self):
        self.avisei()
        self.desfazer(self.registros()[0]["id"])
        self.avisei()
        self.assertEqual(len(self.registros()), 2)
        self.assertNotIn("Aniversário</span>", self.lista())

    def test_desfazer_duas_vezes_ou_aviso_de_outra_ficha_ou_inexistente_da_404(self):
        outro = self.novo_veiculo("XYZ9K88")
        self.avisei()
        aviso = self.registros()[0]["id"]
        self.assertEqual(self.desfazer(aviso, vid=outro).status_code, 404)
        self.assertEqual(self.desfazer(99999).status_code, 404)
        self.assertEqual(self.desfazer(aviso).status_code, 302)
        self.assertEqual(self.desfazer(aviso).status_code, 404)

    def test_aviso_desfeito_de_revisao_volta_para_a_lista(self):
        self.fechar()
        self.sql("UPDATE entrega_itens SET garantia_ate = '2027-10-15'")
        oficina.hoje_brasil = lambda agora_utc=None: date(2027, 1, 15)
        self.avisei("REVISAO")
        self.assertNotIn("Revisão de 3 meses", self.lista())
        self.desfazer(self.registros()[0]["id"])
        self.assertIn("Revisão de 3 meses", self.lista())


if __name__ == "__main__":
    unittest.main()
