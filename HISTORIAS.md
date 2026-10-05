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

## História 5 - Montar o orçamento
Como dono da oficina, quero montar o orçamento com o valor de cada
serviço registrado, para informar ao cliente quanto vai custar.

Critérios de aceitação:
- Cada problema/serviço registrado tem um campo de valor (em reais).
- Só o dono define ou corrige o valor de um serviço.
- O valor total do orçamento é a soma dos valores de todos os
  serviços registrados para o veículo.
- O orçamento só é considerado completo quando todos os serviços do
  veículo têm valor definido.

## História 6 - Registrar a aprovação do cliente
Como dono da oficina, quero registrar se o cliente aprovou ou recusou o
orçamento, para só começar o serviço depois da aprovação e ter como
comprovar o que o cliente decidiu.

Critérios de aceitação (escritos pelo Claude a partir do título do mapa;
o dono deve revisar):
- Só dá para registrar a decisão do cliente quando o orçamento está
  completo (todos os serviços com valor).
- A decisão é "aprovado" ou "recusado", com a forma como o cliente
  respondeu (pessoalmente, telefone ou WhatsApp) e uma observação
  opcional.
- Ficam guardados: quem registrou, quando e o valor total que o cliente
  viu. Dono e funcionário podem registrar.
- Cada decisão fica no histórico; a mais recente é a que vale.
- Se o orçamento mudar depois da decisão (um valor mudar, ou um serviço
  entrar ou sair), a decisão deixa de valer e o sistema pede uma nova.
- Se o orçamento mudar enquanto alguém registra a decisão, o sistema
  recusa e pede para conferir os valores.
- A lista de veículos mostra a situação de cada orçamento: sem
  orçamento, incompleto, aguardando o cliente, aprovado, recusado ou
  "mudou: precisa de nova decisão".

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