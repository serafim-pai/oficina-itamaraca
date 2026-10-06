"""Cabeçalhos de segurança em todas as respostas."""
from base import BaseTest


class CabecalhosTest(BaseTest):
    def confere(self, r, caminho):
        self.assertEqual(r.headers.get("X-Frame-Options"), "DENY", caminho)
        self.assertEqual(r.headers.get("X-Content-Type-Options"), "nosniff", caminho)
        self.assertEqual(r.headers.get("Referrer-Policy"), "same-origin", caminho)

    def test_login_e_paginas_de_quem_entrou(self):
        self.confere(self.c.get("/login"), "/login")
        dono = self.dono()
        for caminho in ("/", "/usuarios", "/limites-garantia"):
            self.confere(dono.get(caminho), caminho)

    def test_ate_o_redirecionamento_leva_os_cabecalhos(self):
        self.criar_usuario("a@teste.com")
        self.confere(self.c.get("/"), "/ sem login")
