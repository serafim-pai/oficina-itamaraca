# Oficina Itamaracá

Sistema de oficina mecânica (projeto de prática). Histórias de usuário em [HISTORIAS.md](HISTORIAS.md).

## O que faz hoje
- **Cadastrar veículo**: responsável, placa, marca, modelo, cor, ano e quilometragem.
- Não salva sem a **placa** e sem marcar que o **documento do carro** foi deixado na oficina.
- **Fotos do veículo** (opcional) na mesma tela de cadastro: até 10 fotos de 8 MB cada (JPG, PNG, WEBP ou GIF), com prévia antes de enviar e miniaturas na lista (clique para ver a foto inteira).
  - O sistema confere o **conteúdo** do arquivo (não o nome), reduz a foto para no máximo 1600 px, endireita fotos de celular e **remove os dados escondidos**, como a localização GPS.
  - Se qualquer foto for recusada, **nada** é cadastrado (nem o veículo, nem as outras fotos).
  - As fotos ficam na pasta `fotos/` (fora do GitHub e fora da pasta pública) e só aparecem para quem entrou no sistema.

- **Problemas e tipos de serviço** (história 3): clique na placa na lista para abrir a página do veículo e registrar cada problema com o tipo de serviço (lataria, pintura, mecânica, elétrica, suspensão, freios, polimento e estética ou outro). Fica guardado quem registrou e quando; só o dono exclui.

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
