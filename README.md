# Oficina Itamaracá

Sistema de oficina mecânica (projeto de prática). Histórias de usuário em [HISTORIAS.md](HISTORIAS.md).

## O que faz hoje
- **Cadastrar veículo**: responsável, placa, marca, modelo, cor, ano e quilometragem.
- Não salva sem a **placa** e sem marcar que o **documento do carro** foi deixado na oficina.

## Login e usuários
- **Ninguém usa o sistema sem entrar** com e-mail e senha. As senhas são guardadas protegidas (nunca "abertas"), com no mínimo 8 caracteres.
- **Primeiro acesso**: na primeira vez, o sistema pede para criar o **DONO** da oficina. Na hospedagem, isso exige também o *código de instalação* (variável `OFICINA_CODIGO_INICIAL`), para ninguém tomar o sistema antes do dono.
- **Dois tipos**: **Dono** (tudo, inclusive a tela de Usuários) e **Funcionário** (cadastra veículos).
- **Tela de Usuários** (só o dono): criar funcionários e **bloquear/desbloquear** acessos. Quem é bloqueado perde o acesso na hora. O dono não bloqueia a si mesmo.
- **Proteções**: 5 senhas erradas seguidas bloqueiam aquele e-mail por 10 minutos; formulários com token anti-CSRF; sair só por botão; cookie de sessão próprio (`oficina_sessao`), para não brigar com o sistema de varejo que usa o mesmo endereço.

## Como rodar
```
pip install -r requirements.txt
python app.py
```
Abra `http://localhost:5000` e crie o dono.

## Testes
```
python -m unittest discover tests -v
```

## Online
https://serafimpai.pythonanywhere.com/oficina/ (PythonAnywhere, plano gratuito, junto do sistema de varejo).
Atualizar: no console, `cd ~/oficina-itamaraca && git pull` e **Reload** na aba Web.
