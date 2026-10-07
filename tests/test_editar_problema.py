"""Editar o tipo e a descrição de um problema registrado.
Rodar na pasta do projeto:  python -m unittest discover tests -v"""
import unittest

import test_entrega
from base import BaseTest

VEICULO = {"responsavel": "JOSE", "placa": "ABC1D23", "marca": "FIAT", "modelo": "UNO", "documento_deixado": "on"}


class EditarProblemaTest(BaseTest):
    def setUp(self):
        super().setUp()
        self.func = self.funcionario()
        self.dono_c = self.dono()
        self.func.post("/veiculos", data=VEICULO)
        self.vid = self.sql("SELECT id FROM veiculos")[0]["id"]
        self.func.post(f"/veiculos/{self.vid}/servicos", data={"tipo": "LATARIA", "problema": "Amasado na porta"})
        self.sid = self.sql("SELECT id FROM servicos")[0]["id"]

    def editar(self, cliente=None, sid=None, **dados):
        base = {"tipo": "PINTURA", "problema": "Amassado na porta do motorista"}
        base.update(dados)
        return (cliente or self.func).post(f"/veiculos/{self.vid}/servicos/{sid or self.sid}/problema", data=base)

    def servico(self):
        return self.sql("SELECT * FROM servicos")[0]

    def test_funcionario_e_dono_corrigem_tipo_e_descricao(self):
        self.assertEqual(self.editar().status_code, 302)
        s = self.servico()
        self.assertEqual((s["tipo"], s["problema"]), ("PINTURA", "Amassado na porta do motorista"))
        self.assertEqual(self.editar(cliente=self.dono_c, tipo="LATARIA", problema="Porta amassada").status_code, 302)
        self.assertEqual(self.servico()["tipo"], "LATARIA")

    def test_nao_perde_valor_garantia_resolucao_nem_quem_registrou(self):
        self.func.post(f"/veiculos/{self.vid}/servicos/{self.sid}/resolucao", data={"como_resolver": "Bater e pintar"})
        self.dono_c.post(f"/veiculos/{self.vid}/servicos/{self.sid}/valor", data={"valor": "300,00"})
        self.dono_c.post(f"/veiculos/{self.vid}/servicos/{self.sid}/garantia", data={"valor": "6", "unidade": "MESES"})
        self.editar(tipo="LATARIA")
        s = self.servico()
        self.assertEqual((s["como_resolver"], s["valor_centavos"], s["garantia_valor"], s["registrado_por"]),
                         ("Bater e pintar", 30000, 6, "PESSOA TESTE"))

    def test_corrigir_o_texto_nao_invalida_a_aprovacao(self):
        self.dono_c.post(f"/veiculos/{self.vid}/servicos/{self.sid}/valor", data={"valor": "300,00"})
        pagina = self.func.get(f"/veiculos/{self.vid}").data.decode()
        assinatura = pagina.split('name="assinatura" value="')[1].split('"')[0]
        self.func.post(f"/veiculos/{self.vid}/aprovacao", data={"decisao": "APROVADO", "forma": "TELEFONE", "assinatura": assinatura})
        self.assertIn("Aprovado pelo cliente", self.func.get(f"/veiculos/{self.vid}").data.decode())
        self.editar(tipo="LATARIA", problema="Porta amassada de lado")
        self.assertIn("Aprovado pelo cliente", self.func.get(f"/veiculos/{self.vid}").data.decode())

    def test_tipo_ou_descricao_invalidos_nao_salvam(self):
        for dados, aviso in (({"tipo": "XYZ"}, "Escolha o tipo"), ({"problema": " "}, "Descreva o problema"),
                             ({"problema": "a" * 501}, "no máximo")):
            self.assertIn(aviso.encode(), self.editar(**dados).data)
        s = self.servico()
        self.assertEqual((s["tipo"], s["problema"]), ("LATARIA", "Amasado na porta"))

    def test_mudar_tipo_com_garantia_acima_do_limite_do_novo_tipo_nao_salva(self):
        self.dono_c.post(f"/veiculos/{self.vid}/servicos/{self.sid}/garantia", data={"valor": "12", "unidade": "MESES"})
        r = self.editar(tipo="FREIOS")           # o limite de freios é 6 meses
        self.assertIn("passa do limite de FREIOS".encode(), r.data)
        self.assertEqual(self.servico()["tipo"], "LATARIA")
        self.assertEqual(self.editar(tipo="PINTURA").status_code, 302)     # pintura aceita até 24 meses
        self.assertEqual(self.servico()["tipo"], "PINTURA")

    def test_sem_mudar_o_tipo_a_garantia_nao_e_conferida(self):
        self.dono_c.post(f"/veiculos/{self.vid}/servicos/{self.sid}/garantia", data={"valor": "12", "unidade": "MESES"})
        self.dono_c.post("/limites-garantia", data={f"meses_{i}": "6" for i in range(8)})   # o dono baixa os limites
        self.assertEqual(self.editar(tipo="LATARIA", problema="Porta amassada").status_code, 302)
        self.assertEqual(self.servico()["problema"], "Porta amassada")

    def test_sem_garantia_informada_pode_mudar_de_tipo(self):
        self.assertEqual(self.editar(tipo="FREIOS").status_code, 302)

    def test_servico_de_outro_veiculo_da_404_e_sem_login_nao_edita(self):
        self.assertEqual(self.editar(sid=9999).status_code, 404)
        from base import oficina
        r = oficina.app.test_client().post(f"/veiculos/{self.vid}/servicos/{self.sid}/problema", data={"tipo": "PINTURA", "problema": "x y z"})
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login", r.headers["Location"])

    def test_html_digitado_nao_executa(self):
        self.editar(problema="<script>alert(1)</script> amassado")
        self.assertNotIn(b"<script>alert(1)</script>", self.func.get(f"/veiculos/{self.vid}").data)

    def test_a_tela_mostra_o_botao_com_os_valores_atuais(self):
        pagina = self.func.get(f"/veiculos/{self.vid}").data.decode()
        self.assertIn("Editar problema", pagina)
        self.assertIn(">Amasado na porta</textarea>", pagina)
        self.assertIn('<option value="LATARIA" selected>', pagina)


class EditarProblemaAposEntregaTest(test_entrega.EntregaBase):
    def test_depois_da_entrega_trava_e_o_botao_some(self):
        self.garantias_ok()
        self.assertEqual(self.fechar().status_code, 302)
        r = self.func.post(f"/veiculos/{self.vid}/servicos/{self.sid1}/problema", data={"tipo": "PINTURA", "problema": "Outro texto aqui"})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.sql("SELECT tipo FROM servicos WHERE id = ?", (self.sid1,))[0]["tipo"], "LATARIA")
        self.assertNotIn("Editar problema", self.pagina())


if __name__ == "__main__":
    unittest.main()
