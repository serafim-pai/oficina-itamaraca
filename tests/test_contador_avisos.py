"""Testes do número de avisos pendentes no menu.
Rodar na pasta do projeto:  python -m unittest discover tests -v"""
import unittest
from datetime import date

from base import oficina
from test_fotos_entrega import Base


class ContadorNoMenuTest(Base):
    def menu(self, cliente=None, caminho="/"):
        pagina = (cliente or self.dono_c).get(caminho).data.decode()
        return pagina.split("</nav>")[0]

    def test_sem_avisos_o_menu_nao_mostra_numero(self):
        menu = self.menu()
        self.assertIn("📣 Avisos", menu)
        self.assertNotIn("contador-menu", menu)

    def test_com_aviso_o_menu_mostra_o_numero_para_dono_e_funcionario(self):
        self.sql("UPDATE veiculos SET data_nascimento = '1985-10-15' WHERE id = ?", (self.vid,))
        for cliente in (self.dono_c, self.func):
            menu = self.menu(cliente)
            self.assertIn('<span class="contador-menu" title="Clientes para avisar">1</span>', menu)

    def test_numero_aparece_em_qualquer_tela(self):
        self.sql("UPDATE veiculos SET data_nascimento = '1985-10-15' WHERE id = ?", (self.vid,))
        for caminho in ("/", f"/veiculos/{self.vid}", "/estoque", "/avisos"):
            self.assertIn('contador-menu', self.menu(caminho=caminho), caminho)

    def test_conta_todos_os_tipos_de_aviso(self):
        self.fechar()
        self.sql("UPDATE entrega_itens SET garantia_ate = '2026-10-25'")      # garantia vencendo
        self.sql("UPDATE veiculos SET data_nascimento = '1985-10-15' WHERE id = ?", (self.vid,))   # aniversário
        self.assertIn('title="Clientes para avisar">2</span>', self.menu())

    def test_numero_cai_depois_do_avisei_e_volta_depois_do_desfazer(self):
        self.sql("UPDATE veiculos SET data_nascimento = '1985-10-15' WHERE id = ?", (self.vid,))
        self.func.post(f"/veiculos/{self.vid}/avisos", data={"tipo": "ANIVERSARIO"})
        self.assertNotIn("contador-menu", self.menu())
        aviso = self.sql("SELECT id FROM avisos")[0]["id"]
        self.dono_c.post(f"/veiculos/{self.vid}/avisos/{aviso}/desfazer")
        self.assertIn("contador-menu", self.menu())

    def test_numero_acompanha_a_data(self):
        self.sql("UPDATE veiculos SET data_nascimento = '1985-11-15' WHERE id = ?", (self.vid,))
        self.assertNotIn("contador-menu", self.menu())
        oficina.hoje_brasil = lambda agora_utc=None: date(2026, 11, 2)
        self.assertIn("contador-menu", self.menu())

    def test_tela_de_login_continua_sem_menu_nem_erro(self):
        resposta = oficina.app.test_client().get("/login")
        self.assertEqual(resposta.status_code, 200)
        self.assertNotIn("contador-menu", resposta.data.decode())

    def test_se_o_calculo_falhar_a_pagina_nao_quebra(self):
        original = oficina.montar_avisos
        oficina.montar_avisos = lambda *a, **k: 1 / 0
        self.addCleanup(setattr, oficina, "montar_avisos", original)
        resposta = self.dono_c.get("/")
        self.assertEqual(resposta.status_code, 200)
        self.assertNotIn("contador-menu", resposta.data.decode().split("</nav>")[0])


if __name__ == "__main__":
    unittest.main()
