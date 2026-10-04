# Oficina Itamaracá

Sistema de oficina mecânica (projeto de prática). Histórias de usuário em [HISTORIAS.md](HISTORIAS.md).

## O que faz hoje
- **Cadastrar veículo**: responsável, placa, marca, modelo, cor, ano e quilometragem.
- Não salva sem a **placa** e sem marcar que o **documento do carro** foi deixado na oficina.

## Como rodar
```
pip install -r requirements.txt
python app.py
```
Abra `http://localhost:5000`.

## Testes
```
python -m unittest discover tests -v
```

## Online
https://serafimpai.pythonanywhere.com/oficina/ (PythonAnywhere, plano gratuito, junto do sistema de varejo).
Atualizar: no console, `cd ~/oficina-itamaraca && git pull` e **Reload** na aba Web.
