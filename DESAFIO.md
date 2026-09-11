# O desafio — configurar um rastreador sem nenhuma documentação

O J16 é um rastreador GPS 4G com porta USB de configuração. A ferramenta que o
fabricante distribui funciona, mas é a única fonte que existe: não há manual do
protocolo, não há especificação pública, nada. Toda vez que era preciso ajustar
um parâmetro que a ferramenta do fabricante não expõe, ou automatizar uma
configuração em lote, a resposta era "abra a ferramenta deles e clique".

Este documento é sobre o que quase deu errado enquanto isso virava um
configurador próprio.

## 1. Provar o protocolo sem um manual para conferir

Sem especificação, a única forma de validar uma hipótese era testar contra um
aparelho real e comparar com o que a tela do fabricante mostrava para a mesma
ação. Cada campo do protocolo — o formato do quadro, o significado de cada
byte, o que cada comando faz — só entrou no código depois de bater com o
aparelho de verdade, não com a primeira hipótese que parecia plausível.

## 2. Testar comandos desconhecidos sem arriscar o aparelho

Uma varredura de opcodes desconhecidos podia travar ou até danificar um
aparelho real se caísse num comando destrutivo por engano. O que tornou isso
seguro: o firmware responde com um código fixo de "não suportado" para
qualquer opcode que não reconhece — o que significa que um opcode não
mapeado pode ser testado sem risco, desde que a lista de comandos já
conhecidos como perigosos fique de fora da varredura desde o início.

## 3. A coordenada errada por um fator de escala

A primeira leitura de posição batia com o mapa, mas ficava sistematicamente
deslocada. A causa: um campo de 2 bytes que parecia natural interpretar como
inteiro binário na verdade guarda dois dígitos decimais — a fração do minuto
de grau, escrita byte a byte em vez de codificada em binário. Lida do jeito
errado, a posição cai a mais de 1 km do lugar certo; lida como decimal, dois
quadros do mesmo aparelho parado batem a poucos metros um do outro — essa
comparação (aparelho parado não pode "andar" entre duas leituras seguidas) foi
o teste que provou qual das duas leituras estava certa.

## 4. Um quadro de tamanho variável que parecia ter campos fixos

O quadro de status de GPS muda de tamanho conforme o número de satélites
visíveis, e nada no início do quadro diz onde ele termina — exceto o próprio
número de satélites, que também está no meio dos dados. Fixar um deslocamento
fixo para o que vem depois funcionava só até o aparelho enxergar mais
satélites que o exemplo usado para descobrir o formato. A prova de que o
layout está certo: o quadro inteiro tem que fechar exatamente em
`23 + 2×(satélites) + 2` bytes — testado contra quadros de tamanhos
diferentes, não só um.

## 5. Duas portas, dois protocolos, comandos parecidos

O aparelho fala dois protocolos completamente diferentes: um pela porta USB
(configuração) e outro pela rede (posição e alarmes para a plataforma). Os
comandos de um não existem no outro — mandar um comando de SMS/plataforma pela
porta USB simplesmente não gera resposta nenhuma, silêncio total, sem erro.
Sem saber que eram dois protocolos distintos, esse silêncio parecia bug do
configurador. Documentar essa fronteira explicitamente evitou repetir a
mesma investigação toda vez que um comando "não fazia nada".

## 6. Comando perigoso do lado de comando inofensivo

Entre os comandos válidos da porta de configuração existem alguns que cortam
o combustível do veículo, desligam o aparelho remotamente ou apagam o
endereço do servidor — todos vizinhos, no mesmo protocolo, de comandos
totalmente inofensivos como ler a frequência de rastreamento. Não dá pra
confiar em nomenclatura ou posição na tela para diferenciar os dois. A solução
foi uma lista explícita de comandos perigosos, checada **antes** de qualquer
envio — nunca depois — mais um backup automático da configuração atual salvo
sozinho antes de qualquer gravação, para sempre existir caminho de volta.

## O que sobrou

Um configurador com console livre, tabela de parâmetros com ajuda contextual,
importação/exportação de configuração e aba de monitoramento ao vivo — cobrindo
mais parâmetros do que a ferramenta original expõe, com testes automatizados
para a parte que decodifica o protocolo (`python j16proto.py`,
`python j16gui.py --selftest`).
