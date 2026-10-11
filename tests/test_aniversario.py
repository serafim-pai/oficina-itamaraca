"""Testes da data de nascimento e do aviso de aniversário (brinde do mês).
Rodar na pasta do projeto:  python -m unittest discover tests -v"""
import unittest
from datetime import date

from base import oficina
from test_fotos_entrega import Base, VEICULO


class NascimentoNoCadastroTest(Base):
    def cadastrar(self, nascimento, placa="NOV1A23"):
        return self.func.post("/veiculos", data={**VEICULO, "placa": placa, "data_nascimento": nascimento},
                              content_type="multipart/form-data")

    def nascimento(self, placa="NOV1A23"):
        return self.sql("SELECT data_nascimento FROM veiculos WHERE placa = ?", (placa,))[0]["data_nascimento"]

    def test_cadastro_sem_data_continua_funcionando(self):
        self.assertEqual(self.cadastrar("").status_code, 302)
        self.assertIsNone(self.nascimento())

    def test_cadastro_guarda_a_data(self):
        self.assertEqual(self.cadastrar("1985-10-20").status_code, 302)
        self.assertEqual(self.nascimento(), "1985-10-20")

    def test_data_invalida_futura_ou_antiga_e_recusada(self):
        for texto, trecho in (("20/10/1985", "não é válida"), ("2026-10-16", "no futuro"), ("1899-12-31", "muito antiga")):
            resposta = self.cadastrar(texto)
            self.assertEqual(resposta.status_code, 200)
            self.assertIn(trecho, resposta.data.decode())
        self.assertEqual(self.sql("SELECT * FROM veiculos WHERE placa = 'NOV1A23'"), [])


class NascimentoNaFichaTest(Base):
    def informar(self, texto, cliente=None):
        return (cliente or self.func).post(f"/veiculos/{self.vid}/nascimento", data={"data_nascimento": texto})

    def nascimento(self):
        return self.sql("SELECT data_nascimento FROM veiculos WHERE id = ?", (self.vid,))[0]["data_nascimento"]

    def test_funcionario_e_dono_informam_e_a_ficha_mostra(self):
        self.assertEqual(self.informar("1990-03-05").status_code, 302)
        self.assertEqual(self.nascimento(), "1990-03-05")
        self.assertIn("05/03/1990", self.pagina(cliente=self.func))
        self.informar("1991-04-06", cliente=self.dono_c)
        self.assertEqual(self.nascimento(), "1991-04-06")

    def test_vazio_apaga(self):
        self.informar("1990-03-05")
        self.informar("")
        self.assertIsNone(self.nascimento())

    def test_data_ruim_nao_grava(self):
        self.informar("1990-03-05")
        self.assertIn("não pode ser no futuro", self.informar("2099-01-01").data.decode())
        self.assertIn("não é válida", self.informar("abc").data.decode())
        self.assertEqual(self.nascimento(), "1990-03-05")

    def test_ficha_inexistente_da_404(self):
        self.assertEqual(self.func.post("/veiculos/99999/nascimento", data={"data_nascimento": ""}).status_code, 404)


