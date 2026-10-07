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
9. Controlar o estoque de peças e tintas

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
revisados e confirmados pelo dono em 06/10/2026):
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

## História 7 - Definir o prazo de entrega
Como dono da oficina, quero definir o prazo de entrega do veículo, para o
cliente saber quando vai receber o carro e para a oficina acompanhar os
atrasos.

Critérios de aceitação (escritos pelo Claude a partir do título do mapa;
revisados e confirmados pelo dono em 06/10/2026):
- Só o dono define ou muda o prazo. O funcionário apenas vê.
- O prazo só pode ser definido depois que o cliente aprovou o orçamento
  (aprovação valendo, ver história 6).
- O prazo é uma data: não pode ser anterior a hoje (data de Brasília) nem
  passar de 1 ano à frente.
- Mudar um prazo já definido exige explicar o motivo; a nova data precisa
  ser diferente da atual.
- Cada prazo fica no histórico (quem definiu, quando, qual data e o
  motivo); o último é o que vale.
- O sistema mostra a situação do prazo, na tela do veículo e na lista:
  sem prazo, "faltam N dias", "entrega amanhã", "entrega hoje" ou
  "atrasado há N dias".
- Se a aprovação do cliente deixar de valer depois (o orçamento mudou), o
  prazo continua guardado, mas aparece o aviso para confirmá-lo com o
  cliente, e ele só pode ser mudado depois de uma nova aprovação.
- A entrega em si (marcar o carro como entregue) fica para a história 8.

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

Como ficou implementado (complemento escrito pelo Claude; o dono deve
revisar):
- O tempo de garantia é informado **por serviço**, em dias ou em meses
  (0 quer dizer "sem garantia" e conta como informado). Só o dono informa,
  e dá para corrigir até a entrega ser fechada. O tempo máximo depende do
  tipo de serviço (ver "Limites de garantia" abaixo).
- "Fechar a entrega" é feito só pelo dono, uma única vez por veículo, e
  só quando: o cliente aprovou o orçamento (aprovação valendo); todos os
  serviços têm o tempo de garantia informado; e as condições que cancelam
  a garantia foram escritas (o sistema sugere um texto, que o dono edita;
  se todos os serviços forem "sem garantia", as condições são opcionais).
- **Fotos do veículo na entrega:** para fechar a entrega é obrigatório
  enviar de 1 a 10 fotos do carro como ele está saindo da oficina. Elas
  passam pelo mesmo tratamento das outras fotos (confere o conteúdo,
  reduz, tira o GPS), são guardadas junto com a entrega (se algo falhar,
  nada fica pela metade), aparecem na tela do veículo, numa galeria
  própria, e no comprovante. Não podem ser trocadas nem excluídas.
  As fotos tiradas no cadastro e depois (as de "entrada") continuam
  separadas e não contam como fotos de entrega.
- Se a entrega for desfeita, as fotos dela **não são apagadas**: ficam
  guardadas no histórico "Entregas desfeitas", ligadas àquela entrega. Ao
  fechar de novo é preciso enviar novas fotos.
- A data de entrega é o dia em que a entrega é fechada (horário de
  Brasília). A garantia de cada serviço vale **até** a data de entrega
  mais o tempo informado (meses contam em calendário: 31/01 + 1 mês =
  28/02, ou 29/02 em ano bissexto).
- Ao fechar, o sistema guarda uma cópia do que foi combinado (serviços,
  o que foi feito, valores e garantias). O comprovante sai dessa cópia e
  por isso nunca muda.
- Depois da entrega o cadastro do veículo fica travado: não aceita novo
  serviço, mudança de valor, de "como resolver", de garantia, de
  aprovação nem de prazo.
- O comprovante (para imprimir) mostra os dados do veículo, a data de
  entrega, os serviços com valor e garantia, a data de fim de cada
  garantia, o total, as condições que cancelam a garantia, a aprovação do
  cliente e linhas de assinatura. Dono e funcionário podem ver e imprimir.
- A tela do veículo mostra se cada garantia está vigente ou vencida, e a
  lista de veículos mostra "Entregue em dd/mm/aaaa".

Limites de garantia por tipo de serviço (definidos com o dono):
- Cada tipo de serviço tem um tempo **máximo** de garantia, em meses.
  Valores de partida: lataria 12, pintura 24, mecânica 6, elétrica 6,
  suspensão 12, freios 6, polimento e estética 3, outro 12.
