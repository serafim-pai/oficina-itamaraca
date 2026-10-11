"""Testes da conferência de entrada (combustível, itens deixados, luzes do painel, avarias) e do termo de entrada.
Rodar na pasta do projeto:  python -m unittest discover tests -v"""
import unittest

from test_fotos_entrega import Base, VEICULO


class ConferenciaNoCadastroTest(Base):
    def cadastrar(self, placa="NOV1A23", **conferencia):
        return self.func.post("/veiculos", data={**VEICULO, "placa": placa, **conferencia},
                              content_type="multipart/form-data")

    def ficha(self, placa="NOV1A23"):
        return self.sql("SELECT * FROM veiculos WHERE placa = ?", (placa,))[0]

    def test_cadastro_sem_conferencia_continua_funcionando(self):
        self.assertEqual(self.cadastrar().status_code, 302)
        ficha = self.ficha()
        for coluna in ("luzes_painel", "luzes_outra", "combustivel", "itens_deixados", "itens_outros", "avarias"):
            self.assertIsNone(ficha[coluna])
        self.assertIsNotNone(ficha["criado_em"])

    def test_cadastro_guarda_tudo(self):
        resposta = self.cadastrar(combustivel="1/2", itens=["ESTEPE", "MACACO"], itens_outros="  capa de banco ",
                                  luzes=["MOTOR", "FREIO"], luz_outra="direção", avarias="Risco na porta\n\n  Amassado no para-choque ")
        self.assertEqual(resposta.status_code, 302)
        ficha = self.ficha()
        self.assertEqual((ficha["combustivel"], ficha["itens_deixados"], ficha["itens_outros"]),
                         ("1/2", "ESTEPE,MACACO", "capa de banco"))
        self.assertEqual((ficha["luzes_painel"], ficha["luzes_outra"]), ("MOTOR,FREIO,OUTRA", "direção"))
        self.assertEqual(ficha["avarias"], "Risco na porta\nAmassado no para-choque")

    def test_nenhuma_luz_acesa_e_uma_resposta(self):
        self.cadastrar(luzes=["NENHUMA"])
        self.assertEqual(self.ficha()["luzes_painel"], "NENHUMA")

    def test_erros_nao_cadastram(self):
        casos = (({"luzes": ["NENHUMA", "MOTOR"]}, "não as duas coisas"),
                 ({"luzes": ["OUTRA"]}, "qual é a outra luz"),
                 ({"luz_outra": "x" * 61}, "no máximo 60"),
                 ({"combustivel": "ABASTECIDO"}, "combustível da lista"),
                 ({"itens_outros": "x" * 101}, "no máximo 100"),
                 ({"avarias": "x" * 501}, "no máximo 500"))
        for dados, trecho in casos:
            resposta = self.cadastrar(**dados)
            self.assertEqual(resposta.status_code, 200)
            self.assertIn(trecho, resposta.data.decode())
        self.assertEqual(self.sql("SELECT * FROM veiculos WHERE placa = 'NOV1A23'"), [])

    def test_valores_desconhecidos_sao_ignorados(self):
        self.cadastrar(itens=["ESTEPE", "FOGUETE"], luzes=["MOTOR", "LASER"])
        ficha = self.ficha()
        self.assertEqual((ficha["itens_deixados"], ficha["luzes_painel"]), ("ESTEPE", "MOTOR"))


class ConferenciaNaFichaTest(Base):
    def registrar(self, cliente=None, **dados):
        return (cliente or self.func).post(f"/veiculos/{self.vid}/conferencia", data=dados)

    def ficha_db(self):
        return self.sql("SELECT * FROM veiculos WHERE id = ?", (self.vid,))[0]

    def test_ficha_nova_pede_a_conferencia_e_mostra_nao_conferido(self):
        pagina = self.pagina()
        self.assertIn("Registrar a conferência de entrada", pagina)
        self.assertIn("Combustível (entrada):</strong> não conferido", pagina)
        self.assertNotIn("luzes acesas no painel</strong>:", pagina)

    def test_funcionario_e_dono_registram_e_a_ficha_mostra(self):
        self.assertEqual(self.registrar(combustivel="CHEIO", itens=["TAPETES"], avarias="Farol trincado").status_code, 302)
        pagina = self.pagina(cliente=self.func)
        self.assertIn("Combustível (entrada):</strong> Cheio", pagina)
        self.assertIn("Itens deixados no carro:</strong> Tapetes", pagina)
        self.assertIn("Avarias que já tinha:</strong> Farol trincado", pagina)
        self.assertIn("Alterar a conferência de entrada", pagina)
        self.registrar(cliente=self.dono_c, combustivel="1/4")
        self.assertEqual(self.ficha_db()["combustivel"], "1/4")

    def test_luz_acesa_mostra_aviso_e_nenhuma_luz_nao(self):
        self.registrar(luzes=["MOTOR", "OUTRA"], luz_outra="ABS")
        pagina = self.pagina()
        self.assertIn("luzes acesas no painel</strong>: Injeção / motor, Outra luz (ABS)", pagina)
        self.registrar(luzes=["NENHUMA"])
        pagina = self.pagina()
        self.assertNotIn("luzes acesas no painel</strong>:", pagina)
        self.assertIn("Luzes no painel (entrada):</strong> Nenhuma luz acesa", pagina)

    def test_conferencia_invalida_nao_salva(self):
        self.registrar(combustivel="CHEIO")
        resposta = self.registrar(combustivel="CHEIO", luzes=["NENHUMA", "AIRBAG"])
        self.assertIn("não as duas coisas", resposta.data.decode())
        self.assertIsNone(self.ficha_db()["luzes_painel"])

    def test_limpar_tudo_volta_para_nao_conferido(self):
        self.registrar(combustivel="CHEIO", avarias="Risco")
        self.registrar()
        ficha = self.ficha_db()
        self.assertIsNone(ficha["combustivel"])
        self.assertIsNone(ficha["avarias"])

    def test_ficha_inexistente_da_404(self):
        self.assertEqual(self.func.post("/veiculos/99999/conferencia", data={}).status_code, 404)

    def test_depois_da_entrega_fica_travada(self):
        self.registrar(combustivel="CHEIO")
        self.fechar()
        resposta = self.registrar(combustivel="1/4")
        self.assertNotEqual(resposta.status_code, 302)
        self.assertEqual(self.ficha_db()["combustivel"], "CHEIO")
        self.assertNotIn("Alterar a conferência de entrada", self.pagina())


