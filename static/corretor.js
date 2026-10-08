// Liga o corretor ortográfico do navegador (em português) nos campos de texto livre.
// Placa, chassi, números e códigos ficam de fora, para não ficarem sublinhados de vermelho.
(function () {
    var campos = document.querySelectorAll("textarea, input[name='peca_nome'], input[name='nome'], input[name='peca']");
    Array.prototype.forEach.call(campos, function (c) {
        c.setAttribute("spellcheck", "true");
        c.setAttribute("lang", "pt-BR");
    });
})();