class AniversarioNosAvisosTest(Base):
    def definir(self, nascimento, vid=None, telefone=None):
        self.sql("UPDATE veiculos SET data_nascimento = ?, telefone = ? WHERE id = ?",
                 (nascimento, telefone, vid or self.vid))

    def em(self, dia):
        oficina.hoje_brasil = lambda agora_utc=None: dia

    def lista(self, cliente=None):
        return (cliente or self.dono_c).get("/avisos").data.decode()

    def avisei(self, tipo="ANIVERSARIO", vid=None):
        return self.func.post(f"/veiculos/{vid or self.vid}/avisos", data={"tipo": tipo})

    def test_aparece_o_mes_inteiro_com_o_dia(self):
        self.definir("1985-10-20")
        for dia, texto in ((date(2026, 10, 1), "em 19 dias"), (date(2026, 10, 20), "hoje"),
                           (date(2026, 10, 28), "fez aniversário há 8 dias")):
            self.em(dia)
            pagina = self.lista()
            self.assertIn("🎂 Aniversário", pagina)
            self.assertIn("20/10/2026", pagina)
            self.assertIn(texto, pagina)

    def test_nao_aparece_em_outro_mes_nem_sem_data(self):
        self.definir("1985-11-02")
        self.assertNotIn("🎂 Aniversário", self.lista())
        self.definir(None)
        self.assertNotIn("🎂 Aniversário", self.lista())

    def test_mensagem_oferece_o_brinde_ate_o_fim_do_mes(self):
        self.definir("1985-10-20", telefone="81987654321")
        pagina = self.lista()
        self.assertIn("https://wa.me/5581987654321?text=", pagina)
        self.assertIn("Feliz%20anivers%C3%A1rio", pagina)
        self.assertIn("revis%C3%A3o%20geral%2C%20alinhamento%20e%20balanceamento%20gr%C3%A1tis", pagina)
        self.assertIn("vale%20at%C3%A9%2031/10/2026", pagina)
        self.assertIn("brinde: revisão geral, alinhamento e balanceamento grátis", pagina)

    def test_texto_da_garantia_nao_promete_diagnostico_gratis(self):
        self.fechar()
        self.sql("UPDATE entrega_itens SET garantia_ate = '2026-10-25'")
        self.sql("UPDATE veiculos SET telefone = '81987654321'")
        pagina = self.lista()
        self.assertIn("Garantia vencendo", pagina)
        self.assertNotIn("diagn%C3%B3stico", pagina)

    def test_avisei_vale_pelo_ano(self):
        self.definir("1985-10-20")
        self.assertEqual(self.avisei().status_code, 302)
        self.assertEqual(self.sql("SELECT tipo, marca_meses FROM avisos")[0]["marca_meses"], 2026)
        self.assertNotIn("🎂 Aniversário", self.lista())
        self.em(date(2027, 10, 5))
        self.assertIn("🎂 Aniversário", self.lista())

    def test_avisei_fora_do_mes_nao_registra(self):
        self.definir("1985-11-02")
        self.avisei()
        self.assertEqual(self.sql("SELECT * FROM avisos"), [])

    def test_nao_avisar_mais_tira(self):
        self.definir("1985-10-20")
        self.avisei("NAO_AVISAR")
        self.assertNotIn("🎂 Aniversário", self.lista())

    def test_ficha_arquivada_nao_aparece(self):
        self.definir("1985-10-20")
        self.dono_c.post(f"/veiculos/{self.vid}/arquivar", data={"motivo": "Cliente mudou de cidade"})
        self.assertNotIn("🎂 Aniversário", self.lista())

    def test_mesma_pessoa_em_duas_fichas_aparece_uma_vez(self):
        outro = self.novo_veiculo("XYZ9K88")
        self.definir("1985-10-20", telefone="81987654321")
        self.definir("1985-10-20", vid=outro, telefone="81987654321")
        pagina = self.lista()
        self.assertEqual(pagina.count("🎂 Aniversário"), 1)
        self.assertIn("XYZ9K88", pagina)    # a ficha mais nova

    def test_avisei_em_uma_ficha_vale_para_a_pessoa(self):
        outro = self.novo_veiculo("XYZ9K88")
        self.definir("1985-10-20", telefone="81987654321")
        self.avisei(vid=self.vid)
        self.definir("1985-10-20", vid=outro, telefone="81987654321")
        self.assertNotIn("🎂 Aniversário", self.lista())

    def test_pessoas_diferentes_sem_telefone_aparecem_cada_uma(self):
        outro = self.novo_veiculo("XYZ9K88")
        self.sql("UPDATE veiculos SET responsavel = 'ANA PAULA' WHERE id = ?", (outro,))
        self.definir("1985-10-20")
        self.definir("1985-10-20", vid=outro)
        self.assertEqual(self.lista().count("🎂 Aniversário"), 2)

    def test_29_de_fevereiro_em_ano_comum_vira_28(self):
        self.definir("2000-02-29")
        self.em(date(2027, 2, 10))
        pagina = self.lista()
        self.assertIn("28/02/2027", pagina)

    def test_funcionario_ve_a_lista_de_aniversarios(self):
        self.definir("1985-10-20")
        self.assertIn("🎂 Aniversário", self.lista(cliente=self.func))


if __name__ == "__main__":
    unittest.main()
