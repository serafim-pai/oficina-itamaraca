"""Limpa todos os cadastros de veículos (e tudo que é deles) para começar do zero, por exemplo para criar um
cadastro-modelo ou para entregar o sistema limpo em outra oficina.

Uso (na pasta do projeto):
    python limpar_cadastros.py              só mostra o que seria apagado (não muda nada)
    python limpar_cadastros.py --executar   apaga de verdade, depois de você digitar a frase de confirmação

Antes de apagar, a ferramenta faz uma cópia do banco e MOVE a pasta de fotos para uma pasta de backup
(nada é perdido de imediato). Ela MANTÉM: usuários e senhas, limites de garantia, estoque (itens e quantidades)
e profissionais (comissão). O histórico do estoque fica, mas sem ligação com os veículos apagados.
"""
import os
import shutil
import sqlite3
import sys
from datetime import datetime

PASTA_DO_SISTEMA = os.path.dirname(os.path.abspath(__file__))
BANCO = os.environ.get("OFICINA_DB") or os.path.join(PASTA_DO_SISTEMA, "oficina.db")
PASTA_FOTOS = os.environ.get("OFICINA_FOTOS") or os.path.join(PASTA_DO_SISTEMA, "fotos")
FRASE = "APAGAR TUDO"

# Tabelas que são apagadas por inteiro (tudo que pertence aos veículos), da mais dependente para a menos
APAGAR = ("fotos_historico", "fotos", "entrega_pecas", "entrega_itens", "entregas", "entrega_itens_desfeitos",
          "entregas_desfeitas", "servico_pecas", "pagamentos", "aprovacoes", "prazos", "etapas", "arquivamentos",
          "avisos", "servicos", "veiculos_excluidos", "veiculos")
MANTER = ("usuarios", "tentativas_login", "limites_garantia", "estoque_itens", "estoque_aplicacoes",
          "estoque_movimentos", "profissionais")


def tabelas_existentes(banco):
    return {linha[0] for linha in banco.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def contar(banco):
    """Quantas linhas há em cada tabela que será apagada e em cada tabela que será mantida."""
    existentes = tabelas_existentes(banco)
    apagar = {t: banco.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in APAGAR if t in existentes}
    manter = {t: banco.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in MANTER if t in existentes}
    return apagar, manter


def limpar_banco(banco):
    """Apaga tudo dos veículos numa transação só (ou tudo, ou nada). O estoque perde só a ligação com os veículos."""
    existentes = tabelas_existentes(banco)
    try:
        for tabela in APAGAR:
            if tabela in existentes:
                banco.execute(f"DELETE FROM {tabela}")
        if "estoque_movimentos" in existentes:
            banco.execute("UPDATE estoque_movimentos SET veiculo_id = NULL, servico_id = NULL")
        if "sqlite_sequence" in existentes:          # os números das fichas voltam a começar do 1
            marcas = ",".join("?" * len(APAGAR))
            banco.execute(f"DELETE FROM sqlite_sequence WHERE name IN ({marcas})", APAGAR)
        banco.commit()
    except Exception:
        banco.rollback()
        raise


def mover_fotos(pasta, carimbo):
    """Move a pasta de fotos para uma pasta de backup e cria uma pasta vazia no lugar. Devolve o novo nome (ou None)."""
    if not os.path.isdir(pasta):
        os.makedirs(pasta, exist_ok=True)
        return None
    destino = f"{pasta.rstrip(os.sep)}-antes-da-limpeza-{carimbo}"
    shutil.move(pasta, destino)
    os.makedirs(pasta, exist_ok=True)
    return destino


def copiar_banco(origem, carimbo):
    destino = os.path.splitext(origem)[0] + f"-antes-da-limpeza-{carimbo}.db"
    with sqlite3.connect(origem) as de, sqlite3.connect(destino) as para:
        de.backup(para)
    return destino


def mostrar(titulo, contagem):
    print(titulo)
    for tabela, quantidade in contagem.items():
        print(f"   {tabela}: {quantidade}")


def principal(argumentos, entrada=input):
    if not os.path.exists(BANCO):
        print(f"Não achei o banco de dados em {BANCO}.")
        return 1
    banco = sqlite3.connect(BANCO)
    apagar, manter = contar(banco)
    print(f"Banco: {BANCO}")
    print(f"Fotos: {PASTA_FOTOS}\n")
    mostrar("Isto será APAGADO:", apagar)
    print()
    mostrar("Isto será MANTIDO:", manter)
    print()
    if "--executar" not in argumentos:
        print("Nada foi alterado. Para apagar de verdade, rode de novo com --executar.")
        banco.close()
        return 0
    print(f"Para confirmar, digite exatamente: {FRASE}")
    if entrada("> ").strip() != FRASE:
        print("Frase diferente. Nada foi alterado.")
        banco.close()
        return 1
    carimbo = datetime.now().strftime("%Y%m%d-%H%M")
    copia = copiar_banco(BANCO, carimbo)
    print(f"Cópia do banco guardada em: {copia}")
    limpar_banco(banco)
    banco.close()
    pasta_antiga = mover_fotos(PASTA_FOTOS, carimbo)
    if pasta_antiga:
        print(f"Fotos antigas guardadas em: {pasta_antiga}")
    print("\nPronto: os cadastros foram apagados. Recarregue o site (Reload na aba Web).")
    print("Quando tiver certeza de que não precisa mais, você pode apagar a cópia do banco e a pasta de fotos antiga.")
    return 0


if __name__ == "__main__":
    sys.exit(principal(sys.argv[1:]))
