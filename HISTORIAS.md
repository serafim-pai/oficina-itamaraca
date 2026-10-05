# OFICINA ITAMARACÁ - Histórias de Usuário

## Mapa de histórias
1. Cadastrar o veículo
2. Anexar fotos da lataria e pintura
3. Registrar os problemas e tipos de serviço
4. Registrar como resolver
5. Montar o orçamento
6. Registrar a aprovação do cliente
7. Definir o prazo de entrega
8. Registrar a garantia

## História 1 - Cadastrar o veículo
Como dono da oficina, quero cadastrar o veículo com o nome do
responsável, placa, marca, modelo, cor, ano e quilometragem, para
facilitar o controle de entrada, o trabalho dos colaboradores nas
etapas seguintes e a hora da entrega.

Critérios de aceitação:
- Não pode salvar o veículo sem a placa.
- Não pode salvar o veículo sem marcar que o documento do carro
  (original ou cópia impressa) foi deixado na oficina.

## História 3 - Registrar os problemas e tipos de serviço
Como dono da oficina, quero registrar cada problema encontrado no
veículo junto com o tipo de serviço necessário, para toda a equipe
saber o que precisa ser feito e para montar o orçamento depois.

Critérios de aceitação:
- Não pode registrar sem escolher o tipo de serviço (lataria, pintura,
  mecânica, elétrica, suspensão, freios, polimento e estética ou outro).
- Não pode registrar sem descrever o problema.
- Um veículo pode ter vários problemas registrados.
- Fica guardado quem registrou e quando.
- Só o dono pode excluir um problema registrado por engano.

## História 4 - Registrar como resolver
Como dono da oficina, quero anotar como cada problema será resolvido,
para os colaboradores saberem o que fazer e para usar isso no
orçamento.

Critérios de aceitação:
- Cada problema registrado tem seu campo "Como resolver".
- Não pode salvar a solução em branco.
- Dá para corrigir a solução depois.
- Fica guardado quem escreveu.

## História 8 - Registrar a garantia
Como dono da oficina, quero registrar o tempo de garantia de cada
serviço e as condições que cancelam a garantia, para o cliente sair
sabendo o que está coberto e a oficina ter como comprovar o que foi
combinado.

Critérios de aceitação:
- Não pode fechar a entrega do carro sem informar o tempo de garantia.
- O sistema calcula a data em que a garantia termina, a partir da
  data de entrega.
- As condições que cancelam a garantia aparecem no comprovante
  entregue ao cliente.