class AvisoDasLuzesNoOrcamentoTest(Base):
    def test_orcamento_do_whatsapp_leva_o_aviso_quando_ha_luz_acesa(self):
        from urllib.parse import quote
        self.func.post(f"/veiculos/{self.vid}/conferencia", data={"luzes": ["MOTOR"]})
        self.sql("UPDATE servicos SET valor_centavos = 15000 WHERE id = ?", (self.sid,))
        pagina = self.pagina()
        self.assertIn(quote("luzes acesas no painel (Injeção / motor)"), pagina)
        self.assertIn(quote("Elas podem indicar outros problemas"), pagina)

    def test_orcamento_sem_luz_acesa_nao_leva_o_aviso(self):
        from urllib.parse import quote
        self.func.post(f"/veiculos/{self.vid}/conferencia", data={"luzes": ["NENHUMA"]})
        self.assertNotIn(quote("luzes acesas no painel"), self.pagina())


class ComprovanteComEntradaTest(Base):
    def test_comprovante_mostra_a_entrada_do_veiculo(self):
        self.func.post(f"/veiculos/{self.vid}/conferencia",
                       data={"combustivel": "3/4", "itens": ["ESTEPE"], "luzes": ["BATERIA"], "avarias": "Risco\nAmassado"})
        self.fechar()
        pagina = self.dono_c.get(f"/veiculos/{self.vid}/comprovante").data.decode()
        self.assertIn("Entrada do veículo", pagina)
        self.assertIn("Combustível: 3/4.", pagina)
        self.assertIn("Itens deixados: Estepe.", pagina)
        self.assertIn("Luzes no painel: Bateria / alternador.", pagina)
        self.assertIn("Avarias que já tinha: Risco / Amassado.", pagina)

    def test_comprovante_sem_conferencia_nao_mostra_a_linha(self):
        self.fechar()
        pagina = self.dono_c.get(f"/veiculos/{self.vid}/comprovante").data.decode()
        self.assertNotIn("Entrada do veículo", pagina)


class TermoDeEntradaTest(Base):
    def termo(self, cliente=None, vid=None):
        return (cliente or self.dono_c).get(f"/veiculos/{vid or self.vid}/termo-entrada")

    def test_funcionario_e_dono_abrem_o_termo(self):
        self.func.post(f"/veiculos/{self.vid}/conferencia",
                       data={"combustivel": "1/2", "itens": ["MACACO", "RADIO"], "luzes": ["FREIO"], "avarias": "Risco na porta"})
        for cliente in (self.func, self.dono_c):
            resposta = self.termo(cliente)
            self.assertEqual(resposta.status_code, 200)
            pagina = resposta.data.decode()
            self.assertIn("Termo de recebimento do veículo", pagina)
            self.assertIn("ABC1D23", pagina)
            self.assertIn("<td>1/2</td>", pagina)
            self.assertIn("Macaco e chave de roda, Rádio / som", pagina)
            self.assertIn("Freio / ABS", pagina)
            self.assertIn("Risco na porta", pagina)
            self.assertIn('class="assinaturas"', pagina)

    def test_sem_conferencia_diz_nao_conferido_e_nenhuma_avaria(self):
        pagina = self.termo().data.decode()
        self.assertIn("não conferido", pagina)
        self.assertIn("Nenhuma avaria registrada", pagina)

    def test_mostra_as_fotos_de_entrada_e_so_elas(self):
        pagina = self.termo().data.decode()
        entrada = self.fotos("ENTRADA")
        self.assertEqual(len(entrada), 2)
        for f in entrada:
            self.assertIn(f"/fotos/{f['id']}/miniatura", pagina)
        self.assertIn("Fotos do veículo na entrada", pagina)

    def test_mostra_a_hora_do_cadastro_quando_existe(self):
        self.sql("UPDATE veiculos SET criado_em = '2026-10-06 00:30:30' WHERE id = ?", (self.vid,))
        self.assertIn("05/10/2026 21:30", self.termo().data.decode())

    def test_ficha_inexistente_da_404(self):
        self.assertEqual(self.termo(vid=99999).status_code, 404)

    def test_a_ficha_tem_o_link_do_termo(self):
        self.assertIn(f"/veiculos/{self.vid}/termo-entrada", self.pagina())


class CadastroMostraOsCamposTest(Base):
    def test_tela_inicial_tem_os_campos_da_conferencia(self):
        pagina = self.dono_c.get("/").data.decode()
        for trecho in ("Conferência de entrada", 'name="combustivel"', 'name="itens"', 'name="luzes"',
                       'name="luz_outra"', 'name="avarias"', "Nenhuma luz acesa", "Estepe"):
            self.assertIn(trecho, pagina)


if __name__ == "__main__":
    unittest.main()
