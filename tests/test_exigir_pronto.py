"""A entrega só pode ser fechada com o veículo na etapa "Pronto para retirada".
Rodar na pasta do projeto:  python -m unittest discover tests -v"""
import unittest

import test_entrega
from test_entrega import CONDICOES
from base import foto_de_entrega


class ExigirProntoTest(test_entrega.EntregaBase):
    def setUp(self):
        super().setUp()
        self.definir_prazo(self.vid)
        self.garantias_ok()

    def fechar_sem_marcar(self):
        return self.dono_c.post(f"/veiculos/{self.vid}/entrega", content_type="multipart/form-data", data={
            "condicoes": CONDICOES, "assinatura": self.assinatura(), "fotos_entrega": foto_de_entrega()})

    def etapa(self, etapa):
        self.func.post(f"/veiculos/{self.vid}/etapa", data={"etapa": etapa})

    def test_em_aguardando_inicio_nao_fecha(self):
        r = self.fechar_sem_marcar()
        self.assertEqual(r.status_code, 200)
        self.assertIn("só pode ser fechada com o veículo na etapa".encode(), r.data)
        self.assertIn("Aguardando início".encode(), r.data)
        self.assertEqual(self.entregas(), [])

    def test_em_reparo_nao_fecha(self):
        self.etapa("EM_REPARO")
        r = self.fechar_sem_marcar()
        self.assertIn("Em reparo".encode(), r.data)
        self.assertEqual(self.entregas(), [])

    def test_pronto_fecha_normalmente(self):
        self.etapa("EM_REPARO")
        self.etapa("PRONTO")
        self.assertEqual(self.fechar_sem_marcar().status_code, 302)
        self.assertEqual(len(self.entregas()), 1)

    def test_voltar_de_pronto_para_reparo_bloqueia_de_novo(self):
        self.etapa("EM_REPARO")
        self.etapa("PRONTO")
        self.etapa("EM_REPARO")
        self.assertEqual(self.fechar_sem_marcar().status_code, 200)
        self.assertEqual(self.entregas(), [])

    def test_a_tela_avisa_e_desabilita_o_botao_ate_ficar_pronto(self):
        pagina = self.pagina()
        self.assertIn("A entrega só pode ser fechada quando ele", pagina)
        self.assertRegex(pagina, r"<button type=\"submit\" disabled>Fechar a entrega de hoje")
        self.etapa("EM_REPARO")
        self.etapa("PRONTO")
        pagina = self.pagina()
        self.assertNotIn("A entrega só pode ser fechada quando ele", pagina)
        self.assertNotRegex(pagina, r"<button type=\"submit\" disabled>Fechar a entrega de hoje")

    def test_depois_de_desfazer_a_entrega_o_veiculo_continua_pronto(self):
        self.etapa("EM_REPARO")
        self.etapa("PRONTO")
        self.assertEqual(self.fechar_sem_marcar().status_code, 302)
        self.dono_c.post(f"/veiculos/{self.vid}/entrega/desfazer", data={"motivo": "Cliente pediu uma correção"})
        self.assertEqual(self.fechar_sem_marcar().status_code, 302)

    def test_erro_de_etapa_aparece_junto_com_os_outros(self):
        self.sql("UPDATE servicos SET garantia_valor = NULL")
        r = self.fechar_sem_marcar()
        self.assertIn("etapa".encode(), r.data)
        self.assertIn("tempo de garantia".encode(), r.data)


if __name__ == "__main__":
    unittest.main()
