"""Testes da história 9: estoque de peças e tintas, uso nos serviços, orçamento e comprovante.
Rodar na pasta do projeto:  python -m unittest discover tests -v"""
import unittest

import test_entrega
from base import BaseTest, oficina


class EstoqueBase(BaseTest):
    def setUp(self):
        super().setUp()
        self.func = self.funcionario()
        self.dono_c = self.dono()

    def cadastrar(self, nome="Pastilha de freio", tipo="PEÇA", quantidade="10", minimo="3", custo="35,00",
                  preco="60,00", cliente=None):
        return (cliente or self.dono_c).post("/estoque/novo", data={
            "nome": nome, "tipo": tipo, "quantidade": quantidade, "minimo": minimo, "custo": custo, "preco": preco})

    def item(self, id=None):
        linhas = self.sql("SELECT * FROM estoque_itens WHERE id = ?" if id else "SELECT * FROM estoque_itens ORDER BY id",
                          (id,) if id else ())
        return linhas[0]

    def movimentos(self):
        return self.sql("SELECT * FROM estoque_movimentos ORDER BY id")


class CadastroDeItensTest(EstoqueBase):
    def test_funcionario_cadastra_item_com_quantidade_inicial(self):
        self.assertEqual(self.cadastrar().status_code, 302)
        i = self.item()
        self.assertEqual((i["nome"], i["tipo"], i["quantidade"], i["minimo"]), ("Pastilha de freio", "PEÇA", 10, 3))
        self.assertEqual((i["custo_centavos"], i["preco_centavos"]), (3500, 6000))
        m = self.movimentos()
        self.assertEqual((len(m), m[0]["tipo"], m[0]["variacao"], m[0]["saldo_apos"]), (1, "INICIAL", 10, 10))

    def test_quantidade_inicial_zero_nao_gera_movimento(self):
        self.cadastrar(quantidade="")
        self.assertEqual(self.item()["quantidade"], 0)
        self.assertEqual(self.movimentos(), [])

    def test_custo_pode_ficar_vazio_mas_preco_nao(self):
        self.cadastrar(custo="")
        self.assertEqual(self.item()["custo_centavos"], 0)
        self.sql("DELETE FROM estoque_itens")
        r = self.cadastrar(nome="Tinta azul", preco="")
        self.assertIn("preço de venda".encode(), r.data)
        self.assertEqual(self.sql("SELECT COUNT(*) AS n FROM estoque_itens")[0]["n"], 0)

    def test_so_aceita_unidades_inteiras(self):
        for ruim in ("1,5", "-2", "abc", "1.5", "²", "999999999"):
            r = self.cadastrar(quantidade=ruim)
            self.assertIn("número inteiro".encode(), r.data, ruim)
        self.assertEqual(self.sql("SELECT COUNT(*) AS n FROM estoque_itens")[0]["n"], 0)

    def test_tipo_invalido_e_nome_vazio(self):
        self.assertIn("peça ou tinta".encode(), self.cadastrar(tipo="OUTRO").data)
        self.assertIn("nome do item".encode(), self.cadastrar(nome=" ").data)
        self.assertEqual(self.sql("SELECT COUNT(*) AS n FROM estoque_itens")[0]["n"], 0)

    def test_nao_repete_item_com_mesmo_nome_e_tipo(self):
        self.cadastrar()
        r = self.cadastrar(nome="PASTILHA  DE FREIO")
        self.assertIn("Já existe um item".encode(), r.data)
        self.assertEqual(self.sql("SELECT COUNT(*) AS n FROM estoque_itens")[0]["n"], 1)
        self.assertEqual(self.cadastrar(nome="Pastilha de freio", tipo="TINTA").status_code, 302)

    def test_funcionario_nao_cadastra_nem_edita_item(self):
        self.assertEqual(self.cadastrar(cliente=self.func).status_code, 403)
        self.assertEqual(self.sql("SELECT COUNT(*) AS n FROM estoque_itens")[0]["n"], 0)
        self.cadastrar()
        iid = self.item()["id"]
        r = self.func.post(f"/estoque/{iid}/editar", data={
            "nome": "X", "tipo": "PEÇA", "minimo": "1", "custo": "1,00", "preco": "1,00"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.item()["preco_centavos"], 6000)

    def test_funcionario_nao_ve_o_custo_mas_o_dono_ve(self):
        self.cadastrar(custo="35,00", preco="60,00")
        func = self.func.get("/estoque").data.decode()
        self.assertIn("R$ 60,00", func)
        self.assertNotIn("R$ 35,00", func)
        self.assertNotIn("Cadastrar item", func)
        self.assertNotIn("pelo custo", func)
        dono = self.dono_c.get("/estoque").data.decode()
        self.assertIn("R$ 35,00", dono)
        self.assertIn("Cadastrar item", dono)

    def test_sem_login_nao_acessa(self):
        r = oficina.app.test_client().get("/estoque")
        self.assertEqual(r.status_code, 302)

    def test_pagina_lista_itens_e_avisa_estoque_baixo(self):
        self.cadastrar(quantidade="2", minimo="3")
        pagina = self.func.get("/estoque").data.decode()
        self.assertIn("Pastilha de freio", pagina)
        self.assertIn("Estoque baixo", pagina)
        self.assertIn("R$ 60,00", pagina)

    def test_nome_com_html_nao_executa(self):
        self.cadastrar(nome="<script>alert(1)</script>")
        self.assertNotIn(b"<script>alert(1)</script>", self.func.get("/estoque").data)


class MovimentosTest(EstoqueBase):
    def setUp(self):
        super().setUp()
        self.cadastrar()
        self.iid = self.item()["id"]

    def test_entrada_soma_e_registra_quem_fez(self):
        r = self.func.post(f"/estoque/{self.iid}/entrada", data={"quantidade": "5", "motivo": "compra"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.item()["quantidade"], 15)
        m = self.movimentos()[-1]
        self.assertEqual((m["tipo"], m["variacao"], m["saldo_apos"], m["motivo"], m["registrado_por"]),
                         ("ENTRADA", 5, 15, "compra", "PESSOA TESTE"))

    def test_entrada_invalida_nao_muda_nada(self):
        for ruim in ("0", "-1", "2,5", "", "100001"):
            self.func.post(f"/estoque/{self.iid}/entrada", data={"quantidade": ruim})
        self.assertEqual(self.item()["quantidade"], 10)
        self.assertEqual(len(self.movimentos()), 1)

    def test_ajuste_leva_ao_valor_contado_e_exige_motivo(self):
        r = self.func.post(f"/estoque/{self.iid}/ajuste", data={"quantidade": "7", "motivo": ""})
        self.assertIn("motivo do ajuste".encode(), r.data)
        self.assertEqual(self.item()["quantidade"], 10)
        self.func.post(f"/estoque/{self.iid}/ajuste", data={"quantidade": "7", "motivo": "contagem da prateleira"})
        self.assertEqual(self.item()["quantidade"], 7)
        m = self.movimentos()[-1]
        self.assertEqual((m["tipo"], m["variacao"], m["saldo_apos"]), ("AJUSTE", -3, 7))

    def test_ajuste_igual_ao_sistema_nao_faz_nada(self):
        r = self.func.post(f"/estoque/{self.iid}/ajuste", data={"quantidade": "10", "motivo": "contagem"})
        self.assertIn("não há o que ajustar".encode(), r.data)

    def test_editar_muda_preco_e_minimo(self):
        self.dono_c.post(f"/estoque/{self.iid}/editar", data={
            "nome": "Pastilha de freio", "tipo": "PEÇA", "minimo": "5", "custo": "40,00", "preco": "70,00"})
        i = self.item()
        self.assertEqual((i["minimo"], i["custo_centavos"], i["preco_centavos"]), (5, 4000, 7000))
        self.assertEqual(i["quantidade"], 10)

    def test_so_o_dono_tira_item_de_uso(self):
        self.assertEqual(self.func.post(f"/estoque/{self.iid}/alternar").status_code, 403)
        self.assertEqual(self.item()["ativo"], 1)
        self.dono_c.post(f"/estoque/{self.iid}/alternar")
        self.assertEqual(self.item()["ativo"], 0)
        self.dono_c.post(f"/estoque/{self.iid}/alternar")
        self.assertEqual(self.item()["ativo"], 1)

    def test_item_inexistente_da_404(self):
        self.assertEqual(self.func.post("/estoque/999/entrada", data={"quantidade": "1"}).status_code, 404)


class UsoNoServicoTest(test_entrega.EntregaBase):
    def setUp(self):
        super().setUp()
        self.dono_c.post("/estoque/novo", data={"nome": "Pastilha de freio", "tipo": "PEÇA", "quantidade": "10",
                                              "minimo": "2", "custo": "35,00", "preco": "60,00"})
        self.iid = self.sql("SELECT id FROM estoque_itens")[0]["id"]

    def usar(self, quantidade="2", sid=None, cliente=None, item=None):
        return (cliente or self.func).post(f"/veiculos/{self.vid}/servicos/{sid or self.sid1}/pecas",
                                           data={"item_id": str(item or self.iid), "quantidade": quantidade})

    def estoque(self):
        return self.sql("SELECT quantidade FROM estoque_itens WHERE id = ?", (self.iid,))[0]["quantidade"]

    def pecas_do_servico(self, sid=None):
        return self.sql("SELECT pecas_centavos FROM servicos WHERE id = ?", (sid or self.sid1,))[0]["pecas_centavos"]

    def test_usar_baixa_o_estoque_e_soma_ao_orcamento(self):
        self.assertEqual(self.usar("2").status_code, 302)
        self.assertEqual(self.estoque(), 8)
        self.assertEqual(self.pecas_do_servico(), 12000)
        p = self.sql("SELECT * FROM servico_pecas")[0]
        self.assertEqual((p["nome"], p["quantidade"], p["preco_centavos"], p["custo_centavos"]),
                         ("Pastilha de freio", 2, 6000, 3500))
        m = self.sql("SELECT * FROM estoque_movimentos ORDER BY id DESC LIMIT 1")[0]
        self.assertEqual((m["tipo"], m["variacao"], m["saldo_apos"], m["veiculo_id"], m["servico_id"]),
                         ("SAIDA", -2, 8, self.vid, self.sid1))
        pagina = self.pagina()
        self.assertIn("2x Pastilha de freio", pagina)
        self.assertIn("R$ 520,50", pagina)          # 150,00 + 250,50 + 120,00 de peças

    def test_nao_deixa_usar_mais_do_que_tem(self):
        r = self.usar("11")
        self.assertIn("não há estoque suficiente".encode().lower(), r.data.lower())
        self.assertEqual(self.estoque(), 10)
        self.assertEqual(self.sql("SELECT COUNT(*) AS n FROM servico_pecas")[0]["n"], 0)
        self.assertEqual(self.pecas_do_servico(), 0)

    def test_pode_usar_ate_zerar(self):
        self.usar("10")
        self.assertEqual(self.estoque(), 0)
        self.assertIn("Acabou", self.func.get("/estoque").data.decode())

    def test_quantidade_invalida(self):
        for ruim in ("0", "-1", "1,5", "x", ""):
            self.assertIn("quantidade usada".encode(), self.usar(ruim).data, ruim)
        self.assertEqual(self.estoque(), 10)

    def test_item_fora_de_uso_ou_inexistente_nao_serve(self):
        self.dono_c.post(f"/estoque/{self.iid}/alternar")
        self.assertIn("Escolha uma peça".encode(), self.usar("1").data)
        self.assertIn("Escolha uma peça".encode(), self.usar("1", item=999).data)
        self.assertEqual(self.estoque(), 10)

    def test_servico_de_outro_veiculo_da_404(self):
        self.assertEqual(self.usar("1", sid=9999).status_code, 404)

    def test_preco_novo_nao_muda_o_que_ja_foi_usado(self):
        self.usar("1")
        self.dono_c.post(f"/estoque/{self.iid}/editar", data={
            "nome": "Pastilha de freio", "tipo": "PEÇA", "minimo": "2", "custo": "50,00", "preco": "99,00"})
        self.assertEqual(self.pecas_do_servico(), 6000)

    def test_devolver_volta_ao_estoque_e_tira_do_orcamento(self):
        self.usar("3")
        peca = self.sql("SELECT id FROM servico_pecas")[0]["id"]
        r = self.func.post(f"/veiculos/{self.vid}/servicos/{self.sid1}/pecas/{peca}/devolver")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.estoque(), 10)
        self.assertEqual(self.pecas_do_servico(), 0)
        self.assertEqual(self.sql("SELECT COUNT(*) AS n FROM servico_pecas")[0]["n"], 0)
        self.assertEqual(self.sql("SELECT tipo FROM estoque_movimentos ORDER BY id DESC LIMIT 1")[0]["tipo"], "DEVOLUCAO")

    def test_excluir_servico_devolve_as_pecas(self):
        self.usar("4")
        self.dono_c.post(f"/veiculos/{self.vid}/servicos/{self.sid1}/excluir")
        self.assertEqual(self.estoque(), 10)
        self.assertEqual(self.sql("SELECT COUNT(*) AS n FROM servico_pecas")[0]["n"], 0)

    def test_excluir_veiculo_devolve_as_pecas(self):
        self.usar("4")
        self.sql("DELETE FROM aprovacoes")
        r = self.dono_c.post(f"/veiculos/{self.vid}/excluir", data={"motivo": "cadastrado por engano"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.estoque(), 10)

    def test_usar_peca_muda_o_orcamento_e_invalida_a_aprovacao(self):
        self.assertEqual(self.sql("SELECT COUNT(*) AS n FROM aprovacoes")[0]["n"], 1)
        self.assertIn("Aprovado pelo cliente", self.pagina())
        self.usar("1")
        self.assertIn("Orçamento mudou", self.pagina())

    def test_aprovacao_antiga_sem_pecas_continua_valendo(self):
        """A assinatura só muda quando há peças: aprovações feitas antes desta história seguem valendo."""
        servicos = self.sql("SELECT * FROM servicos ORDER BY id")
        texto_antigo = "|".join(f"{s['id']}:{s['valor_centavos']}" for s in servicos)
        import hashlib
        self.assertEqual(oficina.assinatura_orcamento(servicos), hashlib.sha256(texto_antigo.encode()).hexdigest()[:16])

    def test_entrega_guarda_copia_das_pecas_e_comprovante_mostra(self):
        self.usar("2")
        self.aprovar()
        self.garantias_ok()
        self.assertEqual(self.fechar().status_code, 302)
        entrega = self.entregas()[0]
        self.assertEqual(entrega["total_centavos"], 15000 + 25050 + 12000)
        item = self.sql("SELECT * FROM entrega_itens WHERE servico_id = ?", (self.sid1,))[0]
        self.assertEqual((item["valor_centavos"], item["pecas_centavos"]), (15000, 12000))
        self.assertEqual(self.sql("SELECT quantidade, preco_centavos FROM entrega_pecas")[0]["quantidade"], 2)
        html = self.comprovante().data.decode()
        self.assertIn("2x Pastilha de freio", html)
        self.assertIn("R$ 270,00", html)            # lataria: 150,00 + 120,00 de peças
        self.assertIn("R$ 520,50", html)

    def test_comprovante_nao_muda_se_o_preco_do_estoque_mudar_depois(self):
        self.usar("2")
        self.aprovar()
        self.garantias_ok()
        self.fechar()
        self.dono_c.post(f"/estoque/{self.iid}/editar", data={
            "nome": "Outro nome", "tipo": "PEÇA", "minimo": "2", "custo": "1,00", "preco": "1,00"})
        html = self.comprovante().data.decode()
        self.assertIn("2x Pastilha de freio", html)
        self.assertIn("R$ 120,00", html)

    def test_depois_da_entrega_nao_usa_nem_devolve_peca(self):
        self.usar("1")
        peca = self.sql("SELECT id FROM servico_pecas")[0]["id"]
        self.aprovar()
        self.garantias_ok()
        self.fechar()
        self.assertEqual(self.usar("1").status_code, 409)
        r = self.func.post(f"/veiculos/{self.vid}/servicos/{self.sid1}/pecas/{peca}/devolver")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.estoque(), 9)

    def test_desfazer_entrega_guarda_pecas_no_historico_e_destrava(self):
        self.usar("2")
        self.aprovar()
        self.garantias_ok()
        self.fechar()
        self.dono_c.post(f"/veiculos/{self.vid}/entrega/desfazer", data={"motivo": "corrigir valor"})
        self.assertEqual(self.entregas(), [])
        self.assertEqual(self.sql("SELECT COUNT(*) AS n FROM entrega_pecas")[0]["n"], 0)
        d = self.sql("SELECT pecas_centavos FROM entrega_itens_desfeitos WHERE pecas_centavos > 0")
        self.assertEqual(d[0]["pecas_centavos"], 12000)
        self.assertEqual(self.estoque(), 8)                      # a peça continua usada
        self.assertEqual(self.usar("1").status_code, 302)        # e o cadastro voltou a aceitar mudanças

    def test_whatsapp_leva_o_valor_com_pecas(self):
        self.usar("2")
        self.assertIn("270%2C00", self.pagina())                 # link wa.me com R$ 270,00 da lataria


if __name__ == "__main__":
    unittest.main()
