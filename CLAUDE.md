# Regras de trabalho — Oficina Itamaracá

Valem para **qualquer sessão do Claude Code** (app, terminal ou VS Code) que abrir este projeto.
Existem duas sessões trabalhando aqui ao mesmo tempo, e a regra abaixo existe para elas não se atropelarem.

## 1. Uma pasta = uma sessão
Nunca deixe duas sessões editarem **a mesma pasta** ao mesmo tempo.
Quem trabalha em paralelo usa a **própria cópia de trabalho** (git worktree) e a **própria branch**:

```
git fetch
git worktree add .claude/worktrees/historia-N -b historia-N-nome origin/main
```

A pasta `.claude/worktrees/` nunca vai para o GitHub. Ao terminar: `git worktree remove .claude/worktrees/historia-N`.

## 2. Ao começar qualquer trabalho
1. `git fetch` e `git status`.
2. Se houver mudanças soltas ou commits que **você não fez**, pare e avise o usuário. Outra sessão pode estar no meio de uma tarefa. Não "arrume" o que não é seu.

## 3. Uma branch por história
- Nome: `historia-N-assunto` (ex.: `historia-6-prazo`). Commits pequenos, mensagem em português.
- **Não** faça commit direto no `main` enquanto houver outra sessão ativa.

## 4. Como integrar no `main` (rápido, para o conflito não crescer)
1. `git fetch && git rebase origin/main` (na sua branch).
2. `python -m unittest discover tests` — **tudo precisa passar**.
3. Na pasta principal: `git merge --ff-only <sua-branch>` e depois `git push`.
4. Se o `rebase` der conflito, resolva com cuidado **sem apagar o trabalho da outra sessão**; em caso de dúvida, pergunte ao usuário.

## 5. Arquivos mais disputados
`app.py`, `templates/veiculo.html`, `static/estilo.css` e `HISTORIAS.md` são editados por quase toda história.
Integre logo e em pedaços pequenos, em vez de deixar a branch ficar velha por dias.

## 6. Cuidados com o que vai para o GitHub
- Antes de `git add`, confira o `git status`. **Não use** `git add -A` às cegas.
- Nunca commitar: `oficina.db`, `fotos/`, `chave_secreta.txt` (já estão no `.gitignore`).

## 7. Banco de dados
- Mudanças só **aditivas** (`CREATE TABLE IF NOT EXISTS`, `ADD COLUMN`), aplicadas sozinhas ao iniciar o sistema.
  Nunca apagar nem renomear coluna/tabela que já está no servidor.

## 8. Publicação no PythonAnywhere
- **Só quando o usuário pedir.** Fluxo: backup do banco → `git pull` → teste de carga com Python 3.10 → Reload → conferir no site.
- O arquivo WSGI do servidor fica fora do repositório (`/var/www/..._wsgi.py`) e também serve o sistema de varejo: não mexa nele sem necessidade.
- Tudo o que está no `main` do GitHub **não** está automaticamente no ar. Só vai ao ar depois do passo acima.