- O dono ajusta cada limite (de 1 a 120 meses) na tela "Garantia" do
  menu. Se algum valor for inválido, nada é salvo.
- O limite vale na hora de informar a garantia de um serviço, em dias ou
  em meses (12 meses = 365 dias, e assim por diante). Garantias já
  informadas não mudam quando o limite muda. "Sem garantia" (0) sempre vale.
- A tela do veículo mostra o limite ao lado do campo de garantia.

Desfazer a entrega:
- Só o dono pode desfazer uma entrega fechada, e o motivo é obrigatório.
- A cópia da entrega (serviços, valores, garantias, condições, quem entregou
  e quando) vai para o histórico "Entregas desfeitas", com quem desfez, quando
  e por quê. Nada é apagado.
- O cadastro do veículo destrava (serviços, valores, garantias etc. podem
  ser corrigidos). O comprovante que o cliente já recebeu deixa de valer; ao
  fechar a entrega de novo, sai um comprovante novo.
- Se o valor de um serviço mudar depois de desfazer, a aprovação do cliente
  deixa de valer e é preciso aprovar de novo antes de fechar a entrega.

## História 9 - Controlar o estoque de peças e tintas
Como dono ou funcionário da oficina, quero cadastrar as peças e tintas que tenho, usar no serviço e ver o
preço entrar no orçamento, para saber o que tenho, o que está acabando e cobrar certo.

Combinado com o dono (ainda a confirmar com ele):
- Só o dono cadastra e edita itens (nome, mínimo, custo e preço) e tira um item de uso (ele some das
  listas, mas o histórico fica). O funcionário não vê o custo. Dono e funcionário dão entrada, ajustam a
  contagem e usam em serviços.
- Tudo é contado em **unidades inteiras** (tinta por lata ou frasco). Cada item tem nome, tipo (peça ou
  tinta), quantidade, estoque mínimo, custo e preço de venda. Não há dois itens com o mesmo nome e tipo.
- Cada item tem também categoria (com sugestões como pastilha de freio, lona e disco; dá para escrever outra),
  fabricante (por exemplo, Fras-le) e código da peça, como num catálogo de autopeças.
- "Serve para": uma linha por carro, no formato `MARCA / MODELO / ANO` (o ano é opcional, um só ou um
  período, como 2010-2015). Tinta e itens universais ficam sem carro. Ao usar uma peça em um serviço, a lista
  mostra primeiro o que serve no veículo (marca e modelo parecidos e ano dentro do período), depois os itens
  sem carro informado e por último os que servem em outros carros. Nada é bloqueado: a decisão é de quem monta.
- A tela do estoque tem busca por nome, categoria, fabricante, código ou carro.
- Quando a quantidade chega ao mínimo, a tela do estoque avisa "Estoque baixo"; zerado mostra "Acabou".
- Toda mudança de quantidade (estoque inicial, entrada, uso, devolução, ajuste) fica numa lista que nunca
  é apagada: quem fez, quando, quanto, saldo depois, veículo e observação. O ajuste exige motivo.
- Usar um item em um serviço baixa o estoque e soma `quantidade x preço` ao valor do serviço. O sistema não
  deixa usar mais do que existe. O nome, o preço e o custo da hora do uso ficam guardados: mudar o preço
  no estoque depois não mexe em orçamentos já feitos.
- Tirar a peça do serviço, excluir o serviço ou excluir o veículo devolve a quantidade ao estoque.
- Peças entram no total do orçamento, no texto do WhatsApp e na aprovação do cliente: se uma peça for
  colocada ou tirada depois da aprovação, o orçamento "mudou" e precisa de nova decisão. Aprovações antigas
  (sem peças) continuam valendo.
- Ao fechar a entrega, as peças de cada serviço são copiadas para o fechamento e aparecem no comprovante
  (serviço + peças = valor do item). Depois da entrega não se usa nem se devolve peça.
- Ao desfazer a entrega, a cópia das peças vai para o histórico junto com o valor; as peças continuam
  usadas (o estoque não volta) e o cadastro destrava.

Limites conhecidos: o valor do serviço (mão de obra) continua sendo obrigatório e maior que zero, mesmo
para serviço só de peça. Não há controle de fornecedor nem relatório de lucro ainda.